-- Fase 4: projeções de fechamento para o Power BI, no dia de referência padrão (último dia com
-- venda). Para simular outro corte, chame as funções dw.fn_projecao_* direto com a data.
-- Reaplicáveis: CREATE OR REPLACE VIEW.

CREATE OR REPLACE VIEW dw.vw_projecao_fechamento_mes AS
SELECT * FROM dw.fn_projecao_fechamento_mes(dw.data_referencia());

CREATE OR REPLACE VIEW dw.vw_projecao_despesas_ano AS
SELECT * FROM dw.fn_projecao_despesas_ano(dw.data_referencia());

COMMENT ON VIEW dw.vw_projecao_fechamento_mes IS 'Fechamento do mês de referência por loja e setor: realizado + previsto dos dias restantes.';
COMMENT ON VIEW dw.vw_projecao_despesas_ano IS 'Fechamento do ano de despesas por centro: realizado até a referência + orçado restante x fator.';
