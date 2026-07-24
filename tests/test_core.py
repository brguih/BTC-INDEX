"""Testes do motor, sem rede: series sinteticas."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from btcindex import cycle, matcher, stats
from btcindex.indicators import Indicator


@pytest.fixture
def panel():
    idx = pd.date_range("2020-01-01", periods=800, freq="D")
    close = pd.Series(np.linspace(100, 900, 800), index=idx)
    df = pd.DataFrame({"btc_close": close})
    for label, days in {"1m": 30, "3m": 91}.items():
        df[f"fwd_{label}"] = close.shift(-days) / close - 1
    return df


def _ind(series, band_mode="abs", **meta):
    return Indicator(key="x", label="X", series=series, unit="u", band_mode=band_mode,
                     default_band=1.0, band_label="+/-", meta=meta)


def test_mask_absoluta(panel):
    s = pd.Series(np.arange(len(panel), dtype=float), index=panel.index)
    ind = _ind(s)
    m = ind.mask(100.0, 2.0)
    assert list(panel.index[m]) == list(panel.index[98:103])


def test_distancia_circular():
    s = pd.Series([5.0, 1430.0, 700.0], index=pd.date_range("2020-01-01", periods=3))
    d = cycle.circular_distance(s, 1435.0, 1435)
    # dia 5 dista 5 do fim do ciclo; dia 1430 dista 5; dia 700 dista 735 -> 700 pelo outro lado
    assert d.tolist() == [5.0, 5.0, 700.0]


def test_cycle_day_usa_ultima_ancora():
    idx = pd.DatetimeIndex(["2024-04-19", "2024-04-20", "2024-05-19", "2012-01-01"])
    cd = cycle.cycle_day(idx)
    assert cd.iloc[0] == 0
    assert cd.iloc[1] == 1
    assert cd.iloc[2] == 30
    assert np.isnan(cd.iloc[3])  # antes do primeiro halving


def test_episodios_separam_por_gap():
    d = pd.DatetimeIndex(
        list(pd.date_range("2020-01-01", periods=10))
        + list(pd.date_range("2020-06-01", periods=5))
    )
    eps = stats.episodes(d, gap_days=45)
    assert len(eps) == 2
    assert eps[0][0] == pd.Timestamp("2020-01-01")
    assert eps[1][1] == pd.Timestamp("2020-06-05")


def test_relaxamento_expande_ate_n_minimo(panel):
    s = pd.Series(np.arange(len(panel), dtype=float), index=panel.index)
    ind = _ind(s)
    res = matcher.match({"x": ind}, {"x": 100.0}, {"x": 1.0}, panel, min_n=20, relax=True,
                        window_col="fwd_1m")
    assert res.relaxed and res.factor > 1.0
    assert res.n_days_with_window >= 20
    assert res.bands_used["x"] == pytest.approx(res.factor)


def test_sem_relaxamento_mantem_banda(panel):
    s = pd.Series(np.arange(len(panel), dtype=float), index=panel.index)
    res = matcher.match({"x": _ind(s)}, {"x": 100.0}, {"x": 1.0}, panel, min_n=500, relax=False,
                        window_col="fwd_1m")
    assert res.factor == 1.0 and res.exhausted and res.n_days == 3


def test_and_e_mais_restritivo_que_individual(panel):
    a = pd.Series(np.arange(len(panel), dtype=float), index=panel.index)
    b = pd.Series(np.arange(len(panel), dtype=float) % 50, index=panel.index)
    inds = {"a": _ind(a), "b": _ind(b)}
    m_a = inds["a"].mask(400.0, 30.0).sum()
    res = matcher.match(inds, {"a": 400.0, "b": 0.0}, {"a": 30.0, "b": 1.0}, panel,
                        min_n=1, relax=False, window_col="fwd_1m")
    assert res.n_days <= m_a


def test_summarize_conta_apenas_dias_com_retorno(panel):
    mask = pd.Series(True, index=panel.index)
    tbl = stats.summarize(panel, mask, {"1m": 30, "3m": 91})
    assert tbl.loc[tbl.janela == "1m", "n_dias"].iloc[0] == len(panel) - 30
    assert tbl.loc[tbl.janela == "3m", "n_dias"].iloc[0] == len(panel) - 91
    # serie monotona crescente -> todo retorno futuro e positivo
    assert tbl["acerto_%"].tolist() == [100.0, 100.0]


def test_summarize_vazio_nao_quebra(panel):
    mask = pd.Series(False, index=panel.index)
    tbl = stats.summarize(panel, mask, {"1m": 30})
    assert tbl["n_dias"].iloc[0] == 0
    assert np.isnan(tbl["media_%"].iloc[0])
