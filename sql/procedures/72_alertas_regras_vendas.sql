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

-- Cupons sem repetição: cada (cupom, item) conta uma vez; as cópias viram "extras".
CREATE OR REPLACE FUNCTION etl.cupons_unicos()
RETURNS TABLE (numero_cupom TEXT, sk_tempo INT, sk_loja INT, sk_vendedor INT, data_hora TIMESTAMP,
               status TEXT, itens INT, total NUMERIC, linhas_extras INT, valor_extra NUMERIC)
LANGUAGE sql STABLE AS $$
    SELECT o.numero_cupom::TEXT, min(o.sk_tempo), min(o.sk_loja), min(o.sk_vendedor),
           min(o.data_hora_venda), min(o.status)::TEXT,
           (count(*) FILTER (WHERE o.ocorrencia = 1))::INT,
           coalesce(sum(o.receita_liquida) FILTER (WHERE o.ocorrencia = 1), 0),
           (count(*) FILTER (WHERE o.ocorrencia > 1))::INT,
           coalesce(sum(o.receita_liquida) FILTER (WHERE o.ocorrencia > 1), 0)
    FROM (SELECT f.*, row_number() OVER (PARTITION BY f.numero_cupom, f.numero_item
                                         ORDER BY f.sk_venda) AS ocorrencia
          FROM dw.fato_vendas f) o
    GROUP BY o.numero_cupom
$$;

CREATE OR REPLACE FUNCTION etl.regra_margem_negativa()
RETURNS TABLE (chave TEXT, severidade TEXT, sk_tempo INT, sk_loja INT, sk_vendedor INT,
               sk_centro_custo INT, valor NUMERIC, explicacao TEXT, detalhe JSONB,
               independente BOOLEAN)
LANGUAGE plpgsql STABLE AS $$
#variable_conflict use_column
DECLARE
    v_media NUMERIC := etl.parametro('margem_sev_media');
    v_alta NUMERIC := etl.parametro('margem_sev_alta');
BEGIN
    RETURN QUERY
    SELECT 'margem_negativa|' || x.id_venda_erp,
           CASE WHEN x.perda / x.custo >= v_alta THEN 'alta'
                WHEN x.perda / x.custo >= v_media THEN 'media' ELSE 'baixa' END,
           x.sk_tempo, x.sk_loja, x.sk_vendedor, NULL::INT, x.perda,
           format('item %s vendido por %s, abaixo do custo de %s (prejuízo de %s, %s do custo; cupom %s)',
                  x.sku, etl.fmt_brl(x.receita_liquida), etl.fmt_brl(x.custo), etl.fmt_brl(x.perda),
                  etl.fmt_pct(x.perda / x.custo), x.numero_cupom),
           jsonb_build_object('id_venda_erp', x.id_venda_erp, 'numero_cupom', x.numero_cupom,
                              'sku', x.sku, 'receita_liquida', x.receita_liquida, 'custo', x.custo,
                              'prejuizo', x.perda),
           TRUE
    FROM (SELECT f.id_venda_erp, f.numero_cupom, f.sk_tempo, f.sk_loja, f.sk_vendedor,
                 f.receita_liquida, f.custo, f.custo - f.receita_liquida AS perda, p.sku
          FROM dw.fato_vendas f JOIN dw.dim_produto p USING (sk_produto)
          WHERE f.receita_liquida < f.custo) x;
END $$;

CREATE OR REPLACE FUNCTION etl.regra_venda_fora_horario()
RETURNS TABLE (chave TEXT, severidade TEXT, sk_tempo INT, sk_loja INT, sk_vendedor INT,
               sk_centro_custo INT, valor NUMERIC, explicacao TEXT, detalhe JSONB,
               independente BOOLEAN)
LANGUAGE plpgsql STABLE AS $$
#variable_conflict use_column
DECLARE
    v_alto NUMERIC := etl.parametro('fora_horario_valor_alto');
BEGIN
    RETURN QUERY
    SELECT 'venda_fora_horario|' || c.numero_cupom,
           CASE WHEN c.total >= v_alto THEN 'alta' ELSE 'media' END,
           c.sk_tempo, c.sk_loja, c.sk_vendedor, NULL::INT, c.total,
           format('cupom %s registrado às %s, fora do horário da loja (das %s às %s, %s); total %s',
                  c.numero_cupom, to_char(c.data_hora, 'HH24:MI'),
                  to_char(h.hora_abertura, 'HH24:MI'), to_char(h.hora_fechamento, 'HH24:MI'),
                  lower(t.nome_dia_semana), etl.fmt_brl(c.total)),
           jsonb_build_object('numero_cupom', c.numero_cupom, 'hora', to_char(c.data_hora, 'HH24:MI:SS'),
                              'abertura', h.hora_abertura, 'fechamento', h.hora_fechamento,
                              'total', c.total),
           TRUE
    FROM etl.cupons_unicos() c
    JOIN dw.dim_tempo t ON t.sk_tempo = c.sk_tempo
    JOIN dw.dim_loja_horario h
      ON h.sk_loja = c.sk_loja AND h.dia_semana = extract(isodow FROM c.data_hora)::INT
    WHERE c.data_hora::TIME < h.hora_abertura OR c.data_hora::TIME >= h.hora_fechamento;
END $$;

CREATE OR REPLACE FUNCTION etl.regra_cupom_duplicado()
RETURNS TABLE (chave TEXT, severidade TEXT, sk_tempo INT, sk_loja INT, sk_vendedor INT,
               sk_centro_custo INT, valor NUMERIC, explicacao TEXT, detalhe JSONB,
               independente BOOLEAN)
LANGUAGE plpgsql STABLE AS $$
#variable_conflict use_column
DECLARE
    v_alto NUMERIC := etl.parametro('cupom_duplicado_valor_alto');
BEGIN
    RETURN QUERY
    SELECT 'cupom_duplicado|' || c.numero_cupom,
           CASE WHEN c.valor_extra >= v_alto THEN 'alta' ELSE 'media' END,
           c.sk_tempo, c.sk_loja, c.sk_vendedor, NULL::INT, c.valor_extra,
           format('cupom %s lançado em duplicidade: %s linha(s) repetida(s), %s a mais no total',
                  c.numero_cupom, c.linhas_extras, etl.fmt_brl(c.valor_extra)),
           jsonb_build_object('numero_cupom', c.numero_cupom, 'itens', c.itens,
                              'linhas_repetidas', c.linhas_extras, 'valor_repetido', c.valor_extra,
                              'total_do_cupom', c.total),
           TRUE
    FROM etl.cupons_unicos() c
    WHERE c.linhas_extras > 0;
END $$;

CREATE OR REPLACE FUNCTION etl.regra_venda_vendedor_inativo()
RETURNS TABLE (chave TEXT, severidade TEXT, sk_tempo INT, sk_loja INT, sk_vendedor INT,
               sk_centro_custo INT, valor NUMERIC, explicacao TEXT, detalhe JSONB,
               independente BOOLEAN)
LANGUAGE plpgsql STABLE AS $$
#variable_conflict use_column
BEGIN
    RETURN QUERY
    SELECT 'venda_vendedor_inativo|' || c.numero_cupom, 'critica',
           c.sk_tempo, c.sk_loja, c.sk_vendedor, NULL::INT, c.total,
           format('cupom %s vendido em %s %s (%s); total %s',
                  c.numero_cupom, etl.fmt_data(c.data_hora::DATE),
                  CASE WHEN c.data_hora::DATE < v.data_admissao
                       THEN 'antes da admissão do vendedor ' || v.cod_vendedor
                       ELSE 'depois do desligamento do vendedor ' || v.cod_vendedor END,
                  CASE WHEN c.data_hora::DATE < v.data_admissao
                       THEN 'admitido em ' || etl.fmt_data(v.data_admissao)
                       ELSE 'desligado em ' || etl.fmt_data(v.data_desligamento) END,
                  etl.fmt_brl(c.total)),
           jsonb_build_object('numero_cupom', c.numero_cupom, 'cod_vendedor', v.cod_vendedor,
                              'data_admissao', v.data_admissao,
                              'data_desligamento', v.data_desligamento, 'total', c.total),
           TRUE
    FROM etl.cupons_unicos() c
    JOIN dw.dim_vendedor v ON v.sk_vendedor = c.sk_vendedor
    WHERE c.data_hora::DATE < v.data_admissao
       OR (v.data_desligamento IS NOT NULL AND c.data_hora::DATE > v.data_desligamento);
END $$;

-- Cancelamento alto, mês a mês: janela móvel de N meses terminando em cada mês, com mínimo de
-- cupons na janela e múltiplo da taxa da rede NA MESMA janela. Um alerta por vendedor e mês final.
CREATE OR REPLACE FUNCTION etl.regra_vendedor_cancelamento_alto()
RETURNS TABLE (chave TEXT, severidade TEXT, sk_tempo INT, sk_loja INT, sk_vendedor INT,
               sk_centro_custo INT, valor NUMERIC, explicacao TEXT, detalhe JSONB,
               independente BOOLEAN)
LANGUAGE plpgsql STABLE AS $$
#variable_conflict use_column
DECLARE
    v_janela INT := etl.parametro('cancelamento_janela_meses')::INT;
    v_multiplo NUMERIC := etl.parametro('cancelamento_multiplo');
    v_minimo NUMERIC := etl.parametro('cancelamento_min_cupons');
    v_alta NUMERIC := etl.parametro('cancelamento_sev_alta_multiplo');
    v_critica NUMERIC := etl.parametro('cancelamento_sev_critica_multiplo');
BEGIN
    RETURN QUERY
    WITH base AS (
        SELECT c.sk_vendedor,
               extract(year FROM c.data_hora)::INT * 12 + extract(month FROM c.data_hora)::INT - 1 AS mi,
               (c.status = 'Cancelada')::INT AS cancelado,
               CASE WHEN c.status = 'Cancelada' THEN c.total ELSE 0 END AS valor_cancelado
        FROM etl.cupons_unicos() c),
    mensal AS (
        SELECT sk_vendedor, mi, count(*) AS cupons, sum(cancelado) AS cancelados,
               sum(valor_cancelado) AS valor
        FROM base GROUP BY sk_vendedor, mi),
    rede AS (SELECT mi, sum(cupons) AS cupons, sum(cancelados) AS cancelados FROM mensal GROUP BY mi),
    janela_v AS (
        SELECT r.mi AS mf, m.sk_vendedor, sum(m.cupons) AS cupons, sum(m.cancelados) AS cancelados,
               sum(m.valor) AS valor
        FROM rede r JOIN mensal m ON m.mi BETWEEN r.mi - (v_janela - 1) AND r.mi
        GROUP BY r.mi, m.sk_vendedor),
    janela_r AS (
        SELECT r.mi AS mf, sum(x.cupons) AS cupons, sum(x.cancelados) AS cancelados
        FROM rede r JOIN rede x ON x.mi BETWEEN r.mi - (v_janela - 1) AND r.mi
        GROUP BY r.mi),
    achados AS (
        SELECT v.*, d.cod_vendedor, d.sk_loja,
               v.cancelados::NUMERIC / v.cupons AS taxa,
               r.cancelados::NUMERIC / r.cupons AS taxa_rede,
               (v.cancelados::NUMERIC / v.cupons) / (r.cancelados::NUMERIC / r.cupons) AS razao,
               to_char(make_date(v.mf / 12, v.mf % 12 + 1, 1), 'YYYY-MM') AS mes_final,
               to_char(make_date((v.mf - v_janela + 1) / 12, (v.mf - v_janela + 1) % 12 + 1, 1),
                       'MM/YYYY') AS mes_inicial,
               to_char(make_date(v.mf / 12, v.mf % 12 + 1, 1), 'MM/YYYY') AS mes_final_br,
               to_char((make_date(v.mf / 12, v.mf % 12 + 1, 1) + interval '1 month - 1 day'),
                       'YYYYMMDD')::INT AS sk_fim
        FROM janela_v v
        JOIN janela_r r ON r.mf = v.mf
        JOIN dw.dim_vendedor d ON d.sk_vendedor = v.sk_vendedor
        WHERE v.cupons >= v_minimo AND r.cancelados > 0
          AND v.cancelados::NUMERIC / v.cupons > v_multiplo * (r.cancelados::NUMERIC / r.cupons))
    SELECT 'vendedor_cancelamento_alto|' || a.cod_vendedor || '|' || a.mes_final,
           CASE WHEN a.razao >= v_critica THEN 'critica' WHEN a.razao >= v_alta THEN 'alta'
                ELSE 'media' END,
           a.sk_fim, a.sk_loja, a.sk_vendedor, NULL::INT, a.valor,
           format('%s de cancelamento (%s de %s cupons) de %s a %s, %s vezes a taxa da rede (%s)',
                  etl.fmt_pct(a.taxa), etl.fmt_num(a.cancelados), etl.fmt_num(a.cupons),
                  a.mes_inicial, a.mes_final_br, etl.fmt_num(a.razao, 1), etl.fmt_pct(a.taxa_rede)),
           jsonb_build_object('cod_vendedor', a.cod_vendedor, 'mes_final', a.mes_final,
                              'janela_meses', v_janela, 'cupons', a.cupons,
                              'cancelados', a.cancelados, 'taxa', round(a.taxa, 4),
                              'taxa_rede', round(a.taxa_rede, 4), 'razao', round(a.razao, 2)),
           TRUE
    FROM achados a;
END $$;
