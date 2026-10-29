-- Base das regras de alerta (Fase 3): leitura de parâmetros e formatação brasileira dos textos.
-- Nada aqui consulta arquivos de gabarito.

-- Valor de um limite em etl.parametros_negocio. Falha alto se o parâmetro não existir
-- (melhor parar do que alertar com um limite inventado).
CREATE OR REPLACE FUNCTION etl.parametro(p_chave TEXT) RETURNS NUMERIC
LANGUAGE plpgsql STABLE AS $$
DECLARE v NUMERIC;
BEGIN
    SELECT valor INTO v FROM etl.parametros_negocio WHERE chave = p_chave;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'parâmetro de negócio inexistente: %', p_chave;
    END IF;
    RETURN v;
END $$;

-- 1234.5 -> 'R$ 1.234,50'; negativos saem como '-R$ 10,00'. Independe do locale do servidor.
CREATE OR REPLACE FUNCTION etl.fmt_brl(p_valor NUMERIC) RETURNS TEXT
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN p_valor < 0 THEN '-' ELSE '' END || 'R$ '
        || translate(to_char(abs(round(p_valor, 2)), 'FM999,999,999,990.00'), ',.', '.,')
$$;

-- Fração -> percentual: (0.352, 1) -> '35,2%'; (0.18, 0) -> '18%'.
CREATE OR REPLACE FUNCTION etl.fmt_pct(p_fracao NUMERIC, p_casas INT DEFAULT 1) RETURNS TEXT
LANGUAGE sql IMMUTABLE AS $$
    SELECT translate(
        to_char(round(p_fracao * 100, p_casas),
                'FM999990' || CASE WHEN p_casas > 0 THEN '.' || repeat('0', p_casas) ELSE '' END),
        '.', ',') || '%'
$$;

-- Número com milhar e decimais brasileiros: (1696, 0) -> '1.696'; (10.64, 1) -> '10,6'.
CREATE OR REPLACE FUNCTION etl.fmt_num(p_valor NUMERIC, p_casas INT DEFAULT 0) RETURNS TEXT
LANGUAGE sql IMMUTABLE AS $$
    SELECT translate(
        to_char(round(p_valor, p_casas),
                'FM999,999,999,990' || CASE WHEN p_casas > 0 THEN '.' || repeat('0', p_casas) ELSE '' END),
        ',.', '.,')
$$;

CREATE OR REPLACE FUNCTION etl.fmt_data(p_data DATE) RETURNS TEXT
LANGUAGE sql IMMUTABLE AS $$
    SELECT to_char(p_data, 'DD/MM/YYYY')
$$;
