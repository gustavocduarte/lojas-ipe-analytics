-- Schemas do data warehouse Lojas Ipê.
--   stg : staging, dados crus (tudo texto) exatamente como vieram dos CSVs do ERP
--   dw  : modelo dimensional (esquema estrela), com tipos corretos

CREATE SCHEMA IF NOT EXISTS stg;
CREATE SCHEMA IF NOT EXISTS dw;

COMMENT ON SCHEMA stg IS 'Staging: dados crus das exportações do ERP, em texto.';
COMMENT ON SCHEMA dw IS 'Modelo dimensional (esquema estrela) de vendas, metas e despesas.';
