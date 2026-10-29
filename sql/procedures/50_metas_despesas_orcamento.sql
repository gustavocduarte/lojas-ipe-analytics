-- Cargas de metas, despesas e orçamento (stg -> dw). Roteiro descrito em 00_comum.sql.
-- A competência (mês) é guardada como o primeiro dia do mês na dim_tempo.

CREATE OR REPLACE PROCEDURE etl.carregar_metas_vendas(p_id_carga BIGINT)
LANGUAGE plpgsql AS $$
DECLARE v_validas INT; v_ins INT; v_upd INT;
BEGIN
    DROP TABLE IF EXISTS _lim_metas_vendas;
    CREATE TEMP TABLE _lim_metas_vendas ON COMMIT DROP AS
    SELECT s.arquivo_origem, s.linha_origem, c.*, l.sk_loja,
           r.coluna AS rej_coluna, r.valor AS rej_valor, r.motivo AS rej_motivo
    FROM stg.metas_vendas s
    CROSS JOIN LATERAL (SELECT
        date_trunc('month', etl.limpar_data(s.competencia))::DATE AS competencia,
        etl.limpar_texto(s.cod_loja) AS cod_loja, etl.limpar_texto(s.setor) AS setor,
        etl.limpar_numero(s.valor_meta) AS valor_meta) c
    LEFT JOIN dw.dim_loja l ON l.cod_loja = c.cod_loja
    LEFT JOIN LATERAL (
        SELECT q.coluna, q.valor, q.motivo FROM (VALUES
            (1, 'competencia', s.competencia,
                etl.motivo(s.competencia, c.competencia IS NULL, 'data_invalida')),
            (2, 'cod_loja', s.cod_loja, etl.motivo(s.cod_loja, l.sk_loja IS NULL, 'loja_inexistente')),
            (3, 'setor', s.setor, etl.motivo_texto(s.setor, 30)),
            (4, 'valor_meta', s.valor_meta, etl.motivo_valor(s.valor_meta, c.valor_meta))
        ) q(ord, coluna, valor, motivo) WHERE q.motivo IS NOT NULL ORDER BY q.ord LIMIT 1
    ) r ON true
    WHERE s.id_carga = p_id_carga;

    CALL etl.rejeitar_duplicadas('metas_vendas', 'competencia, sk_loja, setor', 'valor_meta',
                                 't.valor_meta::TEXT', 'ultima');
    CALL etl.contar_correcao(p_id_carga, 'metas_vendas', 'competencia', 'data_formato_misto',
                             $q$s.competencia ~ '^\s*\d{4}-'$q$);
    CALL etl.contar_correcao(p_id_carga, 'metas_vendas', 'valor_meta', 'valor_texto_formato_br',
                             $q$s.valor_meta ~ ','$q$);

    SELECT count(*) INTO v_validas FROM _lim_metas_vendas WHERE rej_motivo IS NULL;
    WITH up AS (
        INSERT INTO dw.fato_meta_vendas AS f (sk_tempo, sk_loja, setor, valor_meta)
        SELECT to_char(competencia, 'YYYYMMDD')::INT, sk_loja, setor, valor_meta
        FROM _lim_metas_vendas WHERE rej_motivo IS NULL
        ON CONFLICT ON CONSTRAINT uq_fato_meta_vendas DO UPDATE SET valor_meta = EXCLUDED.valor_meta
        WHERE f.valor_meta IS DISTINCT FROM EXCLUDED.valor_meta
        RETURNING (xmax = 0) AS inserida)
    SELECT count(*) FILTER (WHERE inserida), count(*) FILTER (WHERE NOT inserida)
    INTO v_ins, v_upd FROM up;
    CALL etl.fechar_entidade(p_id_carga, 'metas_vendas', v_ins, v_upd, v_validas - v_ins - v_upd);
END $$;

CREATE OR REPLACE PROCEDURE etl.carregar_metas_vendedor(p_id_carga BIGINT)
LANGUAGE plpgsql AS $$
DECLARE v_validas INT; v_ins INT; v_upd INT;
BEGIN
    DROP TABLE IF EXISTS _lim_metas_vendedor;
    CREATE TEMP TABLE _lim_metas_vendedor ON COMMIT DROP AS
    SELECT s.arquivo_origem, s.linha_origem, c.*, v.sk_vendedor,
           r.coluna AS rej_coluna, r.valor AS rej_valor, r.motivo AS rej_motivo
    FROM stg.metas_vendedor s
    CROSS JOIN LATERAL (SELECT
        date_trunc('month', etl.limpar_data(s.competencia))::DATE AS competencia,
        etl.limpar_texto(s.cod_vendedor) AS cod_vendedor,
        etl.limpar_numero(s.valor_meta) AS valor_meta) c
    LEFT JOIN dw.dim_vendedor v ON v.cod_vendedor = c.cod_vendedor
    LEFT JOIN LATERAL (
        SELECT q.coluna, q.valor, q.motivo FROM (VALUES
            (1, 'competencia', s.competencia,
                etl.motivo(s.competencia, c.competencia IS NULL, 'data_invalida')),
            (2, 'cod_vendedor', s.cod_vendedor,
                etl.motivo(s.cod_vendedor, v.sk_vendedor IS NULL, 'vendedor_inexistente')),
            (3, 'valor_meta', s.valor_meta, etl.motivo_valor(s.valor_meta, c.valor_meta))
        ) q(ord, coluna, valor, motivo) WHERE q.motivo IS NOT NULL ORDER BY q.ord LIMIT 1
    ) r ON true
    WHERE s.id_carga = p_id_carga;

    CALL etl.rejeitar_duplicadas('metas_vendedor', 'competencia, sk_vendedor', 'valor_meta',
                                 't.valor_meta::TEXT', 'ultima');
    CALL etl.contar_correcao(p_id_carga, 'metas_vendedor', 'competencia', 'data_formato_misto',
                             $q$s.competencia ~ '^\s*\d{4}-'$q$);
    CALL etl.contar_correcao(p_id_carga, 'metas_vendedor', 'valor_meta', 'valor_texto_formato_br',
                             $q$s.valor_meta ~ ','$q$);

    SELECT count(*) INTO v_validas FROM _lim_metas_vendedor WHERE rej_motivo IS NULL;
    WITH up AS (
        INSERT INTO dw.fato_meta_vendedor AS f (sk_tempo, sk_vendedor, valor_meta)
        SELECT to_char(competencia, 'YYYYMMDD')::INT, sk_vendedor, valor_meta
        FROM _lim_metas_vendedor WHERE rej_motivo IS NULL
        ON CONFLICT ON CONSTRAINT uq_fato_meta_vendedor DO UPDATE
            SET valor_meta = EXCLUDED.valor_meta
        WHERE f.valor_meta IS DISTINCT FROM EXCLUDED.valor_meta
        RETURNING (xmax = 0) AS inserida)
    SELECT count(*) FILTER (WHERE inserida), count(*) FILTER (WHERE NOT inserida)
    INTO v_ins, v_upd FROM up;
    CALL etl.fechar_entidade(p_id_carga, 'metas_vendedor', v_ins, v_upd, v_validas - v_ins - v_upd);
END $$;

CREATE OR REPLACE PROCEDURE etl.carregar_orcamento_despesas(p_id_carga BIGINT)
LANGUAGE plpgsql AS $$
DECLARE v_validas INT; v_ins INT; v_upd INT;
BEGIN
    DROP TABLE IF EXISTS _lim_orcamento_despesas;
    CREATE TEMP TABLE _lim_orcamento_despesas ON COMMIT DROP AS
    SELECT s.arquivo_origem, s.linha_origem, c.*, cc.sk_centro_custo,
           r.coluna AS rej_coluna, r.valor AS rej_valor, r.motivo AS rej_motivo
    FROM stg.orcamento_despesas s
    CROSS JOIN LATERAL (SELECT
        date_trunc('month', etl.limpar_data(s.competencia))::DATE AS competencia,
        etl.limpar_texto(s.cod_centro_custo) AS cod_centro_custo,
        etl.limpar_numero(s.valor_orcado) AS valor_orcado) c
    LEFT JOIN dw.dim_centro_custo cc ON cc.cod_centro_custo = c.cod_centro_custo
    LEFT JOIN LATERAL (
        SELECT q.coluna, q.valor, q.motivo FROM (VALUES
            (1, 'competencia', s.competencia,
                etl.motivo(s.competencia, c.competencia IS NULL, 'data_invalida')),
            (2, 'cod_centro_custo', s.cod_centro_custo,
                etl.motivo(s.cod_centro_custo, cc.sk_centro_custo IS NULL,
                           'centro_custo_inexistente')),
            (3, 'valor_orcado', s.valor_orcado, etl.motivo_valor(s.valor_orcado, c.valor_orcado))
        ) q(ord, coluna, valor, motivo) WHERE q.motivo IS NOT NULL ORDER BY q.ord LIMIT 1
    ) r ON true
    WHERE s.id_carga = p_id_carga;

    CALL etl.rejeitar_duplicadas('orcamento_despesas', 'competencia, sk_centro_custo',
                                 'valor_orcado', 't.valor_orcado::TEXT', 'ultima');
    CALL etl.contar_correcao(p_id_carga, 'orcamento_despesas', 'competencia',
                             'data_formato_misto', $q$s.competencia ~ '^\s*\d{4}-'$q$);
    CALL etl.contar_correcao(p_id_carga, 'orcamento_despesas', 'valor_orcado',
                             'valor_texto_formato_br', $q$s.valor_orcado ~ ','$q$);

    SELECT count(*) INTO v_validas FROM _lim_orcamento_despesas WHERE rej_motivo IS NULL;
    WITH up AS (
        INSERT INTO dw.fato_orcamento_despesas AS f (sk_tempo, sk_centro_custo, valor_orcado)
        SELECT to_char(competencia, 'YYYYMMDD')::INT, sk_centro_custo, valor_orcado
        FROM _lim_orcamento_despesas WHERE rej_motivo IS NULL
        ON CONFLICT ON CONSTRAINT uq_fato_orcamento_despesas DO UPDATE
            SET valor_orcado = EXCLUDED.valor_orcado
        WHERE f.valor_orcado IS DISTINCT FROM EXCLUDED.valor_orcado
        RETURNING (xmax = 0) AS inserida)
    SELECT count(*) FILTER (WHERE inserida), count(*) FILTER (WHERE NOT inserida)
    INTO v_ins, v_upd FROM up;
    CALL etl.fechar_entidade(p_id_carga, 'orcamento_despesas', v_ins, v_upd,
                             v_validas - v_ins - v_upd);
END $$;

-- Despesas não têm chave natural: a linha é identificada por (arquivo, posição no arquivo).
-- Um mesmo documento repetido entra duas vezes e vira sinal para a Fase 3.
CREATE OR REPLACE PROCEDURE etl.carregar_despesas(p_id_carga BIGINT)
LANGUAGE plpgsql AS $$
DECLARE v_validas INT; v_ins INT; v_upd INT; v_rem INT;
BEGIN
    DROP TABLE IF EXISTS _lim_despesas;
    CREATE TEMP TABLE _lim_despesas ON COMMIT DROP AS
    SELECT s.arquivo_origem, s.linha_origem, c.*, cc.sk_centro_custo,
           r.coluna AS rej_coluna, r.valor AS rej_valor, r.motivo AS rej_motivo
    FROM stg.despesas s
    CROSS JOIN LATERAL (SELECT
        etl.limpar_texto(s.numero_documento) AS numero_documento,
        etl.limpar_data(s.data_lancamento) AS data_lancamento,
        etl.limpar_texto(s.cod_centro_custo) AS cod_centro_custo,
        etl.limpar_numero(s.valor) AS valor,
        COALESCE(etl.limpar_texto(s.descricao), 'NAO INFORMADO') AS descricao,
        etl.limpar_texto(s.fornecedor) AS fornecedor) c
    LEFT JOIN dw.dim_centro_custo cc ON cc.cod_centro_custo = c.cod_centro_custo
    LEFT JOIN LATERAL (
        SELECT q.coluna, q.valor, q.motivo FROM (VALUES
            (1, 'numero_documento', s.numero_documento, etl.motivo_texto(s.numero_documento, 20)),
            (2, 'data_lancamento', s.data_lancamento,
                etl.motivo(s.data_lancamento, c.data_lancamento IS NULL, 'data_invalida')),
            (3, 'cod_centro_custo', s.cod_centro_custo,
                etl.motivo(s.cod_centro_custo, cc.sk_centro_custo IS NULL,
                           'centro_custo_inexistente')),
            (4, 'valor', s.valor, etl.motivo_valor(s.valor, c.valor, true)),
            (5, 'descricao', s.descricao, etl.motivo_texto(c.descricao, 200)),
            (6, 'fornecedor', s.fornecedor, etl.motivo_texto(s.fornecedor, 100, false))
        ) q(ord, coluna, valor, motivo) WHERE q.motivo IS NOT NULL ORDER BY q.ord LIMIT 1
    ) r ON true
    WHERE s.id_carga = p_id_carga;

    CALL etl.contar_correcao(p_id_carga, 'despesas', 'data_lancamento', 'data_formato_misto',
                             $q$s.data_lancamento ~ '^\s*\d{4}-'$q$);
    CALL etl.contar_correcao(p_id_carga, 'despesas', 'valor', 'valor_texto_formato_br',
                             $q$s.valor ~ ','$q$);
    CALL etl.contar_correcao(p_id_carga, 'despesas', 'descricao', 'valor_nulo',
                             $q$nullif(btrim(s.descricao), '') IS NULL$q$);

    SELECT count(*) INTO v_validas FROM _lim_despesas WHERE rej_motivo IS NULL;
    WITH up AS (
        INSERT INTO dw.fato_despesas AS f (numero_documento, sk_tempo, sk_centro_custo, fornecedor,
                                           valor, descricao, arquivo_origem, linha_origem, id_carga)
        SELECT numero_documento, to_char(data_lancamento, 'YYYYMMDD')::INT, sk_centro_custo,
               fornecedor, valor, descricao, arquivo_origem, linha_origem, p_id_carga
        FROM _lim_despesas WHERE rej_motivo IS NULL
        ON CONFLICT (arquivo_origem, linha_origem) DO UPDATE SET
            numero_documento = EXCLUDED.numero_documento, sk_tempo = EXCLUDED.sk_tempo,
            sk_centro_custo = EXCLUDED.sk_centro_custo, fornecedor = EXCLUDED.fornecedor,
            valor = EXCLUDED.valor, descricao = EXCLUDED.descricao, id_carga = EXCLUDED.id_carga
        WHERE (f.numero_documento, f.sk_tempo, f.sk_centro_custo, f.fornecedor, f.valor,
               f.descricao)
            IS DISTINCT FROM (EXCLUDED.numero_documento, EXCLUDED.sk_tempo,
               EXCLUDED.sk_centro_custo, EXCLUDED.fornecedor, EXCLUDED.valor, EXCLUDED.descricao)
        RETURNING (xmax = 0) AS inserida)
    SELECT count(*) FILTER (WHERE inserida), count(*) FILTER (WHERE NOT inserida)
    INTO v_ins, v_upd FROM up;

    DELETE FROM dw.fato_despesas f
    WHERE f.arquivo_origem IN (SELECT DISTINCT arquivo_origem FROM _lim_despesas)
      AND NOT EXISTS (SELECT 1 FROM _lim_despesas t
                      WHERE t.rej_motivo IS NULL AND t.arquivo_origem = f.arquivo_origem
                        AND t.linha_origem = f.linha_origem);
    GET DIAGNOSTICS v_rem = ROW_COUNT;

    CALL etl.fechar_entidade(p_id_carga, 'despesas', v_ins, v_upd, v_validas - v_ins - v_upd, v_rem);
END $$;
