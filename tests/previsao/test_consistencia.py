"""Consistência entre a previsão gravada e o modelo atual (lógica, sem banco).

O gravado vem de `geracao.gerar` (o caminho que grava em dw.previsao_vendas) e é comparado com o
recalculado em memória pelo caminho da probabilidade (`montar_cortes`/`prever`)."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.previsao import consistencia, geracao
from src.previsao import probabilidade_cortes as cortes_mod
from src.previsao.painel import Painel
from tests.previsao.test_geracao import _constante, _resultado

CORTE = date(2025, 6, 15)
FIM = date(2025, 6, 30)


def _painel() -> Painel:
    datas = pd.date_range("2025-01-01", "2025-06-30")
    base = 100 + 10 * datas.day_of_week.to_numpy()
    return Painel(datas, [(1, "A"), (1, "B"), (2, "A")], np.array([base, base * 2.0, base * 3.0]))


def _dobro(treino, alvo):
    return 2.0 * _constante(treino, alvo)


def _gravado(painel, modelo=_constante) -> pd.DataFrame:
    """As linhas loja x setor x dia do corte, como ficam em dw.vw_previsao_vigente."""
    resultado = _resultado(painel)
    previsao = geracao.gerar(painel.ate(CORTE), resultado, FIM, modelos={"constante": modelo})
    dia = previsao.linhas[previsao.linhas["granularidade"] == "dia"]
    return dia.assign(treino_ate=CORTE, versao_modelo=previsao.versao)[
        ["treino_ate", "versao_modelo", "data", "sk_loja", "setor", "valor_previsto"]
    ]


def _comparar(gravado, painel, **kw):
    kw.setdefault("modelo", _constante)
    kw.setdefault("versao_atual", "constante@2")
    return consistencia.comparar(gravado.assign(versao_modelo="constante@2"), painel, **kw)


def test_corte_gravado_com_o_modelo_atual_bate_na_rede_e_por_loja():
    painel = _painel()
    r = _comparar(_gravado(painel), painel)
    assert r["ok"].all()
    assert set(r["nivel"]) == {"loja", "rede"} and r["resto_do_mes"].all()
    assert r.loc[r["nivel"] == "loja", "sk_loja"].tolist() == [1, 2]
    assert r["dif"].abs().max() < 1e-9
    rede = r[r["nivel"] == "rede"].iloc[0]
    assert rede["gravado"] == pytest.approx(r.loc[r["nivel"] == "loja", "gravado"].sum())


def test_corte_gravado_com_outro_modelo_falha_em_todas_as_lojas():
    painel = _painel()
    r = _comparar(_gravado(painel, _dobro), painel)  # gravado com o dobro, modelo atual = constante
    assert not r["ok"].any()
    assert np.allclose(r["gravado"], 2 * r["recalculado"])


def test_corte_gravado_com_outra_versao_do_modelo_falha_mesmo_com_valores_iguais():
    painel = _painel()
    gravado = _gravado(painel)
    r = consistencia.comparar(
        gravado.assign(versao_modelo="constante@1"), painel, modelo=_constante,
        versao_atual="constante@2",
    )  # fmt: skip
    assert r["dif"].abs().max() < 1e-9 and not r["ok"].any()
    assert set(r["versao_gravada"]) == {"constante@1"}


def test_corte_gravado_com_painel_diferente_falha():
    painel = _painel()
    gravado = _gravado(painel)
    outro = Painel(painel.datas, painel.chaves, painel.valores * 1.01)
    r = _comparar(gravado, outro)
    assert not r["ok"].any()


def test_diferenca_de_arredondamento_acima_de_um_centavo_por_loja_e_reportada():
    painel = _painel()
    gravado = _gravado(painel)
    gravado.loc[gravado["sk_loja"] == 1, "valor_previsto"] += 0.004  # 15 dias x 2 setores
    r = _comparar(gravado, painel)
    loja1 = r[(r["nivel"] == "loja") & (r["sk_loja"] == 1)].iloc[0]
    assert loja1["dif"] == pytest.approx(0.004 * 30) and not loja1["ok"]
    assert r[(r["nivel"] == "loja") & (r["sk_loja"] == 2)]["ok"].all()
    texto = consistencia.relatorio(r)
    assert "loja 1" in texto and "fora da tolerância" in texto


def test_diferenca_pequena_dentro_da_tolerancia_passa_e_a_da_rede_soma_as_lojas():
    painel = _painel()
    gravado = _gravado(painel)
    gravado.loc[gravado.index[0], "valor_previsto"] += 0.009
    r = _comparar(gravado, painel)
    assert r["ok"].all()
    rede = r[r["nivel"] == "rede"].iloc[0]
    assert rede["tolerancia"] == pytest.approx(0.01 * 2)  # duas lojas
    # na rede, 0,018 passa (tolerância de 2 lojas = 0,02) e 0,021 não
    gravado.loc[gravado.index[-1], "valor_previsto"] += 0.009  # loja 2
    r2 = _comparar(gravado, painel)
    assert r2["ok"].all() and r2.query("nivel == 'rede'")["dif"].iloc[0] == pytest.approx(0.018)
    gravado.loc[gravado.index[-2], "valor_previsto"] += 0.003
    r3 = _comparar(gravado, painel)
    assert not r3.query("nivel == 'rede'")["ok"].iloc[0]
    assert r3.query("nivel == 'rede'")["dif"].iloc[0] == pytest.approx(0.021)


def test_o_previsto_do_resto_do_mes_e_o_mesmo_que_a_probabilidade_usa():
    painel = _painel()
    r = _comparar(_gravado(painel), painel)
    mes = pd.Timestamp(CORTE).replace(day=1)
    metas = {(1, mes): 1e6, (2, mes): 1e6}  # a rede só soma lojas com meta
    cortes = cortes_mod.montar_cortes(
        painel, metas, pd.Timestamp(CORTE), pd.Timestamp(CORTE), modelo=_constante
    )
    prob_rede = cortes[cortes["nivel"] == "rede"]["prev_resto"].iloc[0]
    prob_lojas = cortes[cortes["nivel"] == "loja"].set_index("sk_loja")["prev_resto"]
    lojas = r[(r["nivel"] == "loja") & r["resto_do_mes"]].set_index("sk_loja")["gravado"]
    assert prob_rede == pytest.approx(r[r["nivel"] == "rede"]["gravado"].iloc[0], abs=1e-9)
    assert lojas.to_dict() == pytest.approx(prob_lojas.to_dict(), abs=1e-9)


def test_o_recalculado_arredonda_cada_serie_dia_como_a_gravacao():
    painel = _painel()

    def quebrado(treino, alvo):  # 100,004 por dia: soma sem arredondar != soma arredondada
        return np.full((len(treino.chaves), len(alvo)), 100.004)

    gravado = _gravado(painel, quebrado)
    assert (gravado["valor_previsto"] == 100.0).all()  # a gravação arredonda por série-dia
    r = _comparar(gravado, painel, modelo=quebrado)
    assert r["ok"].all() and r["dif"].abs().max() < 1e-9


def test_relatorio_de_tudo_certo_e_sem_casos():
    painel = _painel()
    texto = consistencia.relatorio(_comparar(_gravado(painel), painel))
    assert "0 fora da tolerância" in texto and "piores casos" not in texto
    assert consistencia.relatorio(pd.DataFrame(columns=consistencia.COLUNAS)).startswith("nenhuma")
