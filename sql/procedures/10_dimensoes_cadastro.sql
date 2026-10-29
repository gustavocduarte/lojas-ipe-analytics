-- Cargas das dimensões de cadastro (stg -> dw): lojas, horários, produtos, centros de custo,
-- formas de pagamento e campanhas. Roteiro descrito em 00_comum.sql.

CREATE OR REPLACE PROCEDURE etl.carregar_lojas(p_id_carga BIGINT)
LANGUAGE plpgsql AS $$
DECLARE v_validas INT; v_ins INT; v_upd INT;
BEGIN
    DROP TABLE IF EXISTS _lim_lojas;
    CREATE TEMP TABLE _lim_lojas ON COMMIT DROP AS
    SELECT s.arquivo_origem, s.linha_origem, c.*,
           r.coluna AS rej_coluna, r.valor AS rej_valor, r.motivo AS rej_motivo
    FROM stg.lojas s
    CROSS JOIN LATERAL (SELECT
        etl.limpar_texto(s.cod_loja) AS cod_loja, etl.limpar_texto(s.nome_loja) AS nome_loja,
        upper(etl.limpar_texto(s.uf)) AS uf, etl.limpar_texto(s.regiao) AS regiao,
        etl.limpar_texto(s.cidade) AS cidade, etl.limpar_texto(s.formato) AS formato,
        etl.limpar_data(s.data_abertura) AS data_abertura) c
    LEFT JOIN LATERAL (
        SELECT q.coluna, q.valor, q.motivo FROM (VALUES
            (1, 'cod_loja', s.cod_loja, etl.motivo_texto(s.cod_loja, 10)),
            (2, 'nome_loja', s.nome_loja, etl.motivo_texto(s.nome_loja, 60)),
            (3, 'uf', s.uf, etl.motivo(s.uf, c.uf !~ '^[A-Z]{2}$', 'uf_invalida')),
            (4, 'regiao', s.regiao, etl.motivo_texto(s.regiao, 15)),
            (5, 'cidade', s.cidade, etl.motivo_texto(s.cidade, 60)),
            (6, 'formato', s.formato, etl.motivo_texto(s.formato, 20)),
            (7, 'data_abertura', s.data_abertura,
                etl.motivo(s.data_abertura, c.data_abertura IS NULL, 'data_invalida'))
        ) q(ord, coluna, valor, motivo) WHERE q.motivo IS NOT NULL ORDER BY q.ord LIMIT 1
    ) r ON true
    WHERE s.id_carga = p_id_carga;

    CALL etl.rejeitar_duplicadas('lojas', 'cod_loja', 'cod_loja', 't.cod_loja', 'ultima');
    CALL etl.contar_correcao(p_id_carga, 'lojas', 'data_abertura', 'data_formato_misto',
                             $q$s.data_abertura ~ '^\s*\d{4}-'$q$);

    SELECT count(*) INTO v_validas FROM _lim_lojas WHERE rej_motivo IS NULL;
    WITH up AS (
        INSERT INTO dw.dim_loja AS d (cod_loja, nome_loja, uf, regiao, cidade, formato, data_abertura)
        SELECT cod_loja, nome_loja, uf, regiao, cidade, formato, data_abertura
        FROM _lim_lojas WHERE rej_motivo IS NULL
        ON CONFLICT (cod_loja) DO UPDATE SET nome_loja = EXCLUDED.nome_loja, uf = EXCLUDED.uf,
            regiao = EXCLUDED.regiao, cidade = EXCLUDED.cidade, formato = EXCLUDED.formato,
            data_abertura = EXCLUDED.data_abertura
        WHERE (d.nome_loja, d.uf, d.regiao, d.cidade, d.formato, d.data_abertura)
            IS DISTINCT FROM (EXCLUDED.nome_loja, EXCLUDED.uf, EXCLUDED.regiao, EXCLUDED.cidade,
                              EXCLUDED.formato, EXCLUDED.data_abertura)
        RETURNING (xmax = 0) AS inserida)
    SELECT count(*) FILTER (WHERE inserida), count(*) FILTER (WHERE NOT inserida)
    INTO v_ins, v_upd FROM up;
    CALL etl.fechar_entidade(p_id_carga, 'lojas', v_ins, v_upd, v_validas - v_ins - v_upd);
END $$;

CREATE OR REPLACE PROCEDURE etl.carregar_horarios_loja(p_id_carga BIGINT)
LANGUAGE plpgsql AS $$
DECLARE v_validas INT; v_ins INT; v_upd INT;
BEGIN
    DROP TABLE IF EXISTS _lim_horarios_loja;
    CREATE TEMP TABLE _lim_horarios_loja ON COMMIT DROP AS
    SELECT s.arquivo_origem, s.linha_origem, c.*, l.sk_loja,
           r.coluna AS rej_coluna, r.valor AS rej_valor, r.motivo AS rej_motivo
    FROM stg.horarios_loja s
    CROSS JOIN LATERAL (SELECT
        etl.limpar_texto(s.cod_loja) AS cod_loja, etl.limpar_inteiro(s.dia_semana) AS dia_semana,
        etl.limpar_hora(s.hora_abertura) AS hora_abertura,
        etl.limpar_hora(s.hora_fechamento) AS hora_fechamento) c
    LEFT JOIN dw.dim_loja l ON l.cod_loja = c.cod_loja
    LEFT JOIN LATERAL (
        SELECT q.coluna, q.valor, q.motivo FROM (VALUES
            (1, 'cod_loja', s.cod_loja,
                etl.motivo(s.cod_loja, l.sk_loja IS NULL, 'loja_inexistente')),
            (2, 'dia_semana', s.dia_semana,
                etl.motivo(s.dia_semana, c.dia_semana IS NULL OR c.dia_semana NOT BETWEEN 1 AND 7,
                           'dia_semana_invalido')),
            (3, 'hora_abertura', s.hora_abertura,
                etl.motivo(s.hora_abertura, c.hora_abertura IS NULL, 'hora_invalida')),
            (4, 'hora_fechamento', s.hora_fechamento,
                etl.motivo(s.hora_fechamento, c.hora_fechamento IS NULL, 'hora_invalida')),
            (5, 'hora_fechamento', s.hora_fechamento,
                CASE WHEN c.hora_fechamento <= c.hora_abertura
                     THEN 'fechamento_nao_posterior_a_abertura' END)
        ) q(ord, coluna, valor, motivo) WHERE q.motivo IS NOT NULL ORDER BY q.ord LIMIT 1
    ) r ON true
    WHERE s.id_carga = p_id_carga;

    CALL etl.rejeitar_duplicadas('horarios_loja', 'sk_loja, dia_semana', 'dia_semana',
                                 't.dia_semana::TEXT', 'ultima');
    CALL etl.contar_correcao(p_id_carga, 'horarios_loja', 'hora_abertura', 'hora_formato_misto',
                             $q$s.hora_abertura !~ '^\d{2}:\d{2}:\d{2}$'$q$);
    CALL etl.contar_correcao(p_id_carga, 'horarios_loja', 'hora_fechamento', 'hora_formato_misto',
                             $q$s.hora_fechamento !~ '^\d{2}:\d{2}:\d{2}$'$q$);

    SELECT count(*) INTO v_validas FROM _lim_horarios_loja WHERE rej_motivo IS NULL;
    WITH up AS (
        INSERT INTO dw.dim_loja_horario AS d (sk_loja, dia_semana, hora_abertura, hora_fechamento)
        SELECT sk_loja, dia_semana, hora_abertura, hora_fechamento
        FROM _lim_horarios_loja WHERE rej_motivo IS NULL
        ON CONFLICT (sk_loja, dia_semana) DO UPDATE SET hora_abertura = EXCLUDED.hora_abertura,
            hora_fechamento = EXCLUDED.hora_fechamento
        WHERE (d.hora_abertura, d.hora_fechamento)
            IS DISTINCT FROM (EXCLUDED.hora_abertura, EXCLUDED.hora_fechamento)
        RETURNING (xmax = 0) AS inserida)
    SELECT count(*) FILTER (WHERE inserida), count(*) FILTER (WHERE NOT inserida)
    INTO v_ins, v_upd FROM up;
    CALL etl.fechar_entidade(p_id_carga, 'horarios_loja', v_ins, v_upd, v_validas - v_ins - v_upd);
END $$;

CREATE OR REPLACE PROCEDURE etl.carregar_produtos(p_id_carga BIGINT)
LANGUAGE plpgsql AS $$
DECLARE v_validas INT; v_ins INT; v_upd INT;
BEGIN
    DROP TABLE IF EXISTS _lim_produtos;
    CREATE TEMP TABLE _lim_produtos ON COMMIT DROP AS
    SELECT s.arquivo_origem, s.linha_origem, c.*,
           r.coluna AS rej_coluna, r.valor AS rej_valor, r.motivo AS rej_motivo
    FROM stg.produtos s
    CROSS JOIN LATERAL (SELECT
        etl.limpar_sku(s.sku) AS sku, etl.limpar_texto(s.nome_produto) AS nome_produto,
        etl.limpar_texto(s.marca) AS marca, etl.limpar_texto(s.setor) AS setor,
        etl.limpar_texto(s.categoria) AS categoria,
        etl.limpar_numero(s.custo_unitario) AS custo_unitario,
        etl.limpar_numero(s.preco_lista) AS preco_lista) c
    LEFT JOIN LATERAL (
        SELECT q.coluna, q.valor, q.motivo FROM (VALUES
            (1, 'sku', s.sku, etl.motivo_texto(s.sku, 20)),
            (2, 'nome_produto', s.nome_produto, etl.motivo_texto(s.nome_produto, 100)),
            (3, 'marca', s.marca, etl.motivo_texto(s.marca, 40)),
            (4, 'setor', s.setor, etl.motivo_texto(s.setor, 30)),
            (5, 'categoria', s.categoria, etl.motivo_texto(s.categoria, 40)),
            (6, 'custo_unitario', s.custo_unitario,
                COALESCE(etl.motivo_valor(s.custo_unitario, c.custo_unitario),
                         CASE WHEN c.custo_unitario >= 10000000000 THEN 'valor_fora_do_intervalo' END)),
            (7, 'preco_lista', s.preco_lista,
                COALESCE(etl.motivo_valor(s.preco_lista, c.preco_lista),
                         CASE WHEN c.preco_lista >= 10000000000 THEN 'valor_fora_do_intervalo' END))
        ) q(ord, coluna, valor, motivo) WHERE q.motivo IS NOT NULL ORDER BY q.ord LIMIT 1
    ) r ON true
    WHERE s.id_carga = p_id_carga;

    CALL etl.rejeitar_duplicadas('produtos', 'sku', 'sku', 't.sku', 'ultima');
    CALL etl.contar_correcao(p_id_carga, 'produtos', 'sku', 'sku_espacos_maiusculas',
                             's.sku IS DISTINCT FROM t.sku');
    CALL etl.contar_correcao(p_id_carga, 'produtos', 'custo_unitario', 'valor_texto_formato_br',
                             $q$s.custo_unitario ~ ','$q$);
    CALL etl.contar_correcao(p_id_carga, 'produtos', 'preco_lista', 'valor_texto_formato_br',
                             $q$s.preco_lista ~ ','$q$);

    SELECT count(*) INTO v_validas FROM _lim_produtos WHERE rej_motivo IS NULL;
    WITH up AS (
        INSERT INTO dw.dim_produto AS d (sku, nome_produto, marca, setor, categoria,
                                         custo_unitario, preco_lista)
        SELECT sku, nome_produto, marca, setor, categoria, custo_unitario, preco_lista
        FROM _lim_produtos WHERE rej_motivo IS NULL
        ON CONFLICT (sku) DO UPDATE SET nome_produto = EXCLUDED.nome_produto,
            marca = EXCLUDED.marca, setor = EXCLUDED.setor, categoria = EXCLUDED.categoria,
            custo_unitario = EXCLUDED.custo_unitario, preco_lista = EXCLUDED.preco_lista
        WHERE (d.nome_produto, d.marca, d.setor, d.categoria, d.custo_unitario, d.preco_lista)
            IS DISTINCT FROM (EXCLUDED.nome_produto, EXCLUDED.marca, EXCLUDED.setor,
                              EXCLUDED.categoria, EXCLUDED.custo_unitario, EXCLUDED.preco_lista)
        RETURNING (xmax = 0) AS inserida)
    SELECT count(*) FILTER (WHERE inserida), count(*) FILTER (WHERE NOT inserida)
    INTO v_ins, v_upd FROM up;
    CALL etl.fechar_entidade(p_id_carga, 'produtos', v_ins, v_upd, v_validas - v_ins - v_upd);
END $$;

CREATE OR REPLACE PROCEDURE etl.carregar_centros_custo(p_id_carga BIGINT)
LANGUAGE plpgsql AS $$
DECLARE v_validas INT; v_ins INT; v_upd INT;
BEGIN
    DROP TABLE IF EXISTS _lim_centros_custo;
    CREATE TEMP TABLE _lim_centros_custo ON COMMIT DROP AS
    SELECT s.arquivo_origem, s.linha_origem, c.*, l.sk_loja,
           r.coluna AS rej_coluna, r.valor AS rej_valor, r.motivo AS rej_motivo
    FROM stg.centros_custo s
    CROSS JOIN LATERAL (SELECT
        etl.limpar_texto(s.cod_centro_custo) AS cod_centro_custo,
        etl.limpar_texto(s.nome_centro_custo) AS nome_centro_custo,
        initcap(etl.limpar_texto(s.tipo_despesa)) AS tipo_despesa,
        etl.limpar_texto(s.cod_loja) AS cod_loja) c
    LEFT JOIN dw.dim_loja l ON l.cod_loja = c.cod_loja
    LEFT JOIN LATERAL (
        SELECT q.coluna, q.valor, q.motivo FROM (VALUES
            (1, 'cod_centro_custo', s.cod_centro_custo, etl.motivo_texto(s.cod_centro_custo, 20)),
            (2, 'nome_centro_custo', s.nome_centro_custo, etl.motivo_texto(s.nome_centro_custo, 80)),
            (3, 'tipo_despesa', s.tipo_despesa,
                etl.motivo(s.tipo_despesa,
                           c.tipo_despesa NOT IN ('Pessoal', 'Terceiros', 'Discricionárias'),
                           'tipo_despesa_invalido')),
            (4, 'cod_loja', s.cod_loja,
                etl.motivo(s.cod_loja, l.sk_loja IS NULL, 'loja_inexistente', false))
        ) q(ord, coluna, valor, motivo) WHERE q.motivo IS NOT NULL ORDER BY q.ord LIMIT 1
    ) r ON true
    WHERE s.id_carga = p_id_carga;

    CALL etl.rejeitar_duplicadas('centros_custo', 'cod_centro_custo', 'cod_centro_custo',
                                 't.cod_centro_custo', 'ultima');

    SELECT count(*) INTO v_validas FROM _lim_centros_custo WHERE rej_motivo IS NULL;
    WITH up AS (
        INSERT INTO dw.dim_centro_custo AS d (cod_centro_custo, nome_centro_custo, tipo_despesa,
                                              sk_loja)
        SELECT cod_centro_custo, nome_centro_custo, tipo_despesa, sk_loja
        FROM _lim_centros_custo WHERE rej_motivo IS NULL
        ON CONFLICT (cod_centro_custo) DO UPDATE SET nome_centro_custo = EXCLUDED.nome_centro_custo,
            tipo_despesa = EXCLUDED.tipo_despesa, sk_loja = EXCLUDED.sk_loja
        WHERE (d.nome_centro_custo, d.tipo_despesa, d.sk_loja)
            IS DISTINCT FROM (EXCLUDED.nome_centro_custo, EXCLUDED.tipo_despesa, EXCLUDED.sk_loja)
        RETURNING (xmax = 0) AS inserida)
    SELECT count(*) FILTER (WHERE inserida), count(*) FILTER (WHERE NOT inserida)
    INTO v_ins, v_upd FROM up;
    CALL etl.fechar_entidade(p_id_carga, 'centros_custo', v_ins, v_upd, v_validas - v_ins - v_upd);
END $$;

CREATE OR REPLACE PROCEDURE etl.carregar_formas_pagamento(p_id_carga BIGINT)
LANGUAGE plpgsql AS $$
DECLARE v_validas INT; v_ins INT; v_upd INT;
BEGIN
    DROP TABLE IF EXISTS _lim_formas_pagamento;
    CREATE TEMP TABLE _lim_formas_pagamento ON COMMIT DROP AS
    SELECT s.arquivo_origem, s.linha_origem, c.*,
           r.coluna AS rej_coluna, r.valor AS rej_valor, r.motivo AS rej_motivo
    FROM stg.formas_pagamento s
    CROSS JOIN LATERAL (SELECT
        upper(etl.limpar_texto(s.cod_forma_pagamento)) AS cod_forma_pagamento,
        etl.limpar_texto(s.nome_forma_pagamento) AS nome_forma_pagamento) c
    LEFT JOIN LATERAL (
        SELECT q.coluna, q.valor, q.motivo FROM (VALUES
            (1, 'cod_forma_pagamento', s.cod_forma_pagamento,
                etl.motivo_texto(s.cod_forma_pagamento, 5)),
            (2, 'nome_forma_pagamento', s.nome_forma_pagamento,
                etl.motivo_texto(s.nome_forma_pagamento, 30))
        ) q(ord, coluna, valor, motivo) WHERE q.motivo IS NOT NULL ORDER BY q.ord LIMIT 1
    ) r ON true
    WHERE s.id_carga = p_id_carga;

    CALL etl.rejeitar_duplicadas('formas_pagamento', 'cod_forma_pagamento', 'cod_forma_pagamento',
                                 't.cod_forma_pagamento', 'ultima');
    -- o nome também é único no dw: um nome já usado por outro código é rejeitado
    CALL etl.rejeitar_duplicadas('formas_pagamento', 'nome_forma_pagamento',
                                 'nome_forma_pagamento', 't.nome_forma_pagamento', 'ultima');

    SELECT count(*) INTO v_validas FROM _lim_formas_pagamento WHERE rej_motivo IS NULL;
    WITH up AS (
        INSERT INTO dw.dim_forma_pagamento AS d (cod_forma_pagamento, nome_forma_pagamento)
        SELECT cod_forma_pagamento, nome_forma_pagamento
        FROM _lim_formas_pagamento WHERE rej_motivo IS NULL
        ON CONFLICT (cod_forma_pagamento) DO UPDATE
            SET nome_forma_pagamento = EXCLUDED.nome_forma_pagamento
        WHERE d.nome_forma_pagamento IS DISTINCT FROM EXCLUDED.nome_forma_pagamento
        RETURNING (xmax = 0) AS inserida)
    SELECT count(*) FILTER (WHERE inserida), count(*) FILTER (WHERE NOT inserida)
    INTO v_ins, v_upd FROM up;
    CALL etl.fechar_entidade(p_id_carga, 'formas_pagamento', v_ins, v_upd,
                             v_validas - v_ins - v_upd);
END $$;

CREATE OR REPLACE PROCEDURE etl.carregar_campanhas(p_id_carga BIGINT)
LANGUAGE plpgsql AS $$
DECLARE v_validas INT; v_ins INT; v_upd INT;
BEGIN
    DROP TABLE IF EXISTS _lim_campanhas;
    CREATE TEMP TABLE _lim_campanhas ON COMMIT DROP AS
    SELECT s.arquivo_origem, s.linha_origem, c.*,
           r.coluna AS rej_coluna, r.valor AS rej_valor, r.motivo AS rej_motivo
    FROM stg.campanhas s
    CROSS JOIN LATERAL (SELECT
        etl.limpar_texto(s.cod_campanha) AS cod_campanha,
        etl.limpar_texto(s.nome_campanha) AS nome_campanha,
        etl.limpar_data(s.data_inicio) AS data_inicio, etl.limpar_data(s.data_fim) AS data_fim,
        etl.limpar_numero(s.desconto_medio_pct) AS desconto_medio) c
    LEFT JOIN LATERAL (
        SELECT q.coluna, q.valor, q.motivo FROM (VALUES
            (1, 'cod_campanha', s.cod_campanha, etl.motivo_texto(s.cod_campanha, 12)),
            (2, 'nome_campanha', s.nome_campanha, etl.motivo_texto(s.nome_campanha, 40)),
            (3, 'data_inicio', s.data_inicio,
                etl.motivo(s.data_inicio, c.data_inicio IS NULL, 'data_invalida')),
            (4, 'data_fim', s.data_fim,
                etl.motivo(s.data_fim, c.data_fim IS NULL, 'data_invalida')),
            (5, 'data_fim', s.data_fim,
                CASE WHEN c.data_fim < c.data_inicio THEN 'fim_antes_do_inicio' END),
            (6, 'desconto_medio_pct', s.desconto_medio_pct,
                COALESCE(etl.motivo_valor(s.desconto_medio_pct, c.desconto_medio),
                         CASE WHEN c.desconto_medio >= 1000 THEN 'valor_fora_do_intervalo' END))
        ) q(ord, coluna, valor, motivo) WHERE q.motivo IS NOT NULL ORDER BY q.ord LIMIT 1
    ) r ON true
    WHERE s.id_carga = p_id_carga;

    CALL etl.rejeitar_duplicadas('campanhas', 'cod_campanha', 'cod_campanha', 't.cod_campanha',
                                 'ultima');
    CALL etl.contar_correcao(p_id_carga, 'campanhas', 'data_inicio', 'data_formato_misto',
                             $q$s.data_inicio ~ '^\s*\d{4}-'$q$);
    CALL etl.contar_correcao(p_id_carga, 'campanhas', 'data_fim', 'data_formato_misto',
                             $q$s.data_fim ~ '^\s*\d{4}-'$q$);

    SELECT count(*) INTO v_validas FROM _lim_campanhas WHERE rej_motivo IS NULL;
    WITH up AS (
        INSERT INTO dw.dim_campanha AS d (cod_campanha, nome_campanha, data_inicio, data_fim,
                                          desconto_medio)
        SELECT cod_campanha, nome_campanha, data_inicio, data_fim, desconto_medio
        FROM _lim_campanhas WHERE rej_motivo IS NULL
        ON CONFLICT (cod_campanha) DO UPDATE SET nome_campanha = EXCLUDED.nome_campanha,
            data_inicio = EXCLUDED.data_inicio, data_fim = EXCLUDED.data_fim,
            desconto_medio = EXCLUDED.desconto_medio
        WHERE (d.nome_campanha, d.data_inicio, d.data_fim, d.desconto_medio)
            IS DISTINCT FROM (EXCLUDED.nome_campanha, EXCLUDED.data_inicio, EXCLUDED.data_fim,
                              EXCLUDED.desconto_medio)
        RETURNING (xmax = 0) AS inserida)
    SELECT count(*) FILTER (WHERE inserida), count(*) FILTER (WHERE NOT inserida)
    INTO v_ins, v_upd FROM up;
    CALL etl.fechar_entidade(p_id_carga, 'campanhas', v_ins, v_upd, v_validas - v_ins - v_upd);
END $$;
