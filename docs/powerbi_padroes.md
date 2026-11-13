# Padrões do relatório Power BI (PBIR)

Receitas para editar o `.pbip` em texto (com o Power BI **fechado**). Cada item diz se foi **confirmado** (gravado/aprovado no Power BI Desktop), **documentado** (nome e valores no schema oficial de temas, mas ainda não conferidos na tela) ou **a confirmar**.

## Formatação condicional "Valor do campo" (cor por medida) — confirmado

Em barras e colunas, o Power BI grava em `visual.objects.dataPoint` uma entrada com o seletor `dataViewWildcard`, sem `metadata`:

```json
"dataPoint": [
  {
    "properties": {
      "fill": { "solid": { "color": { "expr": { "Measure": {
        "Expression": { "SourceRef": { "Entity": "Medidas" } },
        "Property": "Cor da cobertura" } } } } }
    },
    "selector": { "data": [ { "dataViewWildcard": { "matchingOption": 1 } } ] }
  }
]
```

- A medida devolve o texto `#RRGGBB`.
- Cartão: a cor do valor usa o mesmo `solid.color.expr.Measure` em `objects.value[].properties.fontColor`, com `selector: {"id": "default"}`.
- Cor fixa de uma série (linhas, colunas sem status): `fill` com `{"solid":{"color":{"expr":{"Literal":{"Value":"'#2F6DB5'"}}}}}` e `selector: {"metadata": "Medidas.<medida>"}` — a confirmar.

## Propriedades

| Efeito | Onde | Valor | Situação |
|---|---|---|---|
| Linha reta | `objects.lineStyles[].properties.lineChartType` | `'linear'` (o tema Fluent2 define `smooth`; o schema só aceita `linear`, `smooth`, `step`) | `'normal'` funcionou na tela, mas não existe no schema: usar `'linear'` |
| Linha tracejada | `lineStyles[]` com `selector.metadata` da série e `lineStyle: 'dashed'` | `solid`, `dashed`, `dotted` | documentado; seletor a confirmar |
| Esconder legenda | `objects.legend[].properties.show` | `false` | confirmado |
| Subtítulo automático | `visualContainerObjects.subTitle[].properties.show` | `false` | confirmado |
| Título próprio | `visualContainerObjects.title[].properties.show/text/fontSize` | `true`, `'Texto'`, `14D` | confirmado |
| Subtítulo dinâmico (medida) | `subTitle[].properties.text` = `{"expr":{"Measure":{...}}}` | medida de texto | a confirmar |
| Cartão sem abreviação | `objects.value[].properties.labelDisplayUnits` | `1D` (Nenhum; `0D` é Automático) | confirmado |
| Rótulo de dados | `objects.labels[].properties.show` | `true` | documentado |
| Linha de referência (constante) | barras: `y1AxisReferenceLine`/`xAxisReferenceLine` (`show`, `value`, `lineColor`, `style`, `width`) | — | documentado; qual dos dois nas barras horizontais, a confirmar |
| Interações da página | `page.json` → `visualInteractions[]` `{source,target,type}` com `DataFilter`, `HighlightFilter`, `NoFilter`, `Default` | — | documentado no schema da página |
| Tooltips com mais campos | `query.queryState.Tooltips.projections[]` | medidas | a confirmar |
| Faixa e texto | visual `textbox`: `objects.general[].properties.paragraphs[].textRuns[]`; fundo em `visualContainerObjects.background` | — | a confirmar |
| Barras divergentes (diferença % para a meta) | `clusteredColumnChart`: `Y` = medida %, cor por `dataPoint.fill` com o mesmo padrão `dataViewWildcard` (medida `Cor da diferença`); `labels.show/fontSize/labelDisplayUnits/labelPrecision` | `labelPrecision` `1L` | documentado; conferir na tela |
| Rótulo de eixo `dd dia-da-semana` | coluna calculada `Calendário[Dia e semana]` (`FORMAT(data,"dd") & " " & LOWER(LEFT(nome_dia_semana,3))`) com `sortByColumn: data`; no visual, `sortDefinition` pela própria coluna | — | documentado |
| Linha do zero destacada | colunas/barras: `objects.y1AxisReferenceLine[]` com `selector:{id:"linha_zero"}` e `show`, `value` (`0D`), `lineColor`, `style` (`'solid'`), `width` (`2D`), `position` (`'front'`) — nomes do schema de temas | — | documentado; conferir na tela |
| Grade discreta | `objects.valueAxis[].properties.gridlineShow/gridlineColor/gridlineThickness` (`#E3E7ED`, `1D`) | — | confirmado (o Power BI gravou `gridlineColor` e `gridlineThickness`) |
| Rótulo com o formato da medida (sinal +/−) | **não** gravar `labelPrecision` nem `labelDisplayUnits` em `labels`: eles substituem o formato da medida e perdem o sinal | — | documentado; conferir na tela |
| Rótulo de eixo que nunca quebra linha | usar espaço não separável (`UNICHAR(160)`) na coluna do rótulo e fonte menor em `categoryAxis.fontSize` | — | documentado |
| Nome de exibição na legenda | `query.queryState.Y.projections[].displayName` (a medida não é renomeada; o `queryRef` e os seletores `metadata` continuam iguais) | — | a confirmar |
| Segmentação legível em faixa escura | cartão branco: `visualContainerObjects.background` branco e `border` `#E3E7ED`, sobre a faixa (a faixa é a caixa de texto, 1920 de largura) | — | documentado |
| Barras de dados na tabela | — | — | manual (copiar do que o Power BI gravar) |

## Tema

- Arquivo `StaticResources/RegisteredResources/tema_lojas_ipe.json`, registrado em `report.json` (`themeCollection.customTheme` + pacote `RegisteredResources`). Validado contra `reportThemeSchema-2.145.json` (repositório `microsoft/powerbi-desktop-samples`).
- O tema personalizado vem por cima do base (Fluent2): o que o Fluent2 define por tipo de visual (ex.: título de cartão e de tabela desligado, interpolação `smooth` nos gráficos de linha) só muda se o personalizado também definir aquele tipo.
- Paleta: azul-escuro `#1F3A5F` (títulos, faixa), azul `#2F6DB5` (realizado), laranja `#C55A11` (meta), cinza `#9AA5B1` (projeção), verde `#2E7D32` / vermelho `#C62828` (só status), fundo da página `#F3F5F8`, borda `#E3E7ED`. Fonte Segoe UI; títulos 14 pt, rótulos 12 pt, valor dos cartões 28 pt.

## Eixo e posição

- O gráfico de acumulado usa `'Eixo do mês'[dia]`, tabela sem relação com o resto, para mostrar o mês inteiro mesmo com a segmentação cortando o Calendário na posição. As medidas `(linha)` devolvem vazio fora do mês da posição, e o gráfico descarta os dias sem valor.
- `[Posição]` = último dia com venda concluída no contexto de data (ignora loja/setor/vendedor). A previsão só entra quando existe um corte (`treino_ate`) igual à posição.

## Cuidados

- Tamanho de página padrão: 1920 × 1080.
- O schema `visualContainer/2.14.0` não existe no site; validar contra a 2.13.0 (não valida o conteúdo de `objects`).
- Ao salvar, o Power BI reescreve os arquivos (acrescenta `active`, entradas extras de `dataPoint` etc.); regenerar a página pelo script sobrescreve esses ajustes.

- **Lição da linha do zero:** ligar "linha" no formato do Eixo Y grava só `valueAxis.gridlineColor/gridlineThickness` (a grade toda escura e grossa; a mais visível cai em +50%). Para destacar o zero usar a linha de referência (`y1AxisReferenceLine`, valor 0).

- **Regra: linha desativada se remove do JSON, não só se desliga.** Linhas de referência (`y1AxisReferenceLine`/`xAxisReferenceLine`) e grades que ficaram `show: false` voltam a aparecer se alguém religar e confundem a leitura. Cada visual deve ter só as linhas que usa: no gráfico de diferença, uma `y1AxisReferenceLine` em 0 (sólida, `#5B6B7C`, largura 2) e a grade discreta; nada mais.
- **Linha constante nas barras horizontais:** o eixo de valores é o horizontal, então usar `xAxisReferenceLine` (nas colunas, `y1AxisReferenceLine`), com `selector.id` próprio — a confirmar na tela. Para a linha de 100% aparecer, fixar `valueAxis.start/end` (ex.: 0 a 1,2).
- **Sem rolagem em barras:** 15 categorias pedem ~25 px cada: altura 456, fonte 10 pt no eixo e nos rótulos.
- **Propriedades redundantes:** não gravar `subTitle.show=false` onde o tema já desliga, nem `legend.show=false` em gráfico de uma medida só.

## Ranking com N categorias, sem rolagem (gravado pelo Power BI)

O que o Power BI gravou no ranking das lojas (15 categorias), depois do ajuste manual:

- Fonte do eixo: `objects.categoryAxis[].properties.fontSize` = `11D`; rótulos de dados: `objects.labels[].properties.fontSize` = `11D`.
- Tamanho: o visual ficou com 619,35 × 435,61 (posição fracionária 1275,87 / 260,13). **Nenhuma propriedade de espaçamento entre barras foi gravada** (não há `innerPadding` nem equivalente em `categoryAxis`/`general`): o ganho de espaço vem só da altura e da fonte.
- **Regra:** para N categorias sem barra de rolagem, reservar ~25 px por categoria (N × 25) mais ~90 px de título e eixo, com fonte de 10 a 11 pt. Para 15 lojas: altura mínima ≈ 465; usado 436 com fonte 11. Se aparecer rolagem, aumentar a altura antes de mexer em propriedades.
- Depois de salvar no Power BI, a posição vira fracionária; pode ficar assim (o Power BI aceita).

## O que o Power BI gravou nas linhas constantes (gráfico de diferença)

- `y1AxisReferenceLine[]` da linha em 0: `show`, `value` `0D`, `style` `'solid'`, `width` `2D`, `position` `'front'` e `lineColor` como `ThemeDataColor` (`ColorId` 1 = cor de primeiro plano do tema; `ColorId` 0 = branco). Aceita cor literal `'#RRGGBB'` também.
- Ao clicar em "Adicionar linha" no painel Análise sem preencher, o Power BI deixa uma entrada órfã `{show, displayName: 'Linha Constante do Eixo Y 0'}` com `selector.id` = `"NaN"`. **Remover do JSON**: é a linha desativada/sem valor.
- A grade do eixo de valores foi gravada com `gridlineShow` `false` e `valueAxis.fontSize` `9D`: o destaque do zero vem só da linha constante.

## Páginas Lojas e Detalhe da loja — pendências manuais (copiar o JSON depois)

| Efeito | Onde | O que o Power BI deve gravar | Situação |
|---|---|---|---|
| Botões "10 piores \| 10 melhores" | segmentação de `'Modo do ranking'[Modo]` (tabela desconectada) | `selection.strictSingleSelect` e filtro padrão gravados por texto; **estilo de botões/lado a lado: manual** (copiar o que o Power BI gravar) | a confirmar |
| Hierarquia com drill-down | mesmo visual: trocar o eixo `nome_loja` pela hierarquia `Lojas[Geografia]` (Região → UF → Loja) e ligar o drill | `HierarchyLevel` nas projeções de `Category` (com `active`) | manual |
| Drill-through | páginas Detalhe da loja e Diagnóstico da loja: Campos de drill-through = `Lojas[nome_loja]`, manter todos os filtros ligado, botão de voltar | `page.json`: `filterConfig.filters[]` com `howCreated: "Drillthrough"` + `pageBinding` (ver seção abaixo); botão `actionButton` com `visualLink.type = 'Back'` | gravado pelo Power BI (Diagnóstico) e replicado no Detalhe |
| Linha em 100% e eixo 0–120% no ranking | `xAxisReferenceLine` (`linha_100`) + `valueAxis.start/end` | — | a confirmar na tela |

## Filtro N inferior (Top N) gravado pelo Power BI — confirmado

Aplicado à mão, "N inferior = 10 por `Cobertura da meta até o dia`" gravou em `visual.filterConfig.filters[]` (o visual foi o da dispersão, não o ranking):

```json
{ "name": "...", "field": { "Column": { "Expression": { "SourceRef": { "Entity": "Lojas" } }, "Property": "nome_loja" } },
  "type": "TopN",
  "filter": { "Version": 2,
    "From": [ { "Name": "subquery", "Type": 2, "Expression": { "Subquery": { "Query": { "Version": 2,
        "From": [ { "Name": "l", "Entity": "Lojas", "Type": 0 }, { "Name": "m", "Entity": "Medidas", "Type": 0 } ],
        "Select": [ { "Column": { "Expression": { "SourceRef": { "Source": "l" } }, "Property": "nome_loja" }, "Name": "field" } ],
        "OrderBy": [ { "Direction": 1, "Expression": { "Measure": { "Expression": { "SourceRef": { "Source": "m" } }, "Property": "Cobertura da meta até o dia" } } } ],
        "Top": 10 } } } },
      { "Name": "l", "Entity": "Lojas", "Type": 0 } ],
    "Where": [ { "Condition": { "In": { "Expressions": [ { "Column": { "Expression": { "SourceRef": { "Source": "l" } }, "Property": "nome_loja" } } ],
        "Table": { "SourceRef": { "Source": "subquery" } } } } } ] } }
```

- `Direction: 1` = crescente (N **inferior**); decrescente (N superior) seria `2`. `Top` é o N.
- Ao abrir o painel Filtros, o Power BI também deixou entradas `type: "Advanced"` sem `filter` (uma por medida do visual): são só os campos listados, sem condição.
- Substituído nas lojas pelo modo "10 piores | 10 melhores" (abaixo), porque o Top N fixo não alterna.

## Ranking com botões 10 piores | 10 melhores (sem bookmarks) — a confirmar na tela

- Tabela calculada `'Modo do ranking'` (`DATATABLE`, sem relação) com `Modo` (ordenada por `Ordem`).
- `Posição no ranking (modo)`: `RANKX` sobre `ALLSELECTED(Lojas[nome_loja])` (só lojas com cobertura), crescente no modo 1 e decrescente no 2; `Mostrar no ranking` = 1 se posição ≤ `Tamanho do ranking` (parâmetro, 10).
- No visual: `filterConfig` `Advanced` por medida (`Comparison`, `ComparisonKind` 0 = igual, `1L`); a ordem usa a posição (medida no bucket `Tooltips`, só para ordenar); título dinâmico = `title.text` com `expr.Measure` (mesma forma do subtítulo dos cartões).
- Filtro de medida no visual não altera o contexto: o ranking continua calculado sobre todas as lojas selecionadas.
- Filtro "só lojas com falta > 0": `Advanced` com `ComparisonKind: 1` (maior que) e `0D`.

## Rótulo da meta do mês no gráfico de acumulado — não funcionou

Formato dinâmico (`formatStringDefinition`) para mostrar "Meta do mês: R$ …" só no último ponto: o Power BI aceitou a sintaxe (grava a linha depois do `lineageTag`, separada por linha em branco), mas o rótulo não apareceu. Solução usada: o valor vai no **subtítulo do gráfico** (`Subtítulo do acumulado`, medida de texto) e no tooltip.

## Regras de TMDL/DAX aprendidas no Power BI (confirmado)

- **`formatString` com texto entre aspas:** o valor inteiro vai entre aspas, com as internas dobradas. Errado: `formatString: "falta R$ "#,0.00;;"meta batida"`. Certo: `formatString: """falta R$ ""#,0.00;;""meta batida"""`. (`"R$" #,0.00`, com um único par de aspas, o Power BI aceita como está.) O `validar.py` acusa `formatString` com mais de 2 aspas sem dobrar.
- **Ordem do `RANKX` é constante:** o 4º argumento só aceita `ASC`, `DESC`, `0` ou `1`. `IF(melhores, DESC, ASC)` quebra o filtro do ranking com "Broken_Filters". Para alternar a ordem, repetir o `RANKX`: `IF(melhores, RANKX(t, expr, , DESC, DENSE), RANKX(t, expr, , ASC, DENSE))`. O `validar.py` acusa ordem que não seja constante.
- **Segmentação em fila (botões):** lista vertical numa caixa baixa mostra só o 1º item; `objects.general.orientation` = `1D` (horizontal) põe as opções lado a lado (a confirmar na tela). Aspecto de botão/azulejo e seleção única obrigatória: ver "Botões" acima.

## Segmentação em botões lado a lado (gravado pelo Power BI) — confirmado

Depois do estilo de botões aplicado à mão na segmentação `'Modo do ranking'[Modo]`, o `visual.json` ficou (trecho de `objects`):

```json
"selection": [ { "properties": { "strictSingleSelect": { "expr": { "Literal": { "Value": "true" } } } } } ],
"header":    [ { "properties": { "show": { "expr": { "Literal": { "Value": "false" } } } } } ],
"general":   [ { "properties": {
    "filter": { "filter": { "...": "In [ '10 melhores' ]  (a opção selecionada ao salvar)" } },
    "orientation": { "expr": { "Literal": { "Value": "1D" } } } } } ]
```

- O "estilo de botões" é só `general.orientation = 1D` (horizontal) + `selection.strictSingleSelect = true`; **nenhuma outra propriedade de estilo foi gravada**. A caixa precisa de largura para as opções (420 × 44 para duas).
- `general.filter` guarda a seleção atual: salvar com "10 melhores" escolhido grava esse padrão. Para o padrão ser "10 piores", salvar com ela selecionada (ou trocar o valor no JSON).

## Segmentação suspensa de loja com busca (página Detalhe da loja) — a confirmar na tela

`slicer` de `Lojas[nome_loja]`: `data.mode = 'Dropdown'`, `selection.singleSelect = true` e `selection.selectAllCheckboxEnabled = false` (sem "Selecionar tudo"), `general.selfFilterEnabled = true` (campo de busca), título "Loja" e subtítulo dinâmico (`Contexto da loja`). Sem seleção a página mostra a rede.

- **Drill-through e seletor de loja não convivem:** com um seletor de loja na página, o drill-through aplicava os dois filtros (loja de origem E loja do seletor) e a página ficava vazia. Por isso Detalhe da loja e Diagnóstico da loja não têm seletor: a loja vem do filtro de detalhamento (salvo com Ipê Brasília para quem abre a página pela aba) e o cabeçalho mostra a medida `Loja escolhida (cabeçalho)`.

## Seletor de loja na faixa e larguras de coluna (Detalhe da loja) — a confirmar na tela

- **Seletor:** a segmentação suspensa fica numa caixa branca (y 34, altura 50) com fonte de 16 pt (`objects.items.fontSize`); o rótulo "Loja" é uma caixa de texto branca acima (a segmentação, no cartão branco, não pode ter título branco). Sem título nem subtítulo próprios.
- **Subtítulo da faixa:** um `cardVisual` sem fundo nem borda, com a medida `Faixa da loja` (cidade · UF · formato ou "Todas as lojas", mais a posição dos dados), à esquerda sob o título; o parágrafo estático foi retirado da caixa de texto da faixa.
- **Largura de coluna em tabela:** `objects.columnWidth[]` com `selector.metadata` = `queryRef` da coluna e `properties.value` = `150D`; o ajuste automático é `objects.columnHeaders[].properties.autoSizeColumnWidth = false` (nomes a confirmar; se o Power BI não reagir, arrastar uma coluna à mão e copiar o JSON gravado).

## Correções da rodada do Detalhe da loja

- **Meta do vendedor e loja:** `Vendedores` não tem relação com `Lojas`; as medidas de meta do vendedor usam `TREATAS(VALUES(Lojas[sk_loja]), Vendedores[sk_loja])` dentro de `CALCULATE`. Sem isso o total de uma loja mostrava a meta da rede inteira. Conferido no banco: Ipê Brasília, 6 vendedores, meta até 15/12 = R$ 15.797,72; rede = R$ 412.712,28.
- **Texto sem chrome sobre a faixa:** o `cardVisual` mostrava caixa branca mesmo com `background`/`border` desligados em `visualContainerObjects`; usar o cartão clássico (`visualType: "card"`, `objects.labels.color/fontSize`, `categoryLabels.show=false`) com fundo e borda desligados — a confirmar na tela.
- **Texto no lugar de vazio:** `Evolução vs ano anterior (texto)` devolve "loja sem histórico" quando a receita do ano anterior é zero; a cor continua vindo de `Cor da evolução`.

## Tabelas preenchem o cartão (rodada de acabamento)

**Regra:** a tabela sempre preenche a largura útil do cartão: soma das colunas = largura do visual − margens (usamos 28 px: padding do contêiner + folga da barra de rolagem). Sem rolagem horizontal, `autoSizeColumnWidth = false` e `columnWidth` em todas as colunas (selector `metadata` = queryRef).

| Tabela | Largura do cartão | Colunas (soma) | Fonte |
|---|---|---|---|
| Desempenho por setor (Vendas vs Meta) | 1020 | 200+170+170+140+140+172 = 992 | 13 (cabeçalho, valores, total em negrito) |
| Vendedores da loja (Detalhe) | 1020 | 260+150+150+150+120+162 = 992 | 13 |
| Todas as lojas (Lojas) | 1872 | 280+90+240+200+200+200+160+240+234 = 1844 | 12 |

- Altura das linhas: `grid.rowPadding` (6 a 9 px). **A confirmar na tela:** nomes `grid.rowPadding` e `total.bold`; se não valerem, ajustar à mão uma vez e copiar o JSON para cá.
- Cartões de evolução: o rótulo vem do `displayName` da projeção ("Evolução vs ano anterior"); a medida `Evolução vs ano anterior (texto)` não é renomeada.
- Vendedores sem loja escolhida: filtro visual `Loja única escolhida = 1` (tabela vazia na rede) e a orientação vai no **título** da própria tabela (medida `Título dos vendedores`), sem cartão sobreposto (que mostrava "(Em branco)" e cobria a tabela). Ajuste de tamanho: margem de 56 px (28 não bastou: a última coluna saía pela direita); colunas 240+140+145+145+118+176 = 964; fonte 12, `grid.rowPadding` 2; cabem ~10 linhas em 324 px de altura, e a rolagem vertical só aparece acima disso (a maior loja tem 19 vendedores).
- Meta de vendedor × meta da loja: com a recalibração das metas (`docs/metodologia_metas.md`) a soma das metas dos vendedores é a meta da loja. Em 1–15/12/2025, Brasília tem meta da loja de R$ 15.096,06 e dos vendedores de R$ 15.096,02 (a diferença de centavos vem do arredondamento diário), com cobertura de 77,1% nas duas; Florianópolis, R$ 12.459,82 e R$ 12.459,84 (receita R$ 14.447,77, cobertura 116,0%). Antes da recalibração as metas por vendedor cobriam menos que a da loja (Brasília: R$ 15.797,72 contra R$ 17.220,82).

## Rodada de melhorias, etapa 1: medidas de análise, mesmas lojas e área da loja

- **Cascata:** `Receita bruta` (preço × quantidade, todos os status) − `Desconto` (concluídas) − `Cancelamentos (R$)` − `Devoluções (R$)` (valor bruto) = `Receita`. `Conferência da cascata` deve dar 0,00 em qualquer contexto. Conferido no banco (histórico inteiro e 1–15/12/2025).
- **Mês anterior (mesmo intervalo):** `CALCULATE([... acumulado no mês], DATEADD('Calendário'[data], -1, MONTH))`; em mês de 31 dias contra um de 30 o intervalo anterior termina no dia 30.
- **Mesmas lojas:** loja comparável = `Lojas[data_abertura] < EDATE([Posição], -12)`; só DAX, sem coluna calculada (a posição muda com a segmentação).
- **Área (m²):** `dw.dim_loja.area_m2` (opcional no contrato). `Venda por m²` = receita ÷ área das lojas com receita no contexto, no período selecionado (não é anualizada). **Regra de exibição:** o valor principal nas páginas é `Venda por m² no mês (projetada)` (projeção de fechamento ÷ área; um mês inteiro, comparável a referências de mercado); a `Venda por m²` do período fica só no tooltip e serve para comparar lojas entre si. O rótulo sempre diz o período.
- **Vendedores ativos:** vendedores com venda concluída no contexto, não o cadastro.
- **Conferência de números:** nas rodadas de melhoria uma página temporária (segmentação 01–15/12/2025) confere os números na tela e é removida antes do commit.

## Rodada de melhorias, etapa 3 (Lojas e Comparação de lojas)

- **Lojas:** a tabela "Todas as lojas" virou matriz (`pivotTable`, linhas = loja; colunas = medidas), com receita, meta, cobertura, projeção, evolução, evolução mesmas lojas, ticket médio, margem %, participação e `Venda por m² no mês (projetada)`. Larguras somam 1816 px (largura − 56). Barras de dados são manuais (Formatar → Elementos da célula → Barras de dados).
- **Comparação de lojas (página nova):** quadrantes "Crescimento de faturamento × crescimento de rentabilidade" (X = `Evolução vs ano anterior`, Y = `Variação da margem vs ano anterior %`, bolha = receita, cor = `Cor do quadrante` a partir de `Quadrante`, linhas de referência em 0; os nomes dos 4 cantos são caixas de texto, porque medida não serve de legenda). Escolheu-se a evolução geral, e não a de mesmas lojas, porque por loja as duas coincidem (loja sem histórico fica em branco nas duas) e a geral também funciona nos totais, árvore de decomposição da receita (Região → UF → Loja → Setor), venda por m² projetada por loja (a do período no tooltip) e margem % por loja.
- Propriedades ainda não confirmadas no JSON: linhas de referência da dispersão, objetos da matriz (`rowHeaders`, `columnWidth`) e a árvore de decomposição; se o Power BI regravar, copiar o JSON para cá.

### Barras de dados na matriz (gerado pelo Power BI Desktop)

Objeto `columnFormatting` da matriz (`pivotTable`), um item por medida (seletor `metadata`); fica na lista `objects`, ao lado de `values` e `columnWidth`:

```json
{
  "properties": {
    "dataBars": {
      "positiveColor": {
        "solid": {
          "color": {
            "expr": {
              "Literal": {
                "Value": "'maxColor'"
              }
            }
          }
        }
      },
      "negativeColor": {
        "solid": {
          "color": {
            "expr": {
              "Literal": {
                "Value": "'minColor'"
              }
            }
          }
        }
      },
      "axisColor": {
        "solid": {
          "color": {
            "expr": {
              "Literal": {
                "Value": "'foreground'"
              }
            }
          }
        }
      },
      "reverseDirection": {
        "expr": {
          "Literal": {
            "Value": "false"
          }
        }
      },
      "hideText": {
        "expr": {
          "Literal": {
            "Value": "false"
          }
        }
      },
      "totalMatchingOption": {
        "expr": {
          "Literal": {
            "Value": "1L"
          }
        }
      }
    }
  },
  "selector": {
    "metadata": "Medidas.<nome da medida>"
  }
}
```

### Regra do validador: um displayName por queryRef

Em um mesmo visual, cada `queryRef` só pode ter um `displayName`. Se a medida aparece em mais de um papel (por exemplo eixo e `Tooltips`), o `displayName` tem que ser idêntico ou omitido; senão o Power BI recusa abrir o relatório ("Este queryRef só pode ter um displayName"). O `validar.py` confere todos os `visual.json`.

### Etapa 3, ajustes finais

- Quadrantes sem campo de tamanho (bolhas uniformes), rótulos de categoria em fonte 8.
- `Margem vs rede (p.p.)` = (`Margem %` − margem % de todas as lojas do contexto) × 100, formato `+0.0\ \p\.\p\.` (sem aspas, para não precisar escapar); barras verdes/vermelhas por `Cor da margem vs rede`.
- Cartão `Evolução mesmas lojas` na faixa de KPIs da página Lojas (5 cartões de 360 px, passo 378); a coluna saiu da matriz porque por loja repete a `Evolução`.

### Tabelas e fonte; vendedores no Detalhe da loja

- **Tamanho mínimo de fonte em tabelas = 12pt** (canvas 1920×1080; o painel também vai para a TV). Não reduzir a fonte para evitar rolagem; se não couber, preferir gráfico de barras.
- **Detalhe da loja:** a tabela de vendedores foi trocada pelo gráfico de barras "Vendedores: cobertura da meta até o dia" (de 6 a 15 vendedores, a grossura das barras se ajusta ao painel; sem rolagem). Mesmo estilo do gráfico de setores; cor por `Cor da cobertura (vendedor)`; linha tracejada em 100%; tooltip com cargo, receita, meta até o dia e ticket médio. O filtro `Loja única escolhida = 1` e o `TREATAS` das metas do vendedor continuam; o subtítulo (`Subtítulo dos vendedores`) traz a orientação quando não há uma loja só. Painéis de baixo em y = 621, altura 399 (fundo em 1020).
- **Pendência:** quando a página Vendedores for criada, este gráfico deve ganhar drill-through para ela (nome do vendedor como filtro de detalhamento), no mesmo padrão de Lojas → Detalhe da loja.

### Regra do validador: coluna em Tooltips tem que ser agregada

Em visuais que não são tabela nem matriz, uma coluna solta em `Tooltips` vira agrupamento extra e dá o erro "primary projections must have set equality with the corresponding subset in the filter target". Use agregação (`Aggregation`, por exemplo `Min(Vendedores.cargo)`). O `validar.py` confere todos os `visual.json`.

### Regra de interações: visual de detalhe de vendedor não filtra os KPIs da loja

O gráfico "Vendedores: cobertura da meta até o dia" (Detalhe da loja) tem interação **Nenhum** (`NoFilter`) com todos os outros visuais da página; os outros visuais continuam filtrando ele. Senão, clicar numa barra faz os cartões compararem a receita do vendedor com a meta da loja (cobertura 31,7%, "loja sem histórico") e a venda diária fica toda vermelha. Vale para qualquer visual de detalhe de vendedor novo.
- **Drill-through (gravado pelo Power BI na página Diagnóstico, replicado no Detalhe):** o filtro de detalhamento é um filtro de página e o `pageBinding` aponta para ele pelo nome. Estrutura de `page.json` (nomes de filtro e parâmetro são hex aleatórios por página):

```json
"filterConfig": { "filters": [ {
  "name": "<id do filtro>",
  "field": { "Column": { "Expression": { "SourceRef": { "Entity": "Lojas" } }, "Property": "nome_loja" } },
  "type": "Categorical",
  "filter": { "Version": 2, "From": [ { "Name": "l", "Entity": "Lojas", "Type": 0 } ],
    "Where": [ { "Condition": { "In": {
      "Expressions": [ { "Column": { "Expression": { "SourceRef": { "Source": "l" } }, "Property": "nome_loja" } } ],
      "Values": [ [ { "Literal": { "Value": "'Ipê Brasília'" } } ] ] } } } ] },
  "howCreated": "Drillthrough" } ] },
"pageBinding": { "name": "<id>", "type": "Drillthrough",
  "parameters": [ { "name": "<id>", "boundFilter": "<id do filtro>", "asAggregation": false, "qnaSingleSelectRequired": false,
    "fieldExpr": { "Column": { "Expression": { "SourceRef": { "Entity": "Lojas" } }, "Property": "nome_loja" } } } ] }
```

  O valor do filtro (`Values`) é a loja padrão de quando a página é aberta pela aba (Ipê Brasília); o drill-through o substitui. Botão de voltar: `actionButton` com `icon.shapeType = 'back'` e `visualLink.type = 'Back'`, em x=24, y=56 (110×32), abaixo do título, igual nas duas páginas. Cabeçalho: botão, faixa da loja (x=146) e cartão `Loja escolhida (cabeçalho)` (x=760). Medidas com `HASONEVALUE(Lojas[nome_loja])` (`Uma loja escolhida`, `Loja única escolhida`, `Faixa da loja`) funcionam com o filtro de detalhamento, pois ele filtra `Lojas`.
- Cartões de rótulo: o nome da medida é o rótulo do cartão (`Meta vs venda do ano anterior`, `Fluxo de cupons vs ano anterior`); não usar sufixos como "(texto)" em medida exibida.

### Metas de vendedor não são por setor: visual de setor não filtra visual de vendedor

A meta do vendedor é da loja inteira, não de um setor. Se um clique no gráfico de setores filtrar o gráfico de vendedores, a venda do setor é comparada com a meta total do vendedor e a cobertura sai errada (ex.: 7,8%). Por isso, nas páginas Detalhe da loja e Diagnóstico da loja, `visualInteractions` tem `NoFilter` de Setores para Vendedores (cartões e venda diária podem continuar filtrados por setor).

### Formatação condicional em tabela (`tableEx`)

A cor por linha (`values[].properties.fontColor` com `solid.color.expr.Measure`) só vale por linha com o seletor `{"data": [{"dataViewWildcard": {"matchingOption": 1}}], "metadata": "<queryRef da coluna>"}`; só com `metadata` o Power BI ignora a medida (em cartão basta `metadata`). Cores da Situação: verde `#2E7D32` ponto forte, vermelho `#C62828` atenção, âmbar `#B26A00` contexto da meta (folgada/apertada, não é mérito), cinza `#6B7280` neutro ou sem base. Para esconder o tema quando a lista só tem a mensagem, a medida de cor devolve branco (`Cor do tema (atenção)`/`(forte)`).

### Medidas de "rede" e o RLS

Referência da rede sem loja: `Referência da rede` (ticket, desconto e, agora, `custo` para `Margem % da rede`). Ainda dependem de `ALLSELECTED(Lojas)`/`ALLSELECTED(Setores)` e quebrariam com RLS por loja (o gerente passaria a ver a si mesmo como a "rede"): `Posição da loja no ranking`, `Cobertura da pior loja`, `Pior loja`, `Posição no ranking (modo)`, `Participação da loja %` e `Participação do setor %` (esta só pelo denominador de setores, que não depende de loja). O ranking entre lojas e a participação na rede só fazem sentido para a Matriz; para o gerente devem sumir ou usar uma tabela agregada sem loja, como `Referência da rede`.

O gráfico de vendedores não fica na página Diagnóstico da loja: ele já existe no Detalhe da loja (e entrará na página Vendedores), e a linha Equipe da tabela de indicadores resume a equipe. Com 15 vendedores (São Paulo) o gráfico rolava mesmo no menor tamanho. Na linha de baixo do Diagnóstico, Pontos de atenção e Pontos fortes dividem a largura (924 px cada, 24 px entre eles).

Medidas "vs rede": devolver BLANK() quando a medida da loja é vazia (`IF(NOT ISBLANK([Margem %]), ...)`); sem isso, ao selecionar uma loja num gráfico as outras mostram "vazio − rede" (ex.: 30,0 p.p.).

No Desktop o filtro de detalhamento (`howCreated: "Drillthrough"`) **não aparece** no painel Filtros ("Filtros nesta página" fica vazio), então não dá para trocar a loja por ali. Decisão: a troca é pelo botão direito numa loja na página Lojas (Drill-through). O cabeçalho avisa isso ("para trocar: botão direito numa loja na página Lojas") e a medida `Loja escolhida (cabeçalho)` não menciona o painel Filtros.

O Power BI grava estado de tela nos visuais ao salvar (segmentação '10 melhores' selecionada, `expansionStates` e `insights` da árvore de decomposição). Antes de commitar, conferir `git diff` desses visuais e voltar o estado padrão editando o JSON.

## Cores parametrizadas

As cores do relatório ficam no banco: `etl.parametros_cores` (`chave`, `cor` com CHECK `#RRGGBB`, `descricao`; `sql/ddl/27_parametros_cores.sql`), lida pela view `dw.vw_parametros_cores` (`sql/views/24_cores.sql`) e pela tabela `Parâmetros de cores` do modelo (colunas ocultas). Cada chave tem uma medida base `Cor: <nome>` (pasta `4. Formatação`, `LOOKUPVALUE` pela chave), e **toda medida de cor usa essas medidas base**, nunca `"#RRGGBB"` no DAX. Chaves: `verde`, `vermelho`, `vermelho_claro`, `ambar`, `laranja_quadrante`, `azul_quadrante`, `cinza`, `cinza_texto`. Há **um só âmbar** (`#B26A00`) para o relatório inteiro, inclusive a probabilidade. Cor nova = linha em `27_parametros_cores.sql` + medida base `Cor: <nome>`. Exceção: `Cor do tema (atenção/forte)` (texto e fundo da lista) fica com literais. Os literais de cor dentro dos `visual.json` (linhas de referência, rótulos) estão fora desta regra por ora. `tests/test_cores_banco.py` confere que as chaves usadas pelo modelo existem no banco e que o DAX não tem cor fixa.
