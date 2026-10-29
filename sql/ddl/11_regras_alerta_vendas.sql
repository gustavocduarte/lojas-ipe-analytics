-- Regras de alerta sobre vendas: tipos, ordem de execução e limites (parâmetros de negócio).

INSERT INTO dw.dim_tipo_alerta (tipo_alerta, nome, categoria, descricao) VALUES
    ('margem_negativa', 'Venda abaixo do custo', 'vendas',
     'Item vendido por um valor líquido menor que o custo.'),
    ('venda_fora_horario', 'Venda fora do horário da loja', 'vendas',
     'Cupom registrado antes da abertura ou depois do fechamento da loja naquele dia.'),
    ('cupom_duplicado', 'Cupom duplicado', 'vendas',
     'Cupom com o mesmo item lançado mais de uma vez.'),
    ('venda_vendedor_inativo', 'Venda de vendedor inativo', 'vendas',
     'Cupom em data anterior à admissão ou posterior ao desligamento do vendedor.'),
    ('vendedor_cancelamento_alto', 'Cancelamento alto por vendedor', 'vendas',
     'Taxa de cancelamento do vendedor, numa janela móvel de meses, muito acima da taxa da rede.');

INSERT INTO etl.regras_alerta (tipo_alerta, versao, ordem) VALUES
    ('margem_negativa', 1, 20),
    ('venda_fora_horario', 1, 30),
    ('cupom_duplicado', 1, 40),
    ('venda_vendedor_inativo', 1, 50),
    ('vendedor_cancelamento_alto', 1, 60);

INSERT INTO etl.parametros_negocio (chave, valor, descricao) VALUES
    ('margem_sev_media', 0.15, 'Margem negativa: prejuízo sobre o custo a partir do qual a severidade é média.'),
    ('margem_sev_alta', 0.30, 'Margem negativa: prejuízo sobre o custo a partir do qual a severidade é alta.'),
    ('fora_horario_valor_alto', 500, 'Venda fora do horário: total do cupom (R$) a partir do qual a severidade é alta.'),
    ('cupom_duplicado_valor_alto', 1000, 'Cupom duplicado: valor repetido (R$) a partir do qual a severidade é alta.'),
    ('cancelamento_janela_meses', 3, 'Cancelamento alto: tamanho da janela móvel, em meses.'),
    ('cancelamento_sev_alta_multiplo', 6, 'Cancelamento alto: múltiplo da taxa da rede a partir do qual a severidade é alta.'),
    ('cancelamento_sev_critica_multiplo', 10, 'Cancelamento alto: múltiplo da taxa da rede a partir do qual a severidade é crítica.');
