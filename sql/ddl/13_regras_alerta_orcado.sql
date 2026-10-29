-- Regra de despesa acima do orçado, com alertas derivados.

INSERT INTO dw.dim_tipo_alerta (tipo_alerta, nome, categoria, descricao) VALUES
    ('despesa_acima_orcado', 'Despesa acima do orçado', 'despesas',
     'Centro de custo com despesa do mês muito acima do orçado. Pode ser derivado de outros alertas.');

-- Roda por último: depende dos alertas de origem já gravados na mesma geração.
INSERT INTO etl.regras_alerta (tipo_alerta, versao, ordem) VALUES ('despesa_acima_orcado', 1, 110);

INSERT INTO etl.parametros_negocio (chave, valor, descricao) VALUES
    ('orcado_sev_alta_multiplo', 1.6, 'Despesa acima do orçado: múltiplo do orçado a partir do qual a severidade é alta.'),
    ('orcado_sev_critica_multiplo', 2.0, 'Despesa acima do orçado: múltiplo do orçado a partir do qual a severidade é crítica.');
