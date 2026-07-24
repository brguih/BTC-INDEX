"""Ciclo temporal do BTC.

Os halvings NAO sao de 1460 dias. Intervalos observados:
    2012-11-28 -> 2016-07-09 = 1319 dias
    2016-07-09 -> 2020-05-11 = 1402 dias
    2020-05-11 -> 2024-04-19 = 1435 dias
A mediana dos dois ultimos e ~1435, e o proximo halving e projetado para
marco/2028. Por isso o comprimento do ciclo e parametro, com default 1435.

Ancoras disponiveis:
    halving  - objetiva e conhecida em tempo real (default)
    topo     - topos de ciclo; so sao conhecidos DEPOIS que acontecem
    fundo    - fundos de ciclo; mesma ressalva
"""
from __future__ import annotations

import numpy as np
import pandas as pd

HALVINGS = [
    pd.Timestamp("2012-11-28"),
    pd.Timestamp("2016-07-09"),
    pd.Timestamp("2020-05-11"),
    pd.Timestamp("2024-04-19"),
    pd.Timestamp("2028-03-26"),  # projetado
]

TOPS = [
    pd.Timestamp("2013-12-04"),
    pd.Timestamp("2017-12-17"),
    pd.Timestamp("2021-11-10"),
    pd.Timestamp("2025-10-06"),
]

BOTTOMS = [
    pd.Timestamp("2015-01-14"),
    pd.Timestamp("2018-12-15"),
    pd.Timestamp("2022-11-21"),
]

ANCHORS = {"halving": HALVINGS, "topo": TOPS, "fundo": BOTTOMS}
DEFAULT_CYCLE_DAYS = 1435


def anchor_dates(anchor: str = "halving") -> list[pd.Timestamp]:
    if anchor not in ANCHORS:
        raise ValueError(f"ancora invalida: {anchor}")
    return ANCHORS[anchor]


def cycle_day(index: pd.DatetimeIndex, anchor: str = "halving") -> pd.Series:
    """Dias decorridos desde a ultima ancora. NaN antes da primeira ancora."""
    dates = sorted(anchor_dates(anchor))
    arr = np.array([d.value for d in dates])
    idx_vals = index.values.astype("datetime64[ns]").astype("int64")
    pos = np.searchsorted(arr, idx_vals, side="right") - 1
    out = np.full(len(index), np.nan)
    valid = pos >= 0
    out[valid] = (idx_vals[valid] - arr[pos[valid]]) / 86_400_000_000_000
    return pd.Series(out, index=index, name=f"cycle_day_{anchor}")


def circular_distance(values: pd.Series, target: float, cycle_days: int) -> pd.Series:
    """Distancia em dias no circulo do ciclo (dia 1430 e dia 5 distam 10, nao 1425)."""
    diff = (values - target).abs() % cycle_days
    return np.minimum(diff, cycle_days - diff)


def observed_intervals() -> pd.DataFrame:
    rows = []
    for a, b in zip(HALVINGS, HALVINGS[1:]):
        rows.append(
            {
                "de": a.date(),
                "ate": b.date(),
                "dias": (b - a).days,
                "projetado": b == HALVINGS[-1],
            }
        )
    return pd.DataFrame(rows)
