"""Casamento historico: quais dias do passado 'parecem' com hoje.

Individual: |indicador(dia) - alvo| <= banda.
Composto:   E logico das mascaras individuais (interseccao estrita).

Se a interseccao estrita nao alcanca o N minimo, as bandas sao alargadas em
conjunto por um fator, e o fator usado e devolvido para a interface deixar
explicito o quanto foi preciso relaxar. Sem isso o "E" de tres indicadores
frequentemente devolve zero dias e a pergunta fica sem resposta.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .indicators import Indicator

EXPANSION_STEPS = [1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 7.0, 10.0]


@dataclass
class MatchResult:
    mask: pd.Series
    factor: float
    bands_used: dict[str, float]
    n_days: int
    n_days_with_window: int
    relaxed: bool
    exhausted: bool

    @property
    def dates(self) -> pd.DatetimeIndex:
        return self.mask[self.mask].index


def _combine(
    indicators: dict[str, Indicator],
    targets: dict[str, float],
    bands: dict[str, float],
    index: pd.DatetimeIndex,
    factor: float,
) -> pd.Series:
    mask = pd.Series(True, index=index)
    for key, ind in indicators.items():
        m = ind.mask(targets[key], bands[key] * factor).reindex(index, fill_value=False)
        mask &= m
    return mask


def match(
    indicators: dict[str, Indicator],
    targets: dict[str, float],
    bands: dict[str, float],
    panel: pd.DataFrame,
    min_n: int = 30,
    relax: bool = True,
    window_col: str | None = None,
    date_range: tuple[pd.Timestamp, pd.Timestamp] | None = None,
    exclude_recent_days: int = 0,
) -> MatchResult:
    """Devolve a mascara dos dias casados, relaxando as bandas se necessario.

    window_col: coluna de retorno futuro usada para contar a amostra util
    (dias sem retorno futuro conhecido nao contam para o N minimo).
    exclude_recent_days: ignora os ultimos N dias, cujo retorno futuro ainda
    nao existe, evitando que a amostra pareca maior do que e.
    """
    index = panel.index
    if date_range is not None:
        index = index[(index >= date_range[0]) & (index <= date_range[1])]
    if exclude_recent_days > 0:
        index = index[index <= index.max() - pd.Timedelta(days=exclude_recent_days)]

    steps = EXPANSION_STEPS if relax else [1.0]
    last_mask, last_factor = None, 1.0
    for factor in steps:
        mask = _combine(indicators, targets, bands, index, factor)
        last_mask, last_factor = mask, factor
        n_useful = _useful(mask, panel, window_col)
        if n_useful >= min_n:
            return MatchResult(
                mask=mask,
                factor=factor,
                bands_used={k: v * factor for k, v in bands.items()},
                n_days=int(mask.sum()),
                n_days_with_window=n_useful,
                relaxed=factor > 1.0,
                exhausted=False,
            )

    return MatchResult(
        mask=last_mask,
        factor=last_factor,
        bands_used={k: v * last_factor for k, v in bands.items()},
        n_days=int(last_mask.sum()),
        n_days_with_window=_useful(last_mask, panel, window_col),
        relaxed=last_factor > 1.0,
        exhausted=True,
    )


def _useful(mask: pd.Series, panel: pd.DataFrame, window_col: str | None) -> int:
    if window_col is None or window_col not in panel:
        return int(mask.sum())
    sel = panel.loc[mask.reindex(panel.index, fill_value=False), window_col]
    return int(sel.notna().sum())
