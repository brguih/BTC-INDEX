"""Painel diario: preco do BTC + retornos futuros das janelas."""
from __future__ import annotations

import pandas as pd

from .sources import btc_price

# janelas em dias corridos (nao dias uteis: BTC negocia todo dia)
WINDOWS: dict[str, int] = {"1m": 30, "3m": 91, "6m": 182, "12m": 365}


def build(windows: dict[str, int] | None = None, force: bool = False) -> pd.DataFrame:
    windows = windows or WINDOWS
    close = btc_price.close_series(force=force)
    df = pd.DataFrame({"btc_close": close})
    for label, days in windows.items():
        df[f"fwd_{label}"] = close.shift(-days) / close - 1.0
    return df


def last_date(df: pd.DataFrame) -> pd.Timestamp:
    return df.index.max()
