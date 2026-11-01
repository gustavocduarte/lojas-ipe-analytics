-- Simulador v2: base em fatia semanal do setor na loja (com encolhimento) no lugar do percentil 25
-- da venda diária. Parâmetros, resultado do backtest v2 e a curva percentil x cobertura.

INSERT INTO etl.parametros_negocio (chave, valor, descricao) VALUES
    ('simulador_k_encolhimento', 4, 'Simulador v2: peso (em semanas) da fatia média dos lotados no encolhimento da fatia do vendedor; escolhido pelo backtest.'),
    ('simulador_percentil_fatia', 0.05, 'Simulador v2: percentil da distribuição das fatias semanais usado como projeção conservadora; escolhido pelo backtest (cobertura perto de 75%).'),
    ('simulador_semanas_confianca_alta', 13, 'Simulador v2: semanas lotado no setor a partir das quais a confiança é alta.'),
    ('simulador_semanas_confianca_media', 5, 'Simulador v2: semanas lotado no setor a partir das quais a confiança é média.');

ALTER TABLE dw.simulador_backtest
    ADD COLUMN versao      VARCHAR(2)    NOT NULL DEFAULT 'v1' CHECK (versao IN ('v1', 'v2')),
    ADD COLUMN k           NUMERIC(6, 2),   -- encolhimento usado (só v2)
    ADD COLUMN percentil   NUMERIC(4, 2);   -- percentil do conservador (só v2)

-- Cobertura, WAPE e viés da projeção conservadora do v2 para cada percentil.
CREATE TABLE dw.simulador_backtest_curva (
    sk_curva               BIGINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    grupo                  VARCHAR(10)   NOT NULL CHECK (grupo IN ('trocas', 'placebo')),
    horizonte_dias         INTEGER       NOT NULL,
    percentil              NUMERIC(4, 2) NOT NULL,
    k                      NUMERIC(6, 2) NOT NULL,
    eventos                INTEGER       NOT NULL,
    semanas                INTEGER       NOT NULL,
    cobertura_conservadora NUMERIC(6, 4) NOT NULL,
    wape                   NUMERIC(8, 4) NOT NULL,
    vies                   NUMERIC(8, 4) NOT NULL,
    gerado_em              TIMESTAMP     NOT NULL DEFAULT now(),
    UNIQUE (grupo, horizonte_dias, percentil)
);

-- Fatia semanal por vendedor e setor (recalculada junto com o desempenho, por data de referência).
ALTER TABLE dw.desempenho_vendedor_setor
    ADD COLUMN fatia_semanas       INTEGER,         -- n: semanas inteiras lotado no setor, com venda do setor na loja
    ADD COLUMN fatia_propria       NUMERIC(9, 6),   -- média das fatias semanais do vendedor
    ADD COLUMN fatia_media_loja    NUMERIC(9, 6),   -- média das fatias dos outros lotados (loja; senão rede)
    ADD COLUMN nivel_fatia         VARCHAR(5) CHECK (nivel_fatia IN ('loja', 'rede')),
    ADD COLUMN fatia_central       NUMERIC(9, 6),   -- (n x própria + k x média) / (n + k)
    ADD COLUMN fatia_conservadora  NUMERIC(9, 6),   -- percentil da distribuição das fatias já encolhidas
    ADD COLUMN k_encolhimento      NUMERIC(6, 2),
    ADD COLUMN percentil_fatia     NUMERIC(4, 2),
    ADD COLUMN confianca_fatia     VARCHAR(14) CHECK (confianca_fatia IN
                                       ('alta', 'media', 'baixa', 'muito_baixa', 'sem_base'));

COMMENT ON TABLE dw.simulador_backtest_curva IS 'Curva percentil x cobertura x WAPE x viés da projeção conservadora do simulador v2.';
COMMENT ON COLUMN dw.desempenho_vendedor_setor.fatia_central IS 'Fatia semanal esperada do vendedor no setor da loja, encolhida para a média dos lotados.';
