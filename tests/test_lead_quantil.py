"""Shift por janela e bandas por percentil."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from btcindex import engine
from btcindex.indicators import Indicator


@pytest.fixture
def panel():
    idx = pd.date_range("2015-01-01", periods=2000, freq="D")
    close = pd.Series(np.linspace(100, 2100, 2000), index=idx)
    df = pd.DataFrame({"btc_close": close})
    for h, d in {"1m": 30, "3m": 91, "6m": 182}.items():
        df[f"fwd_{h}"] = close.shift(-d) / close - 1
    return df


def _ind_com_lead(panel, lead=91, janela=56, shift=None):
    base = pd.Series(np.arange(len(panel), dtype=float) % 100, index=panel.index)
    shift = engine.shift_para_janela(lead, janela, 91) if shift is None else shift
    return Indicator(
        key="x", label="X - variacao", series=base.shift(shift), unit="u", band_mode="abs",
        default_band=1.0, band_label="+/-",
        meta={"delta_base": base, "lead_days": lead, "window_days": janela,
              "align_lead": True, "shift_aplicado": shift},
    )


# ------------------------------------------------------------------ lead


def test_formula_do_shift():
    # lead = shift + janela/2 + horizonte/2  ->  shift = 91 - 28 - 14 = 49
    assert engine.shift_para_janela(91, 56, 28) == 49
    assert engine.shift_para_janela(91, 56, 56) == 35
    assert engine.shift_para_janela(91, 56, 84) == 21


def test_shift_satura_em_zero_quando_o_horizonte_e_longo():
    """Horizonte de 6 meses ja consome 91 dias so na metade: nao ha shift possivel."""
    assert engine.shift_para_janela(91, 56, 365) == 0
    assert engine.lead_efetivo(0, 56, 365) == 210  # 0 + 28 + 182,5


def test_lead_efetivo_e_o_inverso_do_shift():
    for horizonte in (28, 56, 84):
        sh = engine.shift_para_janela(91, 56, horizonte)
        assert engine.lead_efetivo(sh, 56, horizonte) == pytest.approx(91, abs=1)


def test_shift_fixo_de_70_distorcia_a_janela_longa():
    """O bug que motivou a mudanca: 70d de shift viravam 20 semanas de lead em 12 meses."""
    assert engine.lead_efetivo(70, 56, 365) == 280  # 40 semanas


def test_indicador_para_janela_reancora_o_shift(panel):
    ind = _ind_com_lead(panel)
    curto = engine.indicador_para_janela(ind, 28)
    longo = engine.indicador_para_janela(ind, 84)
    assert curto.meta["shift_aplicado"] == 49
    assert longo.meta["shift_aplicado"] == 21
    assert not curto.series.equals(longo.series)
    # a fixture ancora na janela de referencia de 91 dias: 91 - 28 - 45,5 -> 18
    assert ind.meta["shift_aplicado"] == 18, "o indicador original nao pode ser mutado"


def test_indicador_sem_lead_passa_intacto(panel):
    s = pd.Series(np.arange(len(panel), dtype=float), index=panel.index)
    ind = Indicator(key="fng", label="F", series=s, unit="u", band_mode="abs",
                    default_band=1.0, band_label="+/-")
    assert engine.indicador_para_janela(ind, 28) is ind


def test_analyse_gera_amostra_propria_por_janela(panel):
    ind = _ind_com_lead(panel)
    windows = {"1m": 30, "3m": 91, "6m": 182}
    tbl, res, det = engine.analyse(
        panel, {"x": ind}, {"x": 50.0}, {"x": 2.0}, windows,
        min_n=5, align_lead=True, ref_window="3m", locked={"x": False},
    )
    assert list(tbl["janela"]) == list(windows)
    assert set(det["janela"]) == set(windows)
    shifts = det.set_index("janela")["shift (d)"].to_dict()
    assert shifts["1m"] > shifts["3m"] > shifts["6m"]
    assert det["lead efetivo (d)"].notna().all()


def test_analyse_sem_alinhamento_mantem_uma_amostra_so(panel):
    ind = _ind_com_lead(panel)
    windows = {"1m": 30, "3m": 91}
    _, _, det = engine.analyse(panel, {"x": ind}, {"x": 50.0}, {"x": 2.0}, windows,
                               min_n=5, align_lead=False)
    assert det["shift (d)"].nunique() == 1


# -------------------------------------------------------------- percentil


def test_banda_percentil_seleciona_a_fatia_certa(panel):
    s = pd.Series(np.arange(len(panel), dtype=float), index=panel.index)
    ind = Indicator(key="x", label="X", series=s, unit="u", band_mode="pct",
                    default_band=12.5, band_label="+/- pct")
    mediana = float(s.median())
    m = ind.mask(mediana, 12.5, index=panel.index)
    # +/-12,5 pontos percentuais em torno da mediana = um quartil da amostra
    assert 0.24 <= m.mean() <= 0.26


def test_percentil_respeita_o_escopo(panel):
    s = pd.Series(np.arange(len(panel), dtype=float), index=panel.index)
    ind = Indicator(key="x", label="X", series=s, unit="u", band_mode="pct",
                    default_band=10.0, band_label="+/- pct")
    valor = float(s.iloc[1500])
    inteiro = ind.percentil(valor, panel.index)
    recorte = ind.percentil(valor, panel.index[1000:])
    assert inteiro == pytest.approx(75.0, abs=1)
    assert recorte == pytest.approx(50.0, abs=1), "no recorte, o mesmo valor vira a mediana"


def test_percentil_ignora_a_escala_do_indicador(panel):
    """Duas series monotonas equivalentes casam os mesmos dias, independente da unidade."""
    a = pd.Series(np.arange(len(panel), dtype=float), index=panel.index)
    b = a * 1000 + 7
    ia = Indicator(key="a", label="A", series=a, unit="u", band_mode="pct",
                   default_band=10.0, band_label="p")
    ib = Indicator(key="b", label="B", series=b, unit="u", band_mode="pct",
                   default_band=10.0, band_label="p")
    ma = ia.mask(float(a.iloc[1000]), 10.0, index=panel.index)
    mb = ib.mask(float(b.iloc[1000]), 10.0, index=panel.index)
    assert ma.equals(mb)
