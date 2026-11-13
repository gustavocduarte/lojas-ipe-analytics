-- Cores do relatório Power BI, lidas de etl.parametros_cores. Reaplicável: CREATE OR REPLACE VIEW.
CREATE OR REPLACE VIEW dw.vw_parametros_cores AS
SELECT chave, cor, descricao
FROM etl.parametros_cores;

COMMENT ON VIEW dw.vw_parametros_cores IS 'Cores do relatório Power BI (chave, #RRGGBB, descrição), de etl.parametros_cores.';
