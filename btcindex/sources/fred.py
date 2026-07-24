"""Series do FRED via CSV publico (nao exige chave de API)."""
from __future__ import annotations

import io

import pandas as pd

from ..cache import cached, http_get

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"


def _fetch_series(series_id: str) -> pd.DataFrame:
    r = http_get(URL, params={"id": series_id})
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = ["date", series_id]
    df["date"] = pd.to_datetime(df["date"])
    df[series_id] = pd.to_numeric(df[series_id], errors="coerce")
    return df.dropna().set_index("date").sort_index()


def series(series_id: str, force: bool = False, max_age_hours: float = 12.0) -> pd.Series:
    df = cached(f"fred_{series_id}", lambda: _fetch_series(series_id), max_age_hours=max_age_hours, force=force)
    return df[series_id].astype(float)
