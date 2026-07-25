"""Junta painel + indicadores + casamento + estatisticas.

A busca de dados (`load_raw`) e separada da montagem dos indicadores
(`build_indicators`) de proposito: mudar semanas, lead ou ancora do ciclo nao
deve custar uma rodada de rede.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import pandas as pd

from . import indicators as ind_mod
from . import matcher, panel as panel_mod, stats
from .cycle import DEFAULT_CYCLE_DAYS
from .sources import btc_price, fear_greed, fred, global_m2, net_liquidity


@dataclass
class Params:
    windows: dict[str, int] = field(default_factory=lambda: dict(panel_mod.WINDOWS))
    m2_weeks: int = 8
    m2_lead: int = 70
    m2_components: tuple[str, ...] = global_m2.DEFAULT_COMPONENTS
    netliq_weeks: int = 8
    netliq_lead: int = 70
    cycle_anchor: str = "halving"
    cycle_days: int = DEFAULT_CYCLE_DAYS


@dataclass
class RawData:
    btc: pd.Series
    fng: pd.Series
    m2_components: pd.DataFrame
    netliq: pd.Series
    fetched_at: pd.Timestamp


# series do FRED usadas direto pelo painel (a da China e buscada dentro do
# proprio fetcher dela, entao fica de fora para dois threads nao escreverem o
# mesmo arquivo de cache)
FRED_SERIES = ("WM2NS", "DEXUSEU", "DEXCHUS", "DEXJPUS", "DEXUSUK", "WALCL", "WTREGEN", "RRPONTSYD")


def prefetch(force: bool = False, max_workers: int = 14) -> dict[str, str]:
    """Aquece o cache de todas as fontes em paralelo.

    Sao 14 fontes independentes; em fila custam ~36s, em paralelo ~4s. Cada
    tarefa escreve seu proprio arquivo de cache, entao nao ha disputa. O TTL de
    cada fonte continua valendo: o que estiver fresco nao vai a rede.

    Devolve as falhas por fonte; nao levanta excecao, porque cada consumidor
    ainda tem seu proprio fallback para cache antigo.
    """
    tarefas = {
        "btc_price": lambda: btc_price.fetch(force=force),
        "fear_greed": lambda: fear_greed.fetch(force=force),
        "ecb_m2": lambda: global_m2._ea_m2_eur_tn(force),
        "china_m2": lambda: global_m2._cn_m2_cny_tn(force),
        "japan_m2": lambda: global_m2._jp_m2_jpy_tn(force),
        "uk_m4": lambda: global_m2._uk_m4_gbp_tn(force),
    }
    for sid in FRED_SERIES:
        tarefas[f"fred_{sid}"] = lambda sid=sid: fred.series(sid, force=force)

    falhas: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futuros = {nome: ex.submit(fn) for nome, fn in tarefas.items()}
        for nome, fut in futuros.items():
            try:
                fut.result()
            except Exception as exc:  # noqa: BLE001
                falhas[nome] = str(exc)
                print(f"[aviso] prefetch de {nome} falhou: {exc}")
    return falhas


def load_raw(force: bool = False) -> RawData:
    prefetch(force=force)  # a partir daqui tudo vem do cache, sem rede
    return RawData(
        btc=btc_price.close_series(),
        fng=fear_greed.series(),
        m2_components=global_m2.components_usd_tn(),
        netliq=net_liquidity.series(),
        fetched_at=pd.Timestamp.now(),
    )


def build_panel(raw: RawData, windows: dict[str, int]) -> pd.DataFrame:
    df = pd.DataFrame({"btc_close": raw.btc})
    for label, days in windows.items():
        df[f"fwd_{label}"] = raw.btc.shift(-days) / raw.btc - 1.0
    return df


def build_indicators(raw: RawData, p: Params, index: pd.DatetimeIndex) -> dict[str, ind_mod.Indicator]:
    inds: dict[str, ind_mod.Indicator] = {}

    fng = ind_mod.Indicator(
        key="fng",
        label="Fear & Greed Index",
        series=raw.fng,
        unit="pontos (0-100)",
        band_mode="abs",
        default_band=2.0,
        band_label="+/- pontos",
        note="Dado oficial da alternative.me; comeca em 01/02/2018 (~1,5 ciclo de historico).",
        last_real_date=raw.fng.dropna().index.max(),
    )
    inds["fng"] = ind_mod.align(fng, index)

    comps = [c for c in p.m2_components if c in raw.m2_components.columns]
    m2_level = global_m2.chain_link(raw.m2_components[comps])
    m2_last_real = raw.m2_components[comps].dropna(how="all").index.max()
    m2 = ind_mod.Indicator(
        key="m2_delta",
        label=f"M2 global - variacao em {p.m2_weeks}s (lead {p.m2_lead}d)",
        series=(m2_level.pct_change(p.m2_weeks * 7) * 100).shift(p.m2_lead),
        unit=f"% em {p.m2_weeks} semanas",
        band_mode="abs",
        default_band=0.25,
        band_label="+/- pontos percentuais",
        note="M2 de " + "+".join(comps) + " em USD, agregado encadeado. Publicacao mensal com defasagem; "
        "o lead desloca o sinal para tras, entao o valor de hoje costuma usar dado ja publicado.",
        last_real_date=m2_last_real,
        meta={"weeks": p.m2_weeks, "lead_days": p.m2_lead, "level": m2_level, "components": tuple(comps)},
    )
    inds["m2_delta"] = ind_mod.align(m2, index)

    nl = ind_mod.Indicator(
        key="netliq_delta",
        label=f"Net Liquidity Fed - variacao em {p.netliq_weeks}s (lead {p.netliq_lead}d)",
        series=(raw.netliq.pct_change(p.netliq_weeks * 7) * 100).shift(p.netliq_lead),
        unit=f"% em {p.netliq_weeks} semanas",
        band_mode="abs",
        default_band=1.0,
        band_label="+/- pontos percentuais",
        note="Balanco do Fed - TGA - Reverse Repo (FRED). Semanal/diaria, sem defasagem, desde 2003. So EUA.",
        last_real_date=raw.netliq.dropna().index.max(),
        meta={"weeks": p.netliq_weeks, "lead_days": p.netliq_lead, "level": raw.netliq},
    )
    inds["netliq_delta"] = ind_mod.align(nl, index)

    inds["cycle"] = ind_mod.build_cycle(index, anchor=p.cycle_anchor, cycle_days=p.cycle_days)
    return inds


def load(params: Params | None = None, force: bool = False):
    p = params or Params()
    raw = load_raw(force=force)
    df = build_panel(raw, p.windows)
    return df, build_indicators(raw, p, df.index)


def effective_date(ind: ind_mod.Indicator, date: pd.Timestamp) -> pd.Timestamp:
    """Data do dado subjacente que alimenta o valor do indicador em `date`."""
    lead = int(ind.meta.get("lead_days", 0))
    return date - pd.Timedelta(days=lead)


def stale_warning(ind: ind_mod.Indicator, date: pd.Timestamp) -> str | None:
    """Avisa quando o valor 'de hoje' depende de extrapolacao da fonte."""
    if ind.last_real_date is None or "lead_days" not in ind.meta:
        return None
    eff = effective_date(ind, date)
    if eff > ind.last_real_date:
        atraso = (eff - ind.last_real_date).days
        return (
            f"{ind.label}: o valor de hoje usa dado de {eff.date()}, mas a fonte so publicou ate "
            f"{ind.last_real_date.date()} ({atraso} dias extrapolados por repeticao do ultimo valor)."
        )
    return None


def analyse(
    df: pd.DataFrame,
    selected: dict[str, ind_mod.Indicator],
    targets: dict[str, float],
    bands: dict[str, float],
    windows: dict[str, int],
    min_n: int = 30,
    relax: bool = True,
    gap_days: int = 45,
    date_range: tuple[pd.Timestamp, pd.Timestamp] | None = None,
    anchor_window: str | None = None,
    max_factor: float = 10.0,
    fixed_factor: float | None = None,
) -> tuple[pd.DataFrame, matcher.MatchResult]:
    longest = anchor_window or max(windows, key=lambda k: windows[k])
    res = matcher.match(
        selected,
        targets,
        bands,
        df,
        min_n=min_n,
        relax=relax,
        window_col=f"fwd_{longest}",
        date_range=date_range,
        max_factor=max_factor,
        fixed_factor=fixed_factor,
    )
    scope = df if date_range is None else df.loc[date_range[0] : date_range[1]]
    table = stats.summarize(scope, res.mask, windows, gap_days=gap_days)
    return table, res


def baseline(df: pd.DataFrame, windows: dict[str, int], date_range=None) -> pd.DataFrame:
    scope = df if date_range is None else df.loc[date_range[0] : date_range[1]]
    return stats.summarize(scope, pd.Series(True, index=scope.index), windows, gap_days=10**6)
