"""M2 global em USD: EUA + Zona do Euro + China + Japao + Reino Unido.

Cada componente vem da fonte oficial que ainda esta viva (as series de M2
estrangeiro do FRED foram descontinuadas entre 2017 e 2019 e nao servem):

  EUA    FRED WM2NS                     semanal, US$ bi           -> hoje
  EA     ECB Data Portal BSI M2         mensal, EUR mi            -> hoje
  China  chinadata.live (PBoC) 2015+    mensal, 100 mi CNY        -> hoje
         emendado com FRED MYAGM2CNM189N para 1999-2014
  Japao  IMF IFS via DBnomics           mensal, JPY               -> defasado
  UK     Bank of England LPMAUYM (M4)   mensal, GBP mi            -> hoje

Conversao para USD com FX diario do FRED. O agregado e encadeado (chain-linked):
quando um componente entra ou sai da amostra, o nivel e emendado pela razao do
periodo anterior, entao a serie nunca da um degrau artificial por mudanca de
cobertura. Isso e o que permite incluir o Japao apesar da defasagem.
"""
from __future__ import annotations

import io

import numpy as np
import pandas as pd

from ..cache import cached, http_get, to_daily
from . import fred

# ---------------------------------------------------------------- componentes


def _us_m2_usd_tn(force: bool = False) -> pd.Series:
    """FRED WM2NS: US$ bilhoes, semanal."""
    return fred.series("WM2NS", force=force) / 1000.0  # -> trilhoes


def _fetch_ecb() -> pd.DataFrame:
    url = (
        "https://data-api.ecb.europa.eu/service/data/BSI/"
        "M.U2.Y.V.M20.X.1.U2.2300.Z01.E?startPeriod=1999-01&format=csvdata"
    )
    r = http_get(url, headers={"Accept": "text/csv"})
    df = pd.read_csv(io.StringIO(r.text))
    out = pd.DataFrame(
        {
            "date": pd.PeriodIndex(df["TIME_PERIOD"], freq="M").to_timestamp(how="end").normalize(),
            "ea_m2_eur_mi": pd.to_numeric(df["OBS_VALUE"], errors="coerce"),
        }
    )
    return out.dropna().drop_duplicates("date").set_index("date").sort_index()


def _ea_m2_eur_tn(force: bool = False) -> pd.Series:
    df = cached("ecb_m2", _fetch_ecb, max_age_hours=24, force=force)
    return df["ea_m2_eur_mi"] / 1e6  # milhoes -> trilhoes


def _fetch_china() -> pd.DataFrame:
    """PBoC via chinadata.live (2015+), emendado com FRED (1999-2019) para tras."""
    r = http_get("https://chinadata.live/api/v2/data/china-m2-money-supply")
    rows = r.json()["data"]["data"]
    recent = pd.DataFrame(rows)
    recent["date"] = pd.PeriodIndex(recent["date"], freq="M").to_timestamp(how="end").normalize()
    recent["v"] = pd.to_numeric(recent["value"], errors="coerce") / 1e4  # 100mi CNY -> tri CNY
    recent = recent.dropna(subset=["v"]).set_index("date")["v"].sort_index()

    try:
        legacy = fred.series("MYAGM2CNM189N", max_age_hours=24 * 30) / 1e12  # CNY -> tri CNY
        legacy.index = (
            pd.PeriodIndex(legacy.index, freq="M").to_timestamp(how="end").normalize()
        )
        overlap = legacy.index.intersection(recent.index)
        if len(overlap) >= 6:
            ratio = (recent.loc[overlap] / legacy.loc[overlap]).median()
            legacy = legacy * ratio
            legacy = legacy[legacy.index < recent.index.min()]
            recent = pd.concat([legacy, recent]).sort_index()
    except Exception as exc:  # noqa: BLE001
        print(f"[aviso] emenda historica da China indisponivel ({exc})")

    return recent.to_frame("cn_m2_cny_tn")


def _cn_m2_cny_tn(force: bool = False) -> pd.Series:
    return cached("china_m2", _fetch_china, max_age_hours=24, force=force)["cn_m2_cny_tn"]


def _fetch_japan() -> pd.DataFrame:
    url = "https://api.db.nomics.world/v22/series/IMF/IFS/M.JP.FMB_XDC"
    r = http_get(url, params={"observations": 1}, timeout=90)
    doc = r.json()["series"]["docs"][0]
    s = pd.Series(doc["value"], index=pd.PeriodIndex(doc["period"], freq="M").to_timestamp(how="end").normalize())
    s = pd.to_numeric(s, errors="coerce").dropna() / 1e6  # milhoes de JPY -> tri JPY
    return s.to_frame("jp_m2_jpy_tn")


def _jp_m2_jpy_tn(force: bool = False) -> pd.Series:
    return cached("japan_m2", _fetch_japan, max_age_hours=24 * 7, force=force)["jp_m2_jpy_tn"]


def _fetch_uk() -> pd.DataFrame:
    url = "https://www.bankofengland.co.uk/boeapps/iadb/fromshowcolumns.asp"
    params = {
        "csv.x": "yes",
        "Datefrom": "01/Jan/1999",
        "Dateto": "now",
        "SeriesCodes": "LPMAUYM",  # M4 amostra ampla, GBP milhoes
        "CSVF": "TN",
        "UsingCodes": "Y",
        "VPD": "Y",
        "VFD": "N",
    }
    r = http_get(url, params=params, timeout=90)
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = ["date", "uk_m4_gbp_mi"]
    df["date"] = pd.to_datetime(df["date"], format="%d %b %Y")
    df["uk_m4_gbp_mi"] = pd.to_numeric(df["uk_m4_gbp_mi"], errors="coerce")
    return df.dropna().set_index("date").sort_index()


def _uk_m4_gbp_tn(force: bool = False) -> pd.Series:
    return cached("uk_m4", _fetch_uk, max_age_hours=24, force=force)["uk_m4_gbp_mi"] / 1e6


# ------------------------------------------------------------------ agregacao

COMPONENT_LABELS = {
    "US": "EUA (M2)",
    "EA": "Zona do Euro (M2)",
    "CN": "China (M2)",
    "JP": "Japao (M2)",
    "UK": "Reino Unido (M4)",
}
DEFAULT_COMPONENTS = ("US", "EA", "CN", "JP", "UK")


def components_usd_tn(force: bool = False, end: pd.Timestamp | None = None) -> pd.DataFrame:
    """Cada componente em US$ trilhoes, diario. NaN onde a fonte ainda nao publicou."""
    if end is None:
        end = pd.Timestamp.today().normalize()

    eurusd = to_daily(fred.series("DEXUSEU", force=force), "ffill", end=end)   # USD por EUR
    usdcny = to_daily(fred.series("DEXCHUS", force=force), "ffill", end=end)   # CNY por USD
    usdjpy = to_daily(fred.series("DEXJPUS", force=force), "ffill", end=end)   # JPY por USD
    gbpusd = to_daily(fred.series("DEXUSUK", force=force), "ffill", end=end)   # USD por GBP

    raw = {
        "US": to_daily(_us_m2_usd_tn(force), "interpolate"),
        "EA": to_daily(_ea_m2_eur_tn(force), "interpolate"),
        "CN": to_daily(_cn_m2_cny_tn(force), "interpolate"),
        "JP": to_daily(_jp_m2_jpy_tn(force), "interpolate"),
        "UK": to_daily(_uk_m4_gbp_tn(force), "interpolate"),
    }
    idx = pd.date_range(min(s.index.min() for s in raw.values()), end, freq="D")

    out = pd.DataFrame(index=idx)
    out["US"] = raw["US"].reindex(idx)
    out["EA"] = raw["EA"].reindex(idx) * eurusd.reindex(idx)
    out["CN"] = raw["CN"].reindex(idx) / usdcny.reindex(idx)
    out["JP"] = raw["JP"].reindex(idx) / usdjpy.reindex(idx)
    out["UK"] = raw["UK"].reindex(idx) * gbpusd.reindex(idx)
    return out


def chain_link(frame: pd.DataFrame) -> pd.Series:
    """Soma encadeada: imune a componentes que entram/saem da amostra."""
    # descarta o inicio da amostra onde quase nenhum componente existe (senao o
    # agregado vira "M2 dos EUA" disfarcado de global nos anos 80/90)
    ncols = frame.shape[1]
    need = max(2, ncols - 1)
    ok = frame.notna().sum(axis=1) >= need
    if ok.any():
        frame = frame.loc[ok.idxmax():]

    vals = frame.to_numpy(dtype=float)
    n = len(frame)
    growth = np.ones(n)
    for i in range(1, n):
        prev, cur = vals[i - 1], vals[i]
        both = ~np.isnan(prev) & ~np.isnan(cur)
        if both.any() and prev[both].sum() > 0:
            growth[i] = cur[both].sum() / prev[both].sum()
    level = pd.Series(np.cumprod(growth), index=frame.index)

    # reescala para o valor real somado na data mais recente com cobertura maxima
    coverage = frame.notna().sum(axis=1)
    anchor = coverage[coverage == coverage.max()].index[-1]
    level *= frame.loc[anchor].sum(skipna=True) / level.loc[anchor]
    return level.rename("global_m2_usd_tn")


def series(components: tuple[str, ...] = DEFAULT_COMPONENTS, force: bool = False) -> pd.Series:
    frame = components_usd_tn(force=force)
    return chain_link(frame[list(components)])


def coverage_report(force: bool = False) -> pd.DataFrame:
    """Ultima observacao real de cada componente (para a UI avisar sobre defasagem)."""
    frame = components_usd_tn(force=force)
    rows = []
    for col in frame.columns:
        s = frame[col].dropna()
        rows.append(
            {
                "componente": COMPONENT_LABELS[col],
                "codigo": col,
                "inicio": s.index.min().date() if len(s) else None,
                "ultimo_dado": s.index.max().date() if len(s) else None,
                "valor_US$_tri": round(float(s.iloc[-1]), 2) if len(s) else None,
            }
        )
    return pd.DataFrame(rows)
