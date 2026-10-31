-- Fase 4: gravação da previsão e do backtest no dw.
--
-- O Python (src/previsao) cria uma tabela temporária com as linhas calculadas e chama a procedure.
-- Cada procedure SUBSTITUI tudo o que já existia para o mesmo cenário, então rodar duas vezes
-- deixa o dw igual (idempotente) e um horizonte menor não deixa linhas antigas para trás.

-- tmp_previsao_vendas (nivel, granularidade, data, sk_loja, setor, valor_previsto, valor_baixo,
-- valor_alto, wape_backtest)
CREATE OR REPLACE PROCEDURE dw.gravar_previsao(p_versao VARCHAR, p_treino_ate DATE)
LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM dw.previsao_vendas
    WHERE versao_modelo = p_versao AND treino_ate = p_treino_ate;

    INSERT INTO dw.previsao_vendas (
        nivel, granularidade, data, sk_loja, setor, valor_previsto, valor_baixo, valor_alto,
        versao_modelo, treino_ate, wape_backtest
    )
    SELECT nivel, granularidade, data, sk_loja, setor, valor_previsto, valor_baixo, valor_alto,
           p_versao, p_treino_ate, wape_backtest
    FROM tmp_previsao_vendas;
END;
$$;

-- tmp_previsao_backtest (versao_modelo, nivel, granularidade, sk_loja, setor, teste_inicio,
-- teste_fim, wape, vies, cobertura_faixa, escolhido)
CREATE OR REPLACE PROCEDURE dw.gravar_backtest(p_treino_ate DATE)
LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM dw.previsao_backtest WHERE treino_ate = p_treino_ate;

    INSERT INTO dw.previsao_backtest (
        versao_modelo, nivel, granularidade, sk_loja, setor, treino_ate, teste_inicio,
        teste_fim, wape, vies, cobertura_faixa, escolhido
    )
    SELECT versao_modelo, nivel, granularidade, sk_loja, setor, p_treino_ate, teste_inicio,
           teste_fim, wape, vies, cobertura_faixa, escolhido
    FROM tmp_previsao_backtest;
END;
$$;
