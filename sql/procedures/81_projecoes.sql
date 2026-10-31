-- Fase 4: projeções de fechamento (mês de vendas e ano de despesas). Funções reaplicáveis.
-- O dia de referência é sempre um parâmetro: as views fixas usam dw.data_referencia() (o último dia
-- com venda válida); para simular um corte (ex.: 15/12/2025) chame a função direto com a data.

CREATE OR REPLACE FUNCTION dw.data_referencia() RETURNS DATE
LANGUAGE sql STABLE AS $$
    SELECT max(t.data)
    FROM dw.fato_vendas v
    JOIN dw.dim_tempo t ON t.sk_tempo = v.sk_tempo
    WHERE v.status = 'Concluída';
$$;

-- Fechamento do mês de p_ref, por loja e setor: realizado até p_ref + previsão dos dias restantes.
-- A previsão usada é a gerada com corte exatamente em p_ref (dw.previsao_vendas.treino_ate), e a
-- mais recente se houver mais de uma versão. Sem previsão para os dias que faltam, previsto_restante
-- fica NULL (tem_previsao = FALSE). faixa_* soma as faixas diárias: é mais larga que a faixa real.
CREATE OR REPLACE FUNCTION dw.fn_projecao_fechamento_mes(p_ref DATE)
RETURNS TABLE (
    mes DATE, sk_loja INTEGER, setor VARCHAR, realizado_ate_ref NUMERIC, previsto_restante NUMERIC,
    projecao_fechamento NUMERIC, faixa_baixa NUMERIC, faixa_alta NUMERIC, meta_mes NUMERIC,
    cobertura_projetada NUMERIC, dias_restantes INTEGER, tem_previsao BOOLEAN
)
LANGUAGE sql STABLE AS $$
    WITH limites AS (
        SELECT date_trunc('month', p_ref)::DATE AS inicio,
               (date_trunc('month', p_ref) + INTERVAL '1 month' - INTERVAL '1 day')::DATE AS fim
    ),
    realizado AS (
        SELECT v.sk_loja, p.setor, sum(v.receita_liquida) AS valor
        FROM dw.fato_vendas v
        JOIN dw.dim_tempo t ON t.sk_tempo = v.sk_tempo
        JOIN dw.dim_produto p ON p.sk_produto = v.sk_produto
        CROSS JOIN limites l
        WHERE v.status = 'Concluída' AND t.data BETWEEN l.inicio AND p_ref
        GROUP BY v.sk_loja, p.setor
    ),
    versao AS (
        SELECT versao_modelo FROM dw.previsao_vendas
        WHERE nivel = 'loja_setor' AND treino_ate = p_ref ORDER BY gerado_em DESC, versao_modelo LIMIT 1
    ),
    previsto AS (
        SELECT f.sk_loja, f.setor, sum(f.valor_previsto) AS valor, sum(f.valor_baixo) AS baixo,
               sum(f.valor_alto) AS alto
        FROM dw.previsao_vendas f
        JOIN versao USING (versao_modelo)
        CROSS JOIN limites l
        WHERE f.nivel = 'loja_setor' AND f.granularidade = 'dia' AND f.treino_ate = p_ref AND f.data > p_ref
          AND f.data <= l.fim
        GROUP BY f.sk_loja, f.setor
    ),
    meta AS (
        SELECT m.sk_loja, m.setor, sum(m.valor_meta) AS valor
        FROM dw.fato_meta_vendas m
        JOIN limites l ON m.sk_tempo = to_char(l.inicio, 'YYYYMMDD')::INT
        GROUP BY m.sk_loja, m.setor
    ),
    chaves AS (
        SELECT sk_loja, setor FROM realizado
        UNION SELECT sk_loja, setor FROM previsto
        UNION SELECT sk_loja, setor FROM meta
    )
    SELECT l.inicio,
           c.sk_loja,
           c.setor::VARCHAR,
           COALESCE(r.valor, 0),
           x.restante,
           COALESCE(r.valor, 0) + x.restante,
           COALESCE(r.valor, 0) + x.baixo,
           COALESCE(r.valor, 0) + x.alto,
           m.valor,
           (COALESCE(r.valor, 0) + x.restante) / NULLIF(m.valor, 0),
           (l.fim - p_ref)::INT,
           x.restante IS NOT NULL
    FROM limites l
    CROSS JOIN chaves c
    LEFT JOIN realizado r ON r.sk_loja = c.sk_loja AND r.setor = c.setor
    LEFT JOIN previsto p ON p.sk_loja = c.sk_loja AND p.setor = c.setor
    LEFT JOIN meta m ON m.sk_loja = c.sk_loja AND m.setor = c.setor
    CROSS JOIN LATERAL (
        SELECT CASE WHEN l.fim = p_ref THEN 0 ELSE p.valor END AS restante,
               CASE WHEN l.fim = p_ref THEN 0 ELSE p.baixo END AS baixo,
               CASE WHEN l.fim = p_ref THEN 0 ELSE p.alto END AS alto
    ) x
$$;

-- Fechamento do ano de despesas do ano de p_ref, por centro de custo.
-- Realizado até p_ref + orçado do que falta x fator realizado/orçado do que já passou (sem os
-- lançamentos de alertas vigentes de documento repetido, valor atípico e centro incompatível, salvo
-- falso positivo; o realizado somado à projeção continua completo). O fator fica
-- entre projecao_fator_min e projecao_fator_max (etl.parametros_negocio). O orçado do mês de p_ref é
-- repartido pela fração dos dias (dia / dias do mês). realizado_ano_completo traz tudo que existe
-- no ano (para comparar a projeção com o que de fato aconteceu).
CREATE OR REPLACE FUNCTION dw.fn_projecao_despesas_ano(p_ref DATE)
RETURNS TABLE (
    ano INTEGER, sk_centro_custo INTEGER, orcado_ano NUMERIC, orcado_ate_ref NUMERIC,
    realizado_ate_ref NUMERIC, fator NUMERIC, orcado_restante NUMERIC, previsto_restante NUMERIC,
    projecao_ano NUMERIC, desvio_vs_orcado NUMERIC, realizado_ano_completo NUMERIC
)
LANGUAGE sql STABLE AS $$
    WITH par AS (
        SELECT EXTRACT(YEAR FROM p_ref)::INT AS ano,
               EXTRACT(MONTH FROM p_ref)::INT AS mes_ref,
               EXTRACT(DAY FROM p_ref)::NUMERIC
                   / EXTRACT(DAY FROM (date_trunc('month', p_ref) + INTERVAL '1 month'
                                       - INTERVAL '1 day')) AS fracao,
               (SELECT valor FROM etl.parametros_negocio WHERE chave = 'projecao_fator_min') AS fmin,
               (SELECT valor FROM etl.parametros_negocio WHERE chave = 'projecao_fator_max') AS fmax
    ),
    orcado AS (
        SELECT o.sk_centro_custo,
               sum(o.valor_orcado) AS ano_todo,
               COALESCE(sum(o.valor_orcado) FILTER (WHERE t.mes < par.mes_ref), 0)
                   + COALESCE(sum(o.valor_orcado) FILTER (WHERE t.mes = par.mes_ref), 0) * par.fracao
                   AS ate_ref,
               COALESCE(sum(o.valor_orcado) FILTER (WHERE t.mes > par.mes_ref), 0)
                   + COALESCE(sum(o.valor_orcado) FILTER (WHERE t.mes = par.mes_ref), 0)
                       * (1 - par.fracao) AS restante
        FROM dw.fato_orcamento_despesas o
        JOIN dw.dim_tempo t ON t.sk_tempo = o.sk_tempo
        CROSS JOIN par
        WHERE t.ano = par.ano
        GROUP BY o.sk_centro_custo, par.fracao, par.mes_ref
    ),
    -- Lançamentos que alertas vigentes (e não marcados como falso positivo) apontam como
    -- documento repetido (a cópia, não o primeiro lançamento), valor atípico ou centro
    -- incompatível: contam no realizado, mas ficam de fora do fator realizado/orçado.
    excluidos AS (
        SELECT d.sk_despesa
        FROM dw.fato_despesas d
        JOIN dw.alertas a
          ON a.vigente AND a.status <> 'falso_positivo'
         AND a.tipo_alerta IN ('despesa_valor_atipico', 'despesa_centro_incompativel')
         AND a.chave_alerta = a.tipo_alerta || '|'
                              || coalesce(d.arquivo_origem || '|' || d.linha_origem,
                                          'sk' || d.sk_despesa)
        UNION
        SELECT x.sk_despesa
        FROM (SELECT sk_despesa, numero_documento,
                     row_number() OVER (PARTITION BY numero_documento
                                        ORDER BY arquivo_origem, linha_origem) AS ordem
              FROM dw.fato_despesas) x
        JOIN dw.alertas a
          ON a.vigente AND a.status <> 'falso_positivo'
         AND a.chave_alerta = 'despesa_documento_repetido|' || x.numero_documento
        WHERE x.ordem > 1
    ),
    realizado AS (
        SELECT d.sk_centro_custo,
               sum(d.valor) FILTER (WHERE t.data <= p_ref) AS ate_ref,
               sum(d.valor) FILTER (WHERE t.data <= p_ref
                                    AND d.sk_despesa NOT IN (SELECT sk_despesa FROM excluidos))
                   AS ate_ref_limpo,
               sum(d.valor) AS ano_todo
        FROM dw.fato_despesas d
        JOIN dw.dim_tempo t ON t.sk_tempo = d.sk_tempo
        CROSS JOIN par
        WHERE t.ano = par.ano
        GROUP BY d.sk_centro_custo
    )
    SELECT par.ano,
           c.sk_centro_custo,
           COALESCE(o.ano_todo, 0),
           COALESCE(o.ate_ref, 0),
           COALESCE(r.ate_ref, 0),
           f.fator,
           COALESCE(o.restante, 0),
           COALESCE(o.restante, 0) * f.fator,
           COALESCE(r.ate_ref, 0) + COALESCE(o.restante, 0) * f.fator,
           COALESCE(r.ate_ref, 0) + COALESCE(o.restante, 0) * f.fator - COALESCE(o.ano_todo, 0),
           COALESCE(r.ano_todo, 0)
    FROM (SELECT sk_centro_custo FROM orcado UNION SELECT sk_centro_custo FROM realizado) c
    CROSS JOIN par
    LEFT JOIN orcado o ON o.sk_centro_custo = c.sk_centro_custo
    LEFT JOIN realizado r ON r.sk_centro_custo = c.sk_centro_custo
    CROSS JOIN LATERAL (
        SELECT CASE WHEN COALESCE(o.ate_ref, 0) > 0
                    THEN GREATEST(par.fmin, LEAST(par.fmax, COALESCE(r.ate_ref_limpo, 0) / o.ate_ref))
                    ELSE 1 END AS fator
    ) f
$$;
