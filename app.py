"""BTC INDEX - interface Streamlit.

Rodar:  streamlit run app.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from btcindex import cycle as cycle_mod
from btcindex import engine
from btcindex.sources import global_m2
from btcindex.stats import episode_table, episodes

st.set_page_config(page_title="BTC INDEX", page_icon="B", layout="wide")

COLORS = {"match": "#e8833a", "base": "#8892a6", "up": "#2e9e6b", "down": "#c0392b"}


# --------------------------------------------------------------------- dados
@st.cache_data(ttl=6 * 3600, show_spinner="Buscando dados nas fontes...")
def get_raw(token: int) -> engine.RawData:
    return engine.load_raw(force=token > 0)


def sidebar_controls(raw: engine.RawData):
    st.sidebar.header("Dados")
    if st.sidebar.button("Atualizar dados agora", width="stretch"):
        st.cache_data.clear()
        st.session_state["token"] = st.session_state.get("token", 0) + 1
        st.rerun()
    st.sidebar.caption(f"Carregado em {raw.fetched_at:%d/%m/%Y %H:%M}")

    st.sidebar.header("Janelas de retorno (dias corridos)")
    c1, c2 = st.sidebar.columns(2)
    windows = {
        "1m": c1.number_input("1 mes", 5, 400, 30, 1),
        "3m": c2.number_input("3 meses", 10, 500, 91, 1),
        "6m": c1.number_input("6 meses", 20, 800, 182, 1),
        "12m": c2.number_input("12 meses", 30, 1200, 365, 1),
    }

    st.sidebar.header("Amostra")
    min_year = 2012
    start = st.sidebar.date_input(
        "Considerar historico a partir de",
        value=pd.Timestamp("2015-01-01"),
        min_value=pd.Timestamp(f"{min_year}-01-01"),
        max_value=pd.Timestamp.today(),
        help="Retornos de 2012-2014 sao de outra ordem de grandeza e distorcem as medias.",
    )
    gap = st.sidebar.number_input(
        "Intervalo minimo entre episodios (dias)", 5, 365, 45, 5,
        help="Dias casados separados por menos que isso contam como um mesmo episodio.",
    )

    st.sidebar.header("Fator das bandas")
    modo = st.sidebar.radio(
        "Modo",
        ["Automatico ate um teto", "Fator fixo", "Sem relaxamento"],
        key="modo_fator",
        help="O fator multiplica TODAS as bandas ao mesmo tempo. 2x com banda de +/-2 pontos "
             "no Fear & Greed vira +/-4 pontos.",
    )
    cfg = {"min_n": 30, "relax": True, "max_factor": 10.0, "fixed": None}
    if modo == "Automatico ate um teto":
        cfg["min_n"] = int(st.sidebar.number_input("N minimo de dias na amostra", 5, 500, 30, 5))
        cfg["max_factor"] = float(st.sidebar.slider(
            "Teto do fator", 1.0, 20.0, 5.0, 0.25,
            help="A busca sobe pelos degraus 1; 1,25; 1,5; 2; 2,5; 3; 4; 5; 7; 10 e para no primeiro "
                 "que alcanca o N minimo, sem nunca passar deste teto.",
        ))
    elif modo == "Fator fixo":
        cfg["fixed"] = float(st.sidebar.slider(
            "Fator aplicado as bandas", 0.25, 20.0, 1.0, 0.25,
            help="Abaixo de 1 aperta as bandas em vez de alargar.",
        ))
        st.sidebar.caption("Nesse modo o N minimo nao se aplica: vale exatamente o fator escolhido.")
    else:
        cfg["relax"] = False
        st.sidebar.caption("As bandas valem como voce configurou, mesmo que a amostra fique minuscula.")

    return windows, pd.Timestamp(start), int(gap), cfg


LARGURAS = {"quartil (+/-12,5)": 12.5, "quintil (+/-10)": 10.0, "decil (+/-5)": 5.0}


def controle_banda(key: str, padrao_abs: float, rotulo_abs: str, minimo: float, maximo: float,
                   passo: float) -> tuple[str, float]:
    """Banda em unidade absoluta ou em posicao na distribuicao.

    O modo percentil existe porque sinais fracos e monotonicos (liquidez, juro)
    nao aparecem numa banda estreita em torno de um valor: o que informa e em que
    parte da distribuicao o dia de hoje esta.
    """
    tipo = st.radio("Tipo de banda", ["absoluta", "percentil"], key=f"bt_{key}", horizontal=True,
                    help="Percentil compara a POSICAO de hoje na distribuicao: +/-12,5 pontos "
                         "percentuais e exatamente a largura de um quartil.")
    if tipo == "absoluta":
        return "abs", st.number_input(rotulo_abs, minimo, maximo, padrao_abs, passo, key=f"b_{key}")

    largura = st.selectbox("Largura", [*LARGURAS, "personalizado"], key=f"bp_{key}")
    if largura == "personalizado":
        return "pct", st.number_input("Banda +/- pontos percentuais de posicao", 0.5, 50.0, 12.5,
                                      0.5, key=f"bpc_{key}")
    return "pct", LARGURAS[largura]


def indicator_controls(raw: engine.RawData):
    st.sidebar.header("Indicadores")
    p = engine.Params()

    with st.sidebar.expander("Fear & Greed", expanded=True):
        use_fng = st.checkbox("Usar", value=True, key="use_fng")
        modo_fng, band_fng = controle_banda("fng", 2.0, "Banda +/- pontos", 0.5, 50.0, 0.5)

    with st.sidebar.expander("MVRV Z-score", expanded=True):
        use_mv = st.checkbox("Usar", value=True, key="use_mv")
        modo_mv, band_mv = controle_banda("mv", 0.15, "Banda +/- z", 0.01, 5.0, 0.05)

    with st.sidebar.expander("Ciclo do BTC", expanded=True):
        use_cy = st.checkbox("Usar", value=True, key="use_cy")
        p.cycle_anchor = st.selectbox("Ancora", ["halving", "topo", "fundo"], key="cya")
        p.cycle_days = st.number_input("Comprimento do ciclo (dias)", 900, 2000,
                                       cycle_mod.DEFAULT_CYCLE_DAYS, 5, key="cyd")
        band_cy = st.number_input("Banda +/- dias", 1.0, 200.0, 20.0, 1.0, key="b_cy")

    st.sidebar.header("M2 global (so grafico)")
    st.sidebar.caption("O M2 nao entra em nenhuma analise: ele so e desenhado sobre o preco.")
    p.m2_lead = st.sidebar.number_input(
        "Deslocamento do M2 (dias)", 0, 400, engine.LEAD_PADRAO, 7, key="m2l",
        help="Quantos dias o M2 e empurrado para a frente no grafico.",
    )
    comps = st.sidebar.multiselect(
        "Paises no agregado",
        list(global_m2.DEFAULT_COMPONENTS),
        default=list(global_m2.DEFAULT_COMPONENTS),
        format_func=lambda c: global_m2.COMPONENT_LABELS[c],
        key="m2c",
    )
    p.m2_components = tuple(comps) if comps else global_m2.DEFAULT_COMPONENTS

    use = {"fng": use_fng, "mvrv_z": use_mv, "cycle": use_cy}
    bands = {"fng": band_fng, "mvrv_z": band_mv, "cycle": band_cy}
    modos = {"fng": modo_fng, "mvrv_z": modo_mv, "cycle": "circular"}
    return p, use, bands, modos


# -------------------------------------------------------------------- graficos
def price_chart(df: pd.DataFrame, dates: pd.DatetimeIndex, title: str) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.index, y=df["btc_close"], name="BTC", line=dict(color=COLORS["base"], width=1)))
    if len(dates):
        sel = df.loc[df.index.isin(dates)]
        fig.add_trace(
            go.Scatter(x=sel.index, y=sel["btc_close"], name="dias casados", mode="markers",
                       marker=dict(color=COLORS["match"], size=4))
        )
    fig.update_layout(title=title, yaxis_type="log", height=380, margin=dict(l=10, r=10, t=40, b=10),
                      legend=dict(orientation="h", y=1.12))
    return fig


JANELAS_M2 = {"90 dias": 90, "180 dias": 180, "1 ano": 365, "2 anos": 730,
              "5 anos": 1825, "todo o historico": None}


def m2_chart(btc: pd.Series, m2: pd.Series, lead: int, dias: int | None,
             inicio_amostra: pd.Timestamp) -> go.Figure:
    """M2 global deslocado sobre o preco do BTC, eixo duplo.

    A serie do M2 e cortada em duas: solida ate hoje (o que ja da para conferir
    contra o preco) e tracejada dali para a frente (a parte que e projecao). Sem
    essa separacao o olho le a projecao como se fosse historico.
    """
    hoje = btc.index.max()
    inicio = inicio_amostra if dias is None else hoje - pd.Timedelta(days=int(dias))
    b = btc.loc[inicio:]
    m = m2.loc[inicio:]
    observado, projetado = m.loc[:hoje], m.loc[hoje:]

    # log so ganha algo quando o preco varia varias vezes dentro da janela
    escala = "log" if (dias is None or dias > 730) else "linear"

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=b.index, y=b.values, name="BTC",
                             line=dict(color=COLORS["base"], width=1.6)))
    fig.add_trace(go.Scatter(x=observado.index, y=observado.values, yaxis="y2",
                             name=f"M2 global +{lead}d",
                             line=dict(color=COLORS["match"], width=2.2)))
    if len(projetado) > 1:
        fig.add_trace(go.Scatter(x=projetado.index, y=projetado.values, yaxis="y2",
                                 name="M2 projetado",
                                 line=dict(color=COLORS["match"], width=2.2, dash="dash")))
        # add_vline com anotacao quebra no plotly 6.x quando x e um Timestamp
        # (faz aritmetica de inteiro com a data); shape + annotation separados evitam isso
        fig.add_shape(type="line", x0=hoje, x1=hoje, xref="x", yref="paper", y0=0, y1=1,
                      line=dict(color="#888", width=1, dash="dot"))
        fig.add_annotation(x=hoje, y=1.02, xref="x", yref="paper", text="hoje",
                           showarrow=False, font=dict(size=11, color="#888"))

    fim = max(b.index.max(), m.index.max())
    fig.update_layout(
        height=520, margin=dict(l=10, r=10, t=40, b=10),
        title=f"M2 global deslocado {lead} dias para a frente sobre o preco do BTC",
        xaxis=dict(range=[inicio, fim]),
        yaxis=dict(title="BTC (US$)", type=escala),
        yaxis2=dict(title="M2 global (US$ tri)", overlaying="y", side="right", showgrid=False),
        legend=dict(orientation="h", y=1.1),
    )
    return fig


def indicator_chart(ind, target: float, band: float, start: pd.Timestamp) -> go.Figure:
    s = ind.series.loc[start:].dropna()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=s.index, y=s.values, name=ind.key, line=dict(color=COLORS["base"], width=1.2)))
    fig.add_hrect(y0=target - band, y1=target + band, fillcolor=COLORS["match"], opacity=0.18, line_width=0)
    fig.add_hline(y=target, line_color=COLORS["match"], line_dash="dash")
    fig.update_layout(title=f"{ind.label} ({ind.unit})", height=300, margin=dict(l=10, r=10, t=40, b=10),
                      showlegend=False)
    return fig


def funnel(active, targets, bands_used, index, gap):
    """Quantos dias sobram a cada indicador adicionado ao 'E'.

    Entra do menos para o mais restritivo, entao a linha em que o numero despenca
    mostra qual criterio esta estrangulando a amostra.
    """
    masks = {k: ind.mask(targets[k], bands_used[k]).reindex(index, fill_value=False)
             for k, ind in active.items()}
    ordem = sorted(masks, key=lambda k: int(masks[k].sum()), reverse=True)

    rows, cum, anterior = [], pd.Series(True, index=index), len(index)
    retencao = {}
    for k in ordem:
        ind = active[k]
        cum = cum & masks[k]
        n = int(cum.sum())
        # o gargalo e quem corta mais do que sobrou, nao quem corta mais em termos
        # absolutos - o primeiro filtro sempre parece grande porque parte do universo inteiro
        retencao[ind.label] = n / anterior if anterior else 0.0
        rows.append({
            "passo": f"+ {ind.label}",
            "criterio": f"{targets[k]:.2f} +/- {bands_used[k]:.2f}",
            "dias sozinho": int(masks[k].sum()),
            "dias apos o E": n,
            "episodios": len(episodes(cum[cum].index, gap_days=gap)),
            "sobrou do passo anterior": f"{(n / anterior * 100) if anterior else 0:.0f}%",
        })
        anterior = n
    cabeca = {"passo": "universo do periodo", "criterio": "sem filtro", "dias sozinho": len(index),
              "dias apos o E": len(index), "episodios": 1, "sobrou do passo anterior": "100%"}
    gargalo = min(retencao, key=retencao.get) if retencao else "-"
    return pd.DataFrame([cabeca] + rows), gargalo


def tabela_holder(panel: pd.DataFrame, windows: dict, date_range) -> pd.DataFrame:
    """Comprar em qualquer dia do periodo e segurar - a referencia a bater."""
    h = engine.holder(panel, windows, date_range)
    h.attrs = {}  # carregam Timestamps que o Arrow nao serializa
    return h[["janela", "n_dias", "media_%", "mediana_%", "desvio_%", "p10_%", "p90_%",
              "acerto_%"]].rename(columns={
        "janela": "Janela", "n_dias": "Dias", "media_%": "Media %", "mediana_%": "Mediana %",
        "desvio_%": "Desvio %", "p10_%": "P10 %", "p90_%": "P90 %", "acerto_%": "Positivos %"})


def mostrar_lead(det: pd.DataFrame, align: bool):
    """Mostra o shift de cada janela e avisa quando o lead alvo e inalcancavel.

    Um horizonte de 6 meses ja consome 91 dias so na sua metade, entao nenhum
    shift consegue entregar um lead de 91 dias nessa janela: o shift satura em
    zero e o lead efetivo estoura. Melhor dizer isso do que devolver um numero
    com cara de alinhado.
    """
    if not align or det.empty or "lead efetivo (d)" not in det:
        return
    d = det.dropna(subset=["lead efetivo (d)"])
    if d.empty:
        return
    with st.expander("Lead aplicado em cada janela"):
        st.dataframe(d, hide_index=True, width="stretch")
    fora = d[d["lead efetivo (d)"] > d["lead alvo (d)"] + 7]
    if not fora.empty:
        js = ", ".join(dict.fromkeys(fora["janela"]))
        st.warning(
            f"Janelas {js}: o horizonte e longo demais para o lead pedido; o shift saturou em zero "
            f"e o lead efetivo chega a {int(fora['lead efetivo (d)'].max())} dias. "
            "Nessas janelas o indicador de liquidez esta fora de alinhamento - trate os numeros "
            "como descritivos, nao como teste do efeito de lead."
        )


def show_table(table: pd.DataFrame):
    cols = ["janela", "n_dias", "n_episodios", "media_%", "mediana_%", "desvio_%",
            "p10_%", "p90_%", "acerto_%", "holder_mediana_%", "vantagem_pp"]
    nice = table[[c for c in cols if c in table]].rename(columns={
        "janela": "Janela", "n_dias": "Dias", "n_episodios": "Episodios", "media_%": "Media %",
        "mediana_%": "Mediana %", "desvio_%": "Desvio %", "p10_%": "P10 %", "p90_%": "P90 %",
        "acerto_%": "Positivos %", "holder_mediana_%": "Holder mediana %",
        "vantagem_pp": "Vantagem p.p.",
    })
    nice.attrs = {}  # os attrs carregam Timestamps que o Arrow nao serializa
    st.dataframe(nice, hide_index=True, width="stretch")


def match_caption(res, inds, bands, cfg):
    txt = " | ".join(f"{ind.label}: +/-{res.bands_used[k]:.2f}" for k, ind in inds.items())

    if cfg.get("fixed") is not None:
        msg = f"Fator fixo de {res.factor:.2f}x (N minimo nao se aplica). Bandas: {txt}"
        (st.caption if res.factor == 1.0 else st.info)(msg)
        if res.n_days_with_window < 1:
            st.error("Nenhum dia casado tem retorno futuro conhecido nessa janela.")
        return

    if res.exhausted and res.n_days_with_window < 1:
        st.error(
            f"Nenhum dia do passado casa com esses criterios, nem no teto de {cfg['max_factor']:.2f}x. "
            f"Bandas finais: {txt}"
        )
    elif res.exhausted:
        st.warning(
            f"Amostra abaixo do N minimo no teto de {cfg['max_factor']:.2f}x "
            f"({res.n_days} dias casados). Trate os numeros como indicativos ou suba o teto. "
            f"Bandas finais: {txt}"
        )
    elif res.relaxed:
        st.info(f"Bandas alargadas em {res.factor:.2f}x para alcancar o N minimo. Bandas usadas: {txt}")
    else:
        st.caption(f"Bandas originais, sem relaxamento. {txt}")


# ------------------------------------------------------------------------ app
def main():
    token = st.session_state.get("token", 0)
    raw = get_raw(token)

    windows, start, gap, cfg = sidebar_controls(raw)
    params, use, bands, modos = indicator_controls(raw)
    params.windows = windows

    panel = engine.build_panel(raw, windows)
    inds = engine.build_indicators(raw, params, panel.index)
    for k, modo in modos.items():
        if k in inds and modo != "circular":
            inds[k].band_mode = modo
    today = panel.index.max()
    date_range = (start, today)

    st.title("BTC INDEX")
    st.caption(
        "Como o bitcoin se comportou em 1, 3, 6 e 12 meses a partir dos dias do passado em que "
        "os indicadores estavam como estao hoje."
    )

    # --------------------------------------------------------- cartoes de hoje
    m2 = engine.m2_para_grafico(raw, params.m2_components, params.m2_lead)
    cards = st.columns(4)
    cards[0].metric("BTC", f"US$ {panel['btc_close'].iloc[-1]:,.0f}",
                    f"{(panel['btc_close'].iloc[-1] / panel['btc_close'].iloc[-31] - 1) * 100:+.1f}% em 30d")
    from btcindex.sources.fear_greed import classify
    fng_v = inds["fng"].current
    cards[1].metric("Fear & Greed", f"{fng_v:.0f}", classify(fng_v))
    mv = inds["mvrv_z"].current
    cards[2].metric("MVRV Z-score", f"{mv:.2f}",
                    "lucro nao realizado" if mv > 0 else "mercado no prejuizo")
    cd = inds["cycle"].current
    cards[3].metric("Dia do ciclo", f"{cd:.0f}", f"{cd / params.cycle_days * 100:.0f}% do ciclo")

    # ------------------------------------------------------------------- alvos
    st.sidebar.header("Alvos")
    st.sidebar.caption(
        "Travado = o alvo acompanha o valor de hoje e muda junto com os parametros. "
        "Destrave so para simular um cenario hipotetico."
    )
    targets, locked = {}, {}
    escopo = panel.loc[start:].index
    for key, ind in inds.items():
        if not use[key]:
            continue
        cur = float(ind.current)
        lock = st.sidebar.checkbox(f"{ind.label}: usar valor de hoje", value=True, key=f"lock_{key}")
        locked[key] = lock
        if lock:
            targets[key] = cur
            pct = ind.percentil(cur, escopo)
            st.sidebar.caption(f"alvo = {cur:.3f} ({ind.unit}) | percentil {pct:.0f}")
        else:
            # a chave carrega o valor de hoje: se um parametro mudar o valor atual,
            # nasce um widget novo ja inicializado no numero certo, em vez de o
            # Streamlit reaproveitar o valor velho guardado no session_state
            targets[key] = st.sidebar.number_input(
                f"Alvo simulado - {ind.label}",
                value=round(cur, 3),
                step=1.0 if ind.band_mode == "circular" else 0.1,
                key=f"t_{key}_{cur:.6f}",
            )
            if abs(targets[key] - cur) > 1e-9:
                st.sidebar.caption(f"simulando: hoje o valor real e {cur:.3f}")

    active = {k: v for k, v in inds.items() if use[k]}
    if not active:
        st.info("Selecione ao menos um indicador na barra lateral.")
        return

    tab_ind, tab_comp, tab_m2, tab_dados, tab_metodo = st.tabs(
        ["Individual", "Composto (E)", "M2 global", "Dados e fontes", "Metodologia"]
    )

    # -------------------------------------------------------------- individual
    with tab_ind:
        st.markdown("**Holder** - comprar em um dia qualquer do periodo e segurar. "
                    "E a referencia que todo indicador tem que bater:")
        st.dataframe(tabela_holder(panel, windows, date_range), hide_index=True, width="stretch")
        st.divider()

        for key, ind in active.items():
            st.subheader(ind.label)
            tbl, res, det = engine.analyse(panel, {key: ind}, {key: targets[key]}, {key: bands[key]},
                                           windows, min_n=cfg["min_n"], relax=cfg["relax"], gap_days=gap,
                                           date_range=date_range, max_factor=cfg["max_factor"],
                                           fixed_factor=cfg["fixed"], align_lead=params.align_lead,
                                           ref_window=params.ref_window, locked=locked)
            st.caption(
                f"Alvo {targets[key]:.2f} {ind.unit} | historico desde "
                f"{ind.series.dropna().index.min():%d/%m/%Y}"
            )
            match_caption(res, {key: ind}, bands, cfg)
            show_table(tbl)
            mostrar_lead(det, params.align_lead)
            st.plotly_chart(price_chart(panel.loc[start:], res.dates, "Dias casados sobre o preco"),
                            width="stretch")
            st.plotly_chart(indicator_chart(ind, targets[key], res.bands_used[key], start),
                            width="stretch")
            with st.expander("Episodios"):
                st.dataframe(episode_table(panel.loc[start:], res.mask, windows, gap), hide_index=True,
                             width="stretch")
            if ind.note:
                st.caption(ind.note)
            st.divider()

    # ---------------------------------------------------------------- composto
    with tab_comp:
        st.subheader("Interseccao de todos os indicadores selecionados")
        st.markdown(
            "Procura os dias do passado que satisfizeram **todos** os criterios "
            "**ao mesmo tempo, no mesmo dia**:\n"
            + "\n".join(
                f"- {i.label} entre **{targets[k] - bands[k]:.2f}** e **{targets[k] + bands[k]:.2f}** {i.unit}"
                for k, i in active.items()
            )
        )
        with st.expander("Como ler esta aba"):
            st.markdown(
                """
- **Dias casados**: total de dias do passado que passaram em todos os filtros.
- **Episodios independentes**: blocos separados por pelo menos o intervalo definido na barra
  lateral. Cinco episodios de vinte dias sao **cinco** observacoes, nao cem - e o numero de
  episodios que diz se o resultado tem lastro.
- **Fator de relaxamento**: 1,00x significa que as bandas que voce escolheu bastaram. Acima
  disso, todas as bandas foram multiplicadas por esse fator. Quanto maior o fator, mais frouxa
  a pergunta que esta sendo respondida - controle o comportamento em *Fator das bandas*,
  na barra lateral, e veja o custo de cada degrau na tabela de sensibilidade.
- O **funil** no fim da aba mostra quantos dias cada criterio derruba, um a um.
- Os dias mais recentes entram na contagem de dias casados mas nao nas colunas de retorno
  futuro que ainda nao existem - por isso a coluna Dias encolhe nas janelas mais longas.
"""
            )
        tbl, res, det = engine.analyse(panel, active, targets, bands, windows, min_n=cfg["min_n"],
                                       relax=cfg["relax"], gap_days=gap, date_range=date_range,
                                       max_factor=cfg["max_factor"], fixed_factor=cfg["fixed"],
                                       align_lead=params.align_lead, ref_window=params.ref_window,
                                       locked=locked)
        match_caption(res, active, bands, cfg)
        mostrar_lead(det, params.align_lead)
        c = st.columns(3)
        c[0].metric("Dias casados", res.n_days)
        c[1].metric("Episodios independentes", len(episodes(res.dates, gap_days=gap)))
        c[2].metric("Fator de relaxamento", f"{res.factor:.2f}x")
        show_table(tbl)
        st.plotly_chart(price_chart(panel.loc[start:], res.dates, "Dias casados sobre o preco"),
                        width="stretch")
        st.markdown("**Holder** - a referencia a bater no mesmo periodo:")
        st.dataframe(tabela_holder(panel, windows, date_range), hide_index=True, width="stretch")
        st.markdown("**Episodios**")
        st.dataframe(episode_table(panel.loc[start:], res.mask, windows, gap), hide_index=True,
                     width="stretch")

        st.divider()
        st.markdown("**Sensibilidade ao fator** - o que cada fator entrega de amostra")
        from btcindex.matcher import EXPANSION_STEPS, sensitivity

        fatores = sorted({*EXPANSION_STEPS, round(res.factor, 2)})
        sens = sensitivity(active, targets, bands, panel, windows, fatores, date_range)
        sens.insert(1, "bandas", [
            " | ".join(f"{bands[k] * f:.2f}" for k in active) for f in sens["fator"]
        ])
        st.dataframe(
            sens.style.apply(
                lambda col: ["background-color: rgba(232,131,58,0.22)" if v == res.factor else "" for v in col],
                subset=["fator"],
            ),
            hide_index=True, width="stretch",
        )
        st.caption(
            f"Ordem das bandas: {' | '.join(i.label for i in active.values())}. "
            "A coluna *dias* conta todos os dias casados; as colunas *com 1m/3m/6m/12m* contam so os "
            "que ja tem aquele retorno futuro. O fator em destaque e o que esta em uso. "
            "Escolha olhando o custo: cada degrau compra amostra vendendo semelhanca com hoje."
        )

        if len(active) > 1:
            st.divider()
            st.markdown("**Funil de filtragem** - de onde vem o tamanho da amostra")
            fun, gargalo = funnel(active, targets, res.bands_used, panel.loc[start:].index, gap)
            st.dataframe(fun, hide_index=True, width="stretch")
            st.caption(
                f"Os indicadores entram do menos para o mais restritivo. O gargalo e **{gargalo}**: "
                "e o criterio que mais derruba a amostra, e portanto o primeiro lugar onde mexer "
                "(alargar a banda dele) se voce quiser mais dias sem relaxar todo o resto."
            )

    # --------------------------------------------------------------------- m2
    with tab_m2:
        st.subheader("M2 global sobre o preco do bitcoin")
        st.caption(
            f"Agregado de {'+'.join(params.m2_components)} em USD, encadeado, deslocado "
            f"{params.m2_lead} dias para a frente. Ele nao entra em nenhuma analise desta pagina - "
            "esta aqui como contexto visual."
        )
        c1, c2 = st.columns([1, 2])
        escolha = c1.selectbox("Janela de exibicao", [*JANELAS_M2, "personalizado"],
                               index=2, key="m2win")
        if escolha == "personalizado":
            dias_janela = int(c2.number_input("Dias exibidos (passado)", 30, 6000, 365, 10,
                                              key="m2win_dias"))
        else:
            dias_janela = JANELAS_M2[escolha]
        if dias_janela is not None:
            c2.caption(f"Mostra {dias_janela} dias de passado mais os {params.m2_lead} dias de "
                       "projecao do M2 a direita.")

        st.plotly_chart(m2_chart(panel["btc_close"], m2, params.m2_lead, dias_janela, start),
                        width="stretch")
        ultimo_real = engine.m2_ultimo_dado_real(raw, params.m2_components)
        st.caption(
            f"Linha solida = M2 ja sobreposto ao preco. Tracejada = projecao, o M2 publicado ate "
            f"{ultimo_real:%d/%m/%Y} deslocado para a frente. A serie termina no ultimo dado real: "
            "nao ha trecho chapado fingindo ser previsao."
        )
        st.info(
            "Cuidado ao ler este grafico: duas series que sobem ao longo de uma decada parecem "
            "sempre correlacionadas. Em nivel, a correlacao com o BTC e de +0,95; em variacao, que "
            "e o que se poderia negociar, cai para +0,08. E cerca de dois tercos da variancia do M2 "
            "em dolar vem do proprio cambio, nao de criacao de moeda."
        )

    # ------------------------------------------------------------------- dados
    with tab_dados:
        st.subheader("Cobertura das fontes")
        rows = []
        for name, s in [("BTC (Bitstamp)", raw.btc), ("Fear & Greed (alternative.me)", raw.fng),
                        ("MVRV Z-score (Coin Metrics)", raw.mvrv_z)]:
            d = s.dropna()
            rows.append({"serie": name, "inicio": d.index.min().date(), "fim": d.index.max().date(), "obs": len(d)})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

        st.markdown("**Componentes do M2 global (US$ trilhoes)**")
        cov = []
        for col in raw.m2_components.columns:
            s = raw.m2_components[col].dropna()
            cov.append({"componente": global_m2.COMPONENT_LABELS[col], "codigo": col,
                        "inicio": s.index.min().date(), "ultimo dado real": s.index.max().date(),
                        "valor US$ tri": round(float(s.iloc[-1]), 2)})
        st.dataframe(pd.DataFrame(cov), hide_index=True, width="stretch")
        m2_level = global_m2.chain_link(raw.m2_components[list(params.m2_components)])
        st.metric("M2 global hoje", f"US$ {m2_level.iloc[-1]:.1f} tri")

        st.markdown("**Intervalos entre halvings**")
        st.dataframe(cycle_mod.observed_intervals(), hide_index=True, width="stretch")

        export = panel.copy()
        for k, ind in inds.items():
            export[k] = ind.series
        st.download_button("Baixar painel completo (CSV)", export.to_csv().encode("utf-8"),
                           "btc_index_painel.csv", "text/csv")

    # -------------------------------------------------------------- metodologia
    with tab_metodo:
        st.markdown(
            """
### Como o numero e calculado

1. Monta-se um painel diario com o fechamento do BTC e os retornos futuros de cada janela
   (`preco(t+N)/preco(t) - 1`, em dias corridos).
2. Cada indicador vira uma serie diaria. Para os de liquidez, o valor no dia `t` e a variacao
   percentual da liquidez em `N` semanas medida `lead` dias antes de `t` -- e assim que o
   atraso de 10-12 semanas entre liquidez e preco entra na conta.
3. Selecionam-se os dias do passado em que o indicador esteve dentro da banda em torno do alvo.
4. Calculam-se media, mediana, desvio, P10/P90 e taxa de dias positivos dos retornos futuros
   desses dias, sempre ao lado do **holder**: comprar num dia qualquer do mesmo periodo e
   segurar. A coluna *Vantagem p.p.* e a diferenca entre os dois - se ela for perto de zero,
   o indicador nao esta acrescentando nada ao simples fato de o bitcoin ter subido.

### O lead e medido de centro a centro

A janela de variacao ja olha para tras: um delta de 8 semanas terminando em `tau` tem centro
de massa em `tau-28d`. O retorno futuro de horizonte `H` tem centro em `t+H/2`. Entao

    lead efetivo = shift + janela/2 + horizonte/2

e um shift fixo de 70 dias em todas as janelas testava, na pratica, 20 semanas de lead na
janela de 12 meses. Por isso o parametro na barra lateral e o **lead centro a centro**, e o
shift de cada janela e derivado dele: `shift = lead - janela/2 - horizonte/2`.

O lead de 91 dias que vem por padrao foi medido, nao herdado: o pico da correlacao cruzada
entre a variacao de 8 semanas da liquidez e a do BTC esta em +91 dias, com correlacao
contemporanea de apenas +0,04. Sao as 13 semanas do CrossBorder, nao as 10 populares.

Consequencia incomoda: horizontes longos nao tem como ficar alinhados. Um horizonte de 6
meses ja consome 91 dias so na sua metade, entao o shift satura em zero e o lead efetivo
estoura. A tabela "Lead aplicado em cada janela" mostra isso, e a pagina avisa.

### Bandas por percentil

Sinais fracos e monotonicos nao aparecem numa banda estreita em torno de um valor. Com
correlacao de 0,3, o que informa e **em que parte da distribuicao** o dia de hoje esta, nao
o valor exato. A banda por percentil compara posicao: +/-12,5 pontos percentuais e a largura
de um quartil, +/-10 um quintil, +/-5 um decil. A distribuicao de referencia e a do periodo
filtrado, entao mudar a data inicial muda o que significa "mesmo quartil".

### O M2 global e, em boa parte, um sinal de dolar

Convertendo M2 de China, Zona do Euro, Japao e Reino Unido para dolar, o cambio entra na
conta como se fosse criacao de moeda. Medido: a volatilidade da variacao de 8 semanas cai de
1,71 pp para 0,63 pp quando o cambio e congelado, e a correlacao do sinal com o dolar caindo
e de +0,74. Pior: **com o cambio congelado, a correlacao com o BTC cai de +0,08 para +0,03**.
O pouco de sinal que existe vem do dolar, nao da expansao monetaria. O indicador continua
util - mas saiba que ele esta medindo o dolar.

E o numero famoso de "88% a 91% de correlacao entre M2 e bitcoin" e correlacao de **niveis**
de duas series que sobem: em log-nivel da +0,95 aqui tambem. Em variacao, que e o que se pode
negociar, da +0,08.

### O que olhar com desconfianca

- **N inflado por sobreposicao.** 300 dias casados consecutivos sao praticamente uma unica
  observacao. Por isso a coluna *Episodios*: e ela que diz quantas situacoes realmente
  independentes existem. Tres episodios sao tres observacoes, nao trezentas.
- **Regimes diferentes.** Um retorno de 12 meses de 2013 (+1000%) e outro de 2023 nao sao
  comparaveis. O filtro de data inicial existe para isso; o default comeca em 2015.
- **Fear & Greed so existe desde 2018.** Cobre cerca de um ciclo e meio.
- **M2 e publicado com defasagem** de 1 a 3 meses conforme o pais. O lead de 70 dias faz o
  sinal de hoje cair sobre dado ja publicado; quando isso deixa de valer, aparece um aviso
  no topo da pagina.
- **Ancoras 'topo' e 'fundo' tem vies de retrovisor**: so se sabe onde foi o topo depois.
  A ancora halving e a unica conhecida em tempo real.
- Isto e estatistica descritiva do passado, nao previsao.

### Fontes

| Serie | Fonte | Atualizacao |
|---|---|---|
| Preco BTC/USD | Bitstamp OHLC publico | diaria |
| Fear & Greed | alternative.me | diaria |
| M2 EUA | FRED `WM2NS` | semanal |
| M2 Zona do Euro | ECB Data Portal (BSI) | mensal |
| M2 China | PBoC via chinadata.live, emendado com FRED `MYAGM2CNM189N` | mensal |
| M2 Japao | IMF IFS via DBnomics | mensal, defasado |
| M4 Reino Unido | Bank of England `LPMAUYM` | mensal |
| Cambio | FRED `DEXUSEU`, `DEXCHUS`, `DEXJPUS`, `DEXUSUK` | diaria |
| Net Liquidity | FRED `WALCL`, `WTREGEN`, `RRPONTSYD` | semanal/diaria |
"""
        )


if __name__ == "__main__":
    main()
