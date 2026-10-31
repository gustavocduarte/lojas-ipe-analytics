-- Fase 4: previsão de vendas.
--
-- As previsões são gravadas por `python -m src.previsao` (procedure dw.gravar_previsao). Cada linha
-- guarda de qual modelo veio, até que dia o modelo foi treinado (`treino_ate`) e o erro que ele
-- teve no backtest. As datas previstas ficam em colunas DATE (e não em sk_tempo) porque caem depois
-- do último dia que a dim_tempo cobre.

CREATE TABLE dw.previsao_vendas (
    sk_previsao    BIGINT         GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    granularidade  VARCHAR(3)     NOT NULL CHECK (granularidade IN ('dia', 'mes')),
    data           DATE           NOT NULL,   -- o dia previsto, ou o 1º dia do mês previsto
    sk_loja        INTEGER        NOT NULL REFERENCES dw.dim_loja (sk_loja),
    setor          VARCHAR(30)    NOT NULL,   -- mesmo domínio de dw.dim_produto.setor
    valor_previsto NUMERIC(14, 2) NOT NULL CHECK (valor_previsto >= 0),
    valor_baixo    NUMERIC(14, 2) NOT NULL CHECK (valor_baixo >= 0),
    valor_alto     NUMERIC(14, 2) NOT NULL CHECK (valor_alto >= 0),
    versao_modelo  VARCHAR(40)    NOT NULL,   -- ex.: decomposicao@1
    treino_ate     DATE           NOT NULL,   -- último dia de venda usado no treino
    wape_backtest  NUMERIC(8, 4),             -- WAPE do backtest desta loja e setor, na mesma granularidade
    gerado_em      TIMESTAMP      NOT NULL DEFAULT now(),
    CONSTRAINT ck_previsao_faixa CHECK (valor_baixo <= valor_previsto AND valor_previsto <= valor_alto),
    CONSTRAINT ck_previsao_mes_dia1 CHECK (granularidade = 'dia' OR EXTRACT(DAY FROM data) = 1),
    CONSTRAINT uq_previsao_vendas UNIQUE (granularidade, data, sk_loja, setor, versao_modelo, treino_ate)
);

-- Erro de cada abordagem no backtest (treina até `treino_ate`, prevê `teste_inicio`..`teste_fim`).
-- sk_loja e setor ficam NULL nos níveis em que não se aplicam (rede, setor, loja).
CREATE TABLE dw.previsao_backtest (
    sk_backtest    BIGINT         GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    versao_modelo  VARCHAR(40)    NOT NULL,
    nivel          VARCHAR(10)    NOT NULL CHECK (nivel IN ('rede', 'loja', 'setor', 'loja_setor')),
    granularidade  VARCHAR(3)     NOT NULL CHECK (granularidade IN ('dia', 'mes')),
    sk_loja        INTEGER        REFERENCES dw.dim_loja (sk_loja),
    setor          VARCHAR(30),
    treino_ate     DATE           NOT NULL,
    teste_inicio   DATE           NOT NULL,
    teste_fim      DATE           NOT NULL,
    wape           NUMERIC(8, 4)  NOT NULL,   -- soma dos erros absolutos / soma do real
    vies           NUMERIC(8, 4)  NOT NULL,   -- (soma do previsto / soma do real) - 1
    cobertura_faixa NUMERIC(6, 4),            -- % do real dentro da faixa baixa-alta (só do modelo escolhido)
    escolhido      BOOLEAN        NOT NULL DEFAULT FALSE,
    gerado_em      TIMESTAMP      NOT NULL DEFAULT now(),
    CONSTRAINT ck_previsao_backtest_periodo CHECK (teste_inicio > treino_ate AND teste_fim >= teste_inicio)
);
CREATE UNIQUE INDEX uq_previsao_backtest ON dw.previsao_backtest
    (versao_modelo, treino_ate, nivel, granularidade, COALESCE(sk_loja, 0), COALESCE(setor, ''));

-- Limites do fechamento do ano de despesas (fator realizado/orçado aplicado ao orçado restante).
INSERT INTO etl.parametros_negocio (chave, valor, descricao) VALUES
    ('projecao_fator_min', 0.7, 'Fechamento de despesas: piso do fator realizado/orçado aplicado ao restante do ano.'),
    ('projecao_fator_max', 1.3, 'Fechamento de despesas: teto do fator realizado/orçado aplicado ao restante do ano.');

COMMENT ON TABLE dw.previsao_vendas IS 'Previsão de receita líquida por loja e setor, com faixa baixa/alta, modelo e erro do backtest.';
COMMENT ON COLUMN dw.previsao_vendas.treino_ate IS 'Último dia de venda usado no treino; também identifica o cenário (ex.: corte simulado do mês).';
COMMENT ON TABLE dw.previsao_backtest IS 'Erro (WAPE e viés) de cada abordagem no backtest, por nível e granularidade.';
