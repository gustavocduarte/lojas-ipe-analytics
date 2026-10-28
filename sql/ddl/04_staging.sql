-- Staging: tudo em texto, uma tabela por arquivo do ERP, na ordem original das colunas.
-- arquivo_origem e linha_origem permitem rastrear cada registro até o CSV.

CREATE TABLE stg.lojas (
    cod_loja TEXT, nome_loja TEXT, uf TEXT, regiao TEXT, cidade TEXT, formato TEXT,
    data_abertura TEXT,
    arquivo_origem TEXT, linha_origem INTEGER, carregado_em TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE stg.horarios_loja (
    cod_loja TEXT, dia_semana TEXT, hora_abertura TEXT, hora_fechamento TEXT,
    arquivo_origem TEXT, linha_origem INTEGER, carregado_em TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE stg.produtos (
    sku TEXT, nome_produto TEXT, marca TEXT, setor TEXT, categoria TEXT, custo_unitario TEXT,
    preco_lista TEXT,
    arquivo_origem TEXT, linha_origem INTEGER, carregado_em TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE stg.centros_custo (
    cod_centro_custo TEXT, nome_centro_custo TEXT, tipo_despesa TEXT, cod_loja TEXT,
    arquivo_origem TEXT, linha_origem INTEGER, carregado_em TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE stg.feriados (
    data TEXT, nome_feriado TEXT,
    arquivo_origem TEXT, linha_origem INTEGER, carregado_em TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE stg.formas_pagamento (
    cod_forma_pagamento TEXT, nome_forma_pagamento TEXT,
    arquivo_origem TEXT, linha_origem INTEGER, carregado_em TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE stg.campanhas (
    cod_campanha TEXT, nome_campanha TEXT, data_inicio TEXT, data_fim TEXT,
    desconto_medio_pct TEXT,
    arquivo_origem TEXT, linha_origem INTEGER, carregado_em TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE stg.vendedores (
    cod_vendedor TEXT, nome_vendedor TEXT, cod_loja TEXT, cargo TEXT, turno TEXT,
    data_admissao TEXT, data_desligamento TEXT, percentual_comissao TEXT,
    arquivo_origem TEXT, linha_origem INTEGER, carregado_em TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE stg.clientes (
    cod_cliente TEXT, cidade TEXT, uf TEXT, faixa_etaria TEXT, data_cadastro_fidelidade TEXT,
    arquivo_origem TEXT, linha_origem INTEGER, carregado_em TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE stg.vendas (
    id_venda_erp TEXT, numero_cupom TEXT, numero_item TEXT, data_venda TEXT, hora_venda TEXT,
    cod_loja TEXT, caixa TEXT, cod_vendedor TEXT, cod_cliente TEXT, cod_forma_pagamento TEXT,
    numero_parcelas TEXT, cod_campanha TEXT, sku TEXT, quantidade TEXT, preco_unitario TEXT,
    desconto TEXT, receita_liquida TEXT, custo_total TEXT, total_cupom TEXT, status TEXT,
    motivo_cancelamento_devolucao TEXT,
    arquivo_origem TEXT, linha_origem INTEGER, carregado_em TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE stg.metas_vendas (
    competencia TEXT, cod_loja TEXT, setor TEXT, valor_meta TEXT,
    arquivo_origem TEXT, linha_origem INTEGER, carregado_em TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE stg.metas_vendedor (
    competencia TEXT, cod_vendedor TEXT, valor_meta TEXT,
    arquivo_origem TEXT, linha_origem INTEGER, carregado_em TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE stg.despesas (
    numero_documento TEXT, data_lancamento TEXT, cod_centro_custo TEXT, valor TEXT,
    descricao TEXT, fornecedor TEXT,
    arquivo_origem TEXT, linha_origem INTEGER, carregado_em TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE stg.orcamento_despesas (
    competencia TEXT, cod_centro_custo TEXT, valor_orcado TEXT,
    arquivo_origem TEXT, linha_origem INTEGER, carregado_em TIMESTAMP NOT NULL DEFAULT now()
);
