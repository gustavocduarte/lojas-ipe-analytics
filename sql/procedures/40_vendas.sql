-- Carga dos itens de venda (stg -> dw.fato_vendas). Roteiro descrito em 00_comum.sql.
--
-- Só se corrige formato (data, hora, SKU, número em texto, desconto nulo recalculável). O conteúdo
-- das vendas não é julgado aqui: desconto alto, margem negativa, venda fora do horário, cupom
-- repetido etc. entram no dw como vieram e viram "sinais" na etl.validar_carga.
-- A tabela temporária _lim_vendas fica disponível até o fim da transação (usada nas validações).

CREATE OR REPLACE PROCEDURE etl.carregar_vendas(p_id_carga BIGINT)
LANGUAGE plpgsql AS $$
DECLARE v_validas INT; v_ins INT; v_upd INT; v_rem INT;
BEGIN
    DROP TABLE IF EXISTS _lim_vendas;
    CREATE TEMP TABLE _lim_vendas ON COMMIT DROP AS
    SELECT s.arquivo_origem, s.linha_origem, c.*, d.desconto,
           l.sk_loja, v.sk_vendedor, cl.sk_cliente, fp.sk_forma_pagamento, cp.sk_campanha,
           p.sk_produto,
           r.coluna AS rej_coluna, r.valor AS rej_valor, r.motivo AS rej_motivo
    FROM stg.vendas s
    CROSS JOIN LATERAL (SELECT
        etl.limpar_texto(s.id_venda_erp) AS id_venda_erp,
        etl.limpar_texto(s.numero_cupom) AS numero_cupom,
        etl.limpar_inteiro(s.numero_item) AS numero_item,
        etl.limpar_data(s.data_venda) AS data_venda, etl.limpar_hora(s.hora_venda) AS hora_venda,
        etl.limpar_texto(s.cod_loja) AS cod_loja, etl.limpar_inteiro(s.caixa) AS caixa,
        etl.limpar_texto(s.cod_vendedor) AS cod_vendedor,
        etl.limpar_texto(s.cod_cliente) AS cod_cliente,
        etl.limpar_texto(s.cod_forma_pagamento) AS cod_forma_pagamento,
        etl.limpar_inteiro(s.numero_parcelas) AS numero_parcelas,
        etl.limpar_texto(s.cod_campanha) AS cod_campanha, etl.limpar_sku(s.sku) AS sku,
        etl.limpar_inteiro(s.quantidade) AS quantidade,
        etl.limpar_numero(s.preco_unitario) AS preco_unitario,
        etl.limpar_numero(s.receita_liquida) AS receita_liquida,
        etl.limpar_numero(s.custo_total) AS custo_total,
        etl.limpar_numero(s.total_cupom) AS total_cupom,
        CASE lower(etl.limpar_texto(s.status))
            WHEN 'concluída' THEN 'Concluída' WHEN 'concluida' THEN 'Concluída'
            WHEN 'cancelada' THEN 'Cancelada' WHEN 'devolvida' THEN 'Devolvida'
        END AS status,
        etl.limpar_texto(s.motivo_cancelamento_devolucao) AS motivo_cancelamento_devolucao) c
    -- desconto vazio: recalcula como valor bruto - receita líquida (regra de negócio documentada)
    CROSS JOIN LATERAL (SELECT
        CASE WHEN etl.limpar_texto(s.desconto) IS NULL
             THEN round(c.quantidade * c.preco_unitario - c.receita_liquida, 2)
             ELSE etl.limpar_numero(s.desconto) END AS desconto) d
    LEFT JOIN dw.dim_loja l ON l.cod_loja = c.cod_loja
    LEFT JOIN dw.dim_vendedor v ON v.cod_vendedor = c.cod_vendedor
    LEFT JOIN dw.dim_cliente cl ON cl.cod_cliente = c.cod_cliente
    LEFT JOIN dw.dim_forma_pagamento fp ON fp.cod_forma_pagamento = c.cod_forma_pagamento
    LEFT JOIN dw.dim_campanha cp ON cp.cod_campanha = c.cod_campanha
    LEFT JOIN dw.dim_produto p ON p.sku = c.sku
    LEFT JOIN LATERAL (
        SELECT q.coluna, q.valor, q.motivo FROM (VALUES
            (1, 'id_venda_erp', s.id_venda_erp, etl.motivo_texto(s.id_venda_erp, 20)),
            (2, 'numero_cupom', s.numero_cupom, etl.motivo_texto(s.numero_cupom, 20)),
            (3, 'numero_item', s.numero_item,
                etl.motivo(s.numero_item, c.numero_item IS NULL OR c.numero_item NOT BETWEEN 1 AND 32767,
                           'inteiro_invalido')),
            (4, 'data_venda', s.data_venda,
                etl.motivo(s.data_venda, c.data_venda IS NULL, 'data_invalida')),
            (5, 'hora_venda', s.hora_venda,
                etl.motivo(s.hora_venda, c.hora_venda IS NULL, 'hora_invalida')),
            (6, 'cod_loja', s.cod_loja, etl.motivo(s.cod_loja, l.sk_loja IS NULL, 'loja_inexistente')),
            (7, 'caixa', s.caixa,
                etl.motivo(s.caixa, c.caixa IS NULL OR c.caixa NOT BETWEEN 1 AND 32767,
                           'inteiro_invalido')),
            (8, 'cod_vendedor', s.cod_vendedor,
                etl.motivo(s.cod_vendedor, v.sk_vendedor IS NULL, 'vendedor_inexistente')),
            (9, 'cod_cliente', s.cod_cliente,
                etl.motivo(s.cod_cliente, cl.sk_cliente IS NULL, 'cliente_inexistente', false)),
            (10, 'cod_forma_pagamento', s.cod_forma_pagamento,
                etl.motivo(s.cod_forma_pagamento, fp.sk_forma_pagamento IS NULL,
                           'forma_pagamento_inexistente')),
            (11, 'numero_parcelas', s.numero_parcelas,
                etl.motivo(s.numero_parcelas,
                           c.numero_parcelas IS NULL OR c.numero_parcelas NOT BETWEEN 1 AND 32767,
                           'inteiro_invalido')),
            (12, 'cod_campanha', s.cod_campanha,
                etl.motivo(s.cod_campanha, cp.sk_campanha IS NULL, 'campanha_inexistente', false)),
            (13, 'sku', s.sku, etl.motivo(s.sku, p.sk_produto IS NULL, 'sku_inexistente')),
            (14, 'quantidade', s.quantidade,
                etl.motivo(s.quantidade, c.quantidade IS NULL OR c.quantidade < 1,
                           'inteiro_invalido')),
            (15, 'preco_unitario', s.preco_unitario,
                etl.motivo_valor(s.preco_unitario, c.preco_unitario)),
            (16, 'receita_liquida', s.receita_liquida,
                etl.motivo_valor(s.receita_liquida, c.receita_liquida, true)),
            (17, 'custo_total', s.custo_total, etl.motivo_valor(s.custo_total, c.custo_total)),
            (18, 'total_cupom', s.total_cupom, etl.motivo_valor(s.total_cupom, c.total_cupom, true)),
            (19, 'desconto', s.desconto,
                CASE WHEN etl.limpar_texto(s.desconto) IS NOT NULL
                     THEN etl.motivo_valor(s.desconto, d.desconto)
                     WHEN d.desconto IS NULL THEN 'desconto_nao_recalculavel'
                     WHEN d.desconto < 0 THEN 'desconto_recalculado_negativo' END),
            (20, 'status', s.status, etl.motivo(s.status, c.status IS NULL, 'status_invalido')),
            (21, 'motivo_cancelamento_devolucao', s.motivo_cancelamento_devolucao,
                CASE WHEN c.status <> 'Concluída' AND c.motivo_cancelamento_devolucao IS NULL
                     THEN 'motivo_obrigatorio'
                     WHEN length(c.motivo_cancelamento_devolucao) > 60 THEN 'texto_longo_demais' END)
        ) q(ord, coluna, valor, motivo) WHERE q.motivo IS NOT NULL ORDER BY q.ord LIMIT 1
    ) r ON true
    WHERE s.id_carga = p_id_carga;

    CALL etl.rejeitar_duplicadas('vendas', 'id_venda_erp', 'id_venda_erp', 't.id_venda_erp',
                                 'primeira');

    CALL etl.contar_correcao(p_id_carga, 'vendas', 'data_venda', 'data_formato_misto',
                             $q$s.data_venda ~ '^\s*\d{4}-'$q$);
    CALL etl.contar_correcao(p_id_carga, 'vendas', 'hora_venda', 'hora_formato_misto',
                             $q$s.hora_venda !~ '^\d{2}:\d{2}:\d{2}$'$q$);
    CALL etl.contar_correcao(p_id_carga, 'vendas', 'sku', 'sku_espacos_maiusculas',
                             's.sku IS DISTINCT FROM t.sku');
    CALL etl.contar_correcao(p_id_carga, 'vendas', 'desconto', 'valor_nulo',
                             $q$nullif(btrim(s.desconto), '') IS NULL$q$);
    CALL etl.contar_correcao(p_id_carga, 'vendas', 'preco_unitario', 'valor_texto_formato_br',
                             $q$s.preco_unitario ~ ','$q$);
    CALL etl.contar_correcao(p_id_carga, 'vendas', 'desconto', 'valor_texto_formato_br',
                             $q$s.desconto ~ ','$q$);
    CALL etl.contar_correcao(p_id_carga, 'vendas', 'receita_liquida', 'valor_texto_formato_br',
                             $q$s.receita_liquida ~ ','$q$);
    CALL etl.contar_correcao(p_id_carga, 'vendas', 'custo_total', 'valor_texto_formato_br',
                             $q$s.custo_total ~ ','$q$);
    CALL etl.contar_correcao(p_id_carga, 'vendas', 'total_cupom', 'valor_texto_formato_br',
                             $q$s.total_cupom ~ ','$q$);

    SELECT count(*) INTO v_validas FROM _lim_vendas WHERE rej_motivo IS NULL;
    WITH up AS (
        INSERT INTO dw.fato_vendas AS f (id_venda_erp, numero_cupom, numero_item, sk_tempo, sk_hora,
            data_hora_venda, sk_loja, caixa, sk_vendedor, sk_cliente, sk_forma_pagamento,
            numero_parcelas, sk_campanha, sk_produto, quantidade, preco_unitario, desconto,
            receita_liquida, custo, status, motivo_cancelamento_devolucao, arquivo_origem,
            linha_origem, id_carga)
        SELECT id_venda_erp, numero_cupom, numero_item, to_char(data_venda, 'YYYYMMDD')::INT,
               extract(hour FROM hora_venda)::INT, data_venda + hora_venda, sk_loja, caixa,
               sk_vendedor, sk_cliente, sk_forma_pagamento, numero_parcelas, sk_campanha,
               sk_produto, quantidade, preco_unitario, desconto, receita_liquida, custo_total,
               status, motivo_cancelamento_devolucao, arquivo_origem, linha_origem, p_id_carga
        FROM _lim_vendas WHERE rej_motivo IS NULL
        ON CONFLICT (id_venda_erp) DO UPDATE SET numero_cupom = EXCLUDED.numero_cupom,
            numero_item = EXCLUDED.numero_item, sk_tempo = EXCLUDED.sk_tempo,
            sk_hora = EXCLUDED.sk_hora, data_hora_venda = EXCLUDED.data_hora_venda,
            sk_loja = EXCLUDED.sk_loja, caixa = EXCLUDED.caixa, sk_vendedor = EXCLUDED.sk_vendedor,
            sk_cliente = EXCLUDED.sk_cliente, sk_forma_pagamento = EXCLUDED.sk_forma_pagamento,
            numero_parcelas = EXCLUDED.numero_parcelas, sk_campanha = EXCLUDED.sk_campanha,
            sk_produto = EXCLUDED.sk_produto, quantidade = EXCLUDED.quantidade,
            preco_unitario = EXCLUDED.preco_unitario, desconto = EXCLUDED.desconto,
            receita_liquida = EXCLUDED.receita_liquida, custo = EXCLUDED.custo,
            status = EXCLUDED.status,
            motivo_cancelamento_devolucao = EXCLUDED.motivo_cancelamento_devolucao,
            arquivo_origem = EXCLUDED.arquivo_origem, linha_origem = EXCLUDED.linha_origem,
            id_carga = EXCLUDED.id_carga
        WHERE (f.numero_cupom, f.numero_item, f.sk_tempo, f.sk_hora, f.data_hora_venda, f.sk_loja,
               f.caixa, f.sk_vendedor, f.sk_cliente, f.sk_forma_pagamento, f.numero_parcelas,
               f.sk_campanha, f.sk_produto, f.quantidade, f.preco_unitario, f.desconto,
               f.receita_liquida, f.custo, f.status, f.motivo_cancelamento_devolucao,
               f.arquivo_origem, f.linha_origem)
            IS DISTINCT FROM (EXCLUDED.numero_cupom, EXCLUDED.numero_item, EXCLUDED.sk_tempo,
               EXCLUDED.sk_hora, EXCLUDED.data_hora_venda, EXCLUDED.sk_loja, EXCLUDED.caixa,
               EXCLUDED.sk_vendedor, EXCLUDED.sk_cliente, EXCLUDED.sk_forma_pagamento,
               EXCLUDED.numero_parcelas, EXCLUDED.sk_campanha, EXCLUDED.sk_produto,
               EXCLUDED.quantidade, EXCLUDED.preco_unitario, EXCLUDED.desconto,
               EXCLUDED.receita_liquida, EXCLUDED.custo, EXCLUDED.status,
               EXCLUDED.motivo_cancelamento_devolucao, EXCLUDED.arquivo_origem,
               EXCLUDED.linha_origem)
        RETURNING (xmax = 0) AS inserida)
    SELECT count(*) FILTER (WHERE inserida), count(*) FILTER (WHERE NOT inserida)
    INTO v_ins, v_upd FROM up;

    -- itens que existiam no dw vindos destes arquivos e não estão mais neles (ou ficaram inválidos)
    DELETE FROM dw.fato_vendas f
    WHERE f.arquivo_origem IN (SELECT DISTINCT arquivo_origem FROM _lim_vendas)
      AND NOT EXISTS (SELECT 1 FROM _lim_vendas t
                      WHERE t.rej_motivo IS NULL AND t.id_venda_erp = f.id_venda_erp);
    GET DIAGNOSTICS v_rem = ROW_COUNT;

    CALL etl.fechar_entidade(p_id_carga, 'vendas', v_ins, v_upd, v_validas - v_ins - v_upd, v_rem);
END $$;
