-- Fase 3: alertas persistentes de anomalia.
--
-- Os "sinais de negócio" da Fase 2 só contam ocorrências. Aqui cada ocorrência vira um alerta
-- com chave estável (não duplica entre cargas), explicação legível, severidade e um status de
-- tratamento que as cargas seguintes nunca sobrescrevem. As regras são funções SQL
-- (sql/procedures/7x_*.sql) e todos os limites ficam em etl.parametros_negocio.

CREATE TABLE dw.dim_tipo_alerta (
    tipo_alerta  VARCHAR(50)  PRIMARY KEY,
    nome         VARCHAR(80)  NOT NULL,
    categoria    VARCHAR(10)  NOT NULL CHECK (categoria IN ('vendas', 'despesas')),
    descricao    VARCHAR(300) NOT NULL
);

-- Quais regras existem, em que ordem rodam (derivadas por último) e se estão ligadas.
CREATE TABLE etl.regras_alerta (
    tipo_alerta  VARCHAR(50) PRIMARY KEY REFERENCES dw.dim_tipo_alerta (tipo_alerta),
    versao       INTEGER     NOT NULL DEFAULT 1,
    ordem        INTEGER     NOT NULL,
    ativa        BOOLEAN     NOT NULL DEFAULT TRUE
);

CREATE TABLE dw.alertas (
    sk_alerta        BIGINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    chave_alerta     VARCHAR(200)  NOT NULL UNIQUE,   -- tipo|identificador natural (estável entre cargas)
    tipo_alerta      VARCHAR(50)   NOT NULL REFERENCES dw.dim_tipo_alerta (tipo_alerta),
    severidade       VARCHAR(10)   NOT NULL CHECK (severidade IN ('baixa', 'media', 'alta', 'critica')),
    sk_tempo         INTEGER       REFERENCES dw.dim_tempo (sk_tempo),
    sk_loja          INTEGER       REFERENCES dw.dim_loja (sk_loja),
    sk_vendedor      INTEGER       REFERENCES dw.dim_vendedor (sk_vendedor),
    sk_centro_custo  INTEGER       REFERENCES dw.dim_centro_custo (sk_centro_custo),
    valor_envolvido  NUMERIC(14, 2),
    regra            VARCHAR(80)   NOT NULL,          -- ex.: desconto_acima_limite@1
    explicacao       TEXT          NOT NULL,
    detalhe          JSONB         NOT NULL DEFAULT '{}'::JSONB,
    id_carga_origem  BIGINT        NOT NULL REFERENCES etl.cargas (id_carga),
    id_carga_ultima  BIGINT        NOT NULL REFERENCES etl.cargas (id_carga),
    vigente          BOOLEAN       NOT NULL DEFAULT TRUE,   -- FALSE: a regra deixou de detectá-lo
    independente     BOOLEAN       NOT NULL DEFAULT TRUE,   -- FALSE: derivado de outros alertas
    status           VARCHAR(15)   NOT NULL DEFAULT 'novo'
        CHECK (status IN ('novo', 'em_analise', 'resolvido', 'falso_positivo')),
    status_em        TIMESTAMP,
    tratado_por      VARCHAR(80),
    observacao       TEXT,
    criado_em        TIMESTAMP     NOT NULL DEFAULT now(),
    atualizado_em    TIMESTAMP     NOT NULL DEFAULT now()
);

-- Alerta derivado -> alertas de origem que explicam (no todo ou em parte) o valor dele.
CREATE TABLE dw.alerta_vinculos (
    sk_alerta_derivado  BIGINT         NOT NULL REFERENCES dw.alertas (sk_alerta) ON DELETE CASCADE,
    sk_alerta_origem    BIGINT         NOT NULL REFERENCES dw.alertas (sk_alerta) ON DELETE CASCADE,
    contribuicao        NUMERIC(14, 2) NOT NULL,   -- quanto do excesso vem desta origem, em R$
    PRIMARY KEY (sk_alerta_derivado, sk_alerta_origem),
    CONSTRAINT ck_alerta_vinculo_distintos CHECK (sk_alerta_derivado <> sk_alerta_origem)
);

-- Toda mudança de status (quem, quando, de onde para onde).
CREATE TABLE dw.alerta_historico (
    sk_historico     BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sk_alerta        BIGINT       NOT NULL REFERENCES dw.alertas (sk_alerta),
    status_anterior  VARCHAR(15)  NOT NULL,
    status_novo      VARCHAR(15)  NOT NULL,
    usuario          VARCHAR(80)  NOT NULL,
    observacao       TEXT,
    em               TIMESTAMP    NOT NULL DEFAULT now()
);

-- O que cada geração de alertas fez, por tipo.
CREATE TABLE etl.carga_alertas (
    id_carga              BIGINT      NOT NULL REFERENCES etl.cargas (id_carga),
    tipo_alerta           VARCHAR(50) NOT NULL,
    detectados            INTEGER     NOT NULL,
    novos                 INTEGER     NOT NULL,
    atualizados           INTEGER     NOT NULL,   -- já existiam e mudaram (valor, texto, severidade)
    inalterados           INTEGER     NOT NULL,
    reativados            INTEGER     NOT NULL,   -- estavam não vigentes e voltaram a ser detectados
    deixaram_de_vigorar   INTEGER     NOT NULL,
    PRIMARY KEY (id_carga, tipo_alerta)
);

-- Tipo de despesa esperado para uma descrição, quando o aprendizado estatístico não serve.
CREATE TABLE etl.excecoes_centro_descricao (
    descricao       VARCHAR(200) PRIMARY KEY,
    tipo_esperado   VARCHAR(20)  NOT NULL
        CHECK (tipo_esperado IN ('Pessoal', 'Terceiros', 'Discricionárias'))
);

CREATE INDEX ix_alertas_tipo      ON dw.alertas (tipo_alerta, vigente);
CREATE INDEX ix_alertas_tempo     ON dw.alertas (sk_tempo);
CREATE INDEX ix_alertas_loja      ON dw.alertas (sk_loja) WHERE sk_loja IS NOT NULL;
CREATE INDEX ix_alertas_vendedor  ON dw.alertas (sk_vendedor) WHERE sk_vendedor IS NOT NULL;
CREATE INDEX ix_alertas_centro    ON dw.alertas (sk_centro_custo) WHERE sk_centro_custo IS NOT NULL;
CREATE INDEX ix_alertas_status    ON dw.alertas (status);
CREATE INDEX ix_alerta_vinculos_origem ON dw.alerta_vinculos (sk_alerta_origem);
CREATE INDEX ix_alerta_historico  ON dw.alerta_historico (sk_alerta);

COMMENT ON TABLE dw.alertas IS 'Alertas de anomalia: um por ocorrência, com chave estável e status de tratamento.';
COMMENT ON COLUMN dw.alertas.vigente IS 'FALSE quando a regra deixou de detectar o alerta (o status é preservado).';
COMMENT ON COLUMN dw.alertas.independente IS 'FALSE quando o alerta é consequência de outros (ver dw.alerta_vinculos).';
COMMENT ON TABLE dw.alerta_vinculos IS 'Liga alertas derivados aos alertas de origem, com a contribuição em R$.';
COMMENT ON TABLE dw.alerta_historico IS 'Histórico das mudanças de status dos alertas.';
COMMENT ON TABLE etl.regras_alerta IS 'Regras de alerta existentes, versão, ordem de execução e se estão ativas.';
COMMENT ON TABLE etl.excecoes_centro_descricao IS 'Exceções opcionais ao tipo dominante aprendido para cada descrição.';

-- Limites de todas as regras vivem aqui (nada fixo no código). Os que já existiam desde a Fase 2
-- (desconto_maximo, tolerancia_desconto, cancelamento_*, valor_atipico_multiplo,
-- orcado_excesso_multiplo) continuam valendo.
INSERT INTO etl.parametros_negocio (chave, valor, descricao) VALUES
    ('desconto_sev_media_pp', 0.05, 'Desconto: excesso sobre o limite, em fração do bruto, a partir do qual a severidade é média.'),
    ('desconto_sev_alta_pp', 0.10, 'Desconto: excesso sobre o limite a partir do qual a severidade é alta.');

INSERT INTO dw.dim_tipo_alerta (tipo_alerta, nome, categoria, descricao) VALUES
    ('desconto_acima_limite', 'Desconto acima do limite', 'vendas',
     'Item vendido com desconto maior que o máximo permitido sobre o valor bruto.');

INSERT INTO etl.regras_alerta (tipo_alerta, versao, ordem) VALUES ('desconto_acima_limite', 1, 10);
