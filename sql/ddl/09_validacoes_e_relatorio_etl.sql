-- Resultado das validações, sinais de negócio e relatório de qualidade de cada carga.
--
-- Validações ESTRUTURAIS bloqueiam a carga (reprovada: o dw volta ao estado anterior).
-- Sinais de NEGÓCIO não bloqueiam: os dados entram no dw e só são contados para a Fase 3.

CREATE TABLE etl.parametros_negocio (
    chave      VARCHAR(40)  PRIMARY KEY,
    valor      NUMERIC      NOT NULL,
    descricao  VARCHAR(200) NOT NULL
);

INSERT INTO etl.parametros_negocio (chave, valor, descricao) VALUES
    ('desconto_maximo', 0.18, 'Desconto máximo permitido por item, como fração do valor bruto.'),
    ('tolerancia_desconto', 0.01, 'Folga em R$ no teste de desconto, por causa de arredondamento.'),
    ('cancelamento_multiplo', 3, 'Vendedor com taxa de cancelamento acima de N vezes a da rede.'),
    ('cancelamento_min_cupons', 100, 'Mínimo de cupons do vendedor para avaliar a taxa.'),
    ('valor_atipico_multiplo', 5, 'Despesa acima de N vezes a mediana do seu centro de custo.'),
    ('orcado_excesso_multiplo', 1.3, 'Centro/mês com despesa acima de N vezes o orçado.');

CREATE TABLE etl.carga_validacoes (
    id_carga    BIGINT       NOT NULL REFERENCES etl.cargas (id_carga),
    validacao   VARCHAR(60)  NOT NULL,
    ok          BOOLEAN      NOT NULL,
    quantidade  BIGINT       NOT NULL,   -- ocorrências com problema (0 = tudo certo)
    detalhe     TEXT,
    PRIMARY KEY (id_carga, validacao)
);

CREATE TABLE etl.carga_sinais (
    id_carga    BIGINT       NOT NULL REFERENCES etl.cargas (id_carga),
    sinal       VARCHAR(60)  NOT NULL,
    unidade     VARCHAR(20)  NOT NULL,   -- o que está sendo contado (itens, cupons, ...)
    quantidade  BIGINT       NOT NULL,
    descricao   VARCHAR(200) NOT NULL,
    PRIMARY KEY (id_carga, sinal)
);

CREATE TABLE etl.relatorios_qualidade (
    id_carga    BIGINT       PRIMARY KEY REFERENCES etl.cargas (id_carga),
    gerado_em   TIMESTAMP    NOT NULL DEFAULT now(),
    relatorio   JSONB        NOT NULL
);

COMMENT ON TABLE etl.parametros_negocio IS 'Limites das regras de negócio usadas nos sinais.';
COMMENT ON TABLE etl.carga_validacoes IS 'Validações estruturais de cada carga (falha = carga reprovada).';
COMMENT ON TABLE etl.carga_sinais IS 'Sinais de negócio contados no dw (não bloqueiam a carga).';
COMMENT ON TABLE etl.relatorios_qualidade IS 'Relatório de qualidade de cada carga, em JSON.';
