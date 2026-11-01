"""Consultas ao dw que alimentam o relatório de fechamento (uma por aba).

Todas recebem o primeiro dia do mês (`mes`) e o dia de posição (`dia`, dentro do mês) e devolvem
DataFrames com números (float) e datas (date); a formatação brasileira fica para a planilha.
"""

from datetime import date

import pandas as pd
import psycopg

from src import config

TIPO_CANCELAMENTO_ALTO = "vendedor_cancelamento_alto"

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
           COALESCE(v.acumulado, 0) / NULLIF(md.meta_acumulada, 0) AS cobertura_ate_o_dia,
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


def projecao_por_dia(conexao: psycopg.Connection, mes: date, dia: date) -> pd.DataFrame:
    """Venda prevista da rede em cada dia do mês depois de `dia`: a mesma previsão (mesma execução
    do modelo, treinada até `dia`) que fecha a projeção de fechamento do mês em
    `dw.fn_projecao_fechamento_mes`. Vazio quando não há previsão para essa posição."""
    sql = """
    WITH versao AS (
        SELECT versao_modelo FROM dw.previsao_vendas
        WHERE nivel = 'loja_setor' AND treino_ate = %(dia)s
        ORDER BY gerado_em DESC, versao_modelo LIMIT 1
    )
    SELECT f.data AS dia, SUM(f.valor_previsto) AS projecao
    FROM dw.previsao_vendas f
    JOIN versao USING (versao_modelo)
    WHERE f.nivel = 'loja_setor' AND f.granularidade = 'dia' AND f.treino_ate = %(dia)s
      AND f.data > %(dia)s
      AND f.data <= (date_trunc('month', %(mes)s::DATE) + INTERVAL '1 month' - INTERVAL '1 day')
    GROUP BY f.data
    ORDER BY f.data
    """
    return _df(conexao, sql, {"mes": mes, "dia": dia})


def vendedores(conexao: psycopg.Connection, mes: date, dia: date) -> pd.DataFrame:
    """Ranking de vendedores pela receita do mês até o dia: meta, cobertura e setor principal."""
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
    ),
    meta_dia AS (
        SELECT m.sk_vendedor, SUM(m.valor_meta_dia) AS meta_acumulada
        FROM dw.vw_meta_vendedor_diaria m
        CROSS JOIN par
        WHERE m.data BETWEEN par.ini AND par.dia
        GROUP BY m.sk_vendedor
    ),
    meta_restante AS (  -- a meta dos dias depois da posição, até o fim do mês
        SELECT m.sk_vendedor, SUM(m.valor_meta_dia) AS meta_restante
        FROM dw.vw_meta_vendedor_diaria m
        CROSS JOIN par
        WHERE m.data > par.dia AND m.data < (par.ini + INTERVAL '1 month')::DATE
        GROUP BY m.sk_vendedor
    ),
    setor_do_vendedor AS (
        SELECT v.sk_vendedor, p.setor, SUM(v.receita_liquida) AS receita
        FROM dw.fato_vendas v
        JOIN dw.dim_tempo t ON t.sk_tempo = v.sk_tempo
        JOIN dw.dim_produto p ON p.sk_produto = v.sk_produto
        CROSS JOIN par
        WHERE v.status = %(status)s AND t.data BETWEEN par.ini AND par.dia
        GROUP BY v.sk_vendedor, p.setor
    ),
    principal AS (  -- o setor de maior receita do vendedor (empate: ordem alfabética)
        SELECT DISTINCT ON (sk_vendedor) sk_vendedor, setor, receita
        FROM setor_do_vendedor
        ORDER BY sk_vendedor, receita DESC, setor
    ),
    lotacao AS (  -- o setor em que o vendedor está lotado na posição e quanto vendeu nele
        SELECT h.sk_vendedor, h.setor,
               (SELECT SUM(v.receita_liquida)
                FROM dw.fato_vendas v
                JOIN dw.dim_tempo t ON t.sk_tempo = v.sk_tempo
                JOIN dw.dim_produto p ON p.sk_produto = v.sk_produto
                JOIN dw.vendedor_setor_historico x ON x.sk_vendedor = v.sk_vendedor
                     AND x.setor = p.setor AND t.data BETWEEN x.data_inicio
                         AND COALESCE(x.data_fim, DATE 'infinity')
                WHERE v.status = %(status)s AND v.sk_vendedor = h.sk_vendedor
                  AND t.data BETWEEN par.ini AND par.dia) AS receita_no_setor
        FROM dw.vendedor_setor_historico h
        CROSS JOIN par
        WHERE par.dia BETWEEN h.data_inicio AND COALESCE(h.data_fim, DATE 'infinity')
    )
    SELECT RANK() OVER (ORDER BY COALESCE(v.acumulado, 0) DESC) AS posicao,
           d.cod_vendedor, d.nome_vendedor, l.cod_loja, l.nome_loja,
           COALESCE(v.acumulado, 0) AS acumulado_mes,
           md.meta_acumulada,
           COALESCE(v.acumulado, 0) / NULLIF(md.meta_acumulada, 0) AS cobertura_ate_o_dia,
           m.valor_meta AS meta_mes,
           COALESCE(v.acumulado, 0) / NULLIF(m.valor_meta, 0) AS cobertura_mes,
           -- ritmo necessário: o que falta da meta do mês dividido pelos dias que restam, contados
           -- em "dias médios" (a meta dos dias restantes ÷ a meta de um dia médio do mês)
           GREATEST(m.valor_meta - COALESCE(v.acumulado, 0), 0)
               / NULLIF(mr.meta_restante / NULLIF(m.valor_meta / EXTRACT(DAY FROM
                   (par.ini + INTERVAL '1 month' - INTERVAL '1 day')), 0), 0)
               AS ritmo_necessario_dia,
           pr.setor AS setor_principal,
           pr.receita / NULLIF(v.acumulado, 0) AS percentual_setor_principal,
           lo.setor AS setor_lotacao,
           lo.receita_no_setor / NULLIF(v.acumulado, 0) AS percentual_setor_lotacao
    FROM dw.dim_vendedor d
    JOIN dw.dim_loja l ON l.sk_loja = d.sk_loja
    LEFT JOIN venda v ON v.sk_vendedor = d.sk_vendedor
    LEFT JOIN meta m ON m.sk_vendedor = d.sk_vendedor
    LEFT JOIN meta_dia md ON md.sk_vendedor = d.sk_vendedor
    LEFT JOIN meta_restante mr ON mr.sk_vendedor = d.sk_vendedor
    LEFT JOIN principal pr ON pr.sk_vendedor = d.sk_vendedor
    LEFT JOIN lotacao lo ON lo.sk_vendedor = d.sk_vendedor
    CROSS JOIN par
    WHERE v.sk_vendedor IS NOT NULL OR m.sk_vendedor IS NOT NULL
    ORDER BY posicao, d.cod_vendedor
    """
    return _df(conexao, sql, parametros(mes, dia))


def classificar_abc(participacao_acumulada: pd.Series) -> pd.Series:
    """Classe ABC pela participação acumulada na receita (produtos já ordenados do maior ao menor):
    A até o limite A (inclusive), B até o limite B, C o resto. Limites em `config`."""
    folga = 1e-9  # a soma de frações em ponto flutuante não pode empurrar 80% para a classe B

    def classe(acumulada: float) -> str:
        if acumulada <= config.RELATORIO_ABC_LIMITE_A + folga:
            return "A"
        return "B" if acumulada <= config.RELATORIO_ABC_LIMITE_B + folga else "C"

    return participacao_acumulada.map(classe)


def produtos(conexao: psycopg.Connection, mes: date, dia: date) -> pd.DataFrame:
    """Produtos da rede no mês até o dia (vendas concluídas), do maior ao menor em receita, com
    participação, participação acumulada e classe ABC calculadas sobre a rede inteira."""
    sql = f"""
    WITH {PARAMETROS_BASE}
    SELECT p.sku AS cod_produto, p.nome_produto AS descricao, p.setor,
           SUM(v.quantidade) AS quantidade, SUM(v.receita_liquida) AS receita,
           SUM(v.margem) / NULLIF(SUM(v.receita_liquida), 0) AS margem_percentual
    FROM dw.fato_vendas v
    JOIN dw.dim_tempo t ON t.sk_tempo = v.sk_tempo
    JOIN dw.dim_produto p ON p.sk_produto = v.sk_produto
    CROSS JOIN par
    WHERE v.status = %(status)s AND t.data BETWEEN par.ini AND par.dia
    GROUP BY p.sku, p.nome_produto, p.setor
    ORDER BY receita DESC, p.sku
    """
    quadro = _df(conexao, sql, parametros(mes, dia))
    total = quadro["receita"].sum()
    quadro["participacao"] = quadro["receita"] / total if total else None
    quadro["participacao_acumulada"] = quadro["participacao"].cumsum()
    quadro["classe"] = classificar_abc(quadro["participacao_acumulada"])
    return quadro


def setores(conexao: psycopg.Connection, mes: date, dia: date) -> pd.DataFrame:
    """Receita, participação, margem e evolução (vs o mesmo período do ano anterior) por setor."""
    sql = f"""
    WITH {PARAMETROS_BASE}
    SELECT p.setor,
           SUM(v.receita_liquida) FILTER (WHERE t.data BETWEEN par.ini AND par.dia) AS receita,
           SUM(v.margem) FILTER (WHERE t.data BETWEEN par.ini AND par.dia) AS margem,
           SUM(v.receita_liquida)
               FILTER (WHERE t.data BETWEEN par.ini_ant AND par.dia_ant) AS receita_ano_anterior
    FROM dw.fato_vendas v
    JOIN dw.dim_tempo t ON t.sk_tempo = v.sk_tempo
    JOIN dw.dim_produto p ON p.sk_produto = v.sk_produto
    CROSS JOIN par
    WHERE v.status = %(status)s
      AND (t.data BETWEEN par.ini AND par.dia OR t.data BETWEEN par.ini_ant AND par.dia_ant)
    GROUP BY p.setor
    """
    quadro = _df(conexao, sql, parametros(mes, dia)).dropna(subset=["receita"])
    quadro = quadro.sort_values(["receita", "setor"], ascending=[False, True], ignore_index=True)
    quadro["participacao"] = quadro["receita"] / quadro["receita"].sum()
    quadro["margem_percentual"] = quadro["margem"] / quadro["receita"].where(quadro["receita"] > 0)
    anterior = quadro["receita_ano_anterior"].where(quadro["receita_ano_anterior"] > 0)
    quadro["evolucao"] = quadro["receita"] / anterior - 1
    return quadro[["setor", "receita", "participacao", "margem_percentual", "evolucao"]]


def produtos_por_loja(conexao: psycopg.Connection, mes: date, dia: date) -> pd.DataFrame:
    """Os maiores produtos de cada loja no mês até o dia (vendas concluídas), com a participação
    na receita da loja: cod_loja, posicao, descricao, setor, receita, participacao."""
    sql = f"""
    WITH {PARAMETROS_BASE},
    base AS (
        SELECT l.cod_loja, p.sku, p.nome_produto, p.setor, SUM(v.receita_liquida) AS receita
        FROM dw.fato_vendas v
        JOIN dw.dim_tempo t ON t.sk_tempo = v.sk_tempo
        JOIN dw.dim_loja l ON l.sk_loja = v.sk_loja
        JOIN dw.dim_produto p ON p.sk_produto = v.sk_produto
        CROSS JOIN par
        WHERE v.status = %(status)s AND t.data BETWEEN par.ini AND par.dia
        GROUP BY l.cod_loja, p.sku, p.nome_produto, p.setor
    ),
    ordenado AS (
        SELECT b.*, ROW_NUMBER() OVER (PARTITION BY cod_loja ORDER BY receita DESC, sku) AS posicao,
               receita / NULLIF(SUM(receita) OVER (PARTITION BY cod_loja), 0) AS participacao
        FROM base b
    )
    SELECT cod_loja, posicao, nome_produto AS descricao, setor, receita, participacao
    FROM ordenado
    WHERE posicao <= %(maximo)s
    ORDER BY cod_loja, posicao
    """
    parametros_loja = parametros(mes, dia) | {"maximo": config.RELATORIO_TOP_PRODUTOS_LOJA}
    return _df(conexao, sql, parametros_loja)


def destacar_o_melhor(quadro: pd.DataFrame, rotulo: str) -> pd.DataFrame:
    """Acrescenta a coluna `destaque` com `rotulo` na linha de maior `receita_media` de cada loja
    (empate: a primeira na ordem recebida); as demais ficam vazias."""
    quadro = quadro.copy()
    quadro["destaque"] = None
    if not quadro.empty:
        melhores = quadro.groupby("cod_loja")["receita_media"].idxmax()
        quadro.loc[melhores, "destaque"] = rotulo
    return quadro


def quando_a_loja_vende(conexao: psycopg.Connection, dia: date) -> tuple:
    """(por dia da semana, por faixa horária): receita média por dia de cada loja nos últimos
    `RELATORIO_DIAS_QUANDO_A_LOJA_VENDE` dias até `dia` (vendas concluídas), com a participação na
    receita do período e o melhor dia e a melhor faixa em `destaque`. A média do dia da semana
    divide pelos dias daquele dia da semana em que a loja vendeu; a da faixa, pelos dias em que
    a loja vendeu."""
    base = """
    WITH base AS (
        SELECT l.cod_loja, t.data, EXTRACT(ISODOW FROM t.data)::INT AS dia_da_semana_ordem,
               t.nome_dia_semana, h.faixa_do_dia, h.sk_hora, v.receita_liquida
        FROM dw.fato_vendas v
        JOIN dw.dim_tempo t ON t.sk_tempo = v.sk_tempo
        JOIN dw.dim_loja l ON l.sk_loja = v.sk_loja
        JOIN dw.dim_hora h ON h.sk_hora = v.sk_hora
        WHERE v.status = %(status)s
          AND t.data BETWEEN %(dia)s::DATE - %(janela)s::INT AND %(dia)s::DATE
    )
    """
    parametros_janela = {
        "dia": dia,
        "status": config.STATUS_VENDA_VALIDA,
        "janela": config.RELATORIO_DIAS_QUANDO_A_LOJA_VENDE - 1,
    }
    por_dia = _df(
        conexao,
        base
        + """
    SELECT cod_loja, dia_da_semana_ordem, nome_dia_semana AS dia_da_semana,
           SUM(receita_liquida) / COUNT(DISTINCT data) AS receita_media,
           SUM(receita_liquida) / SUM(SUM(receita_liquida)) OVER (PARTITION BY cod_loja)
               AS participacao
    FROM base
    GROUP BY cod_loja, dia_da_semana_ordem, nome_dia_semana
    ORDER BY cod_loja, dia_da_semana_ordem
    """,
        parametros_janela,
    )
    por_faixa = _df(
        conexao,
        base
        + """
    , dias AS (SELECT cod_loja, COUNT(DISTINCT data) AS dias_com_venda FROM base GROUP BY cod_loja)
    SELECT b.cod_loja, b.faixa_do_dia AS faixa,
           SUM(b.receita_liquida) / MAX(d.dias_com_venda) AS receita_media,
           SUM(b.receita_liquida) / SUM(SUM(b.receita_liquida)) OVER (PARTITION BY b.cod_loja)
               AS participacao
    FROM base b
    JOIN dias d ON d.cod_loja = b.cod_loja
    GROUP BY b.cod_loja, b.faixa_do_dia
    ORDER BY b.cod_loja, MIN(b.sk_hora)
    """,
        parametros_janela,
    )
    return (
        destacar_o_melhor(por_dia.drop(columns="dia_da_semana_ordem"), "Melhor dia"),
        destacar_o_melhor(por_faixa, "Melhor faixa"),
    )


def vendedor_dias(conexao: psycopg.Connection, mes: date, dia: date) -> pd.DataFrame:
    """Venda e meta de cada vendedor em cada dia do mês até a posição (vendas concluídas): `dia`,
    `venda` (0 quando não vendeu) e `meta_dia` (vazia quando o vendedor não tem meta no dia)."""
    sql = f"""
    WITH {PARAMETROS_BASE},
    venda AS (
        SELECT v.sk_vendedor, t.data, SUM(v.receita_liquida) AS venda
        FROM dw.fato_vendas v
        JOIN dw.dim_tempo t ON t.sk_tempo = v.sk_tempo
        CROSS JOIN par
        WHERE v.status = %(status)s AND t.data BETWEEN par.ini AND par.dia
        GROUP BY v.sk_vendedor, t.data
    ),
    meta AS (
        SELECT m.sk_vendedor, m.data, m.valor_meta_dia AS meta_dia
        FROM dw.vw_meta_vendedor_diaria m
        CROSS JOIN par
        WHERE m.data BETWEEN par.ini AND par.dia
    )
    SELECT d.cod_vendedor, COALESCE(v.data, m.data) AS dia, COALESCE(v.venda, 0) AS venda,
           m.meta_dia
    FROM venda v
    FULL JOIN meta m ON m.sk_vendedor = v.sk_vendedor AND m.data = v.data
    JOIN dw.dim_vendedor d ON d.sk_vendedor = COALESCE(v.sk_vendedor, m.sk_vendedor)
    ORDER BY d.cod_vendedor, dia
    """
    return _df(conexao, sql, parametros(mes, dia))


def vendedor_evolucao(conexao: psycopg.Connection, mes: date, dia: date) -> pd.DataFrame:
    """Venda e meta de cada vendedor, mês a mês: os `RELATORIO_MESES_EVOLUCAO_VENDEDOR` meses
    fechados antes do mês da posição (meta do mês inteiro) e o mês corrente até o dia (meta
    acumulada até o dia). Colunas: `cod_vendedor`, `mes_ref` (primeiro dia do mês), `venda`,
    `meta`."""
    sql = f"""
    WITH {PARAMETROS_BASE},
    janela AS (SELECT (par.ini - make_interval(months => %(meses)s))::DATE AS inicio FROM par),
    venda AS (
        SELECT v.sk_vendedor, date_trunc('month', t.data)::DATE AS mes_ref,
               SUM(v.receita_liquida) AS venda
        FROM dw.fato_vendas v
        JOIN dw.dim_tempo t ON t.sk_tempo = v.sk_tempo
        CROSS JOIN par CROSS JOIN janela j
        WHERE v.status = %(status)s AND t.data BETWEEN j.inicio AND par.dia
        GROUP BY v.sk_vendedor, date_trunc('month', t.data)
    ),
    meta AS (
        SELECT m.sk_vendedor, date_trunc('month', m.data)::DATE AS mes_ref,
               SUM(m.valor_meta_dia) AS meta
        FROM dw.vw_meta_vendedor_diaria m
        CROSS JOIN par CROSS JOIN janela j
        WHERE m.data BETWEEN j.inicio AND par.dia
        GROUP BY m.sk_vendedor, date_trunc('month', m.data)
    )
    SELECT d.cod_vendedor, COALESCE(v.mes_ref, m.mes_ref) AS mes_ref,
           COALESCE(v.venda, 0) AS venda, m.meta
    FROM venda v
    FULL JOIN meta m ON m.sk_vendedor = v.sk_vendedor AND m.mes_ref = v.mes_ref
    JOIN dw.dim_vendedor d ON d.sk_vendedor = COALESCE(v.sk_vendedor, m.sk_vendedor)
    ORDER BY d.cod_vendedor, mes_ref
    """
    parametros_evolucao = parametros(mes, dia) | {"meses": config.RELATORIO_MESES_EVOLUCAO_VENDEDOR}
    return _df(conexao, sql, parametros_evolucao)


def vendedor_produtos(conexao: psycopg.Connection, mes: date, dia: date) -> pd.DataFrame:
    """Os maiores produtos de cada vendedor no mês até o dia (vendas concluídas): `cod_vendedor`,
    `posicao`, `descricao`, `setor`, `quantidade`, `receita`."""
    sql = f"""
    WITH {PARAMETROS_BASE},
    base AS (
        SELECT v.sk_vendedor, p.sku, p.nome_produto, p.setor,
               SUM(v.quantidade) AS quantidade, SUM(v.receita_liquida) AS receita
        FROM dw.fato_vendas v
        JOIN dw.dim_tempo t ON t.sk_tempo = v.sk_tempo
        JOIN dw.dim_produto p ON p.sk_produto = v.sk_produto
        CROSS JOIN par
        WHERE v.status = %(status)s AND t.data BETWEEN par.ini AND par.dia
        GROUP BY v.sk_vendedor, p.sku, p.nome_produto, p.setor
    ),
    ordenado AS (
        SELECT b.*, ROW_NUMBER() OVER (PARTITION BY sk_vendedor ORDER BY receita DESC, sku)
                    AS posicao
        FROM base b
    )
    SELECT d.cod_vendedor, o.posicao, o.nome_produto AS descricao, o.setor, o.quantidade,
           o.receita
    FROM ordenado o
    JOIN dw.dim_vendedor d ON d.sk_vendedor = o.sk_vendedor
    WHERE o.posicao <= %(maximo)s
    ORDER BY d.cod_vendedor, o.posicao
    """
    return _df(
        conexao, sql, parametros(mes, dia) | {"maximo": config.RELATORIO_TOP_PRODUTOS_VENDEDOR}
    )


def vendedor_mix_por_setor(conexao: psycopg.Connection, mes: date, dia: date) -> pd.DataFrame:
    """Receita de cada vendedor por setor no mês até o dia (vendas concluídas) e a participação
    de cada setor na receita dele: `cod_vendedor`, `setor`, `receita`, `participacao`."""
    sql = f"""
    WITH {PARAMETROS_BASE},
    base AS (
        SELECT v.sk_vendedor, p.setor, SUM(v.receita_liquida) AS receita
        FROM dw.fato_vendas v
        JOIN dw.dim_tempo t ON t.sk_tempo = v.sk_tempo
        JOIN dw.dim_produto p ON p.sk_produto = v.sk_produto
        CROSS JOIN par
        WHERE v.status = %(status)s AND t.data BETWEEN par.ini AND par.dia
        GROUP BY v.sk_vendedor, p.setor
    )
    SELECT d.cod_vendedor, b.setor, b.receita,
           b.receita / NULLIF(SUM(b.receita) OVER (PARTITION BY b.sk_vendedor), 0) AS participacao
    FROM base b
    JOIN dw.dim_vendedor d ON d.sk_vendedor = b.sk_vendedor
    ORDER BY d.cod_vendedor, b.receita DESC, b.setor
    """
    return _df(conexao, sql, parametros(mes, dia))


def vendedor_comportamento(conexao: psycopg.Connection, mes: date, dia: date) -> pd.DataFrame:
    """Os totais que formam os indicadores de comportamento de cada vendedor no mês até o dia:
    `cupons` e `itens` (vendas concluídas), `bruto` (quantidade x preço) e `desconto` das
    concluídas, `receita` e `cancelados` (cupons cancelados; é o único lugar em que as
    canceladas entram). A loja de cada vendedor é a do cadastro (`cod_loja`)."""
    sql = f"""
    WITH {PARAMETROS_BASE}
    SELECT d.cod_vendedor, l.cod_loja,
           COUNT(DISTINCT (v.sk_loja, v.numero_cupom)) FILTER (WHERE v.status = %(status)s)
               AS cupons,
           COUNT(*) FILTER (WHERE v.status = %(status)s) AS itens,
           COALESCE(SUM(v.quantidade * v.preco_unitario) FILTER (WHERE v.status = %(status)s), 0)
               AS bruto,
           COALESCE(SUM(v.desconto) FILTER (WHERE v.status = %(status)s), 0) AS desconto,
           COALESCE(SUM(v.receita_liquida) FILTER (WHERE v.status = %(status)s), 0) AS receita,
           COUNT(DISTINCT (v.sk_loja, v.numero_cupom))
               FILTER (WHERE v.status = %(cancelada)s) AS cancelados
    FROM dw.fato_vendas v
    JOIN dw.dim_tempo t ON t.sk_tempo = v.sk_tempo
    JOIN dw.dim_vendedor d ON d.sk_vendedor = v.sk_vendedor
    JOIN dw.dim_loja l ON l.sk_loja = d.sk_loja
    CROSS JOIN par
    WHERE v.status IN (%(status)s, %(cancelada)s) AND t.data BETWEEN par.ini AND par.dia
    GROUP BY d.cod_vendedor, l.cod_loja
    ORDER BY d.cod_vendedor
    """
    return _df(conexao, sql, parametros(mes, dia) | {"cancelada": config.STATUS_CANCELADA})


def alertas_abertos(conexao: psycopg.Connection, dia: date) -> pd.DataFrame:
    """Alertas vigentes e independentes ainda não tratados (novo ou em análise), do mais grave.

    Só entram alertas com data até o dia de posição; o cancelamento alto (janela móvel que termina
    no fim de um mês) só vale com a janela fechada antes do mês da posição, e aparece uma vez por
    vendedor (`consolidar_cancelamentos`)."""
    sql = """
    SELECT severidade_nome AS severidade, nome_tipo_alerta AS tipo, data_alerta AS data,
           COALESCE(nome_loja, nome_centro_custo, '-') AS loja_ou_centro,
           nome_vendedor AS vendedor, valor_envolvido, status_nome AS status, explicacao,
           tipo_alerta, cod_vendedor, status AS status_codigo
    FROM dw.vw_alertas_detalhe
    WHERE conta_no_painel AND data_alerta <= %(dia)s
      AND (tipo_alerta <> %(cancelamento)s OR data_alerta < date_trunc('month', %(dia)s::DATE))
    ORDER BY severidade_ordem DESC, valor_envolvido DESC NULLS LAST, data_alerta DESC, chave_alerta
    """
    quadro = _df(conexao, sql, {"dia": dia, "cancelamento": TIPO_CANCELAMENTO_ALTO})
    quadro = consolidar_cancelamentos(quadro)
    return quadro[quadro["status_codigo"].isin(("novo", "em_analise"))].reset_index(drop=True)


def consolidar_cancelamentos(alertas: pd.DataFrame) -> pd.DataFrame:
    """Deixa só a janela mais recente de cancelamento alto de cada vendedor. Quando as janelas dos
    meses anteriores também alertaram, a explicação ganha "N janelas seguidas desde mm/aaaa"
    (o mês em que terminou a primeira janela da sequência). O histórico fica no dw."""
    alertas = alertas.copy()
    eh_cancelamento = alertas["tipo_alerta"] == TIPO_CANCELAMENTO_ALTO
    antigas = []
    for _, grupo in alertas[eh_cancelamento].groupby("cod_vendedor"):
        grupo = grupo.sort_values("data")
        meses = [d.year * 12 + d.month for d in grupo["data"]]
        seguidas = 1
        while seguidas < len(meses) and meses[-seguidas] - meses[-seguidas - 1] == 1:
            seguidas += 1
        ultima = grupo.index[-1]
        antigas.extend(grupo.index[:-1])
        if seguidas > 1:
            desde = grupo["data"].iloc[-seguidas]
            complemento = f" — {seguidas} janelas seguidas desde {desde:%m/%Y}"
            alertas.loc[ultima, "explicacao"] += complemento
    return alertas.drop(index=antigas)


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
    """Previsão diária da rede (execução mais recente), com a faixa baixa e alta calibrada no total
    da rede (nível `rede`); sem essas linhas, cai na soma das faixas de cada loja e setor."""
    sql = """
    WITH ultima AS (
        SELECT versao_modelo, treino_ate
        FROM dw.previsao_vendas
        WHERE nivel = 'loja_setor' AND granularidade = 'mes'
        ORDER BY gerado_em DESC, treino_ate DESC LIMIT 1
    ),
    soma AS (
        SELECT f.data, SUM(f.valor_previsto) AS previsto, SUM(f.valor_baixo) AS baixo,
               SUM(f.valor_alto) AS alto
        FROM dw.previsao_vendas f
        JOIN ultima u ON u.versao_modelo = f.versao_modelo AND u.treino_ate = f.treino_ate
        WHERE f.nivel = 'loja_setor' AND f.granularidade = 'dia'
        GROUP BY f.data
    ),
    rede AS (
        SELECT f.data, f.valor_previsto, f.valor_baixo, f.valor_alto
        FROM dw.previsao_vendas f
        JOIN ultima u ON u.versao_modelo = f.versao_modelo AND u.treino_ate = f.treino_ate
        WHERE f.nivel = 'rede' AND f.granularidade = 'dia'
    )
    SELECT s.data AS dia, COALESCE(r.valor_previsto, s.previsto) AS previsto,
           COALESCE(r.valor_baixo, s.baixo) AS faixa_baixa,
           COALESCE(r.valor_alto, s.alto) AS faixa_alta
    FROM soma s
    LEFT JOIN rede r ON r.data = s.data
    ORDER BY s.data
    """
    return _df(conexao, sql, {})
