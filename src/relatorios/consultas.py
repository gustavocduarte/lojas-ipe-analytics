"""Consultas ao dw que alimentam o relatório de fechamento (uma por aba).

Todas recebem o primeiro dia do mês (`mes`) e o dia de posição (`dia`, dentro do mês) e devolvem
DataFrames com números (float) e datas (date); a formatação brasileira fica para a planilha.
"""

from datetime import date

import pandas as pd
import psycopg

from src import config

PARAMETROS_BASE = """
    par AS (
        SELECT %(mes)s::DATE AS ini, %(dia)s::DATE AS dia,
               (%(mes)s::DATE - INTERVAL '1 year')::DATE AS ini_ant,
               (%(dia)s::DATE - INTERVAL '1 year')::DATE AS dia_ant
    )
"""


def _df(conexao: psycopg.Connection, sql: str, params: dict) -> pd.DataFrame:
    cursor = conexao.execute(sql, params)
    colunas = [c.name for c in cursor.description]
    quadro = pd.DataFrame(cursor.fetchall(), columns=colunas)
    for coluna in quadro.columns:  # Decimal -> float (o Excel guarda float de qualquer jeito)
        if quadro[coluna].map(lambda v: type(v).__name__ == "Decimal").any():
            quadro[coluna] = quadro[coluna].map(lambda v: None if v is None else float(v))
    return quadro


def parametros(mes: date, dia: date) -> dict:
    return {"mes": mes, "dia": dia, "status": config.STATUS_VENDA_VALIDA}


def lojas(conexao: psycopg.Connection, mes: date, dia: date) -> pd.DataFrame:
    """Uma linha por loja: venda e meta do dia, acumulado, meta do mês, evolução e projeção."""
    sql = f"""
    WITH {PARAMETROS_BASE},
    venda AS (
        SELECT v.sk_loja,
               SUM(v.receita_liquida) FILTER (WHERE t.data = par.dia) AS venda_dia,
               SUM(v.receita_liquida)
                   FILTER (WHERE t.data BETWEEN par.ini AND par.dia) AS acumulado,
               SUM(v.receita_liquida)
                   FILTER (WHERE t.data BETWEEN par.ini_ant AND par.dia_ant)
                   AS acumulado_ano_anterior
        FROM dw.fato_vendas v
        JOIN dw.dim_tempo t ON t.sk_tempo = v.sk_tempo
        CROSS JOIN par
        WHERE v.status = %(status)s AND t.data BETWEEN par.ini_ant AND par.dia
        GROUP BY v.sk_loja
    ),
    meta_dia AS (
        SELECT m.sk_loja,
               SUM(m.valor_meta_dia) FILTER (WHERE m.data = par.dia) AS meta_dia,
               SUM(m.valor_meta_dia) FILTER (WHERE m.data BETWEEN par.ini AND par.dia)
                   AS meta_acumulada
        FROM dw.vw_meta_vendas_diaria m
        CROSS JOIN par
        WHERE m.data BETWEEN par.ini AND par.dia
        GROUP BY m.sk_loja
    ),
    meta_mes AS (
        SELECT m.sk_loja, SUM(m.valor_meta) AS meta_mes
        FROM dw.fato_meta_vendas m
        JOIN par ON m.sk_tempo = to_char(par.ini, 'YYYYMMDD')::INT
        GROUP BY m.sk_loja
    ),
    projecao AS (
        SELECT sk_loja, SUM(projecao_fechamento) AS projecao_fechamento
        FROM dw.fn_projecao_fechamento_mes(%(dia)s)
        GROUP BY sk_loja
    )
    SELECT l.cod_loja, l.nome_loja, l.uf,
           COALESCE(v.venda_dia, 0) AS venda_dia,
           md.meta_dia,
           COALESCE(v.venda_dia, 0) / NULLIF(md.meta_dia, 0) AS cobertura_dia,
           COALESCE(v.acumulado, 0) AS acumulado_mes,
           md.meta_acumulada,
           mm.meta_mes,
           COALESCE(v.acumulado, 0) / NULLIF(mm.meta_mes, 0) AS cobertura_mes,
           v.acumulado_ano_anterior,
           v.acumulado / NULLIF(v.acumulado_ano_anterior, 0) - 1 AS evolucao_ano_anterior,
           p.projecao_fechamento,
           p.projecao_fechamento / NULLIF(mm.meta_mes, 0) AS cobertura_projetada
    FROM dw.dim_loja l
    LEFT JOIN venda v ON v.sk_loja = l.sk_loja
    LEFT JOIN meta_dia md ON md.sk_loja = l.sk_loja
    LEFT JOIN meta_mes mm ON mm.sk_loja = l.sk_loja
    LEFT JOIN projecao p ON p.sk_loja = l.sk_loja
    WHERE v.sk_loja IS NOT NULL OR mm.sk_loja IS NOT NULL
    ORDER BY l.cod_loja
    """
    return _df(conexao, sql, parametros(mes, dia))


def indicadores_da_rede(conexao: psycopg.Connection, mes: date, dia: date) -> dict:
    """Margem, cupons e ticket médio do mês até o dia (a receita e as metas vêm de `lojas`)."""
    sql = f"""
    WITH {PARAMETROS_BASE}
    SELECT COALESCE(SUM(v.receita_liquida), 0), COALESCE(SUM(v.margem), 0),
           COUNT(DISTINCT (v.sk_loja, v.numero_cupom))
    FROM dw.fato_vendas v
    JOIN dw.dim_tempo t ON t.sk_tempo = v.sk_tempo
    CROSS JOIN par
    WHERE v.status = %(status)s AND t.data BETWEEN par.ini AND par.dia
    """
    receita, margem, cupons = conexao.execute(sql, parametros(mes, dia)).fetchone()
    receita, margem = float(receita), float(margem)
    return {
        "receita": receita,
        "margem": margem,
        "margem_percentual": margem / receita if receita else None,
        "cupons": cupons,
        "ticket_medio": receita / cupons if cupons else None,
    }


def vendas_por_dia(conexao: psycopg.Connection, mes: date, dia: date) -> pd.DataFrame:
    """Todos os dias do mês: venda (vazia depois de `dia`) e meta do dia da rede."""
    sql = f"""
    WITH {PARAMETROS_BASE},
    venda AS (
        SELECT t.data, SUM(v.receita_liquida) AS venda
        FROM dw.fato_vendas v
        JOIN dw.dim_tempo t ON t.sk_tempo = v.sk_tempo
        CROSS JOIN par
        WHERE v.status = %(status)s AND t.data BETWEEN par.ini AND par.dia
        GROUP BY t.data
    )
    SELECT t.data AS dia, ve.venda, SUM(m.valor_meta_dia) AS meta_dia
    FROM dw.dim_tempo t
    CROSS JOIN par
    LEFT JOIN venda ve ON ve.data = t.data
    LEFT JOIN dw.vw_meta_vendas_diaria m ON m.data = t.data
    WHERE t.data BETWEEN par.ini AND (par.ini + INTERVAL '1 month' - INTERVAL '1 day')
    GROUP BY t.data, ve.venda
    ORDER BY t.data
    """
    return _df(conexao, sql, parametros(mes, dia))


def vendedores(conexao: psycopg.Connection, mes: date, dia: date) -> pd.DataFrame:
    """Ranking de vendedores pela receita do mês até o dia, com meta e cobertura."""
    sql = f"""
    WITH {PARAMETROS_BASE},
    venda AS (
        SELECT v.sk_vendedor, SUM(v.receita_liquida) AS acumulado
        FROM dw.fato_vendas v
        JOIN dw.dim_tempo t ON t.sk_tempo = v.sk_tempo
        CROSS JOIN par
        WHERE v.status = %(status)s AND t.data BETWEEN par.ini AND par.dia
        GROUP BY v.sk_vendedor
    ),
    meta AS (
        SELECT m.sk_vendedor, m.valor_meta
        FROM dw.fato_meta_vendedor m
        JOIN par ON m.sk_tempo = to_char(par.ini, 'YYYYMMDD')::INT
    )
    SELECT RANK() OVER (ORDER BY COALESCE(v.acumulado, 0) DESC) AS posicao,
           d.cod_vendedor, d.nome_vendedor, l.cod_loja, l.nome_loja,
           COALESCE(v.acumulado, 0) AS acumulado_mes,
           m.valor_meta AS meta_mes,
           COALESCE(v.acumulado, 0) / NULLIF(m.valor_meta, 0) AS cobertura_mes
    FROM dw.dim_vendedor d
    JOIN dw.dim_loja l ON l.sk_loja = d.sk_loja
    LEFT JOIN venda v ON v.sk_vendedor = d.sk_vendedor
    LEFT JOIN meta m ON m.sk_vendedor = d.sk_vendedor
    WHERE v.sk_vendedor IS NOT NULL OR m.sk_vendedor IS NOT NULL
    ORDER BY posicao, d.cod_vendedor
    """
    return _df(conexao, sql, parametros(mes, dia))


def alertas_abertos(conexao: psycopg.Connection) -> pd.DataFrame:
    """Alertas vigentes e independentes ainda não tratados (novo ou em análise), do mais grave."""
    sql = """
    SELECT severidade_nome AS severidade, nome_tipo_alerta AS tipo, data_alerta AS data,
           COALESCE(nome_loja, nome_centro_custo, '-') AS loja_ou_centro,
           nome_vendedor AS vendedor, valor_envolvido, status_nome AS status, explicacao
    FROM dw.vw_alertas_detalhe
    WHERE conta_no_painel AND status IN ('novo', 'em_analise')
    ORDER BY severidade_ordem DESC, valor_envolvido DESC NULLS LAST, data_alerta DESC, chave_alerta
    """
    return _df(conexao, sql, {})


def previsao_mensal(conexao: psycopg.Connection) -> pd.DataFrame:
    """Previsão mensal por loja da execução mais recente, com faixa e erro do backtest da loja."""
    sql = """
    WITH ultima AS (
        SELECT versao_modelo, treino_ate
        FROM dw.previsao_vendas
        WHERE nivel = 'loja_setor' AND granularidade = 'mes'
        ORDER BY gerado_em DESC, treino_ate DESC LIMIT 1
    ),
    wape AS (
        SELECT b.sk_loja, b.wape
        FROM dw.previsao_backtest b
        JOIN ultima u ON u.versao_modelo = b.versao_modelo
        WHERE b.nivel = 'loja' AND b.granularidade = 'mes' AND b.sk_loja IS NOT NULL
          AND b.treino_ate = (SELECT max(treino_ate) FROM dw.previsao_backtest
                              WHERE versao_modelo = u.versao_modelo)
    )
    SELECT f.data AS mes, l.cod_loja, l.nome_loja,
           SUM(f.valor_previsto) AS previsto,
           COALESCE(MAX(t.valor_baixo), SUM(f.valor_baixo)) AS faixa_baixa,
           COALESCE(MAX(t.valor_alto), SUM(f.valor_alto)) AS faixa_alta,
           w.wape AS wape_backtest_loja, f.versao_modelo, f.treino_ate
    FROM dw.previsao_vendas f
    JOIN ultima u ON u.versao_modelo = f.versao_modelo AND u.treino_ate = f.treino_ate
    JOIN dw.dim_loja l ON l.sk_loja = f.sk_loja
    LEFT JOIN wape w ON w.sk_loja = f.sk_loja
    LEFT JOIN dw.previsao_vendas t ON t.nivel = 'loja' AND t.granularidade = 'mes'
         AND t.data = f.data AND t.sk_loja = f.sk_loja AND t.versao_modelo = f.versao_modelo
         AND t.treino_ate = f.treino_ate
    WHERE f.nivel = 'loja_setor' AND f.granularidade = 'mes'
    GROUP BY f.data, l.cod_loja, l.nome_loja, w.wape, f.versao_modelo, f.treino_ate
    ORDER BY f.data, l.cod_loja
    """
    return _df(conexao, sql, {})


def previsao_diaria_da_rede(conexao: psycopg.Connection) -> pd.DataFrame:
    """Previsão diária da rede (execução mais recente), para o gráfico da aba Previsão."""
    sql = """
    WITH ultima AS (
        SELECT versao_modelo, treino_ate
        FROM dw.previsao_vendas
        WHERE nivel = 'loja_setor' AND granularidade = 'mes'
        ORDER BY gerado_em DESC, treino_ate DESC LIMIT 1
    )
    SELECT f.data AS dia, SUM(f.valor_previsto) AS previsto
    FROM dw.previsao_vendas f
    JOIN ultima u ON u.versao_modelo = f.versao_modelo AND u.treino_ate = f.treino_ate
    WHERE f.nivel = 'loja_setor' AND f.granularidade = 'dia'
    GROUP BY f.data
    ORDER BY f.data
    """
    return _df(conexao, sql, {})
