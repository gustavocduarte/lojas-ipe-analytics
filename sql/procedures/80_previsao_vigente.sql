-- (Fica em sql/procedures, e não em sql/ddl, porque é uma view que as funções de 81_projecoes.sql precisam ao serem criadas; é reaplicável.)
-- Previsão vigente: uma linha por (corte, grão), com a versão do modelo gerada mais recentemente
-- PARA CADA CORTE (treino_ate). Versões diferentes convivem no histórico (nada é apagado) e cortes
-- diferentes podem ter versões diferentes; quem lê a previsão usa esta view em vez de repetir a regra
-- (tabela Previsão do Power BI, dw.fn_projecao_fechamento_mes, dw.vw_simulador_troca).
CREATE OR REPLACE VIEW dw.vw_previsao_vigente AS
SELECT p.nivel, p.granularidade, p.data, p.sk_loja, p.setor, p.valor_previsto, p.valor_baixo,
       p.valor_alto, p.versao_modelo, p.treino_ate, p.wape_backtest, p.gerado_em
FROM dw.previsao_vendas p
JOIN (
    SELECT DISTINCT ON (treino_ate) treino_ate, versao_modelo
    FROM dw.previsao_vendas
    ORDER BY treino_ate, gerado_em DESC, versao_modelo DESC
) v ON v.treino_ate = p.treino_ate AND v.versao_modelo = p.versao_modelo;

COMMENT ON VIEW dw.vw_previsao_vigente IS 'Previsão de vendas da versão do modelo gerada mais recentemente em cada corte (treino_ate).';
