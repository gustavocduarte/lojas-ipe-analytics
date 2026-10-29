-- Ajustes do dw para o ETL (linhagem e idempotência) e tabelas de contagem por carga.

-- Linhagem das vendas: de qual arquivo/linha e de qual carga veio cada item.
ALTER TABLE dw.fato_vendas ADD COLUMN arquivo_origem VARCHAR(100);
ALTER TABLE dw.fato_vendas ADD COLUMN linha_origem INTEGER;
ALTER TABLE dw.fato_vendas ADD COLUMN id_carga BIGINT;
ALTER TABLE dw.fato_despesas ADD COLUMN id_carga BIGINT;

-- Despesa não tem chave natural no ERP (o mesmo documento pode aparecer duas vezes, e isso é
-- um sinal para a Fase 3): a linha é identificada pelo arquivo e pela posição nele.
CREATE UNIQUE INDEX ux_fato_despesas_origem ON dw.fato_despesas (arquivo_origem, linha_origem);
CREATE INDEX ix_fato_vendas_origem ON dw.fato_vendas (arquivo_origem);

-- Contagens por entidade em cada carga (lidas = rejeitadas + carregadas).
CREATE TABLE etl.carga_tabelas (
    id_carga     BIGINT      NOT NULL REFERENCES etl.cargas (id_carga),
    entidade     VARCHAR(30) NOT NULL,
    lidas        INTEGER     NOT NULL,  -- linhas do staging nesta carga
    rejeitadas   INTEGER     NOT NULL,
    carregadas   INTEGER     NOT NULL,  -- válidas e aplicadas ao dw
    inseridas    INTEGER     NOT NULL,
    atualizadas  INTEGER     NOT NULL,  -- existiam e mudaram
    sem_alteracao INTEGER    NOT NULL,  -- existiam e já estavam iguais
    removidas    INTEGER     NOT NULL DEFAULT 0,  -- linhas do mesmo arquivo que saíram dele
    PRIMARY KEY (id_carga, entidade),
    CONSTRAINT ck_carga_tabelas_soma CHECK (lidas = rejeitadas + carregadas),
    CONSTRAINT ck_carga_tabelas_destino
        CHECK (carregadas = inseridas + atualizadas + sem_alteracao)
);

-- Quantas células foram corrigidas, por entidade, coluna e tipo de problema.
CREATE TABLE etl.carga_correcoes (
    id_carga       BIGINT       NOT NULL REFERENCES etl.cargas (id_carga),
    entidade       VARCHAR(30)  NOT NULL,
    coluna         VARCHAR(40)  NOT NULL,
    tipo_problema  VARCHAR(40)  NOT NULL,
    quantidade     INTEGER      NOT NULL CHECK (quantidade > 0),
    PRIMARY KEY (id_carga, entidade, coluna, tipo_problema)
);

COMMENT ON TABLE etl.carga_tabelas IS 'Linhas lidas, rejeitadas e carregadas por entidade em cada carga.';
COMMENT ON TABLE etl.carga_correcoes IS 'Células corrigidas na limpeza, por tipo de problema.';
