"""Backtest de várias origens (rolling origin) com resíduos sintéticos de distribuição conhecida."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from src import config
from src.previsao import rolling

CHAVES = [(1, "A"), (1, "B"), (2, "A"), (2, "B")]
ULTIMO = date(2025, 12, 31)


def _obter(origem: date, inicio: date, fim: date):
    """Previsto 100 por série e dia; real = previsto x uniforme(0,8; 1,2), semente por origem."""
    datas = pd.date_range(inicio, fim)
    rng = np.random.default_rng(origem.toordinal())
    previsto = np.full((len(CHAVES), len(datas)), 100.0)
    return previsto * rng.uniform(0.8, 1.2, previsto.shape), previsto, datas


def _origens(ultima=date(2025, 9, 30)):
    datas = rolling.origens_mensais(date(2025, 1, 31), ultima)
    return rolling.coletar(_obter, CHAVES, CHAVES, datas, ULTIMO)


def test_origens_sao_fins_de_mes():
    assert rolling.origens_mensais(date(2025, 1, 31), date(2025, 4, 30)) == [
        date(2025, 1, 31), date(2025, 2, 28), date(2025, 3, 31), date(2025, 4, 30),
    ]  # fmt: skip


def test_origem_com_horizonte_alem_do_ultimo_dia_e_pulada():
    origens = rolling.coletar(
        _obter, CHAVES, CHAVES, [date(2025, 9, 30), date(2025, 10, 31)], ULTIMO
    )
    assert [o.origem for o in origens] == [date(2025, 9, 30)]  # 31/10 + 3 meses passa de 31/12


def test_cada_origem_preve_os_tres_meses_seguintes():
    o = _origens()[0]
    assert o.datas[0] == pd.Timestamp("2025-02-01") and o.datas[-1] == pd.Timestamp("2025-04-30")


def test_faixa_da_rede_calibrada_em_varias_origens_cobre_perto_de_80():
    origens = _origens()
    assert len(origens) == 9
    agregadas, series = rolling.calibrar(origens)
    assert set(series) == {(g, s) for g in ("dia", "mes") for s in ("A", "B")}
    baixo, alto = agregadas[("rede", "dia")]
    assert baixo < 1 < alto
    medida = rolling.medir_cobertura(origens)["agregado"]
    rede = medida[(medida.granularidade == "dia") & medida.sk_loja.isna()]
    for linha in rede.itertuples():
        assert linha.cobertura == pytest.approx(config.PREVISAO_COBERTURA_ALVO, abs=0.06)


def test_conta_os_pontos_que_entraram():
    medida = rolling.medir_cobertura(_origens())["agregado"]
    rede_mes = medida[(medida.granularidade == "mes") & medida.sk_loja.isna()]
    na_amostra = rede_mes[rede_mes.origem_faixa == "na_amostra"].pontos.iloc[0]
    assert na_amostra == 9 * 3  # 9 origens x 3 meses, totais da rede
    por_loja = medida[(medida.granularidade == "mes") & medida.sk_loja.notna()]
    assert set(por_loja.pontos) == {9 * 3}


def test_fora_da_amostra_nunca_usa_origens_que_se_sobrepoem():
    # com origens em meses vizinhos todas se sobrepõem: não há como medir fora da amostra
    vizinhas = rolling.coletar(
        _obter, CHAVES, CHAVES, [date(2025, 1, 31), date(2025, 2, 28)], ULTIMO
    )
    medida = rolling.medir_cobertura(vizinhas)["agregado"]
    assert set(medida.origem_faixa) == {"na_amostra"}
    # com 3 meses de distância, cada uma é medida com a faixa da outra
    distantes = rolling.coletar(
        _obter, CHAVES, CHAVES, [date(2025, 1, 31), date(2025, 4, 30)], ULTIMO
    )
    medida = rolling.medir_cobertura(distantes)["agregado"]
    assert set(medida.origem_faixa) == {"na_amostra", "fora_da_amostra"}
    fora = medida[(medida.origem_faixa == "fora_da_amostra") & medida.sk_loja.isna()]
    assert fora.pontos.min() > 0


def test_serie_que_nao_existia_na_origem_fica_fora_dela():
    def obter(origem, inicio, fim):
        real, previsto, datas = _obter(origem, inicio, fim)
        if origem < date(2025, 3, 1):
            real[3] = np.nan  # a série 4 ainda não vendia
        return real, previsto, datas

    origens = rolling.coletar(obter, CHAVES, CHAVES, [date(2025, 1, 31), date(2025, 4, 30)], ULTIMO)
    assert [len(o.lojas) for o in origens] == [3, 4]
