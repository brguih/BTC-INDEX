"""Estatisticas das janelas futuras sobre um conjunto de datas casadas."""
from __future__ import annotations

import numpy as np
import pandas as pd


def episodes(dates: pd.DatetimeIndex, gap_days: int = 45) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Agrupa datas casadas em episodios separados por pelo menos `gap_days`.

    Existe porque janelas sobrepostas inflam o N: 200 dias casados podem ser
    3 episodios independentes, e a significancia real vem do numero de episodios.
    """
    if len(dates) == 0:
        return []
    d = pd.DatetimeIndex(sorted(dates))
    breaks = np.where(np.diff(d.values).astype("timedelta64[D]").astype(int) > gap_days)[0]
    starts = np.concatenate([[0], breaks + 1])
    ends = np.concatenate([breaks, [len(d) - 1]])
    return [(d[s], d[e]) for s, e in zip(starts, ends)]


def summarize(
    panel: pd.DataFrame,
    mask: pd.Series,
    windows: dict[str, int],
    gap_days: int = 45,
) -> pd.DataFrame:
    """Uma linha por janela com N, medias, dispersao e taxa de acerto.

    `panel` precisa ter as colunas fwd_<chave> em fracao (0.10 = +10%).
    """
    sel = panel.loc[mask.reindex(panel.index, fill_value=False)]
    eps = episodes(sel.index, gap_days=gap_days)
    rows = []
    for label, _ in windows.items():
        col = f"fwd_{label}"
        vals = sel[col].dropna() if col in sel else pd.Series(dtype=float)
        base = panel[col].dropna() if col in panel else pd.Series(dtype=float)
        # episodios que efetivamente tem retorno futuro conhecido
        eps_com_dado = len(episodes(vals.index, gap_days=gap_days))
        rows.append(
            {
                "janela": label,
                "n_dias": int(len(vals)),
                "n_episodios": eps_com_dado,
                "media_%": _pct(vals.mean()),
                "mediana_%": _pct(vals.median()),
                "desvio_%": _pct(vals.std()),
                "p10_%": _pct(vals.quantile(0.10)) if len(vals) else np.nan,
                "p90_%": _pct(vals.quantile(0.90)) if len(vals) else np.nan,
                "min_%": _pct(vals.min()),
                "max_%": _pct(vals.max()),
                "acerto_%": _pct((vals > 0).mean(), scale=100) if len(vals) else np.nan,
                "baseline_mediana_%": _pct(base.median()),
                "baseline_n": int(len(base)),
            }
        )
    out = pd.DataFrame(rows)
    out.attrs["episodios"] = eps
    out.attrs["datas"] = sel.index
    return out


def _pct(x, scale: float = 100.0) -> float:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return np.nan
    return round(float(x) * scale, 2)


def episode_table(panel: pd.DataFrame, mask: pd.Series, windows: dict[str, int], gap_days: int = 45) -> pd.DataFrame:
    """Detalhe por episodio: quando foi, quantos dias, e o retorno mediano de cada janela."""
    sel = panel.loc[mask.reindex(panel.index, fill_value=False)]
    rows = []
    for start, end in episodes(sel.index, gap_days=gap_days):
        chunk = sel.loc[start:end]
        row = {
            "inicio": start.date(),
            "fim": end.date(),
            "dias": len(chunk),
            "btc_medio": round(float(chunk["btc_close"].mean()), 0),
        }
        for label in windows:
            col = f"fwd_{label}"
            vals = chunk[col].dropna() if col in chunk else pd.Series(dtype=float)
            row[f"{label}_%"] = _pct(vals.median()) if len(vals) else np.nan
        rows.append(row)
    return pd.DataFrame(rows)
