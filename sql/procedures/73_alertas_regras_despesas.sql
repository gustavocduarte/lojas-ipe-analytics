-- Regras de alerta sobre despesas (Fase 3). Ver 71_alertas_motor.sql.
-- A chave de um lançamento é arquivo|linha de origem (a mesma identificação usada pelo ETL).

CREATE OR REPLACE FUNCTION etl.regra_despesa_documento_repetido()
RETURNS TABLE (chave TEXT, severidade TEXT, sk_tempo INT, sk_loja INT, sk_vendedor INT,
               sk_centro_custo INT, valor NUMERIC, explicacao TEXT, detalhe JSONB,
               independente BOOLEAN)
LANGUAGE plpgsql STABLE AS $$
#variable_conflict use_column
DECLARE
    v_alto NUMERIC := etl.parametro('documento_repetido_valor_alto');
BEGIN
    RETURN QUERY
    SELECT 'despesa_documento_repetido|' || x.numero_documento,
           CASE WHEN x.extra >= v_alto THEN 'alta' ELSE 'media' END,
           x.sk_tempo, c.sk_loja, NULL::INT, x.sk_centro_custo, x.extra,
           format('documento %s lançado %s vezes (%s a mais; primeiro lançamento no centro %s)',
                  x.numero_documento, x.vezes, etl.fmt_brl(x.extra), c.cod_centro_custo),
           jsonb_build_object('numero_documento', x.numero_documento, 'vezes', x.vezes,
                              'valor_repetido', x.extra, 'valor_total', x.total),
           TRUE
    FROM (SELECT f.numero_documento, count(*) AS vezes, sum(f.valor) AS total,
                 sum(f.valor) - (array_agg(f.valor ORDER BY f.arquivo_origem, f.linha_origem))[1]
                     AS extra,
                 (array_agg(f.sk_tempo ORDER BY f.arquivo_origem, f.linha_origem))[1] AS sk_tempo,
                 (array_agg(f.sk_centro_custo ORDER BY f.arquivo_origem, f.linha_origem))[1]
                     AS sk_centro_custo
          FROM dw.fato_despesas f GROUP BY f.numero_documento HAVING count(*) > 1) x
    JOIN dw.dim_centro_custo c ON c.sk_centro_custo = x.sk_centro_custo;
END $$;

CREATE OR REPLACE FUNCTION etl.regra_despesa_fim_semana_feriado()
RETURNS TABLE (chave TEXT, severidade TEXT, sk_tempo INT, sk_loja INT, sk_vendedor INT,
               sk_centro_custo INT, valor NUMERIC, explicacao TEXT, detalhe JSONB,
               independente BOOLEAN)
LANGUAGE plpgsql STABLE AS $$
#variable_conflict use_column
BEGIN
    RETURN QUERY
    SELECT 'despesa_fim_semana_feriado|'
               || coalesce(f.arquivo_origem || '|' || f.linha_origem, 'sk' || f.sk_despesa),
           'baixa', f.sk_tempo, c.sk_loja, NULL::INT, f.sk_centro_custo, f.valor,
           CASE WHEN t.feriado_nacional
                THEN format('lançamento de %s em %s, feriado nacional (%s), no centro %s',
                            etl.fmt_brl(f.valor), etl.fmt_data(t.data), t.nome_feriado,
                            c.cod_centro_custo)
                ELSE format('lançamento de %s em %s (%s), no centro %s', etl.fmt_brl(f.valor),
                            etl.fmt_data(t.data), lower(t.nome_dia_semana), c.cod_centro_custo)
           END,
           jsonb_build_object('numero_documento', f.numero_documento, 'data', t.data,
                              'dia_semana', t.nome_dia_semana, 'feriado', t.nome_feriado,
                              'valor', f.valor),
           TRUE
    FROM dw.fato_despesas f
    JOIN dw.dim_tempo t ON t.sk_tempo = f.sk_tempo
    JOIN dw.dim_centro_custo c ON c.sk_centro_custo = f.sk_centro_custo
    WHERE t.feriado_nacional OR t.nome_dia_semana IN ('Sábado', 'Domingo');
END $$;

CREATE OR REPLACE FUNCTION etl.regra_despesa_valor_atipico()
RETURNS TABLE (chave TEXT, severidade TEXT, sk_tempo INT, sk_loja INT, sk_vendedor INT,
               sk_centro_custo INT, valor NUMERIC, explicacao TEXT, detalhe JSONB,
               independente BOOLEAN)
LANGUAGE plpgsql STABLE AS $$
#variable_conflict use_column
DECLARE
    v_multiplo NUMERIC := etl.parametro('valor_atipico_multiplo');
    v_alta NUMERIC := etl.parametro('valor_atipico_sev_alta_multiplo');
BEGIN
    RETURN QUERY
    SELECT 'despesa_valor_atipico|'
               || coalesce(f.arquivo_origem || '|' || f.linha_origem, 'sk' || f.sk_despesa),
           CASE WHEN f.valor >= v_alta * m.mediana THEN 'alta' ELSE 'media' END,
           f.sk_tempo, c.sk_loja, NULL::INT, f.sk_centro_custo, f.valor,
           format('lançamento de %s equivale a %s vezes a mediana (%s) dos lançamentos do centro %s',
                  etl.fmt_brl(f.valor), etl.fmt_num(f.valor / m.mediana, 1),
                  etl.fmt_brl(m.mediana), c.cod_centro_custo),
           jsonb_build_object('numero_documento', f.numero_documento, 'valor', f.valor,
                              'mediana', round(m.mediana, 2), 'razao', round(f.valor / m.mediana, 2)),
           TRUE
    FROM dw.fato_despesas f
    JOIN (SELECT d.sk_centro_custo, (percentile_cont(0.5) WITHIN GROUP (ORDER BY d.valor))::NUMERIC AS mediana
          FROM dw.fato_despesas d GROUP BY d.sk_centro_custo) m
      ON m.sk_centro_custo = f.sk_centro_custo AND m.mediana > 0
    JOIN dw.dim_centro_custo c ON c.sk_centro_custo = f.sk_centro_custo
    WHERE f.valor > v_multiplo * m.mediana;
END $$;

-- Centro de custo incompatível: aprende o tipo dominante de cada descrição (mínimo de lançamentos e
-- participação mínima, em parâmetros) contando também os lançamentos errados, e aponta os que estão
-- em centros de outro tipo. etl.excecoes_centro_descricao, se preenchida, vale mais que o aprendido.
-- 'NAO INFORMADO' é o texto que o ETL põe quando a descrição vem vazia: não é uma descrição.
CREATE OR REPLACE FUNCTION etl.regra_despesa_centro_incompativel()
RETURNS TABLE (chave TEXT, severidade TEXT, sk_tempo INT, sk_loja INT, sk_vendedor INT,
               sk_centro_custo INT, valor NUMERIC, explicacao TEXT, detalhe JSONB,
               independente BOOLEAN)
LANGUAGE plpgsql STABLE AS $$
#variable_conflict use_column
DECLARE
    v_minimo NUMERIC := etl.parametro('centro_incompativel_min_ocorrencias');
    v_participacao NUMERIC := etl.parametro('centro_incompativel_participacao_min');
BEGIN
    RETURN QUERY
    WITH contagem AS (
        SELECT f.descricao, c.tipo_despesa, count(*) AS n
        FROM dw.fato_despesas f JOIN dw.dim_centro_custo c USING (sk_centro_custo)
        WHERE f.descricao IS NOT NULL AND f.descricao <> 'NAO INFORMADO'
        GROUP BY f.descricao, c.tipo_despesa),
    total AS (SELECT k.*, sum(k.n) OVER (PARTITION BY k.descricao) AS total FROM contagem k),
    aprendido AS (
        SELECT DISTINCT ON (t.descricao) t.descricao, t.tipo_despesa::TEXT AS tipo,
               t.n::NUMERIC / t.total AS participacao, t.total::BIGINT AS ocorrencias,
               'aprendido'::TEXT AS origem
        FROM total t ORDER BY t.descricao, t.n DESC, t.tipo_despesa),
    esperado AS (
        SELECT e.descricao::TEXT, e.tipo_esperado::TEXT AS tipo, NULL::NUMERIC AS participacao,
               NULL::BIGINT AS ocorrencias, 'excecao'::TEXT AS origem
        FROM etl.excecoes_centro_descricao e
        UNION ALL
        SELECT a.descricao::TEXT, a.tipo, a.participacao, a.ocorrencias, a.origem
        FROM aprendido a
        WHERE a.ocorrencias >= v_minimo AND a.participacao >= v_participacao
          AND NOT EXISTS (SELECT 1 FROM etl.excecoes_centro_descricao e
                          WHERE e.descricao = a.descricao)),
    achados AS (
        SELECT f.*, c.cod_centro_custo, c.sk_loja, c.tipo_despesa::TEXT AS tipo_lancado,
               e.tipo AS tipo_esperado, e.participacao, e.ocorrencias, e.origem
        FROM dw.fato_despesas f
        JOIN dw.dim_centro_custo c USING (sk_centro_custo)
        JOIN esperado e ON e.descricao = f.descricao
        WHERE c.tipo_despesa <> e.tipo)
    SELECT 'despesa_centro_incompativel|'
               || coalesce(a.arquivo_origem || '|' || a.linha_origem, 'sk' || a.sk_despesa),
           'media', a.sk_tempo, a.sk_loja, NULL::INT, a.sk_centro_custo, a.valor,
           CASE WHEN a.origem = 'excecao'
                THEN format('"%s" deve ser lançada em centros %s (regra cadastrada), mas foi lançada '
                            'no centro %s, do tipo %s; valor %s', a.descricao, a.tipo_esperado,
                            a.cod_centro_custo, a.tipo_lancado, etl.fmt_brl(a.valor))
                ELSE format('"%s" lançada no centro %s, do tipo %s; %s dos %s lançamentos com essa '
                            'descrição estão em centros %s; valor %s', a.descricao,
                            a.cod_centro_custo, a.tipo_lancado, etl.fmt_pct(a.participacao),
                            etl.fmt_num(a.ocorrencias), a.tipo_esperado, etl.fmt_brl(a.valor))
           END,
           jsonb_build_object('numero_documento', a.numero_documento, 'descricao', a.descricao,
                              'tipo_lancado', a.tipo_lancado, 'tipo_esperado', a.tipo_esperado,
                              'origem_da_regra', a.origem, 'participacao', round(a.participacao, 4),
                              'ocorrencias', a.ocorrencias),
           TRUE
    FROM achados a;
END $$;
