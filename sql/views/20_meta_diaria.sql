-- Fase 4: meta mensal repartida pelos dias do mês (base do acompanhamento diário do Power BI).
-- Reaplicáveis: CREATE OR REPLACE VIEW.
--
-- Meta de loja x setor: usa o peso do calendário comercial (etl.pesos_calendario: eventos, Natal, setor);
-- sem linha ali, cai no peso simples = dia da semana x (peso do feriado, se for feriado nacional). A meta do
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
    SELECT p.sk_tempo, p.data, p.ultimo_dia_do_mes, m.sk_loja, m.setor, m.valor_meta, p.ano, p.mes,
           -- peso do calendário comercial (ou o simples, sem linha na tabela); zero antes da abertura
           CASE WHEN p.data < l.data_abertura THEN 0 ELSE COALESCE(pc.peso, p.peso) END AS peso_dia
    FROM dw.fato_meta_vendas m
    JOIN dw.dim_tempo tm ON tm.sk_tempo = m.sk_tempo
    JOIN dw.vw_peso_dia p ON p.ano = tm.ano AND p.mes = tm.mes
    JOIN dw.dim_loja l ON l.sk_loja = m.sk_loja
    LEFT JOIN etl.pesos_calendario pc ON pc.data = p.data AND pc.setor = m.setor
), com_total AS (
    SELECT *, SUM(peso_dia) OVER (PARTITION BY sk_loja, setor, ano, mes) AS peso_total FROM repartida
), arredondada AS (
    SELECT *, ROUND(valor_meta * peso_dia / NULLIF(peso_total, 0), 2) AS valor_arredondado FROM com_total
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
FROM arredondada;

-- A meta do vendedor segue a curva diária da meta da loja (mesmos eventos, mesma abertura); sem meta
-- de loja no mês, usa os pesos simples.
CREATE OR REPLACE VIEW dw.vw_meta_vendedor_diaria AS
WITH loja_dia AS (
    SELECT sk_loja, data,
           SUM(valor_meta_dia) / NULLIF(SUM(SUM(valor_meta_dia)) OVER (
               PARTITION BY sk_loja, date_trunc('month', data)), 0) AS fracao
    FROM dw.vw_meta_vendas_diaria
    GROUP BY sk_loja, data
), repartida AS (
    SELECT p.sk_tempo, p.data, p.ultimo_dia_do_mes, m.sk_vendedor, m.valor_meta,
           ROUND(m.valor_meta * COALESCE(ld.fracao, p.peso / p.peso_do_mes), 2) AS valor_arredondado,
           p.ano, p.mes
    FROM dw.fato_meta_vendedor m
    JOIN dw.dim_tempo tm ON tm.sk_tempo = m.sk_tempo
    JOIN dw.vw_peso_dia p ON p.ano = tm.ano AND p.mes = tm.mes
    JOIN dw.dim_vendedor v ON v.sk_vendedor = m.sk_vendedor
    LEFT JOIN loja_dia ld ON ld.sk_loja = v.sk_loja AND ld.data = p.data
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
