-- Simulador de troca de setor (v2): projeção semanal de cada vendedor ativo em cada setor de destino,
-- para as semanas inteiras (7 dias contados a partir do dia seguinte à referência) previstas.
-- Projeção = fatia semanal do vendedor no setor x venda prevista do setor na loja na semana:
-- a previsão (decomposição) já traz a sazonalidade e limita a demanda do setor.
--   projecao_central       = fatia encolhida (média esperada)
--   projecao_conservadora  = percentil baixo da distribuição das fatias semanais
-- As duas já vêm multiplicadas por fator_diluicao: quem ainda não está lotado no setor divide a
-- venda com a equipe (n / (n + 1), n = lotados atuais); quem já está lá fica com 1.
-- confianca_fatia: alta (13 semanas ou mais lotado no setor), media (5 ou mais), baixa (poucas
-- semanas ou só a média da loja), muito_baixa (só a média da rede) ou sem_base.
-- O Power BI filtra por vendedor e setor de destino e soma as semanas do período.

DROP VIEW IF EXISTS dw.vw_simulador_troca;

CREATE VIEW dw.vw_simulador_troca AS
WITH ref AS (SELECT max(data_referencia) AS data_referencia FROM dw.desempenho_vendedor_setor),
ultima AS (
    SELECT versao_modelo, treino_ate FROM dw.previsao_vendas
    WHERE nivel = 'loja_setor' AND granularidade = 'dia'
    ORDER BY treino_ate DESC, gerado_em DESC LIMIT 1),
semanal AS (
    SELECT p.sk_loja, p.setor, (p.data - r.data_referencia - 1) / 7 + 1 AS semana,
           min(p.data) AS semana_inicio, sum(p.valor_previsto) AS demanda_prevista
    FROM dw.previsao_vendas p JOIN ultima u USING (versao_modelo, treino_ate)
    CROSS JOIN ref r
    WHERE p.nivel = 'loja_setor' AND p.granularidade = 'dia' AND p.data > r.data_referencia
    GROUP BY p.sk_loja, p.setor, (p.data - r.data_referencia - 1) / 7 + 1
    HAVING count(*) = 7)
SELECT d.data_referencia, d.sk_vendedor, v.cod_vendedor, v.nome_vendedor, d.sk_loja,
       d.setor AS setor_destino, d.lotado_na_referencia AS eh_o_setor_atual,
       d.fatia_semanas AS semanas_de_historico, d.nivel_fatia, d.confianca_fatia,
       d.fatia_central, d.fatia_conservadora, d.lotados_no_setor, d.fator_diluicao, s.semana, s.semana_inicio,
       s.demanda_prevista AS demanda_prevista_semana,
       d.fatia_central * d.fator_diluicao * s.demanda_prevista AS projecao_central,
       d.fatia_conservadora * d.fator_diluicao * s.demanda_prevista AS projecao_conservadora
FROM dw.desempenho_vendedor_setor d
JOIN ref ON ref.data_referencia = d.data_referencia
JOIN semanal s ON s.sk_loja = d.sk_loja AND s.setor = d.setor
JOIN dw.dim_vendedor v ON v.sk_vendedor = d.sk_vendedor
WHERE d.fatia_central IS NOT NULL;

COMMENT ON VIEW dw.vw_simulador_troca IS 'Projeção semanal do vendedor em cada setor de destino: fatia (central e conservadora) x venda prevista do setor na loja.';
