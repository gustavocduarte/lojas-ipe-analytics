-- dw.gravar_fatia_vendedor_setor: fatia semanal do vendedor no setor da loja (simulador v2).
-- fatia = venda do vendedor no setor / venda total do setor na loja, nas semanas (segunda a domingo)
-- em que ele esteve lotado no setor a semana inteira, na janela anterior à referência. A fatia
-- central é encolhida para a média dos outros lotados no setor (loja; senão rede):
-- (n x própria + k x média) / (n + k). A conservadora é o percentil da distribuição das fatias já
-- encolhidas (sem histórico próprio, o percentil das fatias dos outros lotados). Preenche as linhas
-- de dw.desempenho_vendedor_setor da data de referência; só vendas concluídas.

CREATE OR REPLACE PROCEDURE dw.gravar_fatia_vendedor_setor(p_ref DATE DEFAULT NULL)
LANGUAGE plpgsql AS $$
DECLARE
    v_ref DATE := COALESCE(p_ref, dw.data_referencia());
    v_janela INT := etl.parametro('simulador_janela_dias')::INT;
    v_k NUMERIC := etl.parametro('simulador_k_encolhimento');
    v_q NUMERIC := etl.parametro('simulador_percentil_fatia');
    v_alta INT := etl.parametro('simulador_semanas_confianca_alta')::INT;
    v_media INT := etl.parametro('simulador_semanas_confianca_media')::INT;
BEGIN
    DROP TABLE IF EXISTS _f_total, _f_vend, _f_obs, _f_prop, _f_loja, _f_rede;

    CREATE TEMP TABLE _f_total ON COMMIT DROP AS
    SELECT sk_loja, setor, semana, total FROM (
        SELECT v.sk_loja, p.setor, date_trunc('week', t.data)::DATE AS semana,
               sum(v.receita_liquida) AS total
        FROM dw.fato_vendas v JOIN dw.dim_tempo t ON t.sk_tempo = v.sk_tempo
        JOIN dw.dim_produto p ON p.sk_produto = v.sk_produto
        WHERE v.status = 'Concluída' AND t.data BETWEEN v_ref - v_janela - 7 AND v_ref
        GROUP BY v.sk_loja, p.setor, date_trunc('week', t.data)) s
    WHERE semana > v_ref - v_janela AND semana + 6 <= v_ref AND total > 0;

    CREATE TEMP TABLE _f_vend ON COMMIT DROP AS
    SELECT v.sk_vendedor, p.setor, date_trunc('week', t.data)::DATE AS semana,
           sum(v.receita_liquida) AS valor
    FROM dw.fato_vendas v JOIN dw.dim_tempo t ON t.sk_tempo = v.sk_tempo
    JOIN dw.dim_produto p ON p.sk_produto = v.sk_produto
    WHERE v.status = 'Concluída' AND t.data BETWEEN v_ref - v_janela - 7 AND v_ref
    GROUP BY v.sk_vendedor, p.setor, date_trunc('week', t.data);

    CREATE TEMP TABLE _f_obs ON COMMIT DROP AS
    SELECT h.sk_vendedor, d.sk_loja, h.setor, t.semana,
           COALESCE(vs.valor, 0) / t.total AS fatia
    FROM dw.vendedor_setor_historico h
    JOIN dw.dim_vendedor d ON d.sk_vendedor = h.sk_vendedor
    JOIN _f_total t ON t.sk_loja = d.sk_loja AND t.setor = h.setor
         AND t.semana >= h.data_inicio AND t.semana + 6 <= COALESCE(h.data_fim, DATE 'infinity')
    LEFT JOIN _f_vend vs ON vs.sk_vendedor = h.sk_vendedor AND vs.setor = h.setor
         AND vs.semana = t.semana;

    CREATE TEMP TABLE _f_prop ON COMMIT DROP AS
    SELECT sk_vendedor, setor, count(*) AS n, sum(fatia) AS soma, avg(fatia) AS media,
           percentile_cont(v_q::DOUBLE PRECISION) WITHIN GROUP (ORDER BY fatia)::NUMERIC AS pq
    FROM _f_obs GROUP BY sk_vendedor, setor;

    CREATE TEMP TABLE _f_loja ON COMMIT DROP AS
    SELECT sk_loja, setor, count(*) AS c, sum(fatia) AS s,
           percentile_cont(v_q::DOUBLE PRECISION) WITHIN GROUP (ORDER BY fatia)::NUMERIC AS pq
    FROM _f_obs GROUP BY sk_loja, setor;

    CREATE TEMP TABLE _f_rede ON COMMIT DROP AS
    SELECT setor, count(*) AS c, sum(fatia) AS s,
           percentile_cont(v_q::DOUBLE PRECISION) WITHIN GROUP (ORDER BY fatia)::NUMERIC AS pq
    FROM _f_obs GROUP BY setor;

    UPDATE dw.desempenho_vendedor_setor d
    SET fatia_semanas = x.n,
        fatia_propria = round(x.propria, 6),
        fatia_media_loja = round(x.media_outros, 6),
        nivel_fatia = x.nivel,
        fatia_central = round(CASE WHEN x.n = 0 THEN x.media_outros
                                   ELSE (x.n * x.propria + v_k * x.media_outros) / (x.n + v_k) END, 6),
        fatia_conservadora = round(CASE WHEN x.n = 0 THEN x.pq_outros
                                        ELSE (x.n * x.pq_propria + v_k * x.media_outros) / (x.n + v_k)
                                   END, 6),
        k_encolhimento = v_k,
        percentil_fatia = v_q,
        confianca_fatia = CASE WHEN x.media_outros IS NULL THEN 'sem_base'
                               WHEN x.n >= v_alta THEN 'alta'
                               WHEN x.n >= v_media THEN 'media'
                               WHEN x.nivel = 'rede' THEN 'muito_baixa'
                               ELSE 'baixa' END
    FROM (
        SELECT b.sk_vendedor, b.setor, COALESCE(p.n, 0) AS n, p.media AS propria, p.pq AS pq_propria,
               CASE WHEN l.c - COALESCE(p.n, 0) > 0 THEN 'loja'
                    WHEN r.c - COALESCE(p.n, 0) > 0 THEN 'rede' END AS nivel,
               COALESCE(CASE WHEN l.c - COALESCE(p.n, 0) > 0
                             THEN (l.s - COALESCE(p.soma, 0)) / (l.c - COALESCE(p.n, 0)) END,
                        CASE WHEN r.c - COALESCE(p.n, 0) > 0
                             THEN (r.s - COALESCE(p.soma, 0)) / (r.c - COALESCE(p.n, 0)) END,
                        p.media) AS media_outros,
               CASE WHEN l.c > 0 THEN l.pq ELSE r.pq END AS pq_outros
        FROM dw.desempenho_vendedor_setor b
        LEFT JOIN _f_prop p ON p.sk_vendedor = b.sk_vendedor AND p.setor = b.setor
        LEFT JOIN _f_loja l ON l.sk_loja = b.sk_loja AND l.setor = b.setor
        LEFT JOIN _f_rede r ON r.setor = b.setor
        WHERE b.data_referencia = v_ref) x
    WHERE d.data_referencia = v_ref AND d.sk_vendedor = x.sk_vendedor AND d.setor = x.setor;
END $$;

COMMENT ON PROCEDURE dw.gravar_fatia_vendedor_setor(DATE) IS 'Preenche a fatia semanal encolhida (central e conservadora) de dw.desempenho_vendedor_setor para a data de referência.';
