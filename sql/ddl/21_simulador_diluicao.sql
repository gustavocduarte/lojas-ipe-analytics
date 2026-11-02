-- Simulador v2: ajuste de diluição (quem entra no setor divide a venda com a equipe lotada) e a
-- métrica do backtest sobre o total do horizonte.

INSERT INTO etl.parametros_negocio (chave, valor, descricao) VALUES
    ('simulador_aplica_diluicao', 1, 'Simulador v2: 1 = multiplica a fatia de quem não está lotado no destino por n/(n+1), n = lotados atuais; 0 = sem ajuste.');

ALTER TABLE dw.simulador_backtest
    ADD COLUMN escala   VARCHAR(7) NOT NULL DEFAULT 'semanal' CHECK (escala IN ('semanal', 'total')),
    ADD COLUMN diluicao BOOLEAN;   -- o v2 foi avaliado com o ajuste de diluição

ALTER TABLE dw.desempenho_vendedor_setor
    ADD COLUMN lotados_no_setor INTEGER,         -- outros vendedores ativos lotados no setor, na loja
    ADD COLUMN fator_diluicao   NUMERIC(6, 4);   -- n/(n+1) para quem não está lotado; 1 nos demais

COMMENT ON COLUMN dw.desempenho_vendedor_setor.fator_diluicao IS 'Multiplicador da fatia na projeção: n/(n+1) para quem ainda não está lotado no setor (divide a venda com a equipe), 1 para quem já está ou se ninguém está lotado.';
