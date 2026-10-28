-- Fatos do esquema estrela.

-- Item do cupom (granularidade = uma linha por item vendido). A margem é calculada pelo banco.
-- (numero_cupom, numero_item) NÃO é único de propósito: cupons duplicados são um dos
-- alertas da Fase 3 e precisam poder ser carregados.
CREATE TABLE dw.fato_vendas (
    sk_venda            BIGINT         GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_venda_erp        VARCHAR(20)    NOT NULL UNIQUE,
    numero_cupom        VARCHAR(20)    NOT NULL,
    numero_item         SMALLINT       NOT NULL CHECK (numero_item > 0),
    sk_tempo            INTEGER        NOT NULL REFERENCES dw.dim_tempo (sk_tempo),
    sk_hora             SMALLINT       NOT NULL REFERENCES dw.dim_hora (sk_hora),
    data_hora_venda     TIMESTAMP      NOT NULL,
    sk_loja             INTEGER        NOT NULL REFERENCES dw.dim_loja (sk_loja),
    caixa               SMALLINT       NOT NULL CHECK (caixa > 0),           -- número do PDV
    sk_vendedor         INTEGER        NOT NULL REFERENCES dw.dim_vendedor (sk_vendedor),
    sk_cliente          INTEGER        REFERENCES dw.dim_cliente (sk_cliente),  -- NULL = não identificado
    sk_forma_pagamento  SMALLINT       NOT NULL REFERENCES dw.dim_forma_pagamento (sk_forma_pagamento),
    numero_parcelas     SMALLINT       NOT NULL DEFAULT 1 CHECK (numero_parcelas >= 1),
    sk_campanha         INTEGER        REFERENCES dw.dim_campanha (sk_campanha),  -- NULL = sem campanha
    sk_produto          INTEGER        NOT NULL REFERENCES dw.dim_produto (sk_produto),
    quantidade          INTEGER        NOT NULL CHECK (quantidade > 0),
    preco_unitario      NUMERIC(12, 2) NOT NULL CHECK (preco_unitario >= 0),
    desconto            NUMERIC(14, 2) NOT NULL DEFAULT 0 CHECK (desconto >= 0),
    receita_liquida     NUMERIC(14, 2) NOT NULL,   -- valor líquido do item
    custo               NUMERIC(14, 2) NOT NULL,
    margem              NUMERIC(14, 2) GENERATED ALWAYS AS (receita_liquida - custo) STORED,
    status              VARCHAR(10)    NOT NULL
        CHECK (status IN ('Concluída', 'Cancelada', 'Devolvida')),
    motivo_cancelamento_devolucao VARCHAR(60),
    CONSTRAINT ck_fato_vendas_motivo
        CHECK (status = 'Concluída' OR motivo_cancelamento_devolucao IS NOT NULL)
);

-- Meta mensal por loja e setor (sk_tempo = primeiro dia do mês).
CREATE TABLE dw.fato_meta_vendas (
    sk_meta     INTEGER        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sk_tempo    INTEGER        NOT NULL REFERENCES dw.dim_tempo (sk_tempo),
    sk_loja     INTEGER        NOT NULL REFERENCES dw.dim_loja (sk_loja),
    setor       VARCHAR(30)    NOT NULL,   -- mesmo domínio de dw.dim_produto.setor
    valor_meta  NUMERIC(14, 2) NOT NULL CHECK (valor_meta >= 0),
    CONSTRAINT uq_fato_meta_vendas UNIQUE (sk_tempo, sk_loja, setor)
);

-- Meta mensal por vendedor (sk_tempo = primeiro dia do mês).
CREATE TABLE dw.fato_meta_vendedor (
    sk_meta_vendedor  INTEGER        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sk_tempo          INTEGER        NOT NULL REFERENCES dw.dim_tempo (sk_tempo),
    sk_vendedor       INTEGER        NOT NULL REFERENCES dw.dim_vendedor (sk_vendedor),
    valor_meta        NUMERIC(14, 2) NOT NULL CHECK (valor_meta >= 0),
    CONSTRAINT uq_fato_meta_vendedor UNIQUE (sk_tempo, sk_vendedor)
);

-- Lançamentos de despesa. numero_documento NÃO é único de propósito: duplicidades
-- são justamente um dos alertas da Fase 3.
CREATE TABLE dw.fato_despesas (
    sk_despesa        BIGINT         GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    numero_documento  VARCHAR(20)    NOT NULL,
    sk_tempo          INTEGER        NOT NULL REFERENCES dw.dim_tempo (sk_tempo),
    sk_centro_custo   INTEGER        NOT NULL REFERENCES dw.dim_centro_custo (sk_centro_custo),
    fornecedor        VARCHAR(100),             -- fornecedor fictício
    valor             NUMERIC(14, 2) NOT NULL,
    descricao         VARCHAR(200),
    arquivo_origem    VARCHAR(100),            -- linhagem: de onde veio o lançamento
    linha_origem      INTEGER
);

-- Orçamento mensal por centro de custo (sk_tempo = primeiro dia do mês).
CREATE TABLE dw.fato_orcamento_despesas (
    sk_orcamento     INTEGER        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sk_tempo         INTEGER        NOT NULL REFERENCES dw.dim_tempo (sk_tempo),
    sk_centro_custo  INTEGER        NOT NULL REFERENCES dw.dim_centro_custo (sk_centro_custo),
    valor_orcado     NUMERIC(14, 2) NOT NULL CHECK (valor_orcado >= 0),
    CONSTRAINT uq_fato_orcamento_despesas UNIQUE (sk_tempo, sk_centro_custo)
);
