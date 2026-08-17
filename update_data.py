"""Atualiza todas as fontes e imprime um resumo. Uso: python update_data.py [--check]"""
from __future__ import annotations

import argparse
import sys

import pandas as pd

from btcindex import engine
from btcindex.sources import global_m2


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="usa o cache, nao vai na rede")
    args = ap.parse_args()

    raw = engine.load_raw(force=not args.check)
    rows = [
        ("BTC/USD (Bitstamp)", raw.btc),
        ("Fear & Greed (alternative.me)", raw.fng),
        ("MVRV Z-score (Coin Metrics)", raw.mvrv_z),
    ]
    print(f"{'serie':38s} {'inicio':>12s} {'fim':>12s} {'obs':>7s}  ultimo")
    for name, s in rows:
        d = s.dropna()
        print(f"{name:38s} {str(d.index.min().date()):>12s} {str(d.index.max().date()):>12s} "
              f"{len(d):>7d}  {d.iloc[-1]:,.2f}")

    print("\nComponentes do M2 global (US$ trilhoes):")
    for col in raw.m2_components.columns:
        s = raw.m2_components[col].dropna()
        atraso = (pd.Timestamp.today().normalize() - s.index.max()).days
        print(f"  {global_m2.COMPONENT_LABELS[col]:22s} ate {s.index.max().date()} "
              f"({atraso:>4d}d de defasagem)  US$ {s.iloc[-1]:6.2f} tri")
    level = global_m2.chain_link(raw.m2_components)
    print(f"  {'AGREGADO':22s} ate {level.index.max().date()}              US$ {level.iloc[-1]:6.2f} tri")

    stale = [c for c in raw.m2_components.columns
             if (pd.Timestamp.today().normalize() - raw.m2_components[c].dropna().index.max()).days > 120]
    if stale:
        print("\n[aviso] componentes com mais de 120 dias de defasagem: " + ", ".join(stale))
    return 0


if __name__ == "__main__":
    sys.exit(main())
