-- Feriados, calendário (dw.dim_tempo) e horas do dia (dw.dim_hora).

-- Valida os feriados da carga. As marcas na dim_tempo são aplicadas por etl.carregar_calendario.
-- As contagens comparam com o estado da dim_tempo antes da marcação (novo, alterado, igual).
CREATE OR REPLACE PROCEDURE etl.carregar_feriados(p_id_carga BIGINT)
LANGUAGE plpgsql AS $$
DECLARE v_validas INT; v_ins INT; v_upd INT;
BEGIN
    DROP TABLE IF EXISTS _lim_feriados;
    CREATE TEMP TABLE _lim_feriados ON COMMIT DROP AS
    SELECT s.arquivo_origem, s.linha_origem, c.*,
           r.coluna AS rej_coluna, r.valor AS rej_valor, r.motivo AS rej_motivo
    FROM stg.feriados s
    CROSS JOIN LATERAL (SELECT
        etl.limpar_data(s.data) AS data, etl.limpar_texto(s.nome_feriado) AS nome_feriado) c
    LEFT JOIN LATERAL (
        SELECT q.coluna, q.valor, q.motivo FROM (VALUES
            (1, 'data', s.data, etl.motivo(s.data, c.data IS NULL, 'data_invalida')),
            (2, 'nome_feriado', s.nome_feriado, etl.motivo_texto(s.nome_feriado, 60))
        ) q(ord, coluna, valor, motivo) WHERE q.motivo IS NOT NULL ORDER BY q.ord LIMIT 1
    ) r ON true
    WHERE s.id_carga = p_id_carga;

    CALL etl.rejeitar_duplicadas('feriados', 'data', 'data', 't.data::TEXT', 'ultima');
    CALL etl.contar_correcao(p_id_carga, 'feriados', 'data', 'data_formato_misto',
                             $q$s.data ~ '^\s*\d{4}-'$q$);

    SELECT count(*) INTO v_validas FROM _lim_feriados WHERE rej_motivo IS NULL;
    SELECT count(*) FILTER (WHERE d.sk_tempo IS NULL OR NOT d.feriado_nacional),
           count(*) FILTER (WHERE d.feriado_nacional AND d.nome_feriado IS DISTINCT FROM t.nome_feriado)
    INTO v_ins, v_upd
    FROM _lim_feriados t LEFT JOIN dw.dim_tempo d ON d.data = t.data
    WHERE t.rej_motivo IS NULL;
    CALL etl.fechar_entidade(p_id_carga, 'feriados', v_ins, v_upd, v_validas - v_ins - v_upd);
END $$;

-- Cria os dias que faltam (anos inteiros, do menor ao maior ano usado pelos fatos da carga) e
-- marca os feriados nacionais conhecidos no staging. Sem fatos nem feriados na carga, não faz nada.
CREATE OR REPLACE PROCEDURE etl.carregar_calendario(p_id_carga BIGINT)
LANGUAGE plpgsql AS $$
DECLARE v_min DATE; v_max DATE;
BEGIN
    SELECT min(d), max(d) INTO v_min, v_max FROM (
        SELECT etl.limpar_data(data_venda) AS d FROM stg.vendas WHERE id_carga = p_id_carga
        UNION ALL
        SELECT etl.limpar_data(data_lancamento) FROM stg.despesas WHERE id_carga = p_id_carga
        UNION ALL
        SELECT etl.limpar_data(competencia) FROM stg.metas_vendas WHERE id_carga = p_id_carga
        UNION ALL
        SELECT etl.limpar_data(competencia) FROM stg.metas_vendedor WHERE id_carga = p_id_carga
        UNION ALL
        SELECT etl.limpar_data(competencia) FROM stg.orcamento_despesas WHERE id_carga = p_id_carga
        UNION ALL
        SELECT etl.limpar_data(data) FROM stg.feriados WHERE id_carga = p_id_carga
    ) datas;
    IF v_min IS NULL THEN
        RETURN;
    END IF;

    INSERT INTO dw.dim_tempo (sk_tempo, data, dia, semana, mes, trimestre, ano, nome_mes,
                              nome_dia_semana)
    SELECT to_char(g.dia, 'YYYYMMDD')::INT, g.dia::DATE, extract(day FROM g.dia)::INT,
           extract(week FROM g.dia)::INT, extract(month FROM g.dia)::INT,
           extract(quarter FROM g.dia)::INT, extract(year FROM g.dia)::INT,
           (ARRAY['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho', 'Julho', 'Agosto',
                  'Setembro', 'Outubro', 'Novembro', 'Dezembro'])[extract(month FROM g.dia)::INT],
           (ARRAY['Segunda-feira', 'Terça-feira', 'Quarta-feira', 'Quinta-feira', 'Sexta-feira',
                  'Sábado', 'Domingo'])[extract(isodow FROM g.dia)::INT]
    FROM generate_series(make_date(extract(year FROM v_min)::INT, 1, 1),
                         make_date(extract(year FROM v_max)::INT, 12, 31),
                         interval '1 day') AS g(dia)
    ON CONFLICT (sk_tempo) DO NOTHING;

    -- feriados válidos do staging (de qualquer carga), um por data
    UPDATE dw.dim_tempo t SET feriado_nacional = TRUE, nome_feriado = left(f.nome, 60)
    FROM (SELECT DISTINCT ON (etl.limpar_data(data)) etl.limpar_data(data) AS data,
                 etl.limpar_texto(nome_feriado) AS nome
          FROM stg.feriados
          WHERE etl.limpar_data(data) IS NOT NULL AND etl.limpar_texto(nome_feriado) IS NOT NULL
          ORDER BY etl.limpar_data(data), arquivo_origem DESC, linha_origem DESC) f
    WHERE t.data = f.data
      AND (NOT t.feriado_nacional OR t.nome_feriado IS DISTINCT FROM left(f.nome, 60));
END $$;

CREATE OR REPLACE PROCEDURE etl.carregar_horas()
LANGUAGE sql AS $$
    INSERT INTO dw.dim_hora (sk_hora, hora, faixa_do_dia)
    SELECT h, h, CASE WHEN h <= 5 THEN 'Madrugada' WHEN h <= 10 THEN 'Manhã'
                      WHEN h <= 13 THEN 'Almoço' WHEN h <= 17 THEN 'Tarde' ELSE 'Noite' END
    FROM generate_series(0, 23) AS h
    ON CONFLICT (sk_hora) DO NOTHING
$$;
