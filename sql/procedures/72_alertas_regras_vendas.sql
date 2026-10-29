-- Regras de alerta sobre vendas (Fase 3). Cada função devolve os alertas visíveis hoje no dw;
-- todos os limites vêm de etl.parametros_negocio (via etl.parametro). Ver 71_alertas_motor.sql.

CREATE OR REPLACE FUNCTION etl.regra_desconto_acima_limite()
RETURNS TABLE (chave TEXT, severidade TEXT, sk_tempo INT, sk_loja INT, sk_vendedor INT,
               sk_centro_custo INT, valor NUMERIC, explicacao TEXT, detalhe JSONB,
               independente BOOLEAN)
LANGUAGE plpgsql STABLE AS $$
#variable_conflict use_column
DECLARE
    v_limite NUMERIC := etl.parametro('desconto_maximo');
    v_tolerancia NUMERIC := etl.parametro('tolerancia_desconto');
    v_media NUMERIC := etl.parametro('desconto_sev_media_pp');
    v_alta NUMERIC := etl.parametro('desconto_sev_alta_pp');
BEGIN
    RETURN QUERY
    SELECT 'desconto_acima_limite|' || x.id_venda_erp,
           CASE WHEN x.pct - v_limite > v_alta THEN 'alta'
                WHEN x.pct - v_limite > v_media THEN 'media' ELSE 'baixa' END,
           x.sk_tempo, x.sk_loja, x.sk_vendedor, NULL::INT, x.desconto,
           format('desconto de %s acima do limite de %s (item %s, cupom %s)',
                  etl.fmt_pct(x.pct), etl.fmt_pct(v_limite, 0), x.sku, x.numero_cupom),
           jsonb_build_object('id_venda_erp', x.id_venda_erp, 'numero_cupom', x.numero_cupom,
                              'sku', x.sku, 'percentual', round(x.pct, 4), 'limite', v_limite,
                              'valor_bruto', x.bruto, 'desconto', x.desconto),
           TRUE
    FROM (SELECT f.id_venda_erp, f.numero_cupom, f.sk_tempo, f.sk_loja, f.sk_vendedor, f.desconto,
                 f.quantidade * f.preco_unitario AS bruto,
                 f.desconto / NULLIF(f.quantidade * f.preco_unitario, 0) AS pct, p.sku
          FROM dw.fato_vendas f JOIN dw.dim_produto p USING (sk_produto)
          WHERE f.desconto > f.quantidade * f.preco_unitario * v_limite + v_tolerancia) x;
END $$;
