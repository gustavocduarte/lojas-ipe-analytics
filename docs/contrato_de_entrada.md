# Contrato de entrada

Este documento lista, para cada entidade, as colunas que o sistema precisa receber.
Cada fonte de dados (o ERP da Lojas Ipê, uma planilha de outra empresa etc.) é ligada a
este contrato por um arquivo de mapeamento em `config/fontes/`, que diz qual coluna da
fonte corresponde a cada coluna abaixo.

Este arquivo é gerado por `python -m src.etl.contrato`; não edite à mão.

Tipos: `texto`, `inteiro`, `decimal`, `data`, `hora`. Todos chegam ao staging como texto
cru; a conversão e a limpeza acontecem na carga para o data warehouse.

`linha_origem` é a posição da linha de dados no arquivo, contada a partir de 1 na
primeira linha depois do cabeçalho (sem contar linhas ignoradas).

## lojas

Cadastro das lojas da rede.

Chave natural: `cod_loja`

| Coluna | Tipo | Obrigatória | Significado | Se vier vazia |
|---|---|---|---|---|
| `cod_loja` | texto | sim | Código da loja (chave). | rejeita a linha |
| `nome_loja` | texto | sim | Nome da loja. | rejeita a linha |
| `uf` | texto | sim | Sigla do estado, 2 letras. | rejeita a linha |
| `regiao` | texto | sim | Região do país (Sudeste, Nordeste, Sul, Centro-Oeste, Norte). | rejeita a linha |
| `cidade` | texto | sim | Cidade da loja. | rejeita a linha |
| `formato` | texto | sim | Formato da loja (Hipermercado, Supermercado, Express). | rejeita a linha |
| `data_abertura` | data | sim | Data de inauguração da loja. | rejeita a linha |

## horarios_loja

Horário de funcionamento de cada loja por dia da semana.

Chave natural: `cod_loja`, `dia_semana`

| Coluna | Tipo | Obrigatória | Significado | Se vier vazia |
|---|---|---|---|---|
| `cod_loja` | texto | sim | Código da loja. | rejeita a linha |
| `dia_semana` | inteiro | sim | Dia da semana, de 1 (segunda) a 7 (domingo). | rejeita a linha |
| `hora_abertura` | hora | sim | Hora de abertura. | rejeita a linha |
| `hora_fechamento` | hora | sim | Hora de fechamento (depois da abertura). | rejeita a linha |

## produtos

Cadastro de produtos (SKU).

Chave natural: `sku`

| Coluna | Tipo | Obrigatória | Significado | Se vier vazia |
|---|---|---|---|---|
| `sku` | texto | sim | Código do produto (chave). Espaços e caixa são normalizados. | rejeita a linha |
| `nome_produto` | texto | sim | Descrição do produto. | rejeita a linha |
| `marca` | texto | sim | Marca do produto. | rejeita a linha |
| `setor` | texto | sim | Setor (Alimentos, Bebidas, Limpeza, Casa, Eletro, ...). | rejeita a linha |
| `categoria` | texto | sim | Categoria dentro do setor. | rejeita a linha |
| `custo_unitario` | decimal | sim | Custo unitário em R$ (não negativo). | rejeita a linha |
| `preco_lista` | decimal | sim | Preço de lista em R$ (não negativo). | rejeita a linha |

## centros_custo

Centros de custo das despesas (de loja ou corporativos).

Chave natural: `cod_centro_custo`

| Coluna | Tipo | Obrigatória | Significado | Se vier vazia |
|---|---|---|---|---|
| `cod_centro_custo` | texto | sim | Código do centro de custo (chave). | rejeita a linha |
| `nome_centro_custo` | texto | sim | Nome do centro de custo. | rejeita a linha |
| `tipo_despesa` | texto | sim | Pessoal, Terceiros ou Discricionárias. | rejeita a linha |
| `cod_loja` | texto | não | Loja do centro; vazio = centro corporativo. | aceita vazio |

## feriados

Feriados nacionais.

Chave natural: `data`

| Coluna | Tipo | Obrigatória | Significado | Se vier vazia |
|---|---|---|---|---|
| `data` | data | sim | Data do feriado (chave). | rejeita a linha |
| `nome_feriado` | texto | sim | Nome do feriado. | rejeita a linha |

## formas_pagamento

Formas de pagamento aceitas.

Chave natural: `cod_forma_pagamento`

| Coluna | Tipo | Obrigatória | Significado | Se vier vazia |
|---|---|---|---|---|
| `cod_forma_pagamento` | texto | sim | Código da forma de pagamento (chave). | rejeita a linha |
| `nome_forma_pagamento` | texto | sim | Nome (Pix, Débito, Crédito à vista, ...). | rejeita a linha |

## campanhas

Campanhas promocionais.

Chave natural: `cod_campanha`

| Coluna | Tipo | Obrigatória | Significado | Se vier vazia |
|---|---|---|---|---|
| `cod_campanha` | texto | sim | Código da campanha (chave). | rejeita a linha |
| `nome_campanha` | texto | sim | Nome da campanha. | rejeita a linha |
| `data_inicio` | data | sim | Primeiro dia da campanha. | rejeita a linha |
| `data_fim` | data | sim | Último dia da campanha (não anterior ao início). | rejeita a linha |
| `desconto_medio_pct` | decimal | sim | Desconto médio da campanha, em % (5 = 5%). | rejeita a linha |

## vendedores

Cadastro de vendedores, com admissão e desligamento.

Chave natural: `cod_vendedor`

| Coluna | Tipo | Obrigatória | Significado | Se vier vazia |
|---|---|---|---|---|
| `cod_vendedor` | texto | sim | Código do vendedor (chave). | rejeita a linha |
| `nome_vendedor` | texto | sim | Nome; espaços extras e caixa são normalizados. | rejeita a linha |
| `cod_loja` | texto | sim | Loja do vendedor. | rejeita a linha |
| `cargo` | texto | sim | Cargo. | rejeita a linha |
| `turno` | texto | sim | Manhã, Tarde ou Integral. | rejeita a linha |
| `data_admissao` | data | sim | Data de admissão. | rejeita a linha |
| `data_desligamento` | data | não | Data de desligamento; vazio = ainda ativo. | aceita vazio |
| `percentual_comissao` | decimal | sim | Comissão em % (2 = 2%). | rejeita a linha |

## clientes

Clientes do programa de fidelidade (sem dados pessoais identificáveis).

Chave natural: `cod_cliente`

| Coluna | Tipo | Obrigatória | Significado | Se vier vazia |
|---|---|---|---|---|
| `cod_cliente` | texto | sim | Código do cliente (chave). | rejeita a linha |
| `cidade` | texto | sim | Cidade de residência. | rejeita a linha |
| `uf` | texto | sim | Sigla do estado, 2 letras. | rejeita a linha |
| `faixa_etaria` | texto | sim | Faixa etária (ex.: 25-34). | rejeita a linha |
| `data_cadastro_fidelidade` | data | sim | Data de entrada no programa. | rejeita a linha |

## vendas

Itens de cupom de venda (uma linha por item).

Chave natural: `id_venda_erp`

| Coluna | Tipo | Obrigatória | Significado | Se vier vazia |
|---|---|---|---|---|
| `id_venda_erp` | texto | sim | Identificador do item no ERP (chave). | rejeita a linha |
| `numero_cupom` | texto | sim | Número do cupom. | rejeita a linha |
| `numero_item` | inteiro | sim | Posição do item no cupom (1, 2, ...). | rejeita a linha |
| `data_venda` | data | sim | Data da venda. | rejeita a linha |
| `hora_venda` | hora | sim | Hora da venda. | rejeita a linha |
| `cod_loja` | texto | sim | Loja da venda. | rejeita a linha |
| `caixa` | inteiro | sim | Número do caixa (PDV). | rejeita a linha |
| `cod_vendedor` | texto | sim | Vendedor do cupom. | rejeita a linha |
| `cod_cliente` | texto | não | Cliente identificado; vazio = não identificado. | aceita vazio |
| `cod_forma_pagamento` | texto | sim | Forma de pagamento. | rejeita a linha |
| `numero_parcelas` | inteiro | sim | Parcelas (1 = à vista). | rejeita a linha |
| `cod_campanha` | texto | não | Campanha aplicada; vazio = sem campanha. | aceita vazio |
| `sku` | texto | sim | Produto vendido. Espaços e caixa são normalizados. | rejeita a linha |
| `quantidade` | inteiro | sim | Quantidade (maior que zero). | rejeita a linha |
| `preco_unitario` | decimal | sim | Preço unitário praticado em R$. | rejeita a linha |
| `desconto` | decimal | sim | Desconto do item em R$. | recalcula: quantidade * preco_unitario - receita_liquida |
| `receita_liquida` | decimal | sim | Valor líquido do item em R$ (bruto - desconto). | rejeita a linha |
| `custo_total` | decimal | sim | Custo do item em R$ (quantidade * custo unitário). | rejeita a linha |
| `total_cupom` | decimal | sim | Valor total do cupom (soma dos itens), em R$. | rejeita a linha |
| `status` | texto | sim | Concluída, Cancelada ou Devolvida. | rejeita a linha |
| `motivo_cancelamento_devolucao` | texto | não | Motivo; obrigatório quando o status não é Concluída. | aceita vazio |

## metas_vendas

Meta mensal de vendas por loja e setor.

Chave natural: `competencia`, `cod_loja`, `setor`

| Coluna | Tipo | Obrigatória | Significado | Se vier vazia |
|---|---|---|---|---|
| `competencia` | data | sim | Mês da meta (primeiro dia do mês). | rejeita a linha |
| `cod_loja` | texto | sim | Loja. | rejeita a linha |
| `setor` | texto | sim | Setor. | rejeita a linha |
| `valor_meta` | decimal | sim | Meta em R$ (não negativa). | rejeita a linha |

## metas_vendedor

Meta mensal de vendas por vendedor.

Chave natural: `competencia`, `cod_vendedor`

| Coluna | Tipo | Obrigatória | Significado | Se vier vazia |
|---|---|---|---|---|
| `competencia` | data | sim | Mês da meta (primeiro dia do mês). | rejeita a linha |
| `cod_vendedor` | texto | sim | Vendedor. | rejeita a linha |
| `valor_meta` | decimal | sim | Meta em R$ (não negativa). | rejeita a linha |

## despesas

Lançamentos de despesa.

Chave natural: nenhuma (a linha é identificada pelo arquivo e pela posição nele)

| Coluna | Tipo | Obrigatória | Significado | Se vier vazia |
|---|---|---|---|---|
| `numero_documento` | texto | sim | Número do documento do lançamento. | rejeita a linha |
| `data_lancamento` | data | sim | Data do lançamento. | rejeita a linha |
| `cod_centro_custo` | texto | sim | Centro de custo. | rejeita a linha |
| `valor` | decimal | sim | Valor em R$. | rejeita a linha |
| `descricao` | texto | não | Descrição do lançamento. | preenche com 'NAO INFORMADO' |
| `fornecedor` | texto | não | Fornecedor. | aceita vazio |

## orcamento_despesas

Orçamento mensal de despesa por centro de custo.

Chave natural: `competencia`, `cod_centro_custo`

| Coluna | Tipo | Obrigatória | Significado | Se vier vazia |
|---|---|---|---|---|
| `competencia` | data | sim | Mês do orçamento (primeiro dia do mês). | rejeita a linha |
| `cod_centro_custo` | texto | sim | Centro de custo. | rejeita a linha |
| `valor_orcado` | decimal | sim | Valor orçado em R$ (não negativo). | rejeita a linha |
