-- Desempenho do vendedor por setor (Fase 5, preparação do simulador de troca de setor) e o
-- resultado do backtest do simulador. A tabela é recalculada por data de referência
-- (dw.gravar_desempenho_vendedor_setor) e lida pela view dw.vw_simulador_troca.

INSERT INTO etl.parametros_negocio (chave, valor, descricao) VALUES
    ('simulador_janela_dias', 365, 'Simulador de troca de setor: dias de histórico antes da referência.'),
    ('simulador_min_dias_historico', 30, 'Simulador: mínimo de dias lotado no setor para usar o histórico do próprio vendedor; abaixo disso vale o fallback.'),
    ('simulador_percentil', 0.25, 'Simulador: percentil da venda diária usado como base conservadora.'),
    ('simulador_dias_confianca_alta', 90, 'Simulador: dias lotado no setor a partir dos quais a confiança é alta.');

CREATE TABLE dw.desempenho_vendedor_setor (
    data_referencia      DATE           NOT NULL,   -- último dia de venda considerado
    sk_vendedor          INTEGER        NOT NULL REFERENCES dw.dim_vendedor (sk_vendedor),
    sk_loja              INTEGER        NOT NULL REFERENCES dw.dim_loja (sk_loja),
    setor                VARCHAR(30)    NOT NULL,
    lotado_na_referencia BOOLEAN        NOT NULL,   -- trabalha neste setor na data de referência
    dias_lotado          INTEGER        NOT NULL,   -- dias na janela em que esteve lotado no setor (com ou sem venda)
    dias_com_venda       INTEGER        NOT NULL,
    receita              NUMERIC(14, 2) NOT NULL,   -- receita líquida no setor nesses dias
    media_diaria         NUMERIC(14, 2),            -- receita / dias_lotado
    p25_diaria           NUMERIC(14, 2),            -- percentil da venda diária nos dias lotado (zeros incluídos)
    p25_fallback         NUMERIC(14, 2),            -- média do p25 dos vendedores lotados no setor (loja, senão rede)
    nivel_fallback       VARCHAR(5) CHECK (nivel_fallback IN ('loja', 'rede')),
    usa_fallback         BOOLEAN        NOT NULL,   -- menos de simulador_min_dias_historico dias lotado
    valor_conservador    NUMERIC(14, 2),            -- o que o simulador usa: p25 próprio ou fallback
    confianca            VARCHAR(14)    NOT NULL CHECK (confianca IN
                             ('alta', 'media', 'baixa', 'muito_baixa', 'sem_base')),
    media_loja_setor     NUMERIC(14, 2),            -- receita diária média do setor na loja na janela
    calculado_em         TIMESTAMP      NOT NULL DEFAULT now(),
    PRIMARY KEY (data_referencia, sk_vendedor, setor)
);
CREATE INDEX ix_desempenho_vendedor_setor_loja ON dw.desempenho_vendedor_setor (data_referencia, sk_loja, setor);

-- Backtest do simulador: cada linha é um método avaliado sobre um conjunto de eventos (trocas
-- reais ou trocas fictícias do grupo placebo) e um horizonte, em semanas.
CREATE TABLE dw.simulador_backtest (
    sk_simulador_backtest  BIGINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    grupo                  VARCHAR(10)   NOT NULL CHECK (grupo IN ('trocas', 'placebo')),
    metodo                 VARCHAR(30)   NOT NULL,
    horizonte_dias         INTEGER       NOT NULL,
    eventos                INTEGER       NOT NULL,
    semanas                INTEGER       NOT NULL,
    cobertura_conservadora NUMERIC(6, 4) NOT NULL,  -- semanas em que o real ficou igual ou acima do projetado
    wape                   NUMERIC(8, 4) NOT NULL,   -- soma dos erros absolutos semanais / soma do real
    vies                   NUMERIC(8, 4) NOT NULL,   -- soma do projetado / soma do real - 1
    gerado_em              TIMESTAMP     NOT NULL DEFAULT now()
);

COMMENT ON TABLE dw.desempenho_vendedor_setor IS 'Venda diária conservadora (percentil 25) de cada vendedor em cada setor, sobre os dias lotado, com fallback e confiança.';
COMMENT ON TABLE dw.simulador_backtest IS 'Resultado do backtest do simulador de troca de setor por método, grupo e horizonte.';
