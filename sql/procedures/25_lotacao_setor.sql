-- Carga da lotação do vendedor por setor (stg -> dw.vendedor_setor_historico). Roteiro em 00_comum.sql.
-- O arquivo traz o histórico completo de cada vendedor: períodos que sumiram do arquivo saem do dw.

CREATE OR REPLACE PROCEDURE etl.carregar_lotacao_setor(p_id_carga BIGINT)
LANGUAGE plpgsql AS $$
DECLARE v_validas INT; v_ins INT; v_upd INT; v_rem INT;
BEGIN
    DROP TABLE IF EXISTS _lim_lotacao_setor;
    CREATE TEMP TABLE _lim_lotacao_setor ON COMMIT DROP AS
    SELECT s.arquivo_origem, s.linha_origem, c.*, v.sk_vendedor,
           r.coluna AS rej_coluna, r.valor AS rej_valor, r.motivo AS rej_motivo
    FROM stg.lotacao_setor s
    CROSS JOIN LATERAL (SELECT
        etl.limpar_texto(s.cod_vendedor) AS cod_vendedor, etl.limpar_texto(s.setor) AS setor,
        etl.limpar_data(s.data_inicio) AS data_inicio, etl.limpar_data(s.data_fim) AS data_fim,
        etl.limpar_texto(s.motivo) AS motivo) c
    LEFT JOIN dw.dim_vendedor v ON v.cod_vendedor = c.cod_vendedor
    LEFT JOIN LATERAL (
        SELECT q.coluna, q.valor, q.motivo FROM (VALUES
            (1, 'cod_vendedor', s.cod_vendedor,
                etl.motivo(s.cod_vendedor, v.sk_vendedor IS NULL, 'vendedor_inexistente')),
            (2, 'setor', s.setor, COALESCE(etl.motivo_texto(s.setor, 30),
                CASE WHEN NOT EXISTS (SELECT 1 FROM dw.dim_produto p WHERE p.setor = c.setor)
                     THEN 'setor_inexistente' END)),
            (3, 'data_inicio', s.data_inicio,
                etl.motivo(s.data_inicio, c.data_inicio IS NULL, 'data_invalida')),
            (4, 'data_fim', s.data_fim,
                etl.motivo(s.data_fim, c.data_fim IS NULL, 'data_invalida', false)),
            (5, 'data_fim', s.data_fim,
                CASE WHEN c.data_fim < c.data_inicio THEN 'fim_antes_do_inicio' END),
            (6, 'data_inicio', s.data_inicio,
                CASE WHEN c.data_inicio < v.data_admissao THEN 'inicio_antes_da_admissao' END),
            (7, 'data_fim', s.data_fim,
                CASE WHEN v.data_desligamento IS NOT NULL
                          AND COALESCE(c.data_fim, DATE 'infinity') > v.data_desligamento
                     THEN 'periodo_depois_do_desligamento' END),
            (8, 'motivo', s.motivo, etl.motivo_texto(s.motivo, 40, false))
        ) q(ord, coluna, valor, motivo) WHERE q.motivo IS NOT NULL ORDER BY q.ord LIMIT 1
    ) r ON true
    WHERE s.id_carga = p_id_carga;

    CALL etl.rejeitar_duplicadas('lotacao_setor', 'sk_vendedor, data_inicio', 'data_inicio',
                                 't.data_inicio::TEXT', 'ultima');
    -- períodos que começam dentro de um período anterior do mesmo vendedor
    UPDATE _lim_lotacao_setor t SET rej_coluna = 'data_inicio', rej_valor = t.data_inicio::TEXT,
           rej_motivo = 'periodo_sobreposto'
    WHERE t.rej_motivo IS NULL AND EXISTS (
        SELECT 1 FROM _lim_lotacao_setor o
        WHERE o.rej_motivo IS NULL AND o.sk_vendedor = t.sk_vendedor
          AND o.data_inicio < t.data_inicio
          AND COALESCE(o.data_fim, DATE 'infinity') >= t.data_inicio);
    CALL etl.contar_correcao(p_id_carga, 'lotacao_setor', 'data_inicio', 'data_formato_misto',
                             $q$s.data_inicio ~ '^\s*\d{4}-'$q$);
    CALL etl.contar_correcao(p_id_carga, 'lotacao_setor', 'data_fim', 'data_formato_misto',
                             $q$s.data_fim ~ '^\s*\d{4}-'$q$);

    SELECT count(*) INTO v_validas FROM _lim_lotacao_setor WHERE rej_motivo IS NULL;
    WITH up AS (
        INSERT INTO dw.vendedor_setor_historico AS h (sk_vendedor, setor, data_inicio, data_fim,
                                                      motivo, id_carga)
        SELECT sk_vendedor, setor, data_inicio, data_fim, motivo, p_id_carga
        FROM _lim_lotacao_setor WHERE rej_motivo IS NULL
        ON CONFLICT ON CONSTRAINT uq_vendedor_setor_historico DO UPDATE
            SET setor = EXCLUDED.setor, data_fim = EXCLUDED.data_fim, motivo = EXCLUDED.motivo,
                id_carga = EXCLUDED.id_carga
        WHERE (h.setor, h.data_fim, h.motivo)
            IS DISTINCT FROM (EXCLUDED.setor, EXCLUDED.data_fim, EXCLUDED.motivo)
        RETURNING (xmax = 0) AS inserida)
    SELECT count(*) FILTER (WHERE inserida), count(*) FILTER (WHERE NOT inserida)
    INTO v_ins, v_upd FROM up;

    -- períodos que o arquivo não traz mais (dos vendedores que ele cobre)
    WITH fora AS (
        DELETE FROM dw.vendedor_setor_historico h
        WHERE h.sk_vendedor IN (SELECT sk_vendedor FROM _lim_lotacao_setor WHERE rej_motivo IS NULL)
          AND NOT EXISTS (SELECT 1 FROM _lim_lotacao_setor t
                          WHERE t.rej_motivo IS NULL AND t.sk_vendedor = h.sk_vendedor
                            AND t.data_inicio = h.data_inicio)
        RETURNING 1)
    SELECT count(*) INTO v_rem FROM fora;
    CALL etl.fechar_entidade(p_id_carga, 'lotacao_setor', v_ins, v_upd, v_validas - v_ins - v_upd,
                             v_rem);
END $$;
