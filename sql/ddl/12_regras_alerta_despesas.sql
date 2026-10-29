-- Regras de alerta sobre despesas: tipos, ordem de execução e limites (parâmetros de negócio).

INSERT INTO dw.dim_tipo_alerta (tipo_alerta, nome, categoria, descricao) VALUES
    ('despesa_documento_repetido', 'Documento de despesa repetido', 'despesas',
     'Mesmo número de documento lançado mais de uma vez.'),
    ('despesa_fim_semana_feriado', 'Despesa em fim de semana ou feriado', 'despesas',
     'Lançamento datado em sábado, domingo ou feriado nacional.'),
    ('despesa_valor_atipico', 'Despesa de valor atípico', 'despesas',
     'Lançamento muito acima da mediana dos lançamentos do mesmo centro de custo.'),
    ('despesa_centro_incompativel', 'Despesa no centro de custo errado', 'despesas',
     'Descrição do lançamento incompatível com o tipo do centro (tipo dominante dessa descrição).');

INSERT INTO etl.regras_alerta (tipo_alerta, versao, ordem) VALUES
    ('despesa_documento_repetido', 1, 70),
    ('despesa_fim_semana_feriado', 1, 80),
    ('despesa_valor_atipico', 1, 90),
    ('despesa_centro_incompativel', 1, 100);

INSERT INTO etl.parametros_negocio (chave, valor, descricao) VALUES
    ('documento_repetido_valor_alto', 5000, 'Documento repetido: valor repetido (R$) a partir do qual a severidade é alta.'),
    ('valor_atipico_sev_alta_multiplo', 10, 'Valor atípico: múltiplo da mediana do centro a partir do qual a severidade é alta.'),
    ('centro_incompativel_min_ocorrencias', 30, 'Centro incompatível: mínimo de lançamentos com a mesma descrição para aprender seu tipo dominante.'),
    ('centro_incompativel_participacao_min', 0.9, 'Centro incompatível: participação mínima do tipo dominante entre os lançamentos da descrição.');
