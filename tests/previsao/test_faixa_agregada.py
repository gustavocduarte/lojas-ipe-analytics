"""Faixa calibrada no total da rede e da loja (sem banco)."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from src import config
from src.previsao import faixa, faixa_agregada, geracao
from tests.previsao.test_geracao import _constante, _painel, _resultado


def _dados():
    rng = np.random.default_rng(11)
    datas = pd.date_range("2025-07-01", periods=184)
    previsto = np.full((8, len(datas)), 100.0)
    real = previsto * rng.uniform(0.5, 1.5, previsto.shape)  # erros independentes entre séries
    lojas = np.array([1, 1, 2, 2, 3, 3, 4, 4])
    return datas, real, previsto, lojas


def test_faixa_do_total_e_bem_mais_estreita_que_a_soma_das_faixas():
    datas, real, previsto, lojas = _dados()
    setores = ["A"] * 8
    baixo_s, alto_s = faixa.aplicar_faixa(
        previsto, setores, faixa.calibrar_faixas(real, previsto, setores, datas), "dia"
    )
    faixas = faixa_agregada.calibrar(real, previsto, lojas, datas)
    baixo, alto = faixa_agregada.aplicar(previsto.sum(axis=0), faixas[("rede", "dia")])
    assert (alto - baixo).mean() < 0.5 * (alto_s.sum(axis=0) - baixo_s.sum(axis=0)).mean()


def test_cobertura_do_total_fica_perto_do_alvo_nos_proprios_dados():
    datas, real, previsto, lojas = _dados()
    faixas = faixa_agregada.calibrar(real, previsto, lojas, datas)
    c = faixa_agregada.cobertura(real, previsto, lojas, faixas, datas, "dia")
    assert c[("rede", None)] == pytest.approx(config.PREVISAO_COBERTURA_ALVO, abs=0.05)
    assert {loja for nivel, loja in c if nivel == "loja"} == {1, 2, 3, 4}
    assert all(0.7 < v < 0.9 for k, v in c.items() if k[0] == "loja")


def test_faixa_sempre_envolve_o_previsto():
    baixo, alto = faixa_agregada.aplicar(np.array([100.0, 0.0]), (1.2, 0.8))  # backtest enviesado
    assert (baixo <= [100, 0]).all() and (alto >= [100, 0]).all()


def test_gerar_traz_linhas_de_loja_e_rede_coerentes_com_as_series():
    painel = _painel()
    previsao = geracao.gerar(
        painel, _resultado(painel), date(2025, 9, 30), modelos={"constante": _constante}
    )
    ag = previsao.agregadas
    assert set(ag.nivel) == {"loja", "rede"}
    rede = ag[(ag.nivel == "rede") & (ag.granularidade == "mes")]
    assert rede.sk_loja.isna().all() and rede.setor.isna().all() and len(rede) == 3
    series = previsao.linhas[previsao.linhas.granularidade == "mes"]
    soma = series.groupby("data").valor_previsto.sum()
    for linha in rede.itertuples():
        assert linha.valor_previsto == pytest.approx(soma[linha.data], abs=0.5)
    lojas = ag[(ag.nivel == "loja") & (ag.granularidade == "dia")]
    assert set(lojas.sk_loja) == {1, 2} and lojas.setor.isna().all() and len(lojas) == 2 * 92
    assert (ag.valor_baixo <= ag.valor_previsto).all() and (
        ag.valor_previsto <= ag.valor_alto
    ).all()
    assert previsao.mensal_da_rede().index.tolist() == rede.data.tolist()
