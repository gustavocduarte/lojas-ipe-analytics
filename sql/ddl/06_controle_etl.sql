-- Controle do ETL (Fase 2): cargas, arquivos lidos e linhas rejeitadas.
-- Cada execução do ETL recebe um id_carga; as linhas de staging carregadas nela o guardam.

CREATE SCHEMA IF NOT EXISTS etl;
COMMENT ON SCHEMA etl IS 'Controle do ETL: cargas, arquivos, relatório de qualidade e funções de limpeza.';

CREATE TABLE etl.cargas (
    id_carga   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fonte      VARCHAR(60)  NOT NULL,
    modo       VARCHAR(12)  NOT NULL CHECK (modo IN ('incremental', 'completo')),
    inicio     TIMESTAMP    NOT NULL DEFAULT now(),
    fim        TIMESTAMP,
    status     VARCHAR(14)  NOT NULL DEFAULT 'em_andamento'
        CHECK (status IN ('em_andamento', 'concluida', 'reprovada', 'erro')),
    mensagem   TEXT,
    CONSTRAINT ck_cargas_fim CHECK (fim IS NULL OR fim >= inicio)
);

-- Um registro por arquivo visto em cada carga ('carregado' = lido para o staging;
-- 'inalterado' = mesmo conteúdo da última carga bem-sucedida, não relido).
CREATE TABLE etl.carga_arquivos (
    id_carga         BIGINT       NOT NULL REFERENCES etl.cargas (id_carga),
    entidade         VARCHAR(30)  NOT NULL,
    arquivo          VARCHAR(200) NOT NULL,
    hash_arquivo     CHAR(64)     NOT NULL,   -- SHA-256 do conteúdo
    linhas_lidas     INTEGER      NOT NULL,
    linhas_ignoradas INTEGER      NOT NULL DEFAULT 0,
    situacao         VARCHAR(12)  NOT NULL CHECK (situacao IN ('carregado', 'inalterado')),
    PRIMARY KEY (id_carga, entidade, arquivo)
);

-- Último conteúdo de cada arquivo já levado ao dw com sucesso: base da carga incremental.
CREATE TABLE etl.arquivos_processados (
    fonte         VARCHAR(60)  NOT NULL,
    entidade      VARCHAR(30)  NOT NULL,
    arquivo       VARCHAR(200) NOT NULL,
    hash_arquivo  CHAR(64)     NOT NULL,
    id_carga      BIGINT       NOT NULL REFERENCES etl.cargas (id_carga),
    linhas        INTEGER      NOT NULL,
    PRIMARY KEY (fonte, entidade, arquivo)
);

-- Toda linha que não pode ser corrigida vem para cá, com o motivo. Nunca se descarta em silêncio.
CREATE TABLE stg.rejeitados (
    id_rejeicao     BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_carga        BIGINT       NOT NULL REFERENCES etl.cargas (id_carga),
    entidade        VARCHAR(30)  NOT NULL,
    arquivo_origem  VARCHAR(200) NOT NULL,
    linha_origem    INTEGER      NOT NULL,
    coluna          VARCHAR(40)  NOT NULL,
    valor_original  TEXT,
    motivo          VARCHAR(80)  NOT NULL,
    rejeitado_em    TIMESTAMP    NOT NULL DEFAULT now()
);

CREATE INDEX ix_rejeitados_carga   ON stg.rejeitados (id_carga, entidade);
CREATE INDEX ix_rejeitados_arquivo ON stg.rejeitados (arquivo_origem, linha_origem);

-- Cada tabela de staging guarda a carga que trouxe a linha e é consultada por arquivo.
ALTER TABLE stg.lojas              ADD COLUMN id_carga BIGINT;
ALTER TABLE stg.horarios_loja      ADD COLUMN id_carga BIGINT;
ALTER TABLE stg.produtos           ADD COLUMN id_carga BIGINT;
ALTER TABLE stg.centros_custo      ADD COLUMN id_carga BIGINT;
ALTER TABLE stg.feriados           ADD COLUMN id_carga BIGINT;
ALTER TABLE stg.formas_pagamento   ADD COLUMN id_carga BIGINT;
ALTER TABLE stg.campanhas          ADD COLUMN id_carga BIGINT;
ALTER TABLE stg.vendedores         ADD COLUMN id_carga BIGINT;
ALTER TABLE stg.clientes           ADD COLUMN id_carga BIGINT;
ALTER TABLE stg.vendas             ADD COLUMN id_carga BIGINT;
ALTER TABLE stg.metas_vendas       ADD COLUMN id_carga BIGINT;
ALTER TABLE stg.metas_vendedor     ADD COLUMN id_carga BIGINT;
ALTER TABLE stg.despesas           ADD COLUMN id_carga BIGINT;
ALTER TABLE stg.orcamento_despesas ADD COLUMN id_carga BIGINT;

CREATE INDEX ix_stg_vendas_arquivo   ON stg.vendas (arquivo_origem);
CREATE INDEX ix_stg_vendas_carga     ON stg.vendas (id_carga);
CREATE INDEX ix_stg_despesas_arquivo ON stg.despesas (arquivo_origem);
CREATE INDEX ix_stg_despesas_carga   ON stg.despesas (id_carga);

COMMENT ON TABLE etl.cargas IS 'Uma linha por execução do ETL, com início, fim e status.';
COMMENT ON TABLE etl.carga_arquivos IS 'Arquivos vistos em cada carga e linhas lidas de cada um.';
COMMENT ON TABLE etl.arquivos_processados IS 'Último conteúdo (hash) de cada arquivo já levado ao dw.';
COMMENT ON TABLE stg.rejeitados IS 'Linhas rejeitadas na limpeza/validação, com coluna, valor e motivo.';
