# Metodologia das metas de venda

As metas deste projeto (sintético) representam o **esperado do período**: o que a rede planejaria
vender com base no histórico e no calendário comercial, com um esforço pequeno. Elas **não** são
derivadas do realizado do mês que está sendo avaliado (isso faria a meta "acompanhar" a venda e tiraria
o sentido da cobertura).

Implementação: `src/gerador/metas.py` (cálculo), `src/calendario_comercial.py` (pesos do calendário),
`sql/views/20_meta_diaria.sql` (meta diária) e `scripts/simular_metas.py` (conferência dos percentuais).
Para regenerar só as metas: `python -m src.gerador --so-metas`.

## Por que não usa o realizado do mês

A regra anterior calculava `meta = realizado do mês ÷ atingimento da loja`, com um atingimento fixo por
loja e ruído de 6%. Como a meta saía da venda do próprio mês, ela embutia o resultado: a rede ficava em
97–100% em quase todo mês, lojas como Recife e Niterói nunca batiam e outras sempre batiam, e a meta
diária (sem eventos) deixava a primeira quinzena de dezembro quase toda "vermelha".

## Meta de loja × setor × mês

Taxa de um mês = realizado do mês ÷ peso do calendário do mês (loja e setor; só dias depois da abertura
da loja). Só meses **anteriores** ao da meta entram nas taxas.

| Quando | Regra |
|---|---|
| Primeiros 12 meses do período (2024) | **Orçamento inicial**: esperado estrutural do gerador × (1 + esforço) × ruído normal(1; 3%). Como se o orçamento tivesse sido feito no fim do ano anterior. |
| A partir do 13º mês (2025), com o mesmo mês do ano anterior e uma tendência medida | **Regra A**: taxa do mesmo mês do ano anterior × tendência × peso do calendário × (1 + esforço). |
| Falta o ano anterior ou a tendência (jan/2025, ou loja que ainda não tinha o ano anterior) | **Regra B**: média das taxas dos até 3 meses anteriores × peso do calendário × (1 + esforço). |
| Loja nova, sem nenhum histórico (Brasília, 1º mês) | **Regra C**: taxa por m² das lojas do mesmo formato no mês anterior × `area_m2` × peso do calendário × (1 + esforço). |

* **Esforço** (`ESFORCO_META` em `src/config.py`): **0%**. O orçamento estrutural de 2024 já fica cerca de
  0,7% acima do realizado; um esforço extra (testamos +1%) empurrava o batimento para baixo do alvo
  (2024: lojas 44%, setores 43%, dias 39%, rede acima em 4 de 12 meses).
* **Tendência**: soma das taxas dos 3 meses anteriores ÷ soma das taxas dos mesmos 3 meses do ano
  anterior (por loja, somando os setores), limitada a 0,90–1,25. Quando só uma parte dos 3 meses tem par
  no ano anterior (fev e mar/2025), usa os pares que existem; em jan/2025 não há par nenhum e vale a regra B.
* **Esperado estrutural** (`esperado_estrutural`): troca cada sorteio do gerador pela sua média (itens do
  mês repartidos por dia e loja, mix de setor, preço de lista, quantidade, desconto, cancelamento e
  devolução). Não usa nenhuma venda realizada. Ele fica, em média, 0,7% acima do realizado em 2024.
* **Peso do calendário**: dia da semana, feriados, Natal (janela de 18 a 24/12 e dia 25), véspera de
  Ano-Novo, Black Friday, Dia das Mães, Carnaval, volta às aulas e o multiplicador de cada setor, **sem**
  a tendência anual. Uma empresa real conhece tudo isso com antecedência.
* A meta só existe para o que a loja já podia vender: nenhuma meta antes da abertura, e o mês de abertura
  só pesa os dias após a abertura.

## Meta diária

`dw.vw_meta_vendas_diaria` reparte a meta do mês pelos dias com os pesos de `etl.pesos_calendario`
(carregados por `python -m src.banco --calendario`): Natal, Black Friday, Dia das Mães etc. entram na
repartição, e dias anteriores à abertura da loja pesam zero. A soma dos dias continua batendo exatamente
com a meta do mês (o último dia absorve o arredondamento). Se a data não tiver peso na tabela, a view usa
os pesos simples de antes (dia da semana × feriado).

## Meta do vendedor

`meta do vendedor = meta da loja no mês × participação do vendedor`.

* Participação = receita do vendedor nos 3 meses anteriores ÷ receita da loja nesses meses.
* Vendedor sem histórico recebe a **média** das participações da loja; as participações são normalizadas.
* No primeiro mês do período (ninguém tem histórico) a participação é estrutural: desempenho × dias
  ativos no mês × peso do turno (meio turno = 0,5).
* Recebem meta os vendedores com vínculo ativo em algum dia do mês (admissão e desligamento do cadastro).
  Quem não vendeu no mês fica com cobertura 0%.
* A soma das metas dos vendedores é **exatamente** a meta da loja (o vendedor de maior participação
  absorve o arredondamento). O gerador não produz vendas sem vendedor.
* A meta diária do vendedor segue a curva diária da meta da loja.

## Resultado (2024–2025, esforço 0%)

Cobertura ≥ 100% (batimento), em média por mês. Reproduzível com
`python scripts/simular_metas.py validar` (metas carregadas no dw) ou
`python scripts/simular_metas.py simular --esforco 0 0.01` (recalcula em memória).

| Ano | Lojas-mês | Setores-mês | Vendedores-mês | Dias da rede | Meses com a rede acima | Cobertura média da rede |
|---|---|---|---|---|---|---|
| 2024 | 48% | 46% | 45% | 41% | 5/12 | 99,2% |
| 2025 | 52% | 51% | 49% | 44% | 6/12 | 100,2% |

Dezembro/2025 até o dia 15: 9 de 15 lojas acima da meta, rede em 102,8% e 8 de 15 dias acima da meta
(antes da recalibração: 4 de 15 lojas e rede em 89%). Antes, a meta de 1 a 15/12 era R$ 418.361 contra
R$ 372.449 vendidos; agora é R$ 362.218.

Os dias da rede ficam um pouco abaixo de 45% porque os dias de evento (Black Friday, Natal) vencem a meta
por muito, e os demais ficam perto dela.
