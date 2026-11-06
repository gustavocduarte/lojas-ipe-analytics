-- Área de venda da loja (m²), opcional: base da "venda por m²" no Power BI.
-- Migração para bancos que já têm o 02/04 (que agora já trazem a coluna): aqui só entra o que faltar.
ALTER TABLE dw.dim_loja ADD COLUMN IF NOT EXISTS area_m2 NUMERIC(9, 2) CHECK (area_m2 > 0);
ALTER TABLE stg.lojas ADD COLUMN IF NOT EXISTS area_m2 TEXT;
