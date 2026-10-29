"""Testes que precisam de um PostgreSQL. Marcados com @pytest.mark.banco: ficam de fora da
execução padrão (use `pytest -m banco`). Cada teste cria e apaga um banco próprio (fixture
banco_de_teste em conftest.py); nunca usa o lojas_ipe_dw."""

import psycopg
import pytest

from src import banco

pytestmark = pytest.mark.banco

TABELAS_DW = {
    "dim_tempo",
    "dim_hora",
    "dim_loja",
    "dim_loja_horario",
    "dim_produto",
    "dim_vendedor",
    "dim_cliente",
    "dim_forma_pagamento",
    "dim_campanha",
    "dim_centro_custo",
    "fato_vendas",
    "fato_meta_vendas",
    "fato_meta_vendedor",
    "fato_despesas",
    "fato_orcamento_despesas",
}
TABELAS_STG = {
    "lojas",
    "horarios_loja",
    "produtos",
    "centros_custo",
    "feriados",
    "formas_pagamento",
    "campanhas",
    "vendedores",
    "clientes",
    "vendas",
    "metas_vendas",
    "metas_vendedor",
    "despesas",
    "orcamento_despesas",
    "rejeitados",
}
TABELAS_ETL = {"cargas", "carga_arquivos", "arquivos_processados"}


def _tabelas(con, schema: str) -> set[str]:
    linhas = con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = %s", (schema,)
    ).fetchall()
    return {linha[0] for linha in linhas}


def _popular_dimensoes_minimas(con) -> None:
    """Uma linha em cada dimensão necessária para inserir uma venda."""
    con.execute(
        "INSERT INTO dw.dim_tempo VALUES (20240102, '2024-01-02', 2, 1, 1, 1, 2024,"
        " 'Janeiro', 'Terça-feira', FALSE, NULL)"
    )
    con.execute("INSERT INTO dw.dim_hora VALUES (14, 14, 'Tarde')")
    con.execute(
        "INSERT INTO dw.dim_loja"
        " (cod_loja, nome_loja, uf, regiao, cidade, formato, data_abertura)"
        " VALUES ('L01', 'Ipê São Paulo', 'SP', 'Sudeste', 'São Paulo', 'Hipermercado',"
        " '2010-03-12')"
    )
    con.execute(
        "INSERT INTO dw.dim_vendedor (cod_vendedor, nome_vendedor, sk_loja, cargo, turno,"
        " data_admissao, percentual_comissao)"
        " VALUES ('V0001', 'Ana Souza', 1, 'Vendedor', 'Integral', '2020-01-10', 1.00)"
    )
    con.execute(
        "INSERT INTO dw.dim_forma_pagamento (cod_forma_pagamento, nome_forma_pagamento)"
        " VALUES ('PIX', 'Pix')"
    )
    con.execute(
        "INSERT INTO dw.dim_produto"
        " (sku, nome_produto, marca, setor, categoria, custo_unitario, preco_lista)"
        " VALUES ('ALI-0001', 'Arroz', 'Campo Verde', 'Alimentos', 'Mercearia', 20.00, 28.90)"
    )


def _inserir_item(con, id_erp: str, status: str = "Concluída", motivo: str | None = None) -> None:
    con.execute(
        "INSERT INTO dw.fato_vendas (id_venda_erp, numero_cupom, numero_item, sk_tempo, sk_hora,"
        " data_hora_venda, sk_loja, caixa, sk_vendedor, sk_forma_pagamento, sk_produto,"
        " quantidade, preco_unitario, desconto, receita_liquida, custo, status,"
        " motivo_cancelamento_devolucao)"
        " VALUES (%s, 'CP1', 1, 20240102, 14, '2024-01-02 14:30:00', 1, 1, 1, 1, 1,"
        " 2, 28.90, 0, 57.80, 40.00, %s, %s)",
        (id_erp, status, motivo),
    )


def test_ddl_cria_todas_as_tabelas(banco_de_teste):
    aplicados = banco.aplicar_ddl(banco_de_teste)
    assert aplicados[0] == "01_schemas.sql"
    assert _tabelas(banco_de_teste, "dw") == TABELAS_DW
    assert _tabelas(banco_de_teste, "stg") == TABELAS_STG
    assert _tabelas(banco_de_teste, "etl") == TABELAS_ETL


def test_ddl_falha_ao_ser_reaplicado_em_banco_ja_criado(banco_de_teste):
    banco.aplicar_ddl(banco_de_teste)
    with pytest.raises(psycopg.errors.DuplicateTable):
        banco.aplicar_ddl(banco_de_teste)


def test_margem_e_calculada_pelo_banco_e_chaves_sao_geradas(banco_de_teste):
    banco.aplicar_ddl(banco_de_teste)
    _popular_dimensoes_minimas(banco_de_teste)
    _inserir_item(banco_de_teste, "VD1")
    margem = banco_de_teste.execute("SELECT margem FROM dw.fato_vendas").fetchone()[0]
    assert float(margem) == pytest.approx(17.80)


def test_cupom_duplicado_e_aceito_mas_cancelamento_exige_motivo(banco_de_teste):
    banco.aplicar_ddl(banco_de_teste)
    _popular_dimensoes_minimas(banco_de_teste)
    _inserir_item(banco_de_teste, "VD1")
    _inserir_item(banco_de_teste, "VD2")  # mesmo cupom e item, outro id do ERP
    assert banco_de_teste.execute("SELECT count(*) FROM dw.fato_vendas").fetchone()[0] == 2
    with pytest.raises(psycopg.errors.CheckViolation):
        _inserir_item(banco_de_teste, "VD3", status="Cancelada", motivo=None)


def test_despesa_com_documento_repetido_e_aceita_mas_orcamento_duplicado_nao(banco_de_teste):
    banco.aplicar_ddl(banco_de_teste)
    con = banco_de_teste
    con.execute(
        "INSERT INTO dw.dim_tempo VALUES (20240102, '2024-01-02', 2, 1, 1, 1, 2024,"
        " 'Janeiro', 'Terça-feira', FALSE, NULL)"
    )
    con.execute(
        "INSERT INTO dw.dim_centro_custo (cod_centro_custo, nome_centro_custo, tipo_despesa)"
        " VALUES ('COR-TI', 'TI', 'Terceiros')"
    )
    for _ in range(2):
        con.execute(
            "INSERT INTO dw.fato_despesas (numero_documento, sk_tempo, sk_centro_custo, valor)"
            " VALUES ('DOC0000001', 20240102, 1, 100)"
        )
    assert con.execute("SELECT count(*) FROM dw.fato_despesas").fetchone()[0] == 2

    con.execute(
        "INSERT INTO dw.fato_orcamento_despesas (sk_tempo, sk_centro_custo, valor_orcado)"
        " VALUES (20240102, 1, 500)"
    )
    with pytest.raises(psycopg.errors.UniqueViolation):
        con.execute(
            "INSERT INTO dw.fato_orcamento_despesas (sk_tempo, sk_centro_custo, valor_orcado)"
            " VALUES (20240102, 1, 600)"
        )


def test_horario_da_loja_exige_fechamento_depois_da_abertura(banco_de_teste):
    banco.aplicar_ddl(banco_de_teste)
    _popular_dimensoes_minimas(banco_de_teste)
    banco_de_teste.execute("INSERT INTO dw.dim_loja_horario VALUES (1, 7, '08:00', '20:00')")
    with pytest.raises(psycopg.errors.CheckViolation):
        banco_de_teste.execute("INSERT INTO dw.dim_loja_horario VALUES (1, 1, '22:00', '07:00')")
