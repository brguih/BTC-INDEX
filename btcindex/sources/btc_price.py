"""Preco diario do BTC/USD.

Primaria: Bitstamp OHLC publico (sem chave, historico desde 2011).
Fallback: Yahoo Finance (desde 2014-09) -> Coinbase (desde 2015-07).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from ..cache import cached, http_get, load

BITSTAMP = "https://www.bitstamp.net/api/v2/ohlc/btcusd/"
START_TS = 1325376000  # 2012-01-01
STEP = 86400


def _fetch_bitstamp(since_ts: int | None = None) -> pd.DataFrame:
    rows, start = [], since_ts or START_TS
    now = int(datetime.now(tz=timezone.utc).timestamp())
    while start < now:
        r = http_get(BITSTAMP, params={"step": STEP, "limit": 1000, "start": start})
        chunk = r.json()["data"]["ohlc"]
        if not chunk:
            break
        rows.extend(chunk)
        last = int(chunk[-1]["timestamp"])
        if last <= start:
            break
        start = last + STEP
    df = pd.DataFrame(rows)
    df["date"] = (
        pd.to_datetime(df["timestamp"].astype(int), unit="s", utc=True).dt.tz_localize(None).dt.normalize()
    )
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.drop_duplicates("date").set_index("date").sort_index()
    df = df[df["close"] > 0]
    return df[["open", "high", "low", "close", "volume"]]


def _fetch_yahoo() -> pd.DataFrame:
    url = "https://query1.finance.yahoo.com/v8/finance/chart/BTC-USD"
    r = http_get(url, params={"period1": 1279321200, "period2": 9999999999, "interval": "1d"})
    res = r.json()["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(res["timestamp"], unit="s", utc=True).tz_localize(None).normalize(),
            "open": q["open"],
            "high": q["high"],
            "low": q["low"],
            "close": q["close"],
            "volume": q["volume"],
        }
    )
    return df.dropna(subset=["close"]).drop_duplicates("date").set_index("date").sort_index()


def _fetch_incremental() -> pd.DataFrame:
    """Busca so o que falta desde a ultima data em cache.

    O historico completo custa 6 requisicoes paginadas; havendo cache, uma basta.
    Refaz os ultimos 3 dias porque a barra do dia corrente ainda esta se formando.
    """
    old = load("btc_price")
    if old is None or len(old) < 3000:
        return _fetch_bitstamp()

    last = pd.Timestamp(old.index.max())
    since = int((last - pd.Timedelta(days=3)).timestamp())
    new = _fetch_bitstamp(since_ts=since)
    if new.empty:
        return old
    return pd.concat([old[~old.index.isin(new.index)], new]).sort_index()


def fetch(force: bool = False) -> pd.DataFrame:
    def _go():
        try:
            df = _fetch_incremental()
            if len(df) > 3000:
                return df
            print("[aviso] Bitstamp devolveu poucas barras; tentando Yahoo")
        except Exception as exc:  # noqa: BLE001
            print(f"[aviso] Bitstamp falhou ({exc}); tentando Yahoo")
        return _fetch_yahoo()

    return cached("btc_price", _go, max_age_hours=6, force=force)


def close_series(force: bool = False) -> pd.Series:
    """Fechamento diario, reindexado sem buracos."""
    df = fetch(force=force)
    s = df["close"].astype(float)
    idx = pd.date_range(s.index.min(), s.index.max(), freq="D")
    return s.reindex(idx).ffill().rename("btc_close")
