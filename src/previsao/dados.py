"""Leitura das séries de venda no dw (agregadas no banco, nunca linha a linha)."""

from datetime import date

import pandas as pd
import psycopg

from src import config
from src.previsao.painel import Painel, montar_painel

CONSULTA_VENDAS_DIARIAS = """
    SELECT t.data, v.sk_loja, p.setor, SUM(v.receita_liquida) AS valor
    FROM dw.fato_vendas v
    JOIN dw.dim_tempo t ON t.sk_tempo = v.sk_tempo
    JOIN dw.dim_produto p ON p.sk_produto = v.sk_produto
    WHERE v.status = %(status)s AND t.data BETWEEN %(inicio)s AND %(fim)s
    GROUP BY t.data, v.sk_loja, p.setor
"""


def ultimo_dia_com_venda(conexao: psycopg.Connection) -> date:
    """Data de referência padrão: o último dia com venda válida no dw."""
    linha = conexao.execute(
        "SELECT max(t.data) FROM dw.fato_vendas v JOIN dw.dim_tempo t USING (sk_tempo)"
        " WHERE v.status = %s",
        (config.STATUS_VENDA_VALIDA,),
    ).fetchone()
    if linha is None or linha[0] is None:
        raise RuntimeError("o dw não tem nenhuma venda válida")
    return linha[0]


def primeiro_dia_com_venda(conexao: psycopg.Connection) -> date:
    linha = conexao.execute(
        "SELECT min(t.data) FROM dw.fato_vendas v JOIN dw.dim_tempo t USING (sk_tempo)"
        " WHERE v.status = %s",
        (config.STATUS_VENDA_VALIDA,),
    ).fetchone()
    if linha is None or linha[0] is None:
        raise RuntimeError("o dw não tem nenhuma venda válida")
    return linha[0]


def ler_painel(conexao: psycopg.Connection, inicio: date, fim: date) -> Painel:
    """Painel diário de receita líquida por (loja, setor) entre `inicio` e `fim`."""
    cursor = conexao.execute(
        CONSULTA_VENDAS_DIARIAS,
        {"status": config.STATUS_VENDA_VALIDA, "inicio": inicio, "fim": fim},
    )
    linhas = pd.DataFrame(cursor.fetchall(), columns=["data", "sk_loja", "setor", "valor"])
    linhas["valor"] = linhas["valor"].astype(float)
    return montar_painel(linhas, inicio, fim)
