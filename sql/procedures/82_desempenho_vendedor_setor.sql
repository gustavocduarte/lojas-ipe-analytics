-- dw.gravar_desempenho_vendedor_setor: venda diária de cada vendedor ativo em cada setor, medida só
-- nos dias em que ele estava lotado no setor (dw.vendedor_setor_historico), contando como zero o dia
-- lotado sem venda. Idempotente por data de referência. Só vendas concluídas e só até a referência.

CREATE OR REPLACE PROCEDURE dw.gravar_desempenho_vendedor_setor(p_ref DATE DEFAULT NULL)
LANGUAGE plpgsql AS $$
DECLARE
    v_ref DATE := COALESCE(p_ref, dw.data_referencia());
    v_janela INT := etl.parametro('simulador_janela_dias')::INT;
    v_min INT := etl.parametro('simulador_min_dias_historico')::INT;
    v_pct NUMERIC := etl.parametro('simulador_percentil');
    v_alta INT := etl.parametro('simulador_dias_confianca_alta')::INT;
    v_ini DATE := v_ref - (v_janela - 1);
BEGIN
    DELETE FROM dw.desempenho_vendedor_setor WHERE data_referencia = v_ref;
    DROP TABLE IF EXISTS _loja_dia, _venda_dia, _serie, _estat, _pares, _rede, _loja_setor;

    -- dias em que cada loja vendeu (loja aberta) e o que cada vendedor vendeu por setor e dia
    CREATE TEMP TABLE _loja_dia ON COMMIT DROP AS
    SELECT DISTINCT v.sk_loja, t.data
    FROM dw.fato_vendas v JOIN dw.dim_tempo t ON t.sk_tempo = v.sk_tempo
    WHERE v.status = 'Concluída' AND t.data BETWEEN v_ini AND v_ref;

    CREATE TEMP TABLE _venda_dia ON COMMIT DROP AS
    SELECT v.sk_vendedor, p.setor, t.data, sum(v.receita_liquida) AS valor
    FROM dw.fato_vendas v JOIN dw.dim_tempo t ON t.sk_tempo = v.sk_tempo
    JOIN dw.dim_produto p ON p.sk_produto = v.sk_produto
    WHERE v.status = 'Concluída' AND t.data BETWEEN v_ini AND v_ref
    GROUP BY v.sk_vendedor, p.setor, t.data;

    CREATE TEMP TABLE _serie ON COMMIT DROP AS
    SELECT h.sk_vendedor, h.setor, ld.data, COALESCE(vd.valor, 0) AS valor
    FROM dw.vendedor_setor_historico h
    JOIN dw.dim_vendedor d ON d.sk_vendedor = h.sk_vendedor
    JOIN _loja_dia ld ON ld.sk_loja = d.sk_loja
         AND ld.data BETWEEN GREATEST(h.data_inicio, v_ini)
                         AND LEAST(COALESCE(h.data_fim, v_ref), v_ref)
         AND ld.data >= d.data_admissao
         AND (d.data_desligamento IS NULL OR ld.data < d.data_desligamento)
    LEFT JOIN _venda_dia vd ON vd.sk_vendedor = h.sk_vendedor AND vd.setor = h.setor
         AND vd.data = ld.data;

    CREATE TEMP TABLE _estat ON COMMIT DROP AS
    SELECT sk_vendedor, setor, count(*) AS dias_lotado, count(*) FILTER (WHERE valor > 0) AS dias_com_venda,
           sum(valor) AS receita, avg(valor) AS media_diaria,
           percentile_cont(v_pct) WITHIN GROUP (ORDER BY valor)::NUMERIC AS p25
    FROM _serie GROUP BY sk_vendedor, setor;

    -- média do p25 dos vendedores com histórico suficiente, por loja e setor e na rede
    CREATE TEMP TABLE _pares ON COMMIT DROP AS
    SELECT d.sk_loja, e.setor, avg(e.p25) AS p25_medio, count(*) AS vendedores
    FROM _estat e JOIN dw.dim_vendedor d ON d.sk_vendedor = e.sk_vendedor
    WHERE e.dias_lotado >= v_min
      AND (d.data_desligamento IS NULL OR d.data_desligamento > v_ref)
    GROUP BY d.sk_loja, e.setor;
    CREATE TEMP TABLE _rede ON COMMIT DROP AS
    SELECT setor, avg(p25_medio) AS p25_medio FROM _pares GROUP BY setor;

    CREATE TEMP TABLE _loja_setor ON COMMIT DROP AS
    SELECT v.sk_loja, p.setor,
           sum(v.receita_liquida) / NULLIF((SELECT count(*) FROM _loja_dia l WHERE l.sk_loja = v.sk_loja), 0)
               AS media_diaria
    FROM dw.fato_vendas v JOIN dw.dim_tempo t ON t.sk_tempo = v.sk_tempo
    JOIN dw.dim_produto p ON p.sk_produto = v.sk_produto
    WHERE v.status = 'Concluída' AND t.data BETWEEN v_ini AND v_ref
    GROUP BY v.sk_loja, p.setor;

    INSERT INTO dw.desempenho_vendedor_setor (
        data_referencia, sk_vendedor, sk_loja, setor, lotado_na_referencia, dias_lotado,
        dias_com_venda, receita, media_diaria, p25_diaria, p25_fallback, nivel_fallback,
        usa_fallback, valor_conservador, confianca, media_loja_setor)
    SELECT v_ref, d.sk_vendedor, d.sk_loja, s.setor,
           EXISTS (SELECT 1 FROM dw.vendedor_setor_historico h
                   WHERE h.sk_vendedor = d.sk_vendedor AND h.setor = s.setor
                     AND v_ref BETWEEN h.data_inicio AND COALESCE(h.data_fim, DATE 'infinity')),
           COALESCE(e.dias_lotado, 0), COALESCE(e.dias_com_venda, 0), COALESCE(e.receita, 0),
           round(e.media_diaria, 2), round(e.p25, 2),
           round(COALESCE(pl.p25_medio, r.p25_medio), 2),
           CASE WHEN pl.p25_medio IS NOT NULL THEN 'loja' WHEN r.p25_medio IS NOT NULL THEN 'rede' END,
           COALESCE(e.dias_lotado, 0) < v_min,
           round(CASE WHEN COALESCE(e.dias_lotado, 0) >= v_min THEN e.p25
                      ELSE COALESCE(pl.p25_medio, r.p25_medio) END, 2),
           CASE WHEN COALESCE(e.dias_lotado, 0) >= v_alta THEN 'alta'
                WHEN COALESCE(e.dias_lotado, 0) >= v_min THEN 'media'
                WHEN pl.p25_medio IS NOT NULL THEN 'baixa'
                WHEN r.p25_medio IS NOT NULL THEN 'muito_baixa'
                ELSE 'sem_base' END,
           round(ls.media_diaria, 2)
    FROM dw.dim_vendedor d
    CROSS JOIN (SELECT DISTINCT setor FROM dw.dim_produto) s
    LEFT JOIN _estat e ON e.sk_vendedor = d.sk_vendedor AND e.setor = s.setor
    LEFT JOIN _pares pl ON pl.sk_loja = d.sk_loja AND pl.setor = s.setor
    LEFT JOIN _rede r ON r.setor = s.setor
    LEFT JOIN _loja_setor ls ON ls.sk_loja = d.sk_loja AND ls.setor = s.setor
    WHERE d.data_admissao <= v_ref AND (d.data_desligamento IS NULL OR d.data_desligamento > v_ref);
END $$;

COMMENT ON PROCEDURE dw.gravar_desempenho_vendedor_setor(DATE) IS 'Recalcula dw.desempenho_vendedor_setor para a data de referência (padrão: último dia com venda).';
