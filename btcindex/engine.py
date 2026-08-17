"""Junta painel + indicadores + casamento + estatisticas.

A busca de dados (`load_raw`) e separada da montagem dos indicadores
(`build_indicators`) de proposito: mudar semanas, lead ou ancora do ciclo nao
deve custar uma rodada de rede.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace

import pandas as pd

from . import indicators as ind_mod
from . import matcher, panel as panel_mod, stats
from .cycle import DEFAULT_CYCLE_DAYS
from .sources import btc_price, fear_greed, fred, global_m2, mvrv


# Lead verdadeiro medido: o pico da correlacao cruzada entre a variacao de 8
# semanas da liquidez e a variacao de 8 semanas do BTC fica em +91 dias, tanto
# para o M2 global quanto para o juro real. E o numero centro a centro, nao o
# shift bruto - ver shift_para_janela().
LEAD_PADRAO = 91


@dataclass
class Params:
    windows: dict[str, int] = field(default_factory=lambda: dict(panel_mod.WINDOWS))
    m2_lead: int = LEAD_PADRAO  # deslocamento em dias, so para o grafico
    m2_components: tuple[str, ...] = global_m2.DEFAULT_COMPONENTS
    cycle_anchor: str = "halving"
    cycle_days: int = DEFAULT_CYCLE_DAYS
    align_lead: bool = True
    ref_window: str = "3m"


def shift_para_janela(lead: int, janela_dias: int, horizonte_dias: int) -> int:
    """Converte um lead centro a centro no deslocamento que a serie precisa.

    A janela de variacao ja olha para tras: um delta de 8 semanas terminando em
    tau tem centro de massa em tau-28d. O retorno futuro de horizonte H tem
    centro em t+H/2. Entao o lead efetivo e

        lead = shift + janela/2 + horizonte/2

    e o shift que realiza um lead alvo encolhe conforme o horizonte cresce.
    Aplicar um shift fixo de 70 dias a todas as janelas, como era antes, testava
    na pratica 20 semanas de lead na janela de 12 meses - muito alem do efeito
    real, o que apagava o sinal.
    """
    return max(0, int(round(lead - janela_dias / 2 - horizonte_dias / 2)))


def lead_efetivo(shift: int, janela_dias: int, horizonte_dias: int) -> int:
    """O caminho inverso: qual lead centro a centro um shift bruto representa."""
    return int(round(shift + janela_dias / 2 + horizonte_dias / 2))


@dataclass
class RawData:
    btc: pd.Series
    fng: pd.Series
    m2_components: pd.DataFrame
    mvrv_z: pd.Series
    fetched_at: pd.Timestamp


# series do FRED usadas direto pelo painel (a da China e buscada dentro do
# proprio fetcher dela, entao fica de fora para dois threads nao escreverem o
# mesmo arquivo de cache)
FRED_SERIES = ("WM2NS", "DEXUSEU", "DEXCHUS", "DEXJPUS", "DEXUSUK")


def prefetch(force: bool = False, max_workers: int = 12) -> dict[str, str]:
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
        "mvrv": lambda: mvrv.fetch(force=force),
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
        mvrv_z=mvrv.zscore(),
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

    mvrv_ind = ind_mod.Indicator(
        key="mvrv_z",
        label="MVRV Z-score",
        series=raw.mvrv_z,
        unit="desvios-padrao",
        band_mode="abs",
        default_band=0.15,
        band_label="+/- z",
        note="(valor de mercado - valor realizado) / desvio-padrao expansivo do valor de mercado, "
        "com dados da Coin Metrics desde 2011. O valor realizado precifica cada moeda pela ultima "
        "vez que ela se moveu, entao o indicador mede lucro nao realizado do mercado inteiro. "
        "O desvio-padrao usa so o passado ate cada data - usar o da serie inteira embutiria "
        "informacao do futuro e inflaria o backtest. Cuidado: e parcialmente colinear com o dia "
        "do ciclo, entao os dois juntos na composta cortam menos do que parece.",
        last_real_date=raw.mvrv_z.dropna().index.max(),
    )
    inds["mvrv_z"] = ind_mod.align(mvrv_ind, index)

    inds["cycle"] = ind_mod.build_cycle(index, anchor=p.cycle_anchor, cycle_days=p.cycle_days)
    return inds


def _indicador_de_variacao(key, nome, base, weeks, lead, unidade, banda_padrao,
                           rotulo_banda, note, last_real, p, index, extra=None):
    """Monta um indicador de variacao com o lead ja resolvido para a janela de referencia.

    A serie sem deslocamento fica em meta['delta_base'] para que a analise possa
    reancorar o shift em cada janela (ver indicador_para_janela).
    """
    janela = weeks * 7
    base = base.reindex(index)
    horizonte_ref = p.windows.get(p.ref_window, 91)
    shift = shift_para_janela(lead, janela, horizonte_ref) if p.align_lead else lead
    rotulo_lead = (f"lead {lead}d centro a centro -> shift {shift}d" if p.align_lead
                   else f"shift bruto {shift}d")
    return ind_mod.Indicator(
        key=key,
        label=f"{nome} - variacao em {weeks}s ({rotulo_lead})",
        series=base.shift(shift),
        unit=unidade,
        band_mode="abs",
        default_band=banda_padrao,
        band_label=rotulo_banda,
        note=note,
        last_real_date=last_real,
        meta={
            "weeks": weeks,
            "window_days": janela,
            "lead_days": lead,
            "align_lead": p.align_lead,
            "shift_aplicado": shift,
            "delta_base": base,
            **(extra or {}),
        },
    )


def indicador_para_janela(ind: ind_mod.Indicator, horizonte_dias: int) -> ind_mod.Indicator:
    """Reancora o shift do indicador para um horizonte especifico.

    Indicadores sem lead (Fear & Greed, ciclo) voltam inalterados.
    """
    if not ind.meta.get("align_lead") or "delta_base" not in ind.meta:
        return ind
    shift = shift_para_janela(ind.meta["lead_days"], ind.meta["window_days"], horizonte_dias)
    if shift == ind.meta.get("shift_aplicado"):
        return ind
    return replace(
        ind,
        series=ind.meta["delta_base"].shift(shift),
        meta={**ind.meta, "shift_aplicado": shift},
    )


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
    align_lead: bool = False,
    ref_window: str | None = None,
    locked: dict[str, bool] | None = None,
) -> tuple[pd.DataFrame, matcher.MatchResult, pd.DataFrame]:
    """Casa o passado com os alvos e resume as janelas futuras.

    Com align_lead, cada janela recebe seu proprio shift (e portanto sua propria
    amostra), porque o lead centro a centro correto depende do horizonte. Os
    graficos e a lista de episodios usam a janela de referencia.
    """
    scope = df if date_range is None else df.loc[date_range[0] : date_range[1]]
    tem_lead = any(i.meta.get("align_lead") and "delta_base" in i.meta for i in selected.values())

    if not (align_lead and tem_lead):
        longest = anchor_window or max(windows, key=lambda k: windows[k])
        res = matcher.match(
            selected, targets, bands, df, min_n=min_n, relax=relax,
            window_col=f"fwd_{longest}", date_range=date_range,
            max_factor=max_factor, fixed_factor=fixed_factor,
        )
        table = stats.summarize(scope, res.mask, windows, gap_days=gap_days)
        detalhe = pd.DataFrame([
            {"janela": h, "indicador": i.label, "shift (d)": i.meta.get("shift_aplicado", 0),
             "alvo": round(targets[k], 3), "banda": round(res.bands_used[k], 3)}
            for h in windows for k, i in selected.items()
        ])
        return table, res, detalhe

    ref = ref_window if ref_window in windows else list(windows)[0]
    locked = locked or {}
    linhas, detalhes, res_ref = [], [], None
    for h, dias in windows.items():
        sel_h = {k: indicador_para_janela(i, dias) for k, i in selected.items()}
        # alvo travado acompanha o valor de hoje, que muda junto com o shift
        alvos_h = {
            k: (float(sel_h[k].current) if locked.get(k, True) else targets[k])
            for k in sel_h
        }
        res_h = matcher.match(
            sel_h, alvos_h, bands, df, min_n=min_n, relax=relax,
            window_col=f"fwd_{h}", date_range=date_range,
            max_factor=max_factor, fixed_factor=fixed_factor,
        )
        linhas.append(stats.summarize(scope, res_h.mask, {h: dias}, gap_days=gap_days).iloc[0])
        for k, i in sel_h.items():
            shift = i.meta.get("shift_aplicado", 0)
            detalhes.append({
                "janela": h,
                "indicador": i.label.split(" - ")[0],
                "shift (d)": shift,
                "lead alvo (d)": i.meta.get("lead_days"),
                "lead efetivo (d)": (lead_efetivo(shift, i.meta["window_days"], dias)
                                     if "window_days" in i.meta else None),
                "alvo": round(alvos_h[k], 3),
                "banda": round(res_h.bands_used[k], 3),
            })
        if h == ref:
            res_ref = res_h

    return pd.DataFrame(linhas).reset_index(drop=True), res_ref, pd.DataFrame(detalhes)


def holder(df: pd.DataFrame, windows: dict[str, int], date_range=None) -> pd.DataFrame:
    """Benchmark: comprar em qualquer dia do periodo e segurar.

    E a referencia contra a qual todo indicador tem que se justificar - sem ela,
    um "mediana de +34% em 12 meses" parece otimo ate voce descobrir que o
    bitcoin fez +80% em 12 meses partindo de um dia qualquer.
    """
    scope = df if date_range is None else df.loc[date_range[0] : date_range[1]]
    return stats.summarize(scope, pd.Series(True, index=scope.index), windows, gap_days=10**6)


def m2_ultimo_dado_real(raw: RawData, componentes=None) -> pd.Timestamp:
    """Ultima data em que algum componente do M2 foi de fato publicado."""
    comps = [c for c in (componentes or raw.m2_components.columns) if c in raw.m2_components.columns]
    return raw.m2_components[comps].dropna(how="all").index.max()


def m2_para_grafico(raw: RawData, componentes=None, lead_dias: int = 0) -> pd.Series:
    """Nivel do M2 global em US$ trilhoes, deslocado `lead_dias` para a frente.

    Deslocar para a frente e o que materializa a tese: o M2 de hoje aparece no
    grafico na data em que se espera que o bitcoin reaja a ele.

    A serie e cortada no ultimo dado realmente publicado. O agregado diario e
    preenchido por repeticao ate hoje para as contas internas, mas desenhar esse
    trecho seria mostrar uma linha chapada de varias semanas com cara de previsao
    de estagnacao, quando e apenas ausencia de dado.
    """
    comps = [c for c in (componentes or raw.m2_components.columns) if c in raw.m2_components.columns]
    nivel = global_m2.chain_link(raw.m2_components[comps])
    nivel = nivel.loc[: m2_ultimo_dado_real(raw, comps)]
    if lead_dias:
        nivel = nivel.copy()
        nivel.index = nivel.index + pd.Timedelta(days=int(lead_dias))
    return nivel.rename("m2_global_usd_tn")
