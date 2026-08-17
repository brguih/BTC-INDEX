"""MVRV Z-score, via Coin Metrics community API (gratuita, sem chave).

    Z = (valor de mercado - valor realizado) / desvio-padrao do valor de mercado

O valor realizado precifica cada moeda pelo valor da ultima vez que ela se moveu,
entao a diferenca entre os dois mede quanto lucro nao realizado existe no
mercado. O Z-score normaliza essa diferenca pela escala do proprio ciclo, o que
permite comparar 2013 com 2025.

O desvio-padrao e expansivo (usa so o passado ate cada data), nao o da serie
inteira: usar o desvio final embutiria informacao do futuro em toda a serie
historica e inflaria artificialmente a qualidade do indicador no backtest.
"""
from __future__ import annotations

import pandas as pd

from ..cache import cached, http_get

URL = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"

# CapRealUSD (valor realizado) e metrica paga, mas o tier gratuito da a razao
# MVRV e o valor de mercado - e valor realizado = valor de mercado / MVRV.
METRICAS = "CapMVRVCur,CapMrktCurUSD"

# antes disso a rede era minuscula e o MVRV chega a 146; nenhuma leitura util
INICIO = "2011-01-01"


def _fetch() -> pd.DataFrame:
    params = {
        "assets": "btc",
        "metrics": METRICAS,
        "frequency": "1d",
        "page_size": 10000,
        "start_time": INICIO,
    }
    linhas, url, primeiro = [], URL, True
    while url and len(linhas) < 40000:
        r = http_get(url, params=params if primeiro else None, timeout=90)
        j = r.json()
        linhas.extend(j.get("data", []))
        url, primeiro = j.get("next_page_url"), False

    df = pd.DataFrame(linhas)
    df["date"] = pd.to_datetime(df["time"]).dt.tz_localize(None).dt.normalize()
    for col in ("CapMrktCurUSD", "CapMVRVCur"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["CapMrktCurUSD", "CapMVRVCur"])
    df = df[df["CapMVRVCur"] > 0].drop_duplicates("date").set_index("date").sort_index()

    df["mvrv"] = df["CapMVRVCur"]
    df["cap_realizado"] = df["CapMrktCurUSD"] / df["mvrv"]
    desvio = df["CapMrktCurUSD"].expanding(min_periods=180).std()
    df["mvrv_z"] = (df["CapMrktCurUSD"] - df["cap_realizado"]) / desvio
    return df[["mvrv_z", "mvrv", "CapMrktCurUSD", "cap_realizado"]]


def fetch(force: bool = False) -> pd.DataFrame:
    return cached("mvrv", _fetch, max_age_hours=12, force=force)


def zscore(force: bool = False) -> pd.Series:
    df = fetch(force=force)
    s = df["mvrv_z"].dropna()
    idx = pd.date_range(s.index.min(), s.index.max(), freq="D")
    return s.reindex(idx).ffill().rename("mvrv_z")


def ratio(force: bool = False) -> pd.Series:
    df = fetch(force=force)
    s = df["mvrv"].dropna()
    idx = pd.date_range(s.index.min(), s.index.max(), freq="D")
    return s.reindex(idx).ffill().rename("mvrv")
