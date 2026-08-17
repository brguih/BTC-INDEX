"""Grafico do M2: corte da extrapolacao, janela de exibicao e separacao da projecao."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from btcindex import engine

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def appmod():
    spec = importlib.util.spec_from_file_location("appmod", RAIZ / "app.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["appmod"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def raw():
    """M2 publicado ate 01/03, mas o agregado diario vai ate 15/04 por repeticao."""
    idx = pd.date_range("2024-01-01", "2024-04-15", freq="D")
    comp = pd.DataFrame(index=idx)
    comp["US"] = np.linspace(20.0, 21.0, len(idx))
    comp.loc[comp.index > pd.Timestamp("2024-03-01"), "US"] = np.nan
    comp["EA"] = comp["US"] * 0.8
    btc = pd.Series(np.linspace(40000, 70000, len(idx)), index=idx)
    return engine.RawData(btc=btc, fng=pd.Series(dtype=float), m2_components=comp,
                          mvrv_z=pd.Series(dtype=float), fetched_at=pd.Timestamp.now())


def test_ultimo_dado_real_ignora_o_preenchimento(raw):
    assert engine.m2_ultimo_dado_real(raw) == pd.Timestamp("2024-03-01")


def test_serie_termina_no_ultimo_dado_real_deslocado(raw):
    """Sem o corte, sobrariam 45 dias de linha chapada com cara de previsao."""
    s = engine.m2_para_grafico(raw, None, lead_dias=91)
    assert s.index.max() == pd.Timestamp("2024-03-01") + pd.Timedelta(days=91)
    assert s.index.min() == raw.m2_components.index.min() + pd.Timedelta(days=91)


def test_sem_deslocamento_tambem_corta(raw):
    s = engine.m2_para_grafico(raw, None, lead_dias=0)
    assert s.index.max() == pd.Timestamp("2024-03-01")


def test_valores_nao_ficam_repetidos_no_fim(raw):
    s = engine.m2_para_grafico(raw, None, lead_dias=30)
    assert s.iloc[-1] != s.iloc[-5], "cauda chapada indica que a extrapolacao vazou"


# ------------------------------------------------------------------ grafico


def _traces(fig):
    return {tr.name: tr for tr in fig.data}


def test_janela_recorta_o_passado(appmod, raw):
    m2 = engine.m2_para_grafico(raw, None, 91)
    fig = appmod.m2_chart(raw.btc, m2, 91, dias=30, inicio_amostra=raw.btc.index.min())
    btc_trace = _traces(fig)["BTC"]
    span = (pd.Timestamp(btc_trace.x.max()) - pd.Timestamp(btc_trace.x.min())).days
    assert span == 30


def test_projecao_vai_para_a_direita_de_hoje(appmod, raw):
    hoje = raw.btc.index.max()
    m2 = engine.m2_para_grafico(raw, None, 91)
    fig = appmod.m2_chart(raw.btc, m2, 91, dias=60, inicio_amostra=raw.btc.index.min())
    tr = _traces(fig)
    assert pd.Timestamp(tr["M2 global +91d"].x.max()) <= hoje
    assert pd.Timestamp(tr["M2 projetado"].x.min()) >= hoje
    assert tr["M2 projetado"].line.dash == "dash", "a projecao precisa ser visualmente distinta"


def test_eixo_vai_ate_o_fim_da_projecao(appmod, raw):
    m2 = engine.m2_para_grafico(raw, None, 91)
    fig = appmod.m2_chart(raw.btc, m2, 91, dias=30, inicio_amostra=raw.btc.index.min())
    assert pd.Timestamp(fig.layout.xaxis.range[1]) == m2.index.max()


def test_escala_do_preco_acompanha_a_janela(appmod, raw):
    m2 = engine.m2_para_grafico(raw, None, 91)
    curta = appmod.m2_chart(raw.btc, m2, 91, dias=30, inicio_amostra=raw.btc.index.min())
    longa = appmod.m2_chart(raw.btc, m2, 91, dias=None, inicio_amostra=raw.btc.index.min())
    assert curta.layout.yaxis.type == "linear"
    assert longa.layout.yaxis.type == "log"
