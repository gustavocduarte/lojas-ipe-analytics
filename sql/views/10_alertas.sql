-- Views para a página "Alertas" do Power BI (Fase 5). Só leem dw.alertas e as dimensões.
--
-- Convenção: o painel conta os alertas VIGENTES e INDEPENDENTES (um estouro de orçamento causado
-- por uma despesa atípica é derivado e não entra na contagem, mas aparece no detalhe, ligado à
-- origem). Alertas que a regra deixou de detectar (vigente = FALSE) ficam só no histórico.
-- Reaplicáveis: CREATE OR REPLACE VIEW.

CREATE OR REPLACE VIEW dw.vw_alertas_detalhe AS
SELECT a.sk_alerta,
       a.chave_alerta,
       a.tipo_alerta,
       ta.nome AS nome_tipo_alerta,
       ta.categoria,
       a.severidade,
       CASE a.severidade WHEN 'baixa' THEN 'Baixa' WHEN 'media' THEN 'Média'
                         WHEN 'alta' THEN 'Alta' ELSE 'Crítica' END AS severidade_nome,
       CASE a.severidade WHEN 'baixa' THEN 1 WHEN 'media' THEN 2 WHEN 'alta' THEN 3 ELSE 4
       END AS severidade_ordem,
       t.data AS data_alerta,
       t.ano,
       t.mes,
       t.nome_mes,
       l.cod_loja,
       l.nome_loja,
       l.uf,
       l.regiao,
       v.cod_vendedor,
       v.nome_vendedor,
       c.cod_centro_custo,
       c.nome_centro_custo,
       c.tipo_despesa,
       a.valor_envolvido,
       a.regra,
       a.explicacao,
       a.detalhe,
       a.status,
       CASE a.status WHEN 'novo' THEN 'Novo' WHEN 'em_analise' THEN 'Em análise'
                     WHEN 'resolvido' THEN 'Resolvido' ELSE 'Falso positivo' END AS status_nome,
       a.status_em,
       a.tratado_por,
       a.observacao,
       a.vigente,
       a.independente,
       CASE WHEN a.independente THEN 'Independente' ELSE 'Derivado' END AS origem_do_alerta,
       (a.vigente AND a.independente) AS conta_no_painel,
       coalesce(o.qtd_origens, 0) AS qtd_alertas_de_origem,
       o.alerta_origem_principal,
       a.id_carga_origem,
       a.id_carga_ultima,
       a.criado_em,
       a.atualizado_em
FROM dw.alertas a
JOIN dw.dim_tipo_alerta ta ON ta.tipo_alerta = a.tipo_alerta
LEFT JOIN dw.dim_tempo t ON t.sk_tempo = a.sk_tempo
LEFT JOIN dw.dim_loja l ON l.sk_loja = a.sk_loja
LEFT JOIN dw.dim_vendedor v ON v.sk_vendedor = a.sk_vendedor
LEFT JOIN dw.dim_centro_custo c ON c.sk_centro_custo = a.sk_centro_custo
LEFT JOIN LATERAL (
    SELECT count(*) AS qtd_origens,
           (array_agg(org.chave_alerta ORDER BY vi.contribuicao DESC))[1] AS alerta_origem_principal
    FROM dw.alerta_vinculos vi
    JOIN dw.alertas org ON org.sk_alerta = vi.sk_alerta_origem
    WHERE vi.sk_alerta_derivado = a.sk_alerta
) o ON TRUE;

CREATE OR REPLACE VIEW dw.vw_alertas_por_tipo AS
SELECT d.tipo_alerta, d.nome_tipo_alerta, d.categoria, d.severidade, d.severidade_nome,
       d.severidade_ordem, d.status, d.status_nome, d.independente,
       count(*) AS quantidade,
       coalesce(sum(d.valor_envolvido), 0) AS valor_envolvido_total
FROM dw.vw_alertas_detalhe d
WHERE d.vigente
GROUP BY d.tipo_alerta, d.nome_tipo_alerta, d.categoria, d.severidade, d.severidade_nome,
         d.severidade_ordem, d.status, d.status_nome, d.independente;

CREATE OR REPLACE VIEW dw.vw_alertas_por_loja AS
SELECT coalesce(d.cod_loja, 'CORP') AS cod_loja,
       coalesce(d.nome_loja, 'Corporativo (sem loja)') AS nome_loja,
       d.uf, d.regiao, d.tipo_alerta, d.nome_tipo_alerta, d.categoria, d.severidade,
       d.severidade_nome, d.severidade_ordem,
       count(*) AS quantidade,
       coalesce(sum(d.valor_envolvido), 0) AS valor_envolvido_total
FROM dw.vw_alertas_detalhe d
WHERE d.conta_no_painel
GROUP BY d.cod_loja, d.nome_loja, d.uf, d.regiao, d.tipo_alerta, d.nome_tipo_alerta, d.categoria,
         d.severidade, d.severidade_nome, d.severidade_ordem;

-- Todos os meses entre o primeiro e o último alerta, para cada tipo (meses sem alerta valem 0),
-- com média móvel de 3 meses da quantidade.
CREATE OR REPLACE VIEW dw.vw_alertas_tendencia_mensal AS
WITH meses AS (
    SELECT DISTINCT t.ano, t.mes, make_date(t.ano, t.mes, 1) AS mes_inicio
    FROM dw.dim_tempo t
    WHERE make_date(t.ano, t.mes, 1) BETWEEN
          (SELECT date_trunc('month', min(data_alerta))::DATE FROM dw.vw_alertas_detalhe
           WHERE conta_no_painel)
      AND (SELECT max(data_alerta) FROM dw.vw_alertas_detalhe WHERE conta_no_painel)),
por_mes AS (
    SELECT d.tipo_alerta, d.ano, d.mes, count(*) AS quantidade,
           coalesce(sum(d.valor_envolvido), 0) AS valor_envolvido_total
    FROM dw.vw_alertas_detalhe d
    WHERE d.conta_no_painel
    GROUP BY d.tipo_alerta, d.ano, d.mes)
SELECT m.ano, m.mes, m.mes_inicio, ta.tipo_alerta, ta.nome AS nome_tipo_alerta, ta.categoria,
       coalesce(p.quantidade, 0) AS quantidade,
       coalesce(p.valor_envolvido_total, 0) AS valor_envolvido_total,
       round(avg(coalesce(p.quantidade, 0)) OVER (
           PARTITION BY ta.tipo_alerta ORDER BY m.mes_inicio ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
       ), 2) AS media_movel_3m
FROM meses m
CROSS JOIN dw.dim_tipo_alerta ta
LEFT JOIN por_mes p ON p.tipo_alerta = ta.tipo_alerta AND p.ano = m.ano AND p.mes = m.mes;

-- Uma linha com os números dos cartões da página.
CREATE OR REPLACE VIEW dw.vw_alertas_resumo AS
SELECT count(*) FILTER (WHERE conta_no_painel) AS alertas_no_painel,
       count(*) FILTER (WHERE conta_no_painel AND status = 'novo') AS novos,
       count(*) FILTER (WHERE conta_no_painel AND status = 'em_analise') AS em_analise,
       count(*) FILTER (WHERE conta_no_painel AND status = 'resolvido') AS resolvidos,
       count(*) FILTER (WHERE conta_no_painel AND status = 'falso_positivo') AS falsos_positivos,
       count(*) FILTER (WHERE vigente AND NOT independente) AS derivados,
       count(*) FILTER (WHERE NOT vigente) AS deixaram_de_vigorar,
       count(*) FILTER (WHERE conta_no_painel AND severidade = 'critica') AS criticos,
       count(*) FILTER (WHERE conta_no_painel AND severidade = 'alta') AS altos,
       count(*) FILTER (WHERE conta_no_painel AND severidade = 'media') AS medios,
       count(*) FILTER (WHERE conta_no_painel AND severidade = 'baixa') AS baixos,
       coalesce(sum(valor_envolvido) FILTER (WHERE conta_no_painel), 0) AS valor_envolvido_total
FROM dw.vw_alertas_detalhe;

COMMENT ON VIEW dw.vw_alertas_detalhe IS 'Alertas com loja, vendedor, centro, tipo e tratamento já resolvidos (Power BI: detalhe).';
COMMENT ON VIEW dw.vw_alertas_por_tipo IS 'Alertas vigentes por tipo, severidade, status e origem (independente/derivado).';
COMMENT ON VIEW dw.vw_alertas_por_loja IS 'Alertas do painel por loja/UF, tipo e severidade; sem loja = corporativo.';
COMMENT ON VIEW dw.vw_alertas_tendencia_mensal IS 'Alertas do painel por mês e tipo, com meses vazios e média móvel de 3 meses.';
COMMENT ON VIEW dw.vw_alertas_resumo IS 'Cartões da página Alertas: totais por status e severidade.';
