-- Validações da carga (Fase 2). Nada aqui consulta arquivos de gabarito.
--
-- etl.validar_estrutura: ESTRUTURAIS, chamada na mesma transação da carga (usa as tabelas
--   temporárias _lim_*). Se alguma voltar ok = false, quem chama desfaz a transação.
-- etl.sinais_negocio: sinais de NEGÓCIO sobre o estado atual do dw; só contam, nunca bloqueiam.

CREATE OR REPLACE FUNCTION etl.validar_estrutura(p_id_carga BIGINT)
RETURNS TABLE (validacao TEXT, ok BOOLEAN, quantidade BIGINT, detalhe TEXT)
LANGUAGE plpgsql AS $$
#variable_conflict use_column
DECLARE
    v BIGINT; v2 BIGINT; v3 BIGINT;
    r RECORD;
    v_join TEXT;
BEGIN
    -- 1. integridade das chaves: nenhuma linha dos fatos/dimensões aponta para dimensão inexistente
    SELECT count(*) INTO v FROM dw.fato_vendas f
    WHERE NOT EXISTS (SELECT 1 FROM dw.dim_tempo x WHERE x.sk_tempo = f.sk_tempo)
       OR NOT EXISTS (SELECT 1 FROM dw.dim_hora x WHERE x.sk_hora = f.sk_hora)
       OR NOT EXISTS (SELECT 1 FROM dw.dim_loja x WHERE x.sk_loja = f.sk_loja)
       OR NOT EXISTS (SELECT 1 FROM dw.dim_vendedor x WHERE x.sk_vendedor = f.sk_vendedor)
       OR NOT EXISTS (SELECT 1 FROM dw.dim_forma_pagamento x
                      WHERE x.sk_forma_pagamento = f.sk_forma_pagamento)
       OR NOT EXISTS (SELECT 1 FROM dw.dim_produto x WHERE x.sk_produto = f.sk_produto)
       OR (f.sk_cliente IS NOT NULL
           AND NOT EXISTS (SELECT 1 FROM dw.dim_cliente x WHERE x.sk_cliente = f.sk_cliente))
       OR (f.sk_campanha IS NOT NULL
           AND NOT EXISTS (SELECT 1 FROM dw.dim_campanha x WHERE x.sk_campanha = f.sk_campanha));
    RETURN QUERY SELECT 'chaves_fato_vendas'::TEXT, v = 0, v, 'itens de venda com chave sem dimensão';

    SELECT count(*) INTO v FROM dw.fato_despesas f
    WHERE NOT EXISTS (SELECT 1 FROM dw.dim_tempo x WHERE x.sk_tempo = f.sk_tempo)
       OR NOT EXISTS (SELECT 1 FROM dw.dim_centro_custo x WHERE x.sk_centro_custo = f.sk_centro_custo);
    RETURN QUERY SELECT 'chaves_fato_despesas'::TEXT, v = 0, v, 'despesas com chave sem dimensão';

    SELECT (SELECT count(*) FROM dw.fato_meta_vendas f
            WHERE NOT EXISTS (SELECT 1 FROM dw.dim_tempo x WHERE x.sk_tempo = f.sk_tempo)
               OR NOT EXISTS (SELECT 1 FROM dw.dim_loja x WHERE x.sk_loja = f.sk_loja))
         + (SELECT count(*) FROM dw.fato_meta_vendedor f
            WHERE NOT EXISTS (SELECT 1 FROM dw.dim_tempo x WHERE x.sk_tempo = f.sk_tempo)
               OR NOT EXISTS (SELECT 1 FROM dw.dim_vendedor x WHERE x.sk_vendedor = f.sk_vendedor))
         + (SELECT count(*) FROM dw.fato_orcamento_despesas f
            WHERE NOT EXISTS (SELECT 1 FROM dw.dim_tempo x WHERE x.sk_tempo = f.sk_tempo)
               OR NOT EXISTS (SELECT 1 FROM dw.dim_centro_custo x
                              WHERE x.sk_centro_custo = f.sk_centro_custo))
    INTO v;
    RETURN QUERY SELECT 'chaves_metas_e_orcamento'::TEXT, v = 0, v,
                        'metas e orçamentos com chave sem dimensão';

    SELECT (SELECT count(*) FROM dw.dim_vendedor f
            WHERE NOT EXISTS (SELECT 1 FROM dw.dim_loja x WHERE x.sk_loja = f.sk_loja))
         + (SELECT count(*) FROM dw.dim_centro_custo f
            WHERE f.sk_loja IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM dw.dim_loja x WHERE x.sk_loja = f.sk_loja))
         + (SELECT count(*) FROM dw.dim_loja_horario f
            WHERE NOT EXISTS (SELECT 1 FROM dw.dim_loja x WHERE x.sk_loja = f.sk_loja))
    INTO v;
    RETURN QUERY SELECT 'chaves_dimensoes'::TEXT, v = 0, v, 'dimensões com loja inexistente';

    -- 2. soma dos itens = total do cupom (cupons repetidos contam uma vez; cupons com algum item
    --    rejeitado ficam de fora, pois estão incompletos de propósito)
    IF to_regclass('pg_temp._lim_vendas') IS NOT NULL THEN
        WITH validas AS (
            SELECT DISTINCT ON (numero_cupom, numero_item)
                   numero_cupom, numero_item, receita_liquida, total_cupom
            FROM _lim_vendas WHERE rej_motivo IS NULL
            ORDER BY numero_cupom, numero_item, id_venda_erp),
        incompletos AS (
            SELECT DISTINCT numero_cupom FROM _lim_vendas WHERE rej_motivo IS NOT NULL),
        por_cupom AS (
            SELECT v.numero_cupom, sum(v.receita_liquida) AS soma, min(v.total_cupom) AS minimo,
                   max(v.total_cupom) AS maximo
            FROM validas v WHERE NOT EXISTS (SELECT 1 FROM incompletos i
                                             WHERE i.numero_cupom = v.numero_cupom)
            GROUP BY v.numero_cupom)
        SELECT count(*) FILTER (WHERE soma <> minimo OR minimo <> maximo), count(*),
               (SELECT count(*) FROM incompletos)
        INTO v, v2, v3 FROM por_cupom;
        RETURN QUERY SELECT 'soma_itens_igual_total_cupom'::TEXT, v = 0, v,
            format('%s cupons verificados; %s ignorados por terem item rejeitado', v2, v3);
    END IF;

    -- 3. contagem: staging = dw + rejeitados, entidade por entidade
    FOR r IN SELECT t.entidade, t.lidas, t.rejeitadas, t.carregadas
             FROM etl.carga_tabelas t WHERE t.id_carga = p_id_carga ORDER BY t.entidade LOOP
        EXECUTE format('SELECT count(*) FROM stg.%I WHERE id_carga = $1', r.entidade)
            INTO v USING p_id_carga;
        SELECT count(*) INTO v2 FROM stg.rejeitados j
        WHERE j.id_carga = p_id_carga AND j.entidade = r.entidade;
        v_join := CASE r.entidade
            WHEN 'lojas' THEN 'dw.dim_loja d JOIN _lim_lojas t ON d.cod_loja = t.cod_loja'
            WHEN 'horarios_loja' THEN 'dw.dim_loja_horario d JOIN _lim_horarios_loja t'
                ' ON d.sk_loja = t.sk_loja AND d.dia_semana = t.dia_semana'
            WHEN 'produtos' THEN 'dw.dim_produto d JOIN _lim_produtos t ON d.sku = t.sku'
            WHEN 'centros_custo' THEN 'dw.dim_centro_custo d JOIN _lim_centros_custo t'
                ' ON d.cod_centro_custo = t.cod_centro_custo'
            WHEN 'formas_pagamento' THEN 'dw.dim_forma_pagamento d JOIN _lim_formas_pagamento t'
                ' ON d.cod_forma_pagamento = t.cod_forma_pagamento'
            WHEN 'campanhas' THEN 'dw.dim_campanha d JOIN _lim_campanhas t'
                ' ON d.cod_campanha = t.cod_campanha'
            WHEN 'vendedores' THEN 'dw.dim_vendedor d JOIN _lim_vendedores t'
                ' ON d.cod_vendedor = t.cod_vendedor'
            WHEN 'clientes' THEN 'dw.dim_cliente d JOIN _lim_clientes t'
                ' ON d.cod_cliente = t.cod_cliente'
            WHEN 'vendas' THEN 'dw.fato_vendas d JOIN _lim_vendas t'
                ' ON d.id_venda_erp = t.id_venda_erp'
            WHEN 'metas_vendas' THEN 'dw.fato_meta_vendas d JOIN _lim_metas_vendas t'
                ' ON d.sk_tempo = to_char(t.competencia, ''YYYYMMDD'')::INT'
                ' AND d.sk_loja = t.sk_loja AND d.setor = t.setor'
            WHEN 'metas_vendedor' THEN 'dw.fato_meta_vendedor d JOIN _lim_metas_vendedor t'
                ' ON d.sk_tempo = to_char(t.competencia, ''YYYYMMDD'')::INT'
                ' AND d.sk_vendedor = t.sk_vendedor'
            WHEN 'orcamento_despesas' THEN 'dw.fato_orcamento_despesas d JOIN'
                ' _lim_orcamento_despesas t'
                ' ON d.sk_tempo = to_char(t.competencia, ''YYYYMMDD'')::INT'
                ' AND d.sk_centro_custo = t.sk_centro_custo'
            WHEN 'despesas' THEN 'dw.fato_despesas d JOIN _lim_despesas t'
                ' ON d.arquivo_origem = t.arquivo_origem AND d.linha_origem = t.linha_origem'
        END;
        IF v_join IS NULL THEN  -- feriados: viram marcas na dim_tempo, sem tabela própria
            v3 := r.carregadas;
        ELSE
            EXECUTE 'SELECT count(*) FROM ' || v_join || ' WHERE t.rej_motivo IS NULL' INTO v3;
        END IF;
        RETURN QUERY SELECT 'contagem_' || r.entidade,
            v = r.lidas AND v2 = r.rejeitadas AND v3 = r.carregadas AND r.lidas = r.rejeitadas + r.carregadas,
            abs(v - r.lidas) + abs(v2 - r.rejeitadas) + abs(v3 - r.carregadas),
            format('staging %s = dw %s + rejeitados %s (registrado: %s/%s/%s)',
                   v, v3, v2, r.lidas, r.carregadas, r.rejeitadas);
    END LOOP;

    -- 4. tipos/consistência: data e hora do item batem com as chaves de tempo e hora
    SELECT count(*) INTO v FROM dw.fato_vendas f
    WHERE f.sk_tempo <> to_char(f.data_hora_venda, 'YYYYMMDD')::INT
       OR f.sk_hora <> extract(hour FROM f.data_hora_venda)::INT;
    RETURN QUERY SELECT 'consistencia_data_hora_vendas'::TEXT, v = 0, v,
                        'itens cuja data/hora não bate com sk_tempo/sk_hora';

    -- 5. valores monetários não negativos onde a regra exige
    SELECT (SELECT count(*) FROM dw.fato_vendas
            WHERE preco_unitario < 0 OR desconto < 0 OR custo < 0 OR quantidade <= 0)
         + (SELECT count(*) FROM dw.dim_produto WHERE custo_unitario < 0 OR preco_lista < 0)
         + (SELECT count(*) FROM dw.fato_meta_vendas WHERE valor_meta < 0)
         + (SELECT count(*) FROM dw.fato_meta_vendedor WHERE valor_meta < 0)
         + (SELECT count(*) FROM dw.fato_orcamento_despesas WHERE valor_orcado < 0)
    INTO v;
    RETURN QUERY SELECT 'valores_nao_negativos'::TEXT, v = 0, v,
                        'preço, desconto, custo, quantidade, metas e orçamento negativos';
END $$;


CREATE OR REPLACE FUNCTION etl.sinais_negocio()
RETURNS TABLE (sinal TEXT, unidade TEXT, quantidade BIGINT, descricao TEXT)
LANGUAGE plpgsql AS $$
#variable_conflict use_column
DECLARE
    p_desc_max NUMERIC; p_tol NUMERIC; p_canc_mult NUMERIC; p_canc_min NUMERIC;
    p_atip NUMERIC; p_orc NUMERIC;
    v BIGINT; v_taxa_rede NUMERIC;
BEGIN
    SELECT valor INTO p_desc_max FROM etl.parametros_negocio WHERE chave = 'desconto_maximo';
    SELECT valor INTO p_tol FROM etl.parametros_negocio WHERE chave = 'tolerancia_desconto';
    SELECT valor INTO p_canc_mult FROM etl.parametros_negocio WHERE chave = 'cancelamento_multiplo';
    SELECT valor INTO p_canc_min FROM etl.parametros_negocio WHERE chave = 'cancelamento_min_cupons';
    SELECT valor INTO p_atip FROM etl.parametros_negocio WHERE chave = 'valor_atipico_multiplo';
    SELECT valor INTO p_orc FROM etl.parametros_negocio WHERE chave = 'orcado_excesso_multiplo';

    SELECT count(*) INTO v FROM dw.fato_vendas f
    JOIN dw.dim_vendedor d ON d.sk_vendedor = f.sk_vendedor
    WHERE f.data_hora_venda::DATE < d.data_admissao
       OR (d.data_desligamento IS NOT NULL AND f.data_hora_venda::DATE > d.data_desligamento);
    RETURN QUERY SELECT 'venda_de_vendedor_inativo', 'itens', v,
                        'venda em data anterior à admissão ou posterior ao desligamento do vendedor';

    SELECT count(*) INTO v FROM dw.fato_vendas
    WHERE desconto > quantidade * preco_unitario * p_desc_max + p_tol;
    RETURN QUERY SELECT 'desconto_acima_do_limite', 'itens', v,
                        'desconto maior que o máximo permitido sobre o valor bruto do item';

    SELECT count(*) INTO v FROM dw.fato_vendas WHERE receita_liquida < custo;
    RETURN QUERY SELECT 'margem_negativa', 'itens', v, 'item vendido abaixo do custo';

    SELECT count(DISTINCT f.numero_cupom) INTO v
    FROM dw.fato_vendas f
    JOIN dw.dim_loja_horario h ON h.sk_loja = f.sk_loja
        AND h.dia_semana = extract(isodow FROM f.data_hora_venda)::INT
    WHERE f.data_hora_venda::TIME < h.hora_abertura OR f.data_hora_venda::TIME >= h.hora_fechamento;
    RETURN QUERY SELECT 'venda_fora_do_horario', 'cupons', v,
                        'cupom registrado fora do horário de funcionamento da loja';

    SELECT count(DISTINCT numero_cupom) INTO v FROM (
        SELECT numero_cupom FROM dw.fato_vendas GROUP BY numero_cupom, numero_item
        HAVING count(*) > 1) x;
    RETURN QUERY SELECT 'cupom_duplicado', 'cupons', v,
                        'cupom com o mesmo item lançado mais de uma vez';

    SELECT sum((status = 'Cancelada')::INT)::NUMERIC / NULLIF(count(*), 0) INTO v_taxa_rede
    FROM (SELECT DISTINCT numero_cupom, status FROM dw.fato_vendas) c;
    SELECT count(*) INTO v FROM (
        SELECT sk_vendedor FROM (SELECT DISTINCT numero_cupom, sk_vendedor, status
                                 FROM dw.fato_vendas) c
        GROUP BY sk_vendedor
        HAVING count(*) >= p_canc_min
           AND sum((status = 'Cancelada')::INT)::NUMERIC / count(*) > p_canc_mult * v_taxa_rede) x;
    RETURN QUERY SELECT 'vendedor_com_cancelamento_alto', 'vendedores', v,
                        'taxa de cancelamento do vendedor muito acima da média da rede';

    SELECT count(*) INTO v FROM (
        SELECT numero_documento FROM dw.fato_despesas GROUP BY numero_documento
        HAVING count(*) > 1) x;
    RETURN QUERY SELECT 'despesa_documento_repetido', 'documentos', v,
                        'mesmo número de documento lançado mais de uma vez';

    SELECT count(*) INTO v FROM dw.fato_despesas f
    JOIN dw.dim_tempo t ON t.sk_tempo = f.sk_tempo
    WHERE t.feriado_nacional OR t.nome_dia_semana IN ('Sábado', 'Domingo');
    RETURN QUERY SELECT 'despesa_em_fim_de_semana_ou_feriado', 'lancamentos', v,
                        'lançamento em sábado, domingo ou feriado nacional';

    SELECT count(*) INTO v FROM dw.fato_despesas f
    JOIN (SELECT sk_centro_custo, percentile_cont(0.5) WITHIN GROUP (ORDER BY valor) AS mediana
          FROM dw.fato_despesas GROUP BY sk_centro_custo) m USING (sk_centro_custo)
    WHERE f.valor > p_atip * m.mediana;
    RETURN QUERY SELECT 'despesa_de_valor_atipico', 'lancamentos', v,
                        'lançamento muito acima da mediana do seu centro de custo';

    SELECT count(*) INTO v FROM (
        SELECT f.sk_centro_custo, t.ano, t.mes, sum(f.valor) AS realizado
        FROM dw.fato_despesas f JOIN dw.dim_tempo t USING (sk_tempo)
        GROUP BY 1, 2, 3) r
    JOIN (SELECT o.sk_centro_custo, t.ano, t.mes, o.valor_orcado
          FROM dw.fato_orcamento_despesas o JOIN dw.dim_tempo t USING (sk_tempo)) o
        USING (sk_centro_custo, ano, mes)
    WHERE r.realizado > p_orc * o.valor_orcado;
    RETURN QUERY SELECT 'despesa_acima_do_orcado', 'centro_mes', v,
                        'centro de custo com despesa do mês muito acima do orçado';
END $$;
