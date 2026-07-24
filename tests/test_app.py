"""Testes da interface com AppTest. Precisam do cache em data/cache (rode update_data.py antes)."""
from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

pytest.importorskip("streamlit.testing.v1")


@pytest.fixture(scope="module")
def app():
    return AppTest.from_file("app.py", default_timeout=300).run()


def _card(at, prefixo: str):
    return next(m for m in at.metric if m.label.startswith(prefixo))


def _alvo_m2(at) -> float:
    """Alvo efetivamente usado: o valor travado aparece na legenda 'alvo = X'."""
    legendas = [c.value for c in at.sidebar.caption if c.value.startswith("alvo = ")]
    return float(legendas[1].split("=")[1].split("(")[0])


def test_muda_semanas_muda_valor_de_hoje_e_o_alvo(app):
    """Regressao: o alvo ficava congelado no session_state quando a janela mudava,
    e a analise passava a procurar o valor errado sem nenhum aviso."""
    antes_card = _card(app, "M2 global").value
    antes_alvo = _alvo_m2(app)
    assert antes_alvo == pytest.approx(float(antes_card.rstrip("%")), abs=0.01)

    app.sidebar.number_input(key="m2w").set_value(10).run()

    depois_card = _card(app, "M2 global").value
    depois_alvo = _alvo_m2(app)
    assert depois_card != antes_card, "o card do topo deveria refletir a nova janela"
    assert depois_alvo != antes_alvo, "o alvo deveria acompanhar o valor de hoje"
    assert depois_alvo == pytest.approx(float(depois_card.rstrip("%")), abs=0.01)


def test_muda_lead_tambem_propaga(app):
    app.sidebar.number_input(key="m2l").set_value(0).run()
    assert _alvo_m2(app) == pytest.approx(float(_card(app, "M2 global").value.rstrip("%")), abs=0.01)
    app.sidebar.number_input(key="m2l").set_value(70).run()


def test_destravar_libera_campo_manual(app):
    app.sidebar.checkbox(key="lock_m2_delta").set_value(False).run()
    manual = [w for w in app.sidebar.number_input if (w.key or "").startswith("t_m2_delta_")]
    assert len(manual) == 1
    assert manual[0].value == pytest.approx(float(_card(app, "M2 global").value.rstrip("%")), abs=0.01)
    app.sidebar.checkbox(key="lock_m2_delta").set_value(True).run()


def test_app_roda_sem_excecao(app):
    assert not app.exception
