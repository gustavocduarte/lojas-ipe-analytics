-- Fase 5, etapa 5: views da probabilidade de bater a meta para o Power BI.
-- Sempre a versão gerada mais recentemente. A da rede NÃO tem sk_loja (como vw_referencia_rede_dia):
-- com segurança por loja (RLS) o gerente só enxerga a própria loja e a rede viraria a loja dele.

-- Limites de cor, lidos de etl.parametros_negocio.
CREATE OR REPLACE VIEW dw.vw_parametros_probabilidade AS
SELECT chave, valor::float8 AS valor, descricao
FROM etl.parametros_negocio
WHERE chave LIKE 'prob\_%';

CREATE OR REPLACE VIEW dw.vw_probabilidade_meta_loja AS
SELECT p.sk_loja,
       to_char(p.data_referencia, 'YYYYMMDD')::INT AS sk_tempo,
       p.data_referencia, p.mes, p.dias_restantes,
       p.realizado_ate::float8 AS realizado_ate,
       p.previsto_resto::float8 AS previsto_resto,
       p.projecao::float8 AS projecao,
       p.meta_mes::float8 AS meta_mes,
       p.probabilidade::float8 AS probabilidade,
       p.motivo_sem_base
FROM dw.previsao_probabilidade_meta p
WHERE p.nivel = 'loja'
  AND p.versao = (SELECT versao FROM dw.previsao_probabilidade_meta ORDER BY gerado_em DESC, versao DESC LIMIT 1);

CREATE OR REPLACE VIEW dw.vw_probabilidade_meta_rede AS
SELECT to_char(p.data_referencia, 'YYYYMMDD')::INT AS sk_tempo,
       p.data_referencia, p.mes, p.dias_restantes,
       p.realizado_ate::float8 AS realizado_ate,
       p.previsto_resto::float8 AS previsto_resto,
       p.projecao::float8 AS projecao,
       p.meta_mes::float8 AS meta_mes,
       p.probabilidade::float8 AS probabilidade,
       p.motivo_sem_base, p.lojas_incluidas, p.lojas_total
FROM dw.previsao_probabilidade_meta p
WHERE p.nivel = 'rede'
  AND p.versao = (SELECT versao FROM dw.previsao_probabilidade_meta ORDER BY gerado_em DESC, versao DESC LIMIT 1);

CREATE OR REPLACE VIEW dw.vw_probabilidade_calibracao AS
SELECT c.esquema, c.nivel, c.faixa_dias, c.tipo, c.prob_inicio::float8 AS prob_inicio,
       c.prob_fim::float8 AS prob_fim, c.previsto_medio::float8 AS previsto_medio,
       c.observado::float8 AS observado, c.n, c.n_unidades, c.ic_baixo::float8 AS ic_baixo,
       c.ic_alto::float8 AS ic_alto, c.brier::float8 AS brier, c.brier_50::float8 AS brier_50,
       c.brier_frequencia::float8 AS brier_frequencia, c.ece::float8 AS ece
FROM dw.previsao_probabilidade_calibracao c
WHERE c.versao = (SELECT versao FROM dw.previsao_probabilidade_calibracao ORDER BY gerado_em DESC, versao DESC LIMIT 1);

COMMENT ON VIEW dw.vw_parametros_probabilidade IS 'Limites de cor da probabilidade de bater a meta (chaves prob_* de etl.parametros_negocio).';
COMMENT ON VIEW dw.vw_probabilidade_meta_loja IS 'Probabilidade ESTIMADA de bater a meta do mês, por loja e dia; NULL = sem base (motivo_sem_base).';
COMMENT ON VIEW dw.vw_probabilidade_meta_rede IS 'Probabilidade ESTIMADA de bater a meta do mês da rede, por dia, sem loja (pronta para RLS por loja).';
COMMENT ON VIEW dw.vw_probabilidade_calibracao IS 'Curva de confiabilidade, Brier e ECE da probabilidade (esquema so_passado vale para o painel).';
