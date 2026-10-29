-- Procedure mestra: leva ao dw as entidades que têm linhas no staging da carga.
-- Ordem: dimensões, calendário, fatos. Tudo na transação de quem chama; se algo falhar, o chamador
-- desfaz (ROLLBACK) e o dw não muda.

CREATE OR REPLACE FUNCTION etl.entidade_na_carga(p_id_carga BIGINT, p_entidade TEXT)
RETURNS BOOLEAN LANGUAGE plpgsql AS $$
DECLARE v_existe BOOLEAN;
BEGIN
    EXECUTE format('SELECT EXISTS (SELECT 1 FROM stg.%I WHERE id_carga = $1)', p_entidade)
        INTO v_existe USING p_id_carga;
    RETURN v_existe;
END $$;

CREATE OR REPLACE PROCEDURE etl.carregar_dw(p_id_carga BIGINT)
LANGUAGE plpgsql AS $$
DECLARE v_entidade TEXT;
BEGIN
    CALL etl.carregar_horas();
    FOREACH v_entidade IN ARRAY ARRAY['lojas', 'horarios_loja', 'produtos', 'centros_custo',
                                      'formas_pagamento', 'campanhas', 'vendedores', 'clientes',
                                      'feriados'] LOOP
        IF etl.entidade_na_carga(p_id_carga, v_entidade) THEN
            EXECUTE format('CALL etl.carregar_%s($1)', v_entidade) USING p_id_carga;
        END IF;
    END LOOP;
    CALL etl.carregar_calendario(p_id_carga);
    FOREACH v_entidade IN ARRAY ARRAY['vendas', 'metas_vendas', 'metas_vendedor', 'despesas',
                                      'orcamento_despesas'] LOOP
        IF etl.entidade_na_carga(p_id_carga, v_entidade) THEN
            EXECUTE format('CALL etl.carregar_%s($1)', v_entidade) USING p_id_carga;
        END IF;
    END LOOP;
END $$;
