"""Net Liquidity do Fed = Balanco do Fed - Conta do Tesouro (TGA) - Reverse Repo.

WALCL   (semanal, qua)  balanco total do Fed, US$ milhoes
WTREGEN (semanal, qua)  saldo do Tesouro no Fed, US$ milhoes
RRPONTSYD (diaria)      reverse repo overnight, US$ bilhoes

Serie desde 2003, sem defasagem de publicacao relevante (WALCL sai toda quinta).
"""
from __future__ import annotations

import pandas as pd

from ..cache import to_daily
from . import fred


def series(force: bool = False) -> pd.Series:
    walcl = fred.series("WALCL", force=force)          # US$ milhoes
    tga = fred.series("WTREGEN", force=force)          # US$ milhoes
    rrp = fred.series("RRPONTSYD", force=force) * 1000  # bilhoes -> milhoes

    end = max(walcl.index.max(), rrp.index.max())
    w = to_daily(walcl, "interpolate", end=end)
    t = to_daily(tga, "interpolate", end=end)
    r = to_daily(rrp, "ffill", end=end)

    idx = w.index.intersection(t.index).intersection(r.index)
    net = (w.loc[idx] - t.loc[idx] - r.loc[idx]) / 1e6  # -> US$ trilhoes
    return net.rename("net_liquidity_usd_tn")
