"""Controle do fator que multiplica as bandas."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from btcindex import matcher
from btcindex.indicators import Indicator


@pytest.fixture
def panel():
    idx = pd.date_range("2018-01-01", periods=1200, freq="D")
    close = pd.Series(np.linspace(100, 1300, 1200), index=idx)
    df = pd.DataFrame({"btc_close": close})
    df["fwd_1m"] = close.shift(-30) / close - 1
    return df


@pytest.fixture
def ind(panel):
    s = pd.Series(np.arange(len(panel), dtype=float), index=panel.index)
    return Indicator(key="x", label="X", series=s, unit="u", band_mode="abs",
                     default_band=1.0, band_label="+/-")


def test_ladder_respeita_o_teto():
    assert matcher.ladder(max_factor=3.0) == [1.0, 1.25, 1.5, 2.0, 2.5, 3.0]


def test_ladder_inclui_o_proprio_teto_quando_cai_entre_degraus():
    assert matcher.ladder(max_factor=3.7)[-1] == 3.7


def test_ladder_fator_fixo_ignora_a_escada():
    assert matcher.ladder(max_factor=10.0, fixed_factor=2.5) == [2.5]


def test_ladder_sem_relaxamento():
    assert matcher.ladder(max_factor=10.0, relax=False) == [1.0]


def test_teto_limita_o_relaxamento(panel, ind):
    res = matcher.match({"x": ind}, {"x": 100.0}, {"x": 1.0}, panel, min_n=500,
                        window_col="fwd_1m", max_factor=2.0)
    assert res.factor == 2.0 and res.exhausted
    assert res.bands_used["x"] == pytest.approx(2.0)


def test_fator_fixo_ignora_o_n_minimo(panel, ind):
    res = matcher.match({"x": ind}, {"x": 100.0}, {"x": 1.0}, panel, min_n=999,
                        window_col="fwd_1m", fixed_factor=3.0)
    assert res.factor == 3.0
    assert res.n_days == 7  # 100 +/- 3
    assert res.bands_used["x"] == pytest.approx(3.0)


def test_fator_menor_que_um_aperta_a_banda(panel, ind):
    largo = matcher.match({"x": ind}, {"x": 100.0}, {"x": 4.0}, panel, min_n=1,
                          window_col="fwd_1m", fixed_factor=1.0)
    apertado = matcher.match({"x": ind}, {"x": 100.0}, {"x": 4.0}, panel, min_n=1,
                             window_col="fwd_1m", fixed_factor=0.5)
    assert apertado.n_days < largo.n_days
    assert apertado.bands_used["x"] == pytest.approx(2.0)


def test_sensibilidade_e_monotona(panel, ind):
    sens = matcher.sensitivity({"x": ind}, {"x": 100.0}, {"x": 1.0}, panel, {"1m": 30},
                               factors=[1.0, 2.0, 5.0])
    assert list(sens["fator"]) == [1.0, 2.0, 5.0]
    assert sens["dias"].is_monotonic_increasing
    assert (sens["com 1m"] <= sens["dias"]).all()
