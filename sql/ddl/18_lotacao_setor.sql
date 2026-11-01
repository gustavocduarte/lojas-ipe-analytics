-- Lotação do vendedor por setor, com histórico (Fase 5, preparação do simulador de troca de setor).
-- Tabela separada: dw.dim_vendedor continua como está (a mudança lenta tipo 2 fica para a Fase 7).
-- Cada linha é um período em que o vendedor trabalhou em um setor; data_fim vazia = período vigente.
-- Os períodos de um vendedor não se sobrepõem (conferido na carga e em etl.validar_estrutura).

-- Num banco novo o staging já nasceu em 04/06; num banco antigo ele é criado aqui.
CREATE TABLE IF NOT EXISTS stg.lotacao_setor (
    cod_vendedor TEXT, setor TEXT, data_inicio TEXT, data_fim TEXT, motivo TEXT,
    arquivo_origem TEXT, linha_origem INTEGER, carregado_em TIMESTAMP NOT NULL DEFAULT now(),
    id_carga BIGINT
);

CREATE TABLE dw.vendedor_setor_historico (
    sk_lotacao   INTEGER     GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sk_vendedor  INTEGER     NOT NULL REFERENCES dw.dim_vendedor (sk_vendedor),
    setor        VARCHAR(30) NOT NULL,   -- mesmo domínio de dw.dim_produto.setor
    data_inicio  DATE        NOT NULL,
    data_fim     DATE,                   -- NULL = período vigente
    motivo       VARCHAR(40),            -- Lotação inicial, Admissão, Troca de setor
    id_carga     BIGINT,
    CONSTRAINT uq_vendedor_setor_historico UNIQUE (sk_vendedor, data_inicio),
    CONSTRAINT ck_vendedor_setor_periodo CHECK (data_fim IS NULL OR data_fim >= data_inicio)
);
CREATE INDEX ix_vendedor_setor_historico_setor ON dw.vendedor_setor_historico (setor, data_inicio);

COMMENT ON TABLE dw.vendedor_setor_historico IS 'Setor de lotação de cada vendedor, um período por linha (histórico de trocas).';
