-- Rotinas comuns das cargas stg -> dw (Fase 2). Podem ser reaplicadas à vontade (CREATE OR REPLACE).
--
-- Cada carga de entidade segue o mesmo roteiro:
--   1. monta a tabela temporária _lim_<entidade> com um registro por linha do staging da carga,
--      com os valores já limpos e, quando a linha não pode ser aproveitada, a coluna, o valor cru
--      e o motivo (rej_coluna, rej_valor, rej_motivo);
--   2. grava no dw as linhas sem motivo (upsert pela chave natural);
--   3. registra rejeitados, contagens e correções (etl.fechar_entidade / etl.contar_correcao).
-- Nada aqui consulta arquivos de gabarito: só o staging e o dw.

-- ---- motivos de rejeição por tipo de coluna (NULL = a coluna está boa) --------------------------
CREATE OR REPLACE FUNCTION etl.motivo_texto(cru TEXT, limite INT, obrigatorio BOOLEAN DEFAULT TRUE)
RETURNS TEXT LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN etl.limpar_texto(cru) IS NULL THEN CASE WHEN obrigatorio THEN 'obrigatorio_vazio' END
        WHEN length(etl.limpar_texto(cru)) > limite THEN 'texto_longo_demais'
    END
$$;

-- `invalido` diz se a conversão falhou (ou o valor ficou fora da regra); `motivo` é o nome do erro.
CREATE OR REPLACE FUNCTION etl.motivo(
    cru TEXT, invalido BOOLEAN, motivo TEXT, obrigatorio BOOLEAN DEFAULT TRUE
) RETURNS TEXT LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN etl.limpar_texto(cru) IS NULL THEN CASE WHEN obrigatorio THEN 'obrigatorio_vazio' END
        WHEN invalido THEN motivo
    END
$$;

CREATE OR REPLACE FUNCTION etl.motivo_valor(
    cru TEXT, limpo NUMERIC, permite_negativo BOOLEAN DEFAULT FALSE, obrigatorio BOOLEAN DEFAULT TRUE
) RETURNS TEXT LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN etl.limpar_texto(cru) IS NULL THEN CASE WHEN obrigatorio THEN 'obrigatorio_vazio' END
        WHEN limpo IS NULL THEN 'valor_nao_numerico'
        WHEN limpo < 0 AND NOT permite_negativo THEN 'valor_negativo'
    END
$$;

-- ---- fechamento de cada entidade -----------------------------------------------------------------
-- Substitui os rejeitados antigos dos mesmos arquivos pelos desta carga e grava as contagens.
CREATE OR REPLACE PROCEDURE etl.fechar_entidade(
    p_id_carga BIGINT, p_entidade TEXT, p_inseridas INT, p_atualizadas INT, p_sem_alteracao INT,
    p_removidas INT DEFAULT 0
) LANGUAGE plpgsql AS $$
DECLARE
    v_temp TEXT := '_lim_' || p_entidade;
    v_lidas INT;
    v_rejeitadas INT;
BEGIN
    EXECUTE format(
        'DELETE FROM stg.rejeitados WHERE entidade = %L AND arquivo_origem IN '
        '(SELECT DISTINCT arquivo_origem FROM %I)', p_entidade, v_temp);
    EXECUTE format(
        'INSERT INTO stg.rejeitados (id_carga, entidade, arquivo_origem, linha_origem, coluna,'
        ' valor_original, motivo) '
        'SELECT %L, %L, arquivo_origem, linha_origem, rej_coluna, rej_valor, rej_motivo '
        'FROM %I WHERE rej_motivo IS NOT NULL', p_id_carga, p_entidade, v_temp);
    EXECUTE format('SELECT count(*), count(rej_motivo) FROM %I', v_temp) INTO v_lidas, v_rejeitadas;
    INSERT INTO etl.carga_tabelas (id_carga, entidade, lidas, rejeitadas, carregadas, inseridas,
                                   atualizadas, sem_alteracao, removidas)
    VALUES (p_id_carga, p_entidade, v_lidas, v_rejeitadas, v_lidas - v_rejeitadas, p_inseridas,
            p_atualizadas, p_sem_alteracao, p_removidas);
END $$;

-- Conta as células corrigidas (linhas aproveitadas em que `p_condicao` é verdadeira).
-- `p_condicao` é SQL fixo escrito pelas procedures, com `s` = linha crua do staging e
-- `t` = linha limpa da tabela temporária.
CREATE OR REPLACE PROCEDURE etl.contar_correcao(
    p_id_carga BIGINT, p_entidade TEXT, p_coluna TEXT, p_tipo TEXT, p_condicao TEXT
) LANGUAGE plpgsql AS $$
BEGIN
    EXECUTE format(
        'INSERT INTO etl.carga_correcoes (id_carga, entidade, coluna, tipo_problema, quantidade) '
        'SELECT %L, %L, %L, %L, count(*) FROM stg.%I s JOIN %I t '
        'ON t.arquivo_origem = s.arquivo_origem AND t.linha_origem = s.linha_origem '
        'WHERE s.id_carga = %L AND t.rej_motivo IS NULL AND (%s) HAVING count(*) > 0',
        p_id_carga, p_entidade, p_coluna, p_tipo, p_entidade, '_lim_' || p_entidade, p_id_carga,
        p_condicao);
END $$;

-- Chave repetida dentro da mesma carga: mantém uma linha e rejeita as demais com motivo.
-- `p_manter` = 'primeira' ou 'ultima' ocorrência (pela ordem arquivo, linha).
CREATE OR REPLACE PROCEDURE etl.rejeitar_duplicadas(
    p_entidade TEXT, p_chave TEXT, p_coluna TEXT, p_valor TEXT, p_manter TEXT
) LANGUAGE plpgsql AS $$
BEGIN
    EXECUTE format(
        'UPDATE %1$I t SET rej_coluna = %2$L, rej_valor = %3$s, '
        '  rej_motivo = ''chave_duplicada_na_carga'' '
        'FROM (SELECT arquivo_origem, linha_origem, row_number() OVER ('
        '        PARTITION BY %4$s ORDER BY arquivo_origem %5$s, linha_origem %5$s) AS ordem '
        '      FROM %1$I WHERE rej_motivo IS NULL) d '
        'WHERE t.arquivo_origem = d.arquivo_origem AND t.linha_origem = d.linha_origem '
        '  AND d.ordem > 1',
        '_lim_' || p_entidade, p_coluna, p_valor, p_chave,
        CASE WHEN p_manter = 'ultima' THEN 'DESC' ELSE 'ASC' END);
END $$;
