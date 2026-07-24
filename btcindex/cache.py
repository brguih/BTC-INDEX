"""HTTP com retry e cache local em CSV.

Cada fonte grava um CSV em data/cache/<nome>.csv com a coluna `date` como indice.
CSV (em vez de parquet) para nao exigir pyarrow e para o dado ficar inspecionavel.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) BTC-INDEX/1.0"


def http_get(url, params=None, headers=None, timeout=60, retries=3, backoff=2.0):
    """GET com retry exponencial. Levanta a ultima excecao se todas falharem."""
    hdrs = {"User-Agent": UA}
    if headers:
        hdrs.update(headers)
    last = None
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=hdrs, timeout=timeout)
            r.raise_for_status()
            return r
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt < retries - 1:
                time.sleep(backoff ** attempt)
    raise RuntimeError(f"Falha ao buscar {url}: {last}")


def save(df: pd.DataFrame, name: str) -> Path:
    path = CACHE_DIR / f"{name}.csv"
    out = df.copy()
    out.index.name = "date"
    out.to_csv(path)
    return path


def load(name: str) -> pd.DataFrame | None:
    path = CACHE_DIR / f"{name}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, parse_dates=["date"], index_col="date")
    df.index = pd.DatetimeIndex(df.index).normalize()
    return df


def age_hours(name: str) -> float | None:
    """Idade do cache em horas, ou None se nao existe."""
    path = CACHE_DIR / f"{name}.csv"
    if not path.exists():
        return None
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return (datetime.now(timezone.utc) - mtime).total_seconds() / 3600.0


def cached(name: str, fetch_fn, max_age_hours: float = 12.0, force: bool = False) -> pd.DataFrame:
    """Retorna o cache se fresco; senao rebusca. Se a busca falhar, cai no cache velho."""
    age = age_hours(name)
    if not force and age is not None and age < max_age_hours:
        cached_df = load(name)
        if cached_df is not None and not cached_df.empty:
            return cached_df
    try:
        df = fetch_fn()
        if df is None or df.empty:
            raise RuntimeError("fonte retornou vazio")
        save(df, name)
        return df
    except Exception as exc:  # noqa: BLE001
        fallback = load(name)
        if fallback is not None and not fallback.empty:
            print(f"[aviso] {name}: usando cache antigo ({exc})")
            return fallback
        raise


def to_daily(s: pd.Series, method: str = "interpolate", end: pd.Timestamp | None = None) -> pd.Series:
    """Reamostra uma serie mensal/semanal para diaria.

    method='interpolate' -> interpolacao linear entre observacoes (bom para estoques
    como M2, que variam suavemente).
    method='ffill' -> degrau (bom para series ja diarias com buracos de feriado).
    """
    s = s.dropna().sort_index()
    if s.empty:
        return s
    last = end if end is not None else s.index.max()
    idx = pd.date_range(s.index.min(), max(last, s.index.max()), freq="D")
    out = s.reindex(idx)
    if method == "interpolate":
        out = out.interpolate(method="time").ffill()
    else:
        out = out.ffill()
    return out
