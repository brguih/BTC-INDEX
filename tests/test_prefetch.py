"""Busca paralela e incremental, sem tocar na rede."""
from __future__ import annotations

import time

import pandas as pd
import pytest

from btcindex import engine
from btcindex.sources import btc_price


def test_prefetch_roda_tudo_em_paralelo(monkeypatch):
    """14 fontes de 0,3s em fila levariam 4,2s; em paralelo, menos de 1s."""
    chamadas = []

    def lenta(nome):
        def _fn(*a, **kw):
            chamadas.append(nome)
            time.sleep(0.3)
            return pd.Series([1.0])
        return _fn

    monkeypatch.setattr(btc_price, "fetch", lenta("btc"))
    monkeypatch.setattr(engine.fear_greed, "fetch", lenta("fng"))
    monkeypatch.setattr(engine.global_m2, "_ea_m2_eur_tn", lenta("ea"))
    monkeypatch.setattr(engine.global_m2, "_cn_m2_cny_tn", lenta("cn"))
    monkeypatch.setattr(engine.global_m2, "_jp_m2_jpy_tn", lenta("jp"))
    monkeypatch.setattr(engine.global_m2, "_uk_m4_gbp_tn", lenta("uk"))
    monkeypatch.setattr(engine.fred, "series", lenta("fred"))

    inicio = time.perf_counter()
    falhas = engine.prefetch()
    duracao = time.perf_counter() - inicio

    assert falhas == {}
    assert len(chamadas) == 6 + len(engine.FRED_SERIES)
    assert duracao < 1.0, f"prefetch demorou {duracao:.2f}s: parece estar em fila"


def test_prefetch_isola_falha_de_uma_fonte(monkeypatch):
    """Uma fonte fora do ar nao pode derrubar as outras treze."""
    def quebrada(*a, **kw):
        raise RuntimeError("fonte fora do ar")

    monkeypatch.setattr(engine.global_m2, "_jp_m2_jpy_tn", quebrada)
    monkeypatch.setattr(btc_price, "fetch", lambda **kw: pd.Series([1.0]))
    monkeypatch.setattr(engine.fear_greed, "fetch", lambda **kw: pd.Series([1.0]))
    monkeypatch.setattr(engine.global_m2, "_ea_m2_eur_tn", lambda *a: pd.Series([1.0]))
    monkeypatch.setattr(engine.global_m2, "_cn_m2_cny_tn", lambda *a: pd.Series([1.0]))
    monkeypatch.setattr(engine.global_m2, "_uk_m4_gbp_tn", lambda *a: pd.Series([1.0]))
    monkeypatch.setattr(engine.fred, "series", lambda *a, **kw: pd.Series([1.0]))

    falhas = engine.prefetch()
    assert list(falhas) == ["japan_m2"]
    assert "fonte fora do ar" in falhas["japan_m2"]


def test_bitstamp_incremental_pede_so_o_que_falta(monkeypatch):
    idx = pd.date_range("2012-01-01", "2026-07-20", freq="D")
    antigo = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}, index=idx)
    pedidos = []

    def falso(since_ts=None):
        pedidos.append(since_ts)
        novo = pd.date_range("2026-07-18", "2026-07-24", freq="D")
        return pd.DataFrame({"open": 2.0, "high": 2.0, "low": 2.0, "close": 2.0, "volume": 2.0}, index=novo)

    monkeypatch.setattr(btc_price, "load", lambda nome: antigo)
    monkeypatch.setattr(btc_price, "_fetch_bitstamp", falso)

    out = btc_price._fetch_incremental()
    assert pedidos[0] is not None, "deveria pedir so a partir da ultima data em cache"
    assert pd.Timestamp(pedidos[0], unit="s") == pd.Timestamp("2026-07-17")
    assert out.index.max() == pd.Timestamp("2026-07-24")
    assert len(out) == len(idx) + 4  # 21 a 24 de julho
    assert out.loc["2026-07-19", "close"] == 2.0, "dias refeitos vem da fonte, nao do cache"
    assert out.index.is_monotonic_increasing and not out.index.has_duplicates


def test_bitstamp_sem_cache_busca_historico_inteiro(monkeypatch):
    pedidos = []

    def falso(since_ts=None):
        pedidos.append(since_ts)
        idx = pd.date_range("2012-01-01", periods=4000, freq="D")
        return pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}, index=idx)

    monkeypatch.setattr(btc_price, "load", lambda nome: None)
    monkeypatch.setattr(btc_price, "_fetch_bitstamp", falso)

    btc_price._fetch_incremental()
    assert pedidos == [None]
