-- Fase 5, etapa 5: gravação (idempotente) da probabilidade de bater a meta.
-- Cada procedure lê uma tabela temporária que o Python cria na mesma transação.

-- tmp_prob_meta (nivel, sk_loja, data_referencia, mes, dias_restantes, realizado_ate,
-- previsto_resto, projecao, meta_mes, probabilidade, motivo_sem_base, lojas_incluidas, lojas_total)
-- Substitui as linhas desta versão no intervalo de datas de referência.
CREATE OR REPLACE PROCEDURE dw.gravar_probabilidade_meta(p_versao VARCHAR, p_inicio DATE, p_fim DATE)
LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM dw.previsao_probabilidade_meta
    WHERE versao = p_versao AND data_referencia BETWEEN p_inicio AND p_fim;

    INSERT INTO dw.previsao_probabilidade_meta (
        nivel, sk_loja, data_referencia, mes, dias_restantes, realizado_ate, previsto_resto,
        projecao, meta_mes, probabilidade, motivo_sem_base, lojas_incluidas, lojas_total, versao
    )
    SELECT nivel, sk_loja, data_referencia, mes, dias_restantes, realizado_ate, previsto_resto,
           projecao, meta_mes, probabilidade, motivo_sem_base, lojas_incluidas, lojas_total, p_versao
    FROM tmp_prob_meta;
END;
$$;

-- tmp_prob_calibracao (esquema, nivel, faixa_dias, tipo, prob_inicio, prob_fim, previsto_medio,
-- observado, n, n_unidades, ic_baixo, ic_alto, brier, brier_50, brier_frequencia, ece)
-- A calibração é recalculada inteira: substitui tudo desta versão.
CREATE OR REPLACE PROCEDURE dw.gravar_probabilidade_calibracao(p_versao VARCHAR)
LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM dw.previsao_probabilidade_calibracao WHERE versao = p_versao;

    INSERT INTO dw.previsao_probabilidade_calibracao (
        esquema, nivel, faixa_dias, tipo, prob_inicio, prob_fim, previsto_medio, observado, n,
        n_unidades, ic_baixo, ic_alto, brier, brier_50, brier_frequencia, ece, versao
    )
    SELECT esquema, nivel, faixa_dias, tipo, prob_inicio, prob_fim, previsto_medio, observado, n,
           n_unidades, ic_baixo, ic_alto, brier, brier_50, brier_frequencia, ece, p_versao
    FROM tmp_prob_calibracao;
END;
$$;

-- tmp_prob_erro (nivel, sk_loja, faixa_dias, posicao, meses_ate, n_meses, n_amostras, mu_bruto,
-- sigma_bruto, peso, mu, sigma, z)
-- Substitui os ajustes (meses_ate) que a tabela temporária traz, nesta versão.
CREATE OR REPLACE PROCEDURE dw.gravar_erro_resto(p_versao VARCHAR)
LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM dw.previsao_erro_resto
    WHERE versao = p_versao AND meses_ate IN (SELECT DISTINCT meses_ate FROM tmp_prob_erro);

    INSERT INTO dw.previsao_erro_resto (
        nivel, sk_loja, faixa_dias, posicao, meses_ate, n_meses, n_amostras, mu_bruto, sigma_bruto,
        peso, mu, sigma, z, versao
    )
    SELECT nivel, sk_loja, faixa_dias, posicao, meses_ate, n_meses, n_amostras, mu_bruto,
           sigma_bruto, peso, mu, sigma, z, p_versao
    FROM tmp_prob_erro;
END;
$$;
