-- Funções de limpeza do ETL (Fase 2). Recebem o texto cru do staging e devolvem o valor tipado
-- ou NULL quando não há como interpretá-lo; quem chama decide entre corrigir e rejeitar.
-- Todas são puras (IMMUTABLE) e escritas em SQL puro: sem blocos de exceção, para serem rápidas
-- em centenas de milhares de linhas.

-- Vazio ou só espaços -> NULL; senão o texto sem espaços nas pontas.
CREATE FUNCTION etl.limpar_texto(t TEXT) RETURNS TEXT
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT NULLIF(btrim(t), '')
$$;

-- Data válida ou NULL (31/02 e mês 13 não existem).
CREATE FUNCTION etl.montar_data(ano INT, mes INT, dia INT) RETURNS DATE
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE WHEN mes BETWEEN 1 AND 12 AND ano BETWEEN 1900 AND 2100 THEN
        CASE WHEN dia BETWEEN 1 AND
                  extract(day FROM make_date(ano, mes, 1) + interval '1 month' - interval '1 day')
             THEN make_date(ano, mes, dia) END
    END
$$;

-- Aceita dd/mm/aaaa e aaaa-mm-dd (formatos misturados na mesma coluna).
CREATE FUNCTION etl.limpar_data(t TEXT) RETURNS DATE
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE
        WHEN btrim(t) ~ '^\d{2}/\d{2}/\d{4}$' THEN
            etl.montar_data(substr(btrim(t), 7, 4)::INT, substr(btrim(t), 4, 2)::INT,
                            substr(btrim(t), 1, 2)::INT)
        WHEN btrim(t) ~ '^\d{4}-\d{2}-\d{2}$' THEN
            etl.montar_data(substr(btrim(t), 1, 4)::INT, substr(btrim(t), 6, 2)::INT,
                            substr(btrim(t), 9, 2)::INT)
    END
$$;

CREATE FUNCTION etl.montar_hora(h INT, m INT, s INT) RETURNS TIME
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE WHEN h BETWEEN 0 AND 23 AND m BETWEEN 0 AND 59 AND s BETWEEN 0 AND 59
                THEN make_time(h, m, s) END
$$;

-- Aceita HH:MM:SS, HH:MM, HHhMM e HH:MM AM/PM.
CREATE FUNCTION etl.limpar_hora(t TEXT) RETURNS TIME
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE
        WHEN btrim(t) ~ '^\d{1,2}:\d{2}:\d{2}$' THEN
            etl.montar_hora(split_part(btrim(t), ':', 1)::INT, split_part(btrim(t), ':', 2)::INT,
                            split_part(btrim(t), ':', 3)::INT)
        WHEN btrim(t) ~ '^\d{1,2}:\d{2}$' THEN
            etl.montar_hora(split_part(btrim(t), ':', 1)::INT, split_part(btrim(t), ':', 2)::INT, 0)
        WHEN btrim(t) ~ '^\d{1,2}h\d{2}$' THEN
            etl.montar_hora(split_part(btrim(t), 'h', 1)::INT, split_part(btrim(t), 'h', 2)::INT, 0)
        WHEN upper(btrim(t)) ~ '^\d{1,2}:\d{2} ?(AM|PM)$' THEN
            CASE WHEN split_part(btrim(t), ':', 1)::INT BETWEEN 1 AND 12 THEN
                etl.montar_hora(
                    split_part(btrim(t), ':', 1)::INT % 12
                        + CASE WHEN upper(btrim(t)) LIKE '%PM' THEN 12 ELSE 0 END,
                    substr(split_part(btrim(t), ':', 2), 1, 2)::INT, 0)
            END
    END
$$;

-- Aceita 1234.56, 1234,56 e 1.234,56 (texto brasileiro). Fora disso, ou com valor absoluto
-- acima de 10^12 (não cabe nas colunas NUMERIC), devolve NULL.
CREATE FUNCTION etl.limpar_numero(t TEXT) RETURNS NUMERIC
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE WHEN abs(v) < 1000000000000 THEN v END
    FROM (
        SELECT CASE
            WHEN btrim(t) ~ '^-?\d{1,3}(\.\d{3})+,\d+$'
                THEN replace(replace(btrim(t), '.', ''), ',', '.')::NUMERIC
            WHEN btrim(t) ~ '^-?\d+,\d+$' THEN replace(btrim(t), ',', '.')::NUMERIC
            WHEN btrim(t) ~ '^-?\d+(\.\d+)?$' THEN btrim(t)::NUMERIC
        END AS v
    ) q
$$;

-- Inteiro (aceita "3" e "3.0"); fora do intervalo de INTEGER devolve NULL.
CREATE FUNCTION etl.limpar_inteiro(t TEXT) RETURNS INTEGER
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE WHEN abs(v) <= 2147483647 THEN v::INTEGER END
    FROM (
        SELECT CASE
            WHEN btrim(t) ~ '^-?\d{1,10}$' THEN btrim(t)::BIGINT
            WHEN btrim(t) ~ '^-?\d{1,10}\.0+$' THEN split_part(btrim(t), '.', 1)::BIGINT
        END AS v
    ) q
$$;

-- SKU: sem espaços e em maiúsculas.
CREATE FUNCTION etl.limpar_sku(t TEXT) RETURNS TEXT
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT NULLIF(upper(regexp_replace(t, '\s+', '', 'g')), '')
$$;

-- Nome próprio: espaços repetidos viram um só e a caixa é padronizada
-- ("sarah   da MATA" -> "Sarah da Mata"; da/de/do/das/dos/e ficam minúsculas, exceto na 1ª palavra).
CREATE FUNCTION etl.limpar_nome(t TEXT) RETURNS TEXT
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT NULLIF(string_agg(
        CASE WHEN palavra.ordem > 1 AND palavra.texto IN ('da', 'de', 'do', 'das', 'dos', 'e')
             THEN palavra.texto ELSE initcap(palavra.texto) END,
        ' ' ORDER BY palavra.ordem), '')
    FROM unnest(string_to_array(lower(btrim(regexp_replace(t, '\s+', ' ', 'g'))), ' '))
         WITH ORDINALITY AS palavra(texto, ordem)
    WHERE palavra.texto <> ''
$$;

COMMENT ON FUNCTION etl.limpar_data(TEXT) IS 'dd/mm/aaaa ou aaaa-mm-dd -> DATE; inválida -> NULL.';
COMMENT ON FUNCTION etl.limpar_hora(TEXT) IS 'HH:MM:SS, HH:MM, HHhMM ou HH:MM AM/PM -> TIME.';
COMMENT ON FUNCTION etl.limpar_numero(TEXT) IS '1234.56, 1234,56 ou 1.234,56 -> NUMERIC.';
COMMENT ON FUNCTION etl.limpar_sku(TEXT) IS 'Remove espaços e converte para maiúsculas.';
COMMENT ON FUNCTION etl.limpar_nome(TEXT) IS 'Espaços extras e caixa de nome próprio.';
