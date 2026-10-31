-- Fase 4 (ajuste): faixa baixa/alta da loja e da rede calibrada no próprio total.
--
-- A soma das faixas de cada loja e setor é mais larga que a faixa real do total (os erros se
-- compensam). Por isso dw.previsao_vendas passa a ter também linhas de nível 'loja' (soma dos
-- setores; setor NULL) e 'rede' (soma de tudo; sk_loja e setor NULL), com faixa calibrada nos
-- resíduos do backtest naquele nível. As linhas de nível 'loja_setor' continuam as de sempre.

ALTER TABLE dw.previsao_vendas
    ADD COLUMN nivel VARCHAR(10) NOT NULL DEFAULT 'loja_setor'
        CHECK (nivel IN ('loja_setor', 'loja', 'rede'));

ALTER TABLE dw.previsao_vendas ALTER COLUMN sk_loja DROP NOT NULL;
ALTER TABLE dw.previsao_vendas ALTER COLUMN setor DROP NOT NULL;

ALTER TABLE dw.previsao_vendas ADD CONSTRAINT ck_previsao_nivel CHECK (
    (nivel = 'loja_setor' AND sk_loja IS NOT NULL AND setor IS NOT NULL)
    OR (nivel = 'loja' AND sk_loja IS NOT NULL AND setor IS NULL)
    OR (nivel = 'rede' AND sk_loja IS NULL AND setor IS NULL)
);

ALTER TABLE dw.previsao_vendas DROP CONSTRAINT uq_previsao_vendas;
CREATE UNIQUE INDEX uq_previsao_vendas ON dw.previsao_vendas
    (nivel, granularidade, data, COALESCE(sk_loja, 0), COALESCE(setor, ''), versao_modelo, treino_ate);

COMMENT ON COLUMN dw.previsao_vendas.nivel IS 'loja_setor (série prevista), loja (soma dos setores) ou rede (soma de tudo); a faixa de loja e rede é calibrada no próprio nível.';
