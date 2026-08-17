"""Testes da interface com AppTest. Precisam do cache em data/cache (rode update_data.py antes)."""
from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

pytest.importorskip("streamlit.testing.v1")


@pytest.fixture(scope="module")
def app():
    return AppTest.from_file("app.py", default_timeout=400).run()


def _card(at, prefixo: str):
    return next(m for m in at.metric if m.label.startswith(prefixo))


def _alvos(at) -> list[float]:
    """Alvos travados, lidos das legendas 'alvo = X' da barra lateral."""
    return [float(c.value.split("=")[1].split("(")[0])
            for c in at.sidebar.caption if c.value.startswith("alvo = ")]


def test_app_roda_sem_excecao(app):
    assert not app.exception


def test_abas_esperadas(app):
    assert [t.label for t in app.tabs][:5] == [
        "Individual", "Composto (E)", "M2 global", "Dados e fontes", "Metodologia"
    ]


def test_cartoes_do_topo(app):
    rotulos = [m.label for m in app.metric]
    assert "MVRV Z-score" in rotulos
    for sumido in ("Net Liquidity", "Juro real"):
        assert not any(r.startswith(sumido) for r in rotulos), f"{sumido} deveria ter sido removido"


def test_m2_ficou_fora_da_analise(app):
    """O M2 so pode aparecer como grafico: sem trava, sem alvo, sem banda."""
    chaves = {w.key for w in app.sidebar.checkbox if w.key} | {w.key for w in app.sidebar.number_input if w.key}
    assert "lock_m2_delta" not in chaves
    assert "use_m2" not in chaves
    assert "b_m2" not in chaves
    assert "m2l" in chaves, "o deslocamento do M2 para o grafico deve continuar existindo"


def test_holder_aparece_nas_tabelas(app):
    """Toda tabela de resultado precisa da referencia holder e da vantagem."""
    com_vantagem = [d for d in app.dataframe if "Vantagem p.p." in d.value.columns]
    assert com_vantagem, "nenhuma tabela traz a comparacao com o holder"
    t = com_vantagem[0].value
    assert "Holder mediana %" in t.columns
    esperado = (t["Mediana %"] - t["Holder mediana %"]).round(2)
    assert (t["Vantagem p.p."] - esperado).abs().max() < 0.02


def test_sem_histograma(app):
    """O histograma foi retirado; sobra o grafico de preco e o do indicador."""
    chaves = {w.key for w in app.selectbox if w.key}
    assert not any(k.startswith("h_") for k in chaves)


def test_mudar_ancora_do_ciclo_atualiza_o_alvo(app):
    """Regressao: alvo travado tem que acompanhar o valor de hoje quando o parametro muda."""
    antes_card = _card(app, "Dia do ciclo").value
    antes_alvos = _alvos(app)

    app.sidebar.selectbox(key="cya").set_value("topo").run()

    depois_card = _card(app, "Dia do ciclo").value
    assert depois_card != antes_card, "o card deveria refletir a nova ancora"
    assert _alvos(app) != antes_alvos, "o alvo travado deveria acompanhar"
    assert float(depois_card) == pytest.approx(_alvos(app)[-1], abs=0.01)

    app.sidebar.selectbox(key="cya").set_value("halving").run()


def test_destravar_libera_campo_manual(app):
    app.sidebar.checkbox(key="lock_mvrv_z").set_value(False).run()
    manual = [w for w in app.sidebar.number_input if (w.key or "").startswith("t_mvrv_z_")]
    assert len(manual) == 1
    assert manual[0].value == pytest.approx(float(_card(app, "MVRV Z-score").value), abs=0.01)
    app.sidebar.checkbox(key="lock_mvrv_z").set_value(True).run()
