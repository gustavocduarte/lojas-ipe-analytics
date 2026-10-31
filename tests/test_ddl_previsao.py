"""Tabelas da previsão de vendas (Fase 4): restrições e unicidade. Precisam de PostgreSQL."""

import psycopg
import pytest

pytestmark = pytest.mark.banco

LINHA = (
    "INSERT INTO dw.previsao_vendas (granularidade, data, sk_loja, setor, valor_previsto,"
    " valor_baixo, valor_alto, versao_modelo, treino_ate) VALUES (%s, %s, 1, 'Alimentos', %s, %s,"
    " %s, 'decomposicao@1', '2025-12-31')"
)


@pytest.fixture
def base(banco_com_ddl):
    banco_com_ddl.execute(
        "INSERT INTO dw.dim_loja (cod_loja, nome_loja, uf, regiao, cidade, formato, data_abertura)"
        " VALUES ('L01', 'Ipê 1', 'SP', 'Sudeste', 'São Paulo', 'Supermercado', '2010-01-01')"
    )
    return banco_com_ddl


def test_faixa_precisa_envolver_o_previsto(base):
    base.execute(LINHA, ("dia", "2026-01-02", 100, 50, 150))
    with pytest.raises(psycopg.errors.CheckViolation):
        base.execute(LINHA, ("dia", "2026-01-03", 100, 120, 150))


def test_previsao_mensal_precisa_ser_do_primeiro_dia(base):
    base.execute(LINHA, ("mes", "2026-01-01", 100, 50, 150))
    with pytest.raises(psycopg.errors.CheckViolation):
        base.execute(LINHA, ("mes", "2026-01-15", 100, 50, 150))


def test_mesma_previsao_nao_se_repete(base):
    base.execute(LINHA, ("dia", "2026-01-02", 100, 50, 150))
    with pytest.raises(psycopg.errors.UniqueViolation):
        base.execute(LINHA, ("dia", "2026-01-02", 110, 50, 150))


def test_backtest_aceita_nivel_sem_loja_e_barra_duplicidade(base):
    comando = (
        "INSERT INTO dw.previsao_backtest (versao_modelo, nivel, granularidade, treino_ate,"
        " teste_inicio, teste_fim, wape, vies) VALUES ('ingenua@1', 'rede', 'mes', '2025-06-30',"
        " '2025-07-01', '2025-12-31', 0.1, -0.02)"
    )
    base.execute(comando)
    with pytest.raises(psycopg.errors.UniqueViolation):
        base.execute(comando)


def test_backtest_exige_teste_depois_do_treino(base):
    with pytest.raises(psycopg.errors.CheckViolation):
        base.execute(
            "INSERT INTO dw.previsao_backtest (versao_modelo, nivel, granularidade, treino_ate,"
            " teste_inicio, teste_fim, wape, vies) VALUES ('x@1', 'rede', 'mes', '2025-06-30',"
            " '2025-06-30', '2025-12-31', 0.1, 0)"
        )


def test_parametros_do_fechamento_de_despesas_existem(base):
    chaves = {c for (c,) in base.execute("SELECT chave FROM etl.parametros_negocio").fetchall()}
    assert {"projecao_fator_min", "projecao_fator_max"} <= chaves
