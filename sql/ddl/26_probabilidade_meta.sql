-- Fase 5, etapa 5: probabilidade estimada de a receita do mês fechar >= meta do mês.
--
-- Gravada por `python -m src.previsao probabilidade --gravar` (procedures dw.gravar_probabilidade_*).
-- Método e calibração: docs/metodologia_probabilidade.md. É sempre uma ESTIMATIVA.

-- Uma linha por loja (ou rede) e dia de referência: a probabilidade com o que se sabia NAQUELE dia
-- (esquema "so_passado": o erro do modelo vem só de meses que terminaram antes do dia).
-- probabilidade NULL = sem base, e `motivo_sem_base` diz por quê (nunca 50%).
CREATE TABLE dw.previsao_probabilidade_meta (
    sk_probabilidade BIGINT         GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nivel            VARCHAR(4)     NOT NULL CHECK (nivel IN ('loja', 'rede')),
    sk_loja          INTEGER        REFERENCES dw.dim_loja (sk_loja),   -- NULL na rede
    data_referencia  DATE           NOT NULL,   -- a receita até este dia (inclusive) já é conhecida
    mes              DATE           NOT NULL,   -- 1º dia do mês da meta
    dias_restantes   INTEGER        NOT NULL CHECK (dias_restantes >= 0),
    realizado_ate    NUMERIC(14, 2) NOT NULL,
    previsto_resto   NUMERIC(14, 2),            -- previsão dos dias que faltam (NULL sem base)
    projecao         NUMERIC(14, 2),            -- realizado_ate + previsto_resto
    meta_mes         NUMERIC(14, 2),
    probabilidade    NUMERIC(6, 4)  CHECK (probabilidade BETWEEN 0 AND 1),
    motivo_sem_base  VARCHAR(30)    CHECK (motivo_sem_base IN ('loja_nova', 'sem_meta', 'sem_amostra_erro', 'sem_previsao')),
    lojas_incluidas  INTEGER,                   -- só na rede: lojas com base e meta que entraram na conta
    lojas_total      INTEGER,                   -- só na rede: lojas abertas naquele dia
    versao           VARCHAR(40)    NOT NULL,   -- ex.: decomposicao@1/prob@1
    gerado_em        TIMESTAMP      NOT NULL DEFAULT now(),
    CONSTRAINT ck_prob_nivel CHECK ((nivel = 'loja' AND sk_loja IS NOT NULL) OR (nivel = 'rede' AND sk_loja IS NULL)),
    CONSTRAINT ck_prob_motivo CHECK ((probabilidade IS NULL) = (motivo_sem_base IS NOT NULL)),
    CONSTRAINT ck_prob_mes_dia1 CHECK (EXTRACT(DAY FROM mes) = 1)
);
CREATE UNIQUE INDEX uq_prob_meta ON dw.previsao_probabilidade_meta
    (nivel, COALESCE(sk_loja, 0), data_referencia, versao);

-- Curva de confiabilidade (tipo 'faixa': previsto médio x observado, por faixa de probabilidade) e
-- Brier/ECE (tipo 'resumo'), por esquema, nível e faixa de dias que faltam (0 = todas).
-- 'so_passado' = a que vale para o painel; 'leave_one_month_out' usa meses POSTERIORES (otimista).
CREATE TABLE dw.previsao_probabilidade_calibracao (
    sk_calibracao    BIGINT         GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    esquema          VARCHAR(20)    NOT NULL CHECK (esquema IN ('so_passado', 'leave_one_month_out')),
    nivel            VARCHAR(5)     NOT NULL CHECK (nivel IN ('loja', 'rede')),
    faixa_dias       SMALLINT       NOT NULL CHECK (faixa_dias BETWEEN 0 AND 5),
    tipo             VARCHAR(7)     NOT NULL CHECK (tipo IN ('faixa', 'resumo')),
    prob_inicio      NUMERIC(4, 2),
    prob_fim         NUMERIC(4, 2),
    previsto_medio   NUMERIC(6, 4),
    observado        NUMERIC(6, 4),
    n                INTEGER        NOT NULL CHECK (n > 0),   -- cortes diários
    n_unidades       INTEGER        NOT NULL CHECK (n_unidades > 0),   -- (loja, mês) distintos: o n efetivo
    ic_baixo         NUMERIC(6, 4),
    ic_alto          NUMERIC(6, 4),
    brier            NUMERIC(8, 6),
    brier_50         NUMERIC(8, 6),
    brier_frequencia NUMERIC(8, 6),
    ece              NUMERIC(8, 6),
    versao           VARCHAR(40)    NOT NULL,
    gerado_em        TIMESTAMP      NOT NULL DEFAULT now(),
    CONSTRAINT ck_prob_calibracao_tipo CHECK ((tipo = 'faixa') = (prob_inicio IS NOT NULL))
);
CREATE UNIQUE INDEX uq_prob_calibracao ON dw.previsao_probabilidade_calibracao
    (esquema, nivel, faixa_dias, tipo, COALESCE(prob_inicio, -1), versao);

-- Parâmetros do erro do que falta do mês (ln R) de cada ajuste mensal: viés e dispersão por loja,
-- conjunto das lojas e rede, por faixa de dias que faltam; e a forma dos resíduos padronizados (101
-- quantis, nivel 'forma'). `meses_ate` = último mês fechado usado no ajuste.
CREATE TABLE dw.previsao_erro_resto (
    sk_erro_resto BIGINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nivel         VARCHAR(8)    NOT NULL CHECK (nivel IN ('loja', 'conjunto', 'rede', 'forma')),
    sk_loja       INTEGER       REFERENCES dw.dim_loja (sk_loja),
    faixa_dias    SMALLINT      CHECK (faixa_dias BETWEEN 1 AND 5),   -- 1 = faixa de 1 a 5 dias que faltam
    posicao       SMALLINT      CHECK (posicao BETWEEN 0 AND 100),    -- só na forma: quantil em %
    meses_ate     DATE          NOT NULL,
    n_meses       INTEGER       NOT NULL,
    n_amostras    INTEGER       NOT NULL,
    mu_bruto      NUMERIC(10, 6),
    sigma_bruto   NUMERIC(10, 6),
    peso          NUMERIC(10, 6),   -- peso da loja no encolhimento n / (n + K)
    mu            NUMERIC(10, 6),
    sigma         NUMERIC(10, 6),
    z             NUMERIC(10, 6),   -- só na forma
    versao        VARCHAR(40)   NOT NULL,
    gerado_em     TIMESTAMP     NOT NULL DEFAULT now(),
    CONSTRAINT ck_erro_resto_forma CHECK (
        (nivel = 'forma' AND posicao IS NOT NULL AND z IS NOT NULL AND faixa_dias IS NULL)
        OR (nivel <> 'forma' AND posicao IS NULL AND faixa_dias IS NOT NULL AND mu IS NOT NULL AND sigma IS NOT NULL)
    ),
    CONSTRAINT ck_erro_resto_loja CHECK ((nivel = 'loja') = (sk_loja IS NOT NULL))
);
CREATE UNIQUE INDEX uq_erro_resto ON dw.previsao_erro_resto
    (versao, meses_ate, nivel, COALESCE(sk_loja, 0), COALESCE(faixa_dias, 0), COALESCE(posicao, -1));

COMMENT ON TABLE dw.previsao_probabilidade_meta IS 'Probabilidade ESTIMADA de a receita do mês fechar >= meta, por loja e rede, em cada dia (esquema so_passado). NULL = sem base (motivo_sem_base).';
COMMENT ON TABLE dw.previsao_probabilidade_calibracao IS 'Curva de confiabilidade, Brier e ECE da probabilidade, por esquema (so_passado vale para o painel).';
COMMENT ON TABLE dw.previsao_erro_resto IS 'Viés e dispersão do erro do resto do mês por loja/faixa de dias e a forma dos resíduos, de cada ajuste mensal.';

-- Limites de cor da probabilidade no Power BI (nada fixo no DAX). Reaplicável: só atualiza a descrição.
INSERT INTO etl.parametros_negocio (chave, valor, descricao) VALUES
    ('prob_verde_min', 0.70, 'Probabilidade de bater a meta: a partir desta fração a chance é alta (verde).'),
    ('prob_ambar_min', 0.30, 'Probabilidade de bater a meta: abaixo desta fração a chance é baixa (vermelho); entre as duas, âmbar.')
ON CONFLICT (chave) DO UPDATE SET descricao = EXCLUDED.descricao;
