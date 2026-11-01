-- Simulador de troca de setor: projeção diária de cada vendedor ativo em cada setor de destino,
-- para os dias previstos depois da referência. Base conservadora do vendedor (percentil 25 dos dias
-- lotado, ou o fallback da loja/rede se tiver pouco histórico), ajustada pela sazonalidade da
-- previsão (previsto do dia ÷ média diária recente do setor na loja) e limitada pela demanda
-- prevista do setor na loja que sobra depois dos outros vendedores lotados nele.
-- O Power BI filtra por vendedor e setor de destino e soma os dias do mês.

CREATE OR REPLACE VIEW dw.vw_simulador_troca AS
WITH ref AS (SELECT max(data_referencia) AS data_referencia FROM dw.desempenho_vendedor_setor),
ultima AS (
    SELECT versao_modelo, treino_ate FROM dw.previsao_vendas
    WHERE nivel = 'loja_setor' AND granularidade = 'dia'
    ORDER BY treino_ate DESC, gerado_em DESC LIMIT 1),
prev AS (
    SELECT p.sk_loja, p.setor, p.data, p.valor_previsto
    FROM dw.previsao_vendas p JOIN ultima u USING (versao_modelo, treino_ate)
    WHERE p.nivel = 'loja_setor' AND p.granularidade = 'dia'),
base AS (
    SELECT d.* FROM dw.desempenho_vendedor_setor d JOIN ref USING (data_referencia)),
colegas AS (  -- o que os outros vendedores lotados no setor, na loja, costumam vender por dia
    SELECT b.sk_loja, b.setor, b.sk_vendedor,
           COALESCE(sum(o.media_diaria) FILTER (WHERE o.sk_vendedor <> b.sk_vendedor), 0) AS media_dos_outros
    FROM base b
    LEFT JOIN base o ON o.sk_loja = b.sk_loja AND o.setor = b.setor AND o.lotado_na_referencia
    GROUP BY b.sk_loja, b.setor, b.sk_vendedor),
projetado AS (
    SELECT b.*, p.data AS dia, p.valor_previsto,
           p.valor_previsto / NULLIF(b.media_loja_setor, 0) AS fator_sazonal,
           c.media_dos_outros
    FROM base b
    JOIN colegas c ON c.sk_vendedor = b.sk_vendedor AND c.setor = b.setor
    JOIN prev p ON p.sk_loja = b.sk_loja AND p.setor = b.setor AND p.data > b.data_referencia
    WHERE b.valor_conservador IS NOT NULL AND b.media_loja_setor > 0)
SELECT pr.data_referencia, pr.sk_vendedor, v.cod_vendedor, v.nome_vendedor, pr.sk_loja,
       pr.setor AS setor_destino, pr.lotado_na_referencia AS eh_o_setor_atual, pr.dias_lotado,
       pr.usa_fallback, pr.nivel_fallback, pr.confianca, pr.valor_conservador AS base_conservadora,
       pr.dia, pr.valor_previsto AS demanda_prevista, pr.fator_sazonal,
       GREATEST(pr.valor_previsto - pr.media_dos_outros * pr.fator_sazonal, 0) AS demanda_restante,
       LEAST(pr.valor_conservador * pr.fator_sazonal,
             GREATEST(pr.valor_previsto - pr.media_dos_outros * pr.fator_sazonal, 0)) AS projecao_dia
FROM projetado pr
JOIN dw.dim_vendedor v ON v.sk_vendedor = pr.sk_vendedor;

COMMENT ON VIEW dw.vw_simulador_troca IS 'Projeção diária conservadora de cada vendedor em cada setor de destino (base, sazonalidade e teto de demanda).';
