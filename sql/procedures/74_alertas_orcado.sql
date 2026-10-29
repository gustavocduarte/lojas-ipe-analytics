-- Despesa acima do orçado e alertas derivados (Fase 3). Ver 71_alertas_motor.sql.
--
-- Um estouro de orçamento muitas vezes é só consequência de outro alerta (um lançamento atípico,
-- um documento em duplicidade, um lançamento no centro errado). Para não contar o mesmo problema
-- duas vezes, o alerta de orçado desconta a contribuição desses alertas de origem:
--   * se, sem elas, o realizado deixa de estourar o limite, o alerta é DERIVADO
--     (independente = FALSE, severidade baixa, ligado às origens em dw.alerta_vinculos);
--   * se ainda estoura, é INDEPENDENTE (e as origens continuam ligadas, em parte).
-- Origens marcadas como falso positivo não explicam nada: o gasto é considerado real.

-- Quanto do excesso de um centro/mês um alerta de origem explica, em R$ (0 se não é origem).
CREATE OR REPLACE FUNCTION etl.contribuicao_orcado(a dw.alertas) RETURNS NUMERIC
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN NOT a.vigente OR a.status = 'falso_positivo' THEN 0
        WHEN a.tipo_alerta = 'despesa_valor_atipico'
            THEN greatest(a.valor_envolvido - (a.detalhe ->> 'mediana')::NUMERIC, 0)
        WHEN a.tipo_alerta IN ('despesa_documento_repetido', 'despesa_centro_incompativel')
            THEN coalesce(a.valor_envolvido, 0)
        ELSE 0
    END
$$;

CREATE OR REPLACE FUNCTION etl.regra_despesa_acima_orcado()
RETURNS TABLE (chave TEXT, severidade TEXT, sk_tempo INT, sk_loja INT, sk_vendedor INT,
               sk_centro_custo INT, valor NUMERIC, explicacao TEXT, detalhe JSONB,
               independente BOOLEAN)
LANGUAGE plpgsql STABLE AS $$
#variable_conflict use_column
DECLARE
    v_multiplo NUMERIC := etl.parametro('orcado_excesso_multiplo');
    v_alta NUMERIC := etl.parametro('orcado_sev_alta_multiplo');
    v_critica NUMERIC := etl.parametro('orcado_sev_critica_multiplo');
BEGIN
    RETURN QUERY
    WITH realizado AS (
        SELECT f.sk_centro_custo, t.ano, t.mes, sum(f.valor) AS realizado
        FROM dw.fato_despesas f JOIN dw.dim_tempo t USING (sk_tempo)
        GROUP BY f.sk_centro_custo, t.ano, t.mes),
    orcado AS (
        SELECT o.sk_centro_custo, t.ano, t.mes, o.sk_tempo, o.valor_orcado
        FROM dw.fato_orcamento_despesas o JOIN dw.dim_tempo t USING (sk_tempo)),
    -- um mesmo lançamento pode ser atípico E estar no centro errado: conta uma vez só (a maior
    -- contribuição); o documento repetido é outro lançamento (a cópia) e conta à parte
    por_item AS (
        SELECT a.sk_centro_custo, t.ano, t.mes,
               CASE WHEN a.tipo_alerta = 'despesa_documento_repetido' THEN a.chave_alerta
                    ELSE substr(a.chave_alerta, strpos(a.chave_alerta, '|') + 1) END AS item,
               max(etl.contribuicao_orcado(a)) AS contribuicao
        FROM dw.alertas a JOIN dw.dim_tempo t ON t.sk_tempo = a.sk_tempo
        WHERE a.tipo_alerta IN ('despesa_valor_atipico', 'despesa_documento_repetido',
                                'despesa_centro_incompativel')
        GROUP BY a.sk_centro_custo, t.ano, t.mes, 4),
    origens AS (
        SELECT sk_centro_custo, ano, mes, sum(contribuicao) AS explicado,
               count(*) FILTER (WHERE contribuicao > 0) AS qtd_origens
        FROM por_item GROUP BY sk_centro_custo, ano, mes),
    achados AS (
        SELECT r.*, o.sk_tempo, o.valor_orcado, c.cod_centro_custo, c.sk_loja,
               coalesce(g.explicado, 0) AS explicado, coalesce(g.qtd_origens, 0) AS qtd_origens,
               r.realizado / o.valor_orcado AS razao,
               r.realizado - least(coalesce(g.explicado, 0), greatest(r.realizado - o.valor_orcado, 0))
                   AS sem_origens
        FROM realizado r
        JOIN orcado o USING (sk_centro_custo, ano, mes)
        JOIN dw.dim_centro_custo c USING (sk_centro_custo)
        LEFT JOIN origens g USING (sk_centro_custo, ano, mes)
        WHERE o.valor_orcado > 0 AND r.realizado > v_multiplo * o.valor_orcado)
    SELECT 'despesa_acima_orcado|' || a.cod_centro_custo || '|'
               || to_char(make_date(a.ano, a.mes, 1), 'YYYY-MM'),
           CASE WHEN a.sem_origens <= v_multiplo * a.valor_orcado THEN 'baixa'
                WHEN a.razao >= v_critica THEN 'critica'
                WHEN a.razao >= v_alta THEN 'alta' ELSE 'media' END,
           a.sk_tempo, a.sk_loja, NULL::INT, a.sk_centro_custo, a.realizado - a.valor_orcado,
           CASE WHEN a.sem_origens <= v_multiplo * a.valor_orcado
                THEN format('realizado de %s em %s no centro %s = %s vezes o orçado de %s; o excesso é '
                            'explicado por %s alerta(s) de origem (%s); sem eles seria %s',
                            etl.fmt_brl(a.realizado), to_char(make_date(a.ano, a.mes, 1), 'MM/YYYY'),
                            a.cod_centro_custo, etl.fmt_num(a.razao, 1), etl.fmt_brl(a.valor_orcado),
                            a.qtd_origens, etl.fmt_brl(a.explicado), etl.fmt_brl(a.sem_origens))
                ELSE format('realizado de %s em %s no centro %s = %s vezes o orçado de %s '
                            '(excesso de %s)',
                            etl.fmt_brl(a.realizado), to_char(make_date(a.ano, a.mes, 1), 'MM/YYYY'),
                            a.cod_centro_custo, etl.fmt_num(a.razao, 1), etl.fmt_brl(a.valor_orcado),
                            etl.fmt_brl(a.realizado - a.valor_orcado))
           END,
           jsonb_build_object('cod_centro_custo', a.cod_centro_custo, 'competencia',
                              to_char(make_date(a.ano, a.mes, 1), 'YYYY-MM'),
                              'realizado', a.realizado, 'orcado', a.valor_orcado,
                              'razao', round(a.razao, 3), 'explicado_por_origens', a.explicado,
                              'realizado_sem_origens', a.sem_origens, 'origens', a.qtd_origens),
           a.sem_origens > v_multiplo * a.valor_orcado
    FROM achados a;
END $$;

-- Refaz os vínculos derivado -> origem de todos os alertas de orçado vigentes.
CREATE OR REPLACE PROCEDURE etl.vincular_derivados()
LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM dw.alerta_vinculos v
    USING dw.alertas d
    WHERE d.sk_alerta = v.sk_alerta_derivado AND d.tipo_alerta = 'despesa_acima_orcado';

    INSERT INTO dw.alerta_vinculos (sk_alerta_derivado, sk_alerta_origem, contribuicao)
    SELECT d.sk_alerta, o.sk_alerta, etl.contribuicao_orcado(o)
    FROM dw.alertas d
    JOIN dw.dim_tempo td ON td.sk_tempo = d.sk_tempo
    JOIN dw.alertas o ON o.sk_centro_custo = d.sk_centro_custo
        AND o.tipo_alerta IN ('despesa_valor_atipico', 'despesa_documento_repetido',
                              'despesa_centro_incompativel')
    JOIN dw.dim_tempo tor ON tor.sk_tempo = o.sk_tempo AND tor.ano = td.ano AND tor.mes = td.mes
    WHERE d.tipo_alerta = 'despesa_acima_orcado' AND d.vigente
      AND etl.contribuicao_orcado(o) > 0;
END $$;
