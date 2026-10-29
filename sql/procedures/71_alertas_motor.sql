-- Motor dos alertas (Fase 3). Nada aqui consulta arquivos de gabarito.
--
-- Cada regra é uma função etl.regra_<tipo_alerta>() que devolve os alertas que ela enxerga HOJE no
-- dw. etl.gerar_alertas confronta isso com dw.alertas por chave_alerta:
--   * alerta novo           -> inserido com status 'novo';
--   * alerta já existente   -> valor, texto e severidade são atualizados; status, observação e
--                              histórico NUNCA são tocados (resolvido/falso positivo não volta
--                              como novo);
--   * alerta que sumiu      -> vigente = FALSE (continua no banco, com o status que tinha);
--   * alerta que reaparece  -> vigente = TRUE de novo, com o mesmo status.

CREATE OR REPLACE PROCEDURE etl.gerar_alertas(p_id_carga BIGINT)
LANGUAGE plpgsql AS $$
DECLARE
    r RECORD;
    v_det INT; v_novos INT; v_mudou INT; v_reativ INT; v_sumiu INT;
BEGIN
    FOR r IN SELECT tipo_alerta, versao, ativa FROM etl.regras_alerta ORDER BY ordem, tipo_alerta LOOP
        DROP TABLE IF EXISTS _candidatos;
        IF r.ativa THEN
            EXECUTE format('CREATE TEMP TABLE _candidatos ON COMMIT DROP AS SELECT * FROM etl.regra_%s()',
                           r.tipo_alerta);
        ELSE  -- regra desligada: nada é detectado, os alertas dela deixam de ser vigentes
            CREATE TEMP TABLE _candidatos ON COMMIT DROP AS
            SELECT * FROM etl.regra_vazia() WHERE FALSE;
        END IF;

        SELECT count(*) INTO v_det FROM _candidatos;
        IF v_det <> (SELECT count(DISTINCT chave) FROM _candidatos) THEN
            RAISE EXCEPTION 'a regra % devolveu a mesma chave de alerta mais de uma vez', r.tipo_alerta;
        END IF;
        SELECT count(*) INTO v_reativ
        FROM _candidatos c JOIN dw.alertas a ON a.chave_alerta = c.chave WHERE NOT a.vigente;

        WITH up AS (
            INSERT INTO dw.alertas AS a (chave_alerta, tipo_alerta, severidade, sk_tempo, sk_loja,
                sk_vendedor, sk_centro_custo, valor_envolvido, regra, explicacao, detalhe,
                id_carga_origem, id_carga_ultima, independente)
            SELECT c.chave, r.tipo_alerta, c.severidade, c.sk_tempo, c.sk_loja, c.sk_vendedor,
                   c.sk_centro_custo, c.valor, r.tipo_alerta || '@' || r.versao, c.explicacao,
                   c.detalhe, p_id_carga, p_id_carga, c.independente
            FROM _candidatos c
            ON CONFLICT (chave_alerta) DO UPDATE SET
                severidade = EXCLUDED.severidade, sk_tempo = EXCLUDED.sk_tempo,
                sk_loja = EXCLUDED.sk_loja, sk_vendedor = EXCLUDED.sk_vendedor,
                sk_centro_custo = EXCLUDED.sk_centro_custo,
                valor_envolvido = EXCLUDED.valor_envolvido, regra = EXCLUDED.regra,
                explicacao = EXCLUDED.explicacao, detalhe = EXCLUDED.detalhe,
                independente = EXCLUDED.independente, vigente = TRUE,
                id_carga_ultima = EXCLUDED.id_carga_ultima, atualizado_em = now()
            WHERE (a.severidade, a.sk_tempo, a.sk_loja, a.sk_vendedor, a.sk_centro_custo,
                   a.valor_envolvido, a.regra, a.explicacao, a.detalhe, a.independente, a.vigente)
                IS DISTINCT FROM (EXCLUDED.severidade, EXCLUDED.sk_tempo, EXCLUDED.sk_loja,
                   EXCLUDED.sk_vendedor, EXCLUDED.sk_centro_custo, EXCLUDED.valor_envolvido,
                   EXCLUDED.regra, EXCLUDED.explicacao, EXCLUDED.detalhe, EXCLUDED.independente,
                   TRUE)
            RETURNING (xmax = 0) AS inserido)
        SELECT count(*) FILTER (WHERE inserido), count(*) FILTER (WHERE NOT inserido)
        INTO v_novos, v_mudou FROM up;

        UPDATE dw.alertas a SET vigente = FALSE, id_carga_ultima = p_id_carga, atualizado_em = now()
        WHERE a.tipo_alerta = r.tipo_alerta AND a.vigente
          AND NOT EXISTS (SELECT 1 FROM _candidatos c WHERE c.chave = a.chave_alerta);
        GET DIAGNOSTICS v_sumiu = ROW_COUNT;

        INSERT INTO etl.carga_alertas (id_carga, tipo_alerta, detectados, novos, atualizados,
                                       inalterados, reativados, deixaram_de_vigorar)
        VALUES (p_id_carga, r.tipo_alerta, v_det, v_novos, v_mudou - v_reativ,
                v_det - v_novos - v_mudou, v_reativ, v_sumiu);
    END LOOP;

    CALL etl.vincular_derivados();  -- liga os alertas derivados às origens (ver 74_alertas_orcado.sql)
END $$;

-- Molde do que toda regra devolve (usado só para criar a tabela vazia de regras desligadas).
CREATE OR REPLACE FUNCTION etl.regra_vazia()
RETURNS TABLE (chave TEXT, severidade TEXT, sk_tempo INT, sk_loja INT, sk_vendedor INT,
               sk_centro_custo INT, valor NUMERIC, explicacao TEXT, detalhe JSONB,
               independente BOOLEAN)
LANGUAGE sql STABLE AS $$
    SELECT NULL::TEXT, NULL::TEXT, NULL::INT, NULL::INT, NULL::INT, NULL::INT, NULL::NUMERIC,
           NULL::TEXT, NULL::JSONB, NULL::BOOLEAN
$$;

-- Muda o status de um alerta e registra no histórico. É o único caminho para tratar alertas.
CREATE OR REPLACE PROCEDURE dw.tratar_alerta(
    p_sk_alerta BIGINT, p_status TEXT, p_usuario TEXT, p_observacao TEXT DEFAULT NULL
) LANGUAGE plpgsql AS $$
DECLARE v_anterior TEXT;
BEGIN
    IF p_status NOT IN ('novo', 'em_analise', 'resolvido', 'falso_positivo') THEN
        RAISE EXCEPTION 'status inválido: %', p_status;
    END IF;
    IF p_usuario IS NULL OR btrim(p_usuario) = '' THEN
        RAISE EXCEPTION 'informe quem está tratando o alerta';
    END IF;
    SELECT status INTO v_anterior FROM dw.alertas WHERE sk_alerta = p_sk_alerta FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'alerta inexistente: %', p_sk_alerta;
    END IF;
    IF v_anterior = p_status THEN
        RAISE EXCEPTION 'o alerta % já está com o status %', p_sk_alerta, p_status;
    END IF;
    UPDATE dw.alertas SET status = p_status, status_em = now(), tratado_por = p_usuario,
        observacao = COALESCE(p_observacao, observacao), atualizado_em = now()
    WHERE sk_alerta = p_sk_alerta;
    INSERT INTO dw.alerta_historico (sk_alerta, status_anterior, status_novo, usuario, observacao)
    VALUES (p_sk_alerta, v_anterior, p_status, p_usuario, p_observacao);
END $$;
