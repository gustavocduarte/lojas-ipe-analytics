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
