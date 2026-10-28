-- Índices de apoio às consultas analíticas (PKs e UNIQUEs já criam os seus).
-- FKs não ganham índice automático no PostgreSQL, então criamos os que importam.

-- fato_vendas: período/hora, loja, vendedor, cliente, produto, campanha e busca por cupom
CREATE INDEX ix_fato_vendas_tempo_loja ON dw.fato_vendas (sk_tempo, sk_loja);
CREATE INDEX ix_fato_vendas_loja       ON dw.fato_vendas (sk_loja);
CREATE INDEX ix_fato_vendas_vendedor   ON dw.fato_vendas (sk_vendedor, sk_tempo);
CREATE INDEX ix_fato_vendas_cliente    ON dw.fato_vendas (sk_cliente) WHERE sk_cliente IS NOT NULL;
CREATE INDEX ix_fato_vendas_produto    ON dw.fato_vendas (sk_produto);
CREATE INDEX ix_fato_vendas_campanha   ON dw.fato_vendas (sk_campanha) WHERE sk_campanha IS NOT NULL;
CREATE INDEX ix_fato_vendas_hora       ON dw.fato_vendas (sk_hora);
CREATE INDEX ix_fato_vendas_forma_pag  ON dw.fato_vendas (sk_forma_pagamento);
CREATE INDEX ix_fato_vendas_cupom      ON dw.fato_vendas (numero_cupom, numero_item);
CREATE INDEX ix_fato_vendas_status     ON dw.fato_vendas (status) WHERE status <> 'Concluída';

-- fato_despesas: período, centro de custo e busca de duplicidades por documento
CREATE INDEX ix_fato_despesas_tempo_cc  ON dw.fato_despesas (sk_tempo, sk_centro_custo);
CREATE INDEX ix_fato_despesas_cc        ON dw.fato_despesas (sk_centro_custo);
CREATE INDEX ix_fato_despesas_documento ON dw.fato_despesas (numero_documento);

-- metas e orçamento: o UNIQUE (sk_tempo, ...) já cobre sk_tempo; falta o outro lado do join
CREATE INDEX ix_fato_meta_vendas_loja    ON dw.fato_meta_vendas (sk_loja);
CREATE INDEX ix_fato_meta_vendedor_vend  ON dw.fato_meta_vendedor (sk_vendedor);
CREATE INDEX ix_fato_orcamento_cc        ON dw.fato_orcamento_despesas (sk_centro_custo);

-- dimensões
CREATE INDEX ix_dim_produto_setor      ON dw.dim_produto (setor);
CREATE INDEX ix_dim_vendedor_loja      ON dw.dim_vendedor (sk_loja);
CREATE INDEX ix_dim_centro_custo_loja  ON dw.dim_centro_custo (sk_loja);
CREATE INDEX ix_dim_tempo_ano_mes      ON dw.dim_tempo (ano, mes);
