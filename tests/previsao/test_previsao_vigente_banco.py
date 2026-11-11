"""Previsão vigente POR CORTE: a view, a função de fechamento e as views da probabilidade leem só a
versão certa de cada corte, sem duplicar, mesmo com versões em ordem cruzada (PostgreSQL)."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.previsao import consistencia, geracao
from src.previsao.painel import Painel
from tests.etl import base_alertas as b
from tests.previsao.test_geracao import _constante, _resultado
from tests.previsao.test_probabilidade_meta_banco import _inserir, _lojas
from tests.previsao.test_projecoes import _fechamento, _prever_resto, _vender_ate

pytestmark = pytest.mark.banco

A, B = date(2024, 3, 10), date(2024, 3, 20)  # dois cortes do mesmo mês


@pytest.fixture
def base(banco_com_ddl):
    b.montar_base(banco_com_ddl, ano=2024)
    return banco_com_ddl


def _versoes_cruzadas(con):
    """A: m@2 é a mais nova (m@1 é velha). B: m@1 é a mais nova de todas, m@2 é velha. A versão mais
    recente do banco inteiro é m@1 (corte B), mas o corte A tem que ficar com m@2."""
    _prever_resto(con, A, "m@1", valor=10, gerado="2024-03-20 00:00")
    _prever_resto(con, A, "m@2", valor=20, gerado="2024-03-30 00:00")
    _prever_resto(con, B, "m@2", valor=30, gerado="2024-03-25 00:00")
    _prever_resto(con, B, "m@1", valor=40, gerado="2024-04-05 00:00")


def test_view_vigente_traz_uma_versao_por_corte_sem_duplicar(base):
    _versoes_cruzadas(base)
    linhas = base.execute(
        "SELECT treino_ate, versao_modelo, count(*), sum(valor_previsto)"
        " FROM dw.vw_previsao_vigente GROUP BY 1, 2 ORDER BY 1"
    ).fetchall()
    assert [(c, v, n, float(s)) for c, v, n, s in linhas] == [
        (A, "m@2", 21, 21 * 20.0),
        (B, "m@1", 11, 11 * 40.0),
    ]
    # nenhuma chave duplicada no grão
    duplicadas = base.execute(
        "SELECT count(*) FROM (SELECT treino_ate, granularidade, data, sk_loja, setor, nivel"
        " FROM dw.vw_previsao_vigente GROUP BY 1, 2, 3, 4, 5, 6 HAVING count(*) > 1) d"
    ).fetchone()[0]
    assert duplicadas == 0
    # as linhas antigas continuam na tabela (nada é apagado)
    assert base.execute("SELECT count(*) FROM dw.previsao_vendas").fetchone()[0] == 2 * (21 + 11)


def test_funcao_de_fechamento_usa_a_versao_vigente_de_cada_corte(base):
    _vender_ate(base, 20)
    _versoes_cruzadas(base)
    (a,) = _fechamento(base, A)
    (bb,) = _fechamento(base, B)
    assert a[1] == 21 * 20 and bb[1] == 11 * 40  # previsto_restante de cada corte
    assert a[2] == a[0] + 21 * 20 and bb[2] == bb[0] + 11 * 40


def test_corte_com_uma_unica_versao_continua_valendo(base):
    _vender_ate(base, 10)
    _prever_resto(base, A, "so@1", valor=7, gerado="2020-01-01")
    (linha,) = _fechamento(base, A)
    assert linha[1] == 21 * 7


def test_simulador_le_a_previsao_vigente(base):
    definicao = base.execute("SELECT pg_get_viewdef('dw.vw_simulador_troca'::regclass)").fetchone()[
        0
    ]
    assert "vw_previsao_vigente" in definicao
    assert base.execute("SELECT count(*) FROM dw.vw_simulador_troca").fetchone()[0] == 0


# --- probabilidade: a versão vigente é por dia de referência -------------------------------------
def test_probabilidade_vigente_por_dia_com_versoes_cruzadas_e_sem_duplicar(base):
    sk = _lojas(base)[0]
    for dia in range(3, 9):  # p1, a mais antiga, nos dias 3 a 8
        _inserir(base, data_referencia=f"2025-03-{dia:02d}", versao="p1", probabilidade=0.1,
                 gerado_em="2025-01-01")  # fmt: skip
        _inserir(base, nivel="rede", sk_loja=None, data_referencia=f"2025-03-{dia:02d}",
                 versao="p1", probabilidade=0.1, gerado_em="2025-01-01")  # fmt: skip
    for dia in range(1, 6):  # p2, a mais nova, nos dias 1 a 5
        _inserir(base, data_referencia=f"2025-03-{dia:02d}", versao="p2", probabilidade=0.2,
                 gerado_em="2025-02-01")  # fmt: skip
        _inserir(base, nivel="rede", sk_loja=None, data_referencia=f"2025-03-{dia:02d}",
                 versao="p2", probabilidade=0.2, gerado_em="2025-02-01")  # fmt: skip
    esperado = {dia: 0.2 if dia <= 5 else 0.1 for dia in range(1, 9)}
    for view in ("vw_probabilidade_meta_loja", "vw_probabilidade_meta_rede"):
        linhas = base.execute(
            f"SELECT data_referencia, probabilidade FROM dw.{view} ORDER BY data_referencia"
        ).fetchall()
        assert len(linhas) == 8  # uma por dia: nada duplicado
        assert {d.day: round(p, 4) for d, p in linhas} == esperado
    assert sk is not None


# --- consistência com o banco ---------------------------------------------------------------------
def _painel_da_loja(sk: int) -> Painel:
    datas = pd.date_range("2025-01-01", "2025-06-30")
    base_ = 100 + 10 * datas.day_of_week.to_numpy()
    return Painel(datas, [(sk, "Alimentos")], np.array([base_]))


def _dobro(treino, alvo):
    return 2.0 * _constante(treino, alvo)


def test_corte_gravado_atual_bate_e_corte_desatualizado_falha(base):
    sk = _lojas(base)[0]
    painel = _painel_da_loja(sk)
    resultado = _resultado(painel)
    corte, fim = date(2025, 6, 15), date(2025, 6, 30)
    atual = geracao.gerar(painel.ate(corte), resultado, fim, modelos={"constante": _constante})
    geracao.gravar_previsao(base, atual)
    r = consistencia.verificar(base, painel, modelo=_constante, versao_atual=atual.versao)
    assert not r.empty and r["ok"].all() and r["dif"].abs().max() < 0.01

    # o mesmo corte regravado por um modelo antigo (o dobro) fica desatualizado: tem que falhar
    velho = geracao.gerar(painel.ate(corte), resultado, fim, modelos={"constante": _dobro})
    geracao.gravar_previsao(base, velho)
    r = consistencia.verificar(base, painel, modelo=_constante, versao_atual=atual.versao)
    assert not r["ok"].any()
    assert r.loc[r["nivel"] == "rede", "dif"].iloc[0] == pytest.approx(
        r.loc[r["nivel"] == "rede", "recalculado"].iloc[0]
    )

    # versão do modelo diferente da atual também falha, mesmo com os valores certos
    geracao.gravar_previsao(base, atual)
    r = consistencia.verificar(base, painel, modelo=_constante, versao_atual="constante@99")
    assert not r["ok"].any()
