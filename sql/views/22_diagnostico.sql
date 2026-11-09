-- Painel de diagnóstico da loja (Power BI). Reaplicáveis: CREATE OR REPLACE VIEW.

-- Limites do diagnóstico, lidos de etl.parametros_negocio.
CREATE OR REPLACE VIEW dw.vw_parametros_diagnostico AS
SELECT chave, valor::float8 AS valor, descricao
FROM etl.parametros_negocio
WHERE chave LIKE 'diag\_%';

-- Referência da rede por dia, SEM loja: o Power BI calcula as médias da rede (ticket médio, desconto
-- médio) daqui, e não de CALCULATE(..., ALL(Lojas)), porque com segurança por loja (RLS) o gerente só
-- enxerga a própria loja e a "rede" viraria a loja dele. Sem setor de propósito: um cupom pode ter itens
-- de vários setores, então cupons por setor não somam. Só vendas concluídas, como as medidas.
CREATE OR REPLACE VIEW dw.vw_referencia_rede_dia AS
SELECT f.sk_tempo,
       t.data,
       SUM(f.receita_liquida)::float8                  AS receita,
       COUNT(DISTINCT f.numero_cupom)                  AS cupons,
       SUM(f.quantidade)                               AS unidades,
       SUM(f.desconto)::float8                         AS desconto,
       SUM(f.preco_unitario * f.quantidade)::float8    AS receita_bruta,
       SUM(f.custo)::float8                            AS custo
FROM dw.fato_vendas f
JOIN dw.dim_tempo t USING (sk_tempo)
WHERE f.status = 'Concluída'
GROUP BY f.sk_tempo, t.data;

COMMENT ON VIEW dw.vw_parametros_diagnostico IS 'Limites do painel de diagnóstico da loja (chaves diag_* de etl.parametros_negocio).';
COMMENT ON VIEW dw.vw_referencia_rede_dia IS 'Totais da rede por dia (concluídas), sem loja: referência de ticket, desconto e margem da rede, pronta para RLS por loja.';
