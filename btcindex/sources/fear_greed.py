"""Crypto Fear & Greed Index (alternative.me).

Historico real comeca em 2018-02-01. Nao ha reconstrucao sintetica aqui por opcao
do projeto: so dado oficial.
"""
from __future__ import annotations

import pandas as pd

from ..cache import cached, http_get

URL = "https://api.alternative.me/fng/"


def _fetch() -> pd.DataFrame:
    r = http_get(URL, params={"limit": 0, "format": "json"})
    data = r.json()["data"]
    df = pd.DataFrame(data)
    df["date"] = (
        pd.to_datetime(df["timestamp"].astype(int), unit="s", utc=True).dt.tz_localize(None).dt.normalize()
    )
    df["fng"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["fng"]).drop_duplicates("date").set_index("date").sort_index()
    return df[["fng", "value_classification"]].rename(columns={"value_classification": "fng_label"})


def fetch(force: bool = False) -> pd.DataFrame:
    return cached("fear_greed", _fetch, max_age_hours=6, force=force)


def series(force: bool = False) -> pd.Series:
    df = fetch(force=force)
    s = df["fng"].astype(float)
    idx = pd.date_range(s.index.min(), s.index.max(), freq="D")
    return s.reindex(idx).ffill().rename("fng")


CLASSIFICATION = [
    (0, 24, "Medo Extremo"),
    (25, 44, "Medo"),
    (45, 55, "Neutro"),
    (56, 75, "Ganancia"),
    (76, 100, "Ganancia Extrema"),
]


def classify(value: float) -> str:
    for lo, hi, label in CLASSIFICATION:
        if lo <= value <= hi:
            return label
    return "?"
