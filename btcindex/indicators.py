"""Definicao dos indicadores.

Cada indicador expoe uma serie diaria e diz como comparar dois valores dela.
Adicionar um indicador novo = escrever uma funcao build_* que devolve um
Indicator e registra-lo em `available()`. O resto do sistema (casamento,
estatisticas, interface) nao muda.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import cycle as cycle_mod
from .sources import fear_greed, global_m2, net_liquidity


@dataclass
class Indicator:
    key: str
    label: str
    series: pd.Series
    unit: str
    band_mode: str  # 'abs' | 'rel' | 'circular'
    default_band: float
    band_label: str
    note: str = ""
    last_real_date: pd.Timestamp | None = None
    higher_is: str = ""
    meta: dict = field(default_factory=dict)

    @property
    def current(self) -> float:
        s = self.series.dropna()
        return float(s.iloc[-1]) if len(s) else float("nan")

    @property
    def current_date(self) -> pd.Timestamp | None:
        s = self.series.dropna()
        return s.index[-1] if len(s) else None

    def distance(self, target: float) -> pd.Series:
        """Distancia de cada dia ate `target`, na unidade da banda."""
        if self.band_mode == "circular":
            return cycle_mod.circular_distance(self.series, target, int(self.meta["cycle_days"]))
        if self.band_mode == "rel":
            denom = abs(target) if abs(target) > 1e-9 else 1.0
            return (self.series - target).abs() / denom * 100.0
        return (self.series - target).abs()

    def mask(self, target: float, band: float) -> pd.Series:
        d = self.distance(target)
        return (d <= band).fillna(False)


# ----------------------------------------------------------------- construtores


def build_fng(force: bool = False) -> Indicator:
    s = fear_greed.series(force=force)
    return Indicator(
        key="fng",
        label="Fear & Greed Index",
        series=s,
        unit="pontos (0-100)",
        band_mode="abs",
        default_band=2.0,
        band_label="+/- pontos",
        note="Dado oficial da alternative.me, comeca em 01/02/2018 (~1,5 ciclo).",
        last_real_date=s.dropna().index.max(),
        higher_is="ganancia",
    )


def _delta_indicator(
    base: pd.Series,
    key: str,
    label: str,
    weeks: int,
    lead_days: int,
    note: str,
    last_real: pd.Timestamp | None,
) -> Indicator:
    delta = base.pct_change(weeks * 7) * 100.0
    shifted = delta.shift(lead_days)  # o BTC de hoje responde a liquidez de `lead` dias atras
    return Indicator(
        key=key,
        label=f"{label} - variacao em {weeks} semanas (lead {lead_days}d)",
        series=shifted.rename(key),
        unit="% em " + str(weeks) + " semanas",
        band_mode="abs",
        default_band=0.25,
        band_label="+/- pontos percentuais",
        note=note,
        last_real_date=last_real,
        higher_is="expansao",
        meta={"weeks": weeks, "lead_days": lead_days, "base": base},
    )


def build_global_m2(
    weeks: int = 8,
    lead_days: int = 70,
    components: tuple[str, ...] = global_m2.DEFAULT_COMPONENTS,
    force: bool = False,
) -> Indicator:
    base = global_m2.series(components=components, force=force)
    frame = global_m2.components_usd_tn(force=False)
    last_real = frame[list(components)].dropna(how="all").index.max()
    ind = _delta_indicator(
        base,
        "m2_delta",
        "M2 global (USD)",
        weeks,
        lead_days,
        "M2 de EUA+Zona do Euro+China+Japao+UK convertido a USD, agregado encadeado. "
        "Publicacao mensal com defasagem: o lead de ~70 dias faz o sinal de hoje usar dado ja publicado.",
        last_real,
    )
    ind.meta["components"] = components
    ind.meta["level"] = base
    return ind


def build_net_liquidity(weeks: int = 8, lead_days: int = 70, force: bool = False) -> Indicator:
    base = net_liquidity.series(force=force)
    ind = _delta_indicator(
        base,
        "netliq_delta",
        "Net Liquidity do Fed",
        weeks,
        lead_days,
        "Balanco do Fed - TGA - Reverse Repo (FRED). Semanal/diaria, sem defasagem, desde 2003. So EUA.",
        base.dropna().index.max(),
    )
    ind.meta["level"] = base
    return ind


def build_cycle(
    index: pd.DatetimeIndex,
    anchor: str = "halving",
    cycle_days: int = cycle_mod.DEFAULT_CYCLE_DAYS,
) -> Indicator:
    s = cycle_mod.cycle_day(index, anchor=anchor)
    aviso = ""
    if anchor in ("topo", "fundo"):
        aviso = " ATENCAO: topos e fundos so sao conhecidos depois do fato, entao essa ancora tem vies de retrovisor."
    return Indicator(
        key="cycle",
        label=f"Dia do ciclo (ancora: {anchor})",
        series=s,
        unit="dias desde a ancora",
        band_mode="circular",
        default_band=20.0,
        band_label="+/- dias",
        note=f"Comprimento do ciclo: {cycle_days} dias. Intervalos reais entre halvings: 1319, 1402, 1435.{aviso}",
        last_real_date=s.dropna().index.max(),
        higher_is="fim de ciclo",
        meta={"cycle_days": cycle_days, "anchor": anchor},
    )


def available() -> dict[str, str]:
    """Chave -> rotulo curto, para a interface montar a lista."""
    return {
        "fng": "Fear & Greed",
        "m2_delta": "M2 global",
        "netliq_delta": "Net Liquidity Fed",
        "cycle": "Ciclo do BTC",
    }


def align(ind: Indicator, index: pd.DatetimeIndex) -> Indicator:
    """Reindexa a serie do indicador no calendario do painel."""
    ind.series = ind.series.reindex(index)
    return ind


def current_summary(indicators: dict[str, Indicator]) -> pd.DataFrame:
    rows = []
    for ind in indicators.values():
        v = ind.current
        rows.append(
            {
                "indicador": ind.label,
                "valor_hoje": round(v, 2) if not np.isnan(v) else None,
                "unidade": ind.unit,
                "data_do_valor": ind.current_date.date() if ind.current_date is not None else None,
                "ultimo_dado_real": ind.last_real_date.date() if ind.last_real_date is not None else None,
                "historico_desde": ind.series.dropna().index.min().date() if ind.series.notna().any() else None,
            }
        )
    return pd.DataFrame(rows)
