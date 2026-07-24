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
    min_n = st.sidebar.number_input("N minimo de dias na amostra", 5, 500, 30, 5)
    relax = st.sidebar.checkbox(
        "Relaxar bandas automaticamente ate atingir o N minimo", value=True,
        help="Se a interseccao estrita nao alcanca o N minimo, todas as bandas sao multiplicadas pelo mesmo fator.",
    )
    gap = st.sidebar.number_input(
        "Intervalo minimo entre episodios (dias)", 5, 365, 45, 5,
        help="Dias casados separados por menos que isso contam como um mesmo episodio.",
    )
    return windows, pd.Timestamp(start), int(min_n), relax, int(gap)


def indicator_controls(raw: engine.RawData):
    st.sidebar.header("Indicadores")
    p = engine.Params()

    with st.sidebar.expander("Fear & Greed", expanded=True):
        use_fng = st.checkbox("Usar", value=True, key="use_fng")
        band_fng = st.number_input("Banda +/- pontos", 0.5, 50.0, 2.0, 0.5, key="b_fng")

    with st.sidebar.expander("M2 global", expanded=True):
        use_m2 = st.checkbox("Usar", value=True, key="use_m2")
        p.m2_weeks = st.number_input("Janela de variacao (semanas)", 1, 104, 8, 1, key="m2w")
        p.m2_lead = st.number_input("Lead sobre o BTC (dias)", 0, 365, 70, 5, key="m2l",
                                    help="O BTC responde a liquidez com atraso; 70 dias = 10 semanas.")
        comps = st.multiselect(
            "Paises no agregado",
            list(global_m2.DEFAULT_COMPONENTS),
            default=list(global_m2.DEFAULT_COMPONENTS),
            format_func=lambda c: global_m2.COMPONENT_LABELS[c],
            key="m2c",
        )
        p.m2_components = tuple(comps) if comps else global_m2.DEFAULT_COMPONENTS
        band_m2 = st.number_input("Banda +/- p.p.", 0.01, 10.0, 0.25, 0.05, key="b_m2")

    with st.sidebar.expander("Net Liquidity do Fed", expanded=False):
        use_nl = st.checkbox("Usar", value=False, key="use_nl")
        p.netliq_weeks = st.number_input("Janela de variacao (semanas)", 1, 104, 8, 1, key="nlw")
        p.netliq_lead = st.number_input("Lead sobre o BTC (dias)", 0, 365, 70, 5, key="nll")
        band_nl = st.number_input("Banda +/- p.p.", 0.05, 20.0, 1.0, 0.05, key="b_nl")

    with st.sidebar.expander("Ciclo do BTC", expanded=True):
        use_cy = st.checkbox("Usar", value=True, key="use_cy")
        p.cycle_anchor = st.selectbox("Ancora", ["halving", "topo", "fundo"], key="cya")
        p.cycle_days = st.number_input("Comprimento do ciclo (dias)", 900, 2000,
                                       cycle_mod.DEFAULT_CYCLE_DAYS, 5, key="cyd")
        band_cy = st.number_input("Banda +/- dias", 1.0, 200.0, 20.0, 1.0, key="b_cy")

    use = {"fng": use_fng, "m2_delta": use_m2, "netliq_delta": use_nl, "cycle": use_cy}
    bands = {"fng": band_fng, "m2_delta": band_m2, "netliq_delta": band_nl, "cycle": band_cy}
    return p, use, bands


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


def distribution_chart(panel: pd.DataFrame, dates: pd.DatetimeIndex, window: str) -> go.Figure:
    col = f"fwd_{window}"
    matched = panel.loc[panel.index.isin(dates), col].dropna() * 100
    base = panel[col].dropna() * 100
    fig = go.Figure()
    fig.add_trace(go.Histogram(x=base, name="todos os dias", opacity=0.45, histnorm="probability",
                               marker_color=COLORS["base"], nbinsx=60))
    fig.add_trace(go.Histogram(x=matched, name="dias casados", opacity=0.75, histnorm="probability",
                               marker_color=COLORS["match"], nbinsx=60))
    fig.add_vline(x=0, line_dash="dot", line_color="#555")
    if len(matched):
        fig.add_vline(x=float(matched.median()), line_color=COLORS["match"],
                      annotation_text=f"mediana {matched.median():.1f}%")
    fig.update_layout(barmode="overlay", height=340, title=f"Distribuicao do retorno em {window}",
                      xaxis_title="retorno (%)", margin=dict(l=10, r=10, t=40, b=10),
                      legend=dict(orientation="h", y=1.12))
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


def show_table(table: pd.DataFrame):
    cols = ["janela", "n_dias", "n_episodios", "media_%", "mediana_%", "desvio_%",
            "p10_%", "p90_%", "acerto_%", "baseline_mediana_%"]
    nice = table[cols].rename(columns={
        "janela": "Janela", "n_dias": "Dias", "n_episodios": "Episodios", "media_%": "Media %",
        "mediana_%": "Mediana %", "desvio_%": "Desvio %", "p10_%": "P10 %", "p90_%": "P90 %",
        "acerto_%": "Positivos %", "baseline_mediana_%": "Baseline mediana %",
    })
    nice.attrs = {}  # os attrs carregam Timestamps que o Arrow nao serializa
    st.dataframe(nice, hide_index=True, width="stretch")


def match_caption(res, inds, bands):
    parts = []
    for k, ind in inds.items():
        parts.append(f"{ind.label}: +/-{res.bands_used[k]:.2f}")
    txt = " | ".join(parts)
    if res.exhausted and res.n_days_with_window < 1:
        st.error(f"Nenhum dia do passado casa com esses criterios, nem alargando 10x as bandas. Bandas finais: {txt}")
    elif res.exhausted:
        st.warning(
            f"Amostra abaixo do N minimo mesmo alargando as bandas em {res.factor:.2f}x "
            f"({res.n_days} dias). Trate os numeros como indicativos. Bandas finais: {txt}"
        )
    elif res.relaxed:
        st.info(f"Bandas alargadas em {res.factor:.2f}x para alcancar o N minimo. Bandas usadas: {txt}")
    else:
        st.caption(f"Bandas originais, sem relaxamento. {txt}")


# ------------------------------------------------------------------------ app
def main():
    token = st.session_state.get("token", 0)
    raw = get_raw(token)

    windows, start, min_n, relax, gap = sidebar_controls(raw)
    params, use, bands = indicator_controls(raw)
    params.windows = windows

    panel = engine.build_panel(raw, windows)
    inds = engine.build_indicators(raw, params, panel.index)
    today = panel.index.max()
    date_range = (start, today)

    st.title("BTC INDEX")
    st.caption(
        "Como o bitcoin se comportou em 1, 3, 6 e 12 meses a partir dos dias do passado em que "
        "os indicadores estavam como estao hoje."
    )

    # --------------------------------------------------------- cartoes de hoje
    cards = st.columns(5)
    cards[0].metric("BTC", f"US$ {panel['btc_close'].iloc[-1]:,.0f}",
                    f"{(panel['btc_close'].iloc[-1] / panel['btc_close'].iloc[-31] - 1) * 100:+.1f}% em 30d")
    from btcindex.sources.fear_greed import classify
    fng_v = inds["fng"].current
    cards[1].metric("Fear & Greed", f"{fng_v:.0f}", classify(fng_v))
    cards[2].metric(f"M2 global {params.m2_weeks}s", f"{inds['m2_delta'].current:+.2f}%",
                    f"lead {params.m2_lead}d")
    cards[3].metric(f"Net Liquidity {params.netliq_weeks}s", f"{inds['netliq_delta'].current:+.2f}%",
                    f"lead {params.netliq_lead}d")
    cd = inds["cycle"].current
    cards[4].metric("Dia do ciclo", f"{cd:.0f}", f"{cd / params.cycle_days * 100:.0f}% do ciclo")

    for key in ("m2_delta", "netliq_delta"):
        w = engine.stale_warning(inds[key], today)
        if w:
            st.warning(w)

    # ------------------------------------------------------------------- alvos
    st.sidebar.header("Alvos")
    st.sidebar.caption(
        "Travado = o alvo acompanha o valor de hoje e muda junto com os parametros. "
        "Destrave so para simular um cenario hipotetico."
    )
    targets = {}
    for key, ind in inds.items():
        if not use[key]:
            continue
        cur = float(ind.current)
        lock = st.sidebar.checkbox(f"{ind.label}: usar valor de hoje", value=True, key=f"lock_{key}")
        if lock:
            targets[key] = cur
            st.sidebar.caption(f"alvo = {cur:.3f} ({ind.unit})")
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

    tab_ind, tab_comp, tab_dados, tab_metodo = st.tabs(
        ["Individual", "Composto (E)", "Dados e fontes", "Metodologia"]
    )

    # -------------------------------------------------------------- individual
    with tab_ind:
        base_tbl = engine.baseline(panel, windows, date_range)
        st.markdown("**Baseline** - todos os dias do periodo, sem nenhum filtro:")
        show_table(base_tbl)
        st.divider()

        for key, ind in active.items():
            st.subheader(ind.label)
            tbl, res = engine.analyse(panel, {key: ind}, {key: targets[key]}, {key: bands[key]},
                                      windows, min_n=min_n, relax=relax, gap_days=gap, date_range=date_range)
            st.caption(
                f"Alvo {targets[key]:.2f} {ind.unit} | historico desde "
                f"{ind.series.dropna().index.min():%d/%m/%Y}"
            )
            match_caption(res, {key: ind}, bands)
            show_table(tbl)
            c1, c2 = st.columns([3, 2])
            c1.plotly_chart(price_chart(panel.loc[start:], res.dates, "Dias casados sobre o preco"),
                            width="stretch")
            win = c2.selectbox("Janela do histograma", list(windows), index=len(windows) - 1, key=f"h_{key}")
            c2.plotly_chart(distribution_chart(panel.loc[start:], res.dates, win), width="stretch")
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
  disso, todas as bandas foram multiplicadas por esse fator ate a amostra alcancar o N minimo.
  Quanto maior o fator, mais frouxa a pergunta que esta sendo respondida.
- O **funil** no fim da aba mostra quantos dias cada criterio derruba, um a um.
- Os dias mais recentes entram na contagem de dias casados mas nao nas colunas de retorno
  futuro que ainda nao existem - por isso a coluna Dias encolhe nas janelas mais longas.
"""
            )
        tbl, res = engine.analyse(panel, active, targets, bands, windows, min_n=min_n, relax=relax,
                                  gap_days=gap, date_range=date_range)
        match_caption(res, active, bands)
        c = st.columns(3)
        c[0].metric("Dias casados", res.n_days)
        c[1].metric("Episodios independentes", len(tbl.attrs.get("episodios", [])))
        c[2].metric("Fator de relaxamento", f"{res.factor:.2f}x")
        show_table(tbl)
        c1, c2 = st.columns([3, 2])
        c1.plotly_chart(price_chart(panel.loc[start:], res.dates, "Dias casados sobre o preco"),
                        width="stretch")
        win = c2.selectbox("Janela do histograma", list(windows), index=len(windows) - 1, key="h_comp")
        c2.plotly_chart(distribution_chart(panel.loc[start:], res.dates, win), width="stretch")
        st.markdown("**Episodios**")
        st.dataframe(episode_table(panel.loc[start:], res.mask, windows, gap), hide_index=True,
                     width="stretch")

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

    # ------------------------------------------------------------------- dados
    with tab_dados:
        st.subheader("Cobertura das fontes")
        rows = []
        for name, s in [("BTC (Bitstamp)", raw.btc), ("Fear & Greed (alternative.me)", raw.fng),
                        ("Net Liquidity (FRED)", raw.netliq)]:
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
   desses dias, sempre ao lado do baseline (todos os dias do mesmo periodo).

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
