-- Fase 4: meta mensal repartida pelos dias do mês (base do acompanhamento diário do Power BI).
-- Reaplicáveis: CREATE OR REPLACE VIEW.
--
-- O peso de cada dia = peso do dia da semana x (peso do feriado, se for feriado nacional). A meta do
-- dia é a meta do mês x peso do dia / soma dos pesos do mês, arredondada em centavos; o último dia
-- do mês absorve o resto do arredondamento, então a soma dos dias bate exatamente com a meta do mês.

CREATE OR REPLACE VIEW dw.vw_peso_dia AS
SELECT t.sk_tempo,
       t.data,
       t.ano,
       t.mes,
       p.valor * CASE WHEN t.feriado_nacional THEN f.valor ELSE 1 END AS peso,
       sum(p.valor * CASE WHEN t.feriado_nacional THEN f.valor ELSE 1 END)
           OVER (PARTITION BY t.ano, t.mes) AS peso_do_mes,
       t.data = max(t.data) OVER (PARTITION BY t.ano, t.mes) AS ultimo_dia_do_mes
FROM dw.dim_tempo t
JOIN etl.parametros_negocio p ON p.chave = 'peso_dia_semana_' || EXTRACT(ISODOW FROM t.data)::INT
CROSS JOIN (SELECT valor FROM etl.parametros_negocio WHERE chave = 'peso_feriado') f;

CREATE OR REPLACE VIEW dw.vw_meta_vendas_diaria AS
WITH repartida AS (
    SELECT p.sk_tempo, p.data, p.ultimo_dia_do_mes, m.sk_loja, m.setor, m.valor_meta,
           ROUND(m.valor_meta * p.peso / p.peso_do_mes, 2) AS valor_arredondado,
           p.ano, p.mes
    FROM dw.fato_meta_vendas m
    JOIN dw.dim_tempo tm ON tm.sk_tempo = m.sk_tempo
    JOIN dw.vw_peso_dia p ON p.ano = tm.ano AND p.mes = tm.mes
)
SELECT sk_tempo,
       data,
       sk_loja,
       setor,
       CASE WHEN ultimo_dia_do_mes
            THEN valor_meta - COALESCE(
                SUM(valor_arredondado) FILTER (WHERE NOT ultimo_dia_do_mes)
                    OVER (PARTITION BY sk_loja, setor, ano, mes), 0)
            ELSE valor_arredondado
       END AS valor_meta_dia
FROM repartida;

CREATE OR REPLACE VIEW dw.vw_meta_vendedor_diaria AS
WITH repartida AS (
    SELECT p.sk_tempo, p.data, p.ultimo_dia_do_mes, m.sk_vendedor, m.valor_meta,
           ROUND(m.valor_meta * p.peso / p.peso_do_mes, 2) AS valor_arredondado,
           p.ano, p.mes
    FROM dw.fato_meta_vendedor m
    JOIN dw.dim_tempo tm ON tm.sk_tempo = m.sk_tempo
    JOIN dw.vw_peso_dia p ON p.ano = tm.ano AND p.mes = tm.mes
)
SELECT sk_tempo,
       data,
       sk_vendedor,
       CASE WHEN ultimo_dia_do_mes
            THEN valor_meta - COALESCE(
                SUM(valor_arredondado) FILTER (WHERE NOT ultimo_dia_do_mes)
                    OVER (PARTITION BY sk_vendedor, ano, mes), 0)
            ELSE valor_arredondado
       END AS valor_meta_dia
FROM repartida;

COMMENT ON VIEW dw.vw_meta_vendas_diaria IS 'Meta mensal por loja e setor repartida pelos dias (soma dos dias = meta do mês).';
COMMENT ON VIEW dw.vw_meta_vendedor_diaria IS 'Meta mensal por vendedor repartida pelos dias (soma dos dias = meta do mês).';
