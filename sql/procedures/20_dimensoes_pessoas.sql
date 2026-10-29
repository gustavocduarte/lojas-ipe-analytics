-- Cargas de vendedores e clientes (stg -> dw). Roteiro descrito em 00_comum.sql.

CREATE OR REPLACE PROCEDURE etl.carregar_vendedores(p_id_carga BIGINT)
LANGUAGE plpgsql AS $$
DECLARE v_validas INT; v_ins INT; v_upd INT;
BEGIN
    DROP TABLE IF EXISTS _lim_vendedores;
    CREATE TEMP TABLE _lim_vendedores ON COMMIT DROP AS
    SELECT s.arquivo_origem, s.linha_origem, c.*, l.sk_loja,
           r.coluna AS rej_coluna, r.valor AS rej_valor, r.motivo AS rej_motivo
    FROM stg.vendedores s
    CROSS JOIN LATERAL (SELECT
        etl.limpar_texto(s.cod_vendedor) AS cod_vendedor,
        etl.limpar_nome(s.nome_vendedor) AS nome_vendedor,
        etl.limpar_texto(s.cod_loja) AS cod_loja, etl.limpar_texto(s.cargo) AS cargo,
        initcap(etl.limpar_texto(s.turno)) AS turno,
        etl.limpar_data(s.data_admissao) AS data_admissao,
        etl.limpar_data(s.data_desligamento) AS data_desligamento,
        etl.limpar_numero(s.percentual_comissao) AS percentual_comissao) c
    LEFT JOIN dw.dim_loja l ON l.cod_loja = c.cod_loja
    LEFT JOIN LATERAL (
        SELECT q.coluna, q.valor, q.motivo FROM (VALUES
            (1, 'cod_vendedor', s.cod_vendedor, etl.motivo_texto(s.cod_vendedor, 10)),
            (2, 'nome_vendedor', s.nome_vendedor,
                COALESCE(etl.motivo_texto(s.nome_vendedor, 80),
                         etl.motivo_texto(c.nome_vendedor, 80))),
            (3, 'cod_loja', s.cod_loja,
                etl.motivo(s.cod_loja, l.sk_loja IS NULL, 'loja_inexistente')),
            (4, 'cargo', s.cargo, etl.motivo_texto(s.cargo, 30)),
            (5, 'turno', s.turno,
                etl.motivo(s.turno, c.turno NOT IN ('Manhã', 'Tarde', 'Integral'), 'turno_invalido')),
            (6, 'data_admissao', s.data_admissao,
                etl.motivo(s.data_admissao, c.data_admissao IS NULL, 'data_invalida')),
            (7, 'data_desligamento', s.data_desligamento,
                etl.motivo(s.data_desligamento, c.data_desligamento IS NULL, 'data_invalida', false)),
            (8, 'data_desligamento', s.data_desligamento,
                CASE WHEN c.data_desligamento < c.data_admissao
                     THEN 'desligamento_antes_da_admissao' END),
            (9, 'percentual_comissao', s.percentual_comissao,
                COALESCE(etl.motivo_valor(s.percentual_comissao, c.percentual_comissao),
                         CASE WHEN c.percentual_comissao >= 1000 THEN 'valor_fora_do_intervalo' END))
        ) q(ord, coluna, valor, motivo) WHERE q.motivo IS NOT NULL ORDER BY q.ord LIMIT 1
    ) r ON true
    WHERE s.id_carga = p_id_carga;

    CALL etl.rejeitar_duplicadas('vendedores', 'cod_vendedor', 'cod_vendedor', 't.cod_vendedor',
                                 'ultima');
    CALL etl.contar_correcao(p_id_carga, 'vendedores', 'nome_vendedor', 'nome_espacos_caixa',
                             's.nome_vendedor IS DISTINCT FROM t.nome_vendedor');
    CALL etl.contar_correcao(p_id_carga, 'vendedores', 'data_admissao', 'data_formato_misto',
                             $q$s.data_admissao ~ '^\s*\d{4}-'$q$);
    CALL etl.contar_correcao(p_id_carga, 'vendedores', 'data_desligamento', 'data_formato_misto',
                             $q$s.data_desligamento ~ '^\s*\d{4}-'$q$);

    SELECT count(*) INTO v_validas FROM _lim_vendedores WHERE rej_motivo IS NULL;
    WITH up AS (
        INSERT INTO dw.dim_vendedor AS d (cod_vendedor, nome_vendedor, sk_loja, cargo, turno,
                                          data_admissao, data_desligamento, percentual_comissao)
        SELECT cod_vendedor, nome_vendedor, sk_loja, cargo, turno, data_admissao,
               data_desligamento, percentual_comissao
        FROM _lim_vendedores WHERE rej_motivo IS NULL
        ON CONFLICT (cod_vendedor) DO UPDATE SET nome_vendedor = EXCLUDED.nome_vendedor,
            sk_loja = EXCLUDED.sk_loja, cargo = EXCLUDED.cargo, turno = EXCLUDED.turno,
            data_admissao = EXCLUDED.data_admissao,
            data_desligamento = EXCLUDED.data_desligamento,
            percentual_comissao = EXCLUDED.percentual_comissao
        WHERE (d.nome_vendedor, d.sk_loja, d.cargo, d.turno, d.data_admissao,
               d.data_desligamento, d.percentual_comissao)
            IS DISTINCT FROM (EXCLUDED.nome_vendedor, EXCLUDED.sk_loja, EXCLUDED.cargo,
                              EXCLUDED.turno, EXCLUDED.data_admissao, EXCLUDED.data_desligamento,
                              EXCLUDED.percentual_comissao)
        RETURNING (xmax = 0) AS inserida)
    SELECT count(*) FILTER (WHERE inserida), count(*) FILTER (WHERE NOT inserida)
    INTO v_ins, v_upd FROM up;
    CALL etl.fechar_entidade(p_id_carga, 'vendedores', v_ins, v_upd, v_validas - v_ins - v_upd);
END $$;

CREATE OR REPLACE PROCEDURE etl.carregar_clientes(p_id_carga BIGINT)
LANGUAGE plpgsql AS $$
DECLARE v_validas INT; v_ins INT; v_upd INT;
BEGIN
    DROP TABLE IF EXISTS _lim_clientes;
    CREATE TEMP TABLE _lim_clientes ON COMMIT DROP AS
    SELECT s.arquivo_origem, s.linha_origem, c.*,
           r.coluna AS rej_coluna, r.valor AS rej_valor, r.motivo AS rej_motivo
    FROM stg.clientes s
    CROSS JOIN LATERAL (SELECT
        etl.limpar_texto(s.cod_cliente) AS cod_cliente, etl.limpar_texto(s.cidade) AS cidade,
        upper(etl.limpar_texto(s.uf)) AS uf, etl.limpar_texto(s.faixa_etaria) AS faixa_etaria,
        etl.limpar_data(s.data_cadastro_fidelidade) AS data_cadastro_fidelidade) c
    LEFT JOIN LATERAL (
        SELECT q.coluna, q.valor, q.motivo FROM (VALUES
            (1, 'cod_cliente', s.cod_cliente, etl.motivo_texto(s.cod_cliente, 10)),
            (2, 'cidade', s.cidade, etl.motivo_texto(s.cidade, 60)),
            (3, 'uf', s.uf, etl.motivo(s.uf, c.uf !~ '^[A-Z]{2}$', 'uf_invalida')),
            (4, 'faixa_etaria', s.faixa_etaria, etl.motivo_texto(s.faixa_etaria, 10)),
            (5, 'data_cadastro_fidelidade', s.data_cadastro_fidelidade,
                etl.motivo(s.data_cadastro_fidelidade, c.data_cadastro_fidelidade IS NULL,
                           'data_invalida'))
        ) q(ord, coluna, valor, motivo) WHERE q.motivo IS NOT NULL ORDER BY q.ord LIMIT 1
    ) r ON true
    WHERE s.id_carga = p_id_carga;

    CALL etl.rejeitar_duplicadas('clientes', 'cod_cliente', 'cod_cliente', 't.cod_cliente',
                                 'ultima');
    CALL etl.contar_correcao(p_id_carga, 'clientes', 'data_cadastro_fidelidade',
                             'data_formato_misto', $q$s.data_cadastro_fidelidade ~ '^\s*\d{4}-'$q$);

    SELECT count(*) INTO v_validas FROM _lim_clientes WHERE rej_motivo IS NULL;
    WITH up AS (
        INSERT INTO dw.dim_cliente AS d (cod_cliente, cidade, uf, faixa_etaria,
                                         data_cadastro_fidelidade)
        SELECT cod_cliente, cidade, uf, faixa_etaria, data_cadastro_fidelidade
        FROM _lim_clientes WHERE rej_motivo IS NULL
        ON CONFLICT (cod_cliente) DO UPDATE SET cidade = EXCLUDED.cidade, uf = EXCLUDED.uf,
            faixa_etaria = EXCLUDED.faixa_etaria,
            data_cadastro_fidelidade = EXCLUDED.data_cadastro_fidelidade
        WHERE (d.cidade, d.uf, d.faixa_etaria, d.data_cadastro_fidelidade)
            IS DISTINCT FROM (EXCLUDED.cidade, EXCLUDED.uf, EXCLUDED.faixa_etaria,
                              EXCLUDED.data_cadastro_fidelidade)
        RETURNING (xmax = 0) AS inserida)
    SELECT count(*) FILTER (WHERE inserida), count(*) FILTER (WHERE NOT inserida)
    INTO v_ins, v_upd FROM up;
    CALL etl.fechar_entidade(p_id_carga, 'clientes', v_ins, v_upd, v_validas - v_ins - v_upd);
END $$;
