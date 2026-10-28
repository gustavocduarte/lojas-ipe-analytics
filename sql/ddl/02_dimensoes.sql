-- Dimensões do esquema estrela. Chaves substitutas (sk_*) geradas pelo banco.
-- Sem dados pessoais sensíveis: nenhum CPF, telefone ou e-mail em lugar algum.

CREATE TABLE dw.dim_tempo (
    sk_tempo         INTEGER      PRIMARY KEY,            -- AAAAMMDD
    data             DATE         NOT NULL UNIQUE,
    dia              SMALLINT     NOT NULL CHECK (dia BETWEEN 1 AND 31),
    semana           SMALLINT     NOT NULL CHECK (semana BETWEEN 1 AND 53),  -- semana ISO
    mes              SMALLINT     NOT NULL CHECK (mes BETWEEN 1 AND 12),
    trimestre        SMALLINT     NOT NULL CHECK (trimestre BETWEEN 1 AND 4),
    ano              SMALLINT     NOT NULL,
    nome_mes         VARCHAR(15)  NOT NULL,
    nome_dia_semana  VARCHAR(15)  NOT NULL,
    feriado_nacional BOOLEAN      NOT NULL DEFAULT FALSE,
    nome_feriado     VARCHAR(60),
    CONSTRAINT ck_dim_tempo_feriado_nome CHECK (feriado_nacional OR nome_feriado IS NULL)
);

CREATE TABLE dw.dim_hora (
    sk_hora        SMALLINT    PRIMARY KEY CHECK (sk_hora BETWEEN 0 AND 23),  -- a própria hora
    hora           SMALLINT    NOT NULL UNIQUE,
    faixa_do_dia   VARCHAR(15) NOT NULL
        CHECK (faixa_do_dia IN ('Madrugada', 'Manhã', 'Almoço', 'Tarde', 'Noite'))
);

CREATE TABLE dw.dim_loja (
    sk_loja        INTEGER      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cod_loja       VARCHAR(10)  NOT NULL UNIQUE,
    nome_loja      VARCHAR(60)  NOT NULL,
    uf             CHAR(2)      NOT NULL,
    regiao         VARCHAR(15)  NOT NULL,
    cidade         VARCHAR(60)  NOT NULL,
    formato        VARCHAR(20)  NOT NULL,
    data_abertura  DATE         NOT NULL
);

-- Horário de funcionamento por dia da semana (1 = segunda ... 7 = domingo, padrão ISO).
CREATE TABLE dw.dim_loja_horario (
    sk_loja          INTEGER  NOT NULL REFERENCES dw.dim_loja (sk_loja),
    dia_semana       SMALLINT NOT NULL CHECK (dia_semana BETWEEN 1 AND 7),
    hora_abertura    TIME     NOT NULL,
    hora_fechamento  TIME     NOT NULL,
    PRIMARY KEY (sk_loja, dia_semana),
    CONSTRAINT ck_dim_loja_horario CHECK (hora_fechamento > hora_abertura)
);

CREATE TABLE dw.dim_produto (
    sk_produto      INTEGER        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sku             VARCHAR(20)    NOT NULL UNIQUE,
    nome_produto    VARCHAR(100)   NOT NULL,
    marca           VARCHAR(40)    NOT NULL,   -- marcas fictícias
    setor           VARCHAR(30)    NOT NULL,
    categoria       VARCHAR(40)    NOT NULL,
    custo_unitario  NUMERIC(12, 2) NOT NULL CHECK (custo_unitario >= 0),
    preco_lista     NUMERIC(12, 2) NOT NULL CHECK (preco_lista >= 0)
);

CREATE TABLE dw.dim_vendedor (
    sk_vendedor          INTEGER      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cod_vendedor         VARCHAR(10)  NOT NULL UNIQUE,
    nome_vendedor        VARCHAR(80)  NOT NULL,   -- nome fictício
    sk_loja              INTEGER      NOT NULL REFERENCES dw.dim_loja (sk_loja),
    cargo                VARCHAR(30)  NOT NULL,
    turno                VARCHAR(10)  NOT NULL CHECK (turno IN ('Manhã', 'Tarde', 'Integral')),
    data_admissao        DATE         NOT NULL,
    data_desligamento    DATE,                    -- NULL = ainda ativo
    percentual_comissao  NUMERIC(5, 2) NOT NULL CHECK (percentual_comissao >= 0),
    CONSTRAINT ck_dim_vendedor_periodo
        CHECK (data_desligamento IS NULL OR data_desligamento >= data_admissao)
);

-- Cliente do programa de fidelidade. Apenas atributos não identificáveis.
CREATE TABLE dw.dim_cliente (
    sk_cliente                INTEGER      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cod_cliente               VARCHAR(10)  NOT NULL UNIQUE,
    cidade                    VARCHAR(60)  NOT NULL,
    uf                        CHAR(2)      NOT NULL,
    faixa_etaria              VARCHAR(10)  NOT NULL,
    data_cadastro_fidelidade  DATE         NOT NULL
);

CREATE TABLE dw.dim_forma_pagamento (
    sk_forma_pagamento   SMALLINT    GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cod_forma_pagamento  VARCHAR(5)  NOT NULL UNIQUE,
    nome_forma_pagamento VARCHAR(30) NOT NULL UNIQUE   -- Pix, Débito, Crédito à vista, ...
);

CREATE TABLE dw.dim_campanha (
    sk_campanha     INTEGER       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cod_campanha    VARCHAR(12)   NOT NULL UNIQUE,
    nome_campanha   VARCHAR(40)   NOT NULL,
    data_inicio     DATE          NOT NULL,
    data_fim        DATE          NOT NULL,
    desconto_medio  NUMERIC(5, 2) NOT NULL CHECK (desconto_medio >= 0),  -- em %
    CONSTRAINT ck_dim_campanha_periodo CHECK (data_fim >= data_inicio)
);

CREATE TABLE dw.dim_centro_custo (
    sk_centro_custo    INTEGER      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cod_centro_custo   VARCHAR(20)  NOT NULL UNIQUE,
    nome_centro_custo  VARCHAR(80)  NOT NULL,
    tipo_despesa       VARCHAR(20)  NOT NULL
        CHECK (tipo_despesa IN ('Pessoal', 'Terceiros', 'Discricionárias')),
    sk_loja            INTEGER      REFERENCES dw.dim_loja (sk_loja),  -- NULL = corporativo
    corporativo        BOOLEAN      GENERATED ALWAYS AS (sk_loja IS NULL) STORED
);

COMMENT ON TABLE dw.dim_tempo IS 'Calendário diário com feriados nacionais.';
COMMENT ON TABLE dw.dim_hora IS 'Horas do dia (0 a 23) e faixa do dia.';
COMMENT ON TABLE dw.dim_loja IS 'Lojas da rede.';
COMMENT ON TABLE dw.dim_loja_horario IS 'Horário de funcionamento da loja por dia da semana.';
COMMENT ON TABLE dw.dim_produto IS 'Produtos (SKU) com marca fictícia, setor e categoria.';
COMMENT ON TABLE dw.dim_vendedor IS 'Vendedores (nomes fictícios), com admissão e desligamento.';
COMMENT ON TABLE dw.dim_cliente IS 'Clientes do programa de fidelidade, sem CPF, telefone ou e-mail.';
COMMENT ON TABLE dw.dim_forma_pagamento IS 'Pix, débito, crédito à vista, crédito parcelado, dinheiro.';
COMMENT ON TABLE dw.dim_campanha IS 'Campanhas promocionais com período e desconto médio (%).';
COMMENT ON TABLE dw.dim_centro_custo IS 'Centros de custo; sk_loja nulo indica centro corporativo.';
