# Macros VBA do relatório de fechamento

O relatório de fechamento (`python -m src.relatorios fechamento`) pode sair como `.xlsx` simples
ou como `.xlsm` com três macros:

| Macro | O que faz | Atalho |
|---|---|---|
| `GerarAbaDaLoja` | Pergunta o código da loja (ex.: `L01`) e cria a aba `Loja L01` com os indicadores da loja (blocos Dia e Mês), os vendedores dela (sem as colunas repetidas de loja), o top 5 de produtos da loja no mês, "Quando a loja vende" (receita média por dia da semana e por faixa horária nos últimos 90 dias, com o melhor dia e a melhor faixa destacados) e os alertas abertos dela, tudo copiado das abas do próprio arquivo; produtos e "quando a loja vende" vêm da aba oculta `Dados por loja`, que o Python grava e a macro filtra pela loja escolhida. As coberturas e a evolução levam as cores de status (verde/vermelho), como nas abas do Python. | `Ctrl+Shift+L` |
| `GerarAbaDoVendedor` | Pergunta o código do vendedor (ex.: `V0001`) e cria a aba `Vendedor V0001`, no mesmo padrão visual da aba da loja (títulos de seção, cores de status, larguras pelo texto, fonte Calibri): identificação (nome, loja, setor principal, posição na loja e na rede); metas do dia, do mês (com o **ritmo necessário por dia**) e do ano; "Dias que bateu a meta no mês: X de Y dias com venda" com a tabela dia a dia; evolução dos 12 últimos meses fechados mais o mês corrente, com gráfico nativo de colunas (venda) e linha (meta); top 10 de produtos (quantidade e receita); mix por setor; comportamento no mês (ticket médio, itens por cupom, desconto médio e taxa de cancelamento, cada um ao lado da média da loja); e os alertas abertos dele. Os números vêm da aba oculta `Dados por vendedor`, em formato longo (uma linha por item de cada bloco), que o Python grava com todos os vendedores; a macro só filtra pelo código e formata. Código inexistente gera uma mensagem amigável. | `Ctrl+Shift+V` |
| `ExportarResumoPDF` | Exporta a aba `Resumo da rede` para PDF (paisagem, uma página), na mesma pasta do arquivo: `Resumo_da_rede_AAAA-MM-DD.pdf`, com a **data de posição** do relatório (não a de hoje). O gerador grava essa data no rodapé da aba `Resumo da rede` (coluna L) e a nomeia `DataPosicao`; a macro lê esse nome. | `Ctrl+Shift+P` |

As macros só leem o que já está na planilha: **não abrem conexão com o banco, não acessam a rede e
não têm senha nem caminho fixo**. Sem os atalhos (ou se preferir), use `Alt+F8`, escolha a macro e
clique em Executar.

## Como os arquivos ficam no repositório

```
vba/ModuloLoja.bas      código de GerarAbaDaLoja (texto, ASCII, quebra CRLF)
vba/ModuloVendedor.bas  código de GerarAbaDoVendedor
vba/ModuloPDF.bas       código de ExportarResumoPDF
vba/ModuloAtalhos.bas   registra os atalhos (Auto_Open) e os remove ao fechar (Auto_Close)
vba/modelo_fechamento.xlsm   pasta de trabalho com os quatro módulos já importados (binário pequeno)
```

O `.xlsm` é a **única exceção binária** versionada. Ele existe porque o `openpyxl` não consegue
criar código VBA: ele só **preserva** o `vbaProject.bin` de um `.xlsm` já existente
(`load_workbook(..., keep_vba=True)`) e **descarta botões e formas** ao salvar. Por isso:

* o gerador carrega o modelo, apaga as abas dele e monta as abas novas (com gráficos criados pelo
  próprio `openpyxl`); o projeto VBA do modelo segue junto no arquivo salvo;
* as macros rodam por **atalho de teclado** (ou `Alt+F8`), não por botão;
* se `vba/modelo_fechamento.xlsm` não existir, o gerador cria um `.xlsx` sem macros (tudo o mais
  é igual). `--sem-macros` força isso mesmo com o modelo presente.

## Criar o modelo `.xlsm` (uma vez só, à mão, no Excel)

Precisa do Microsoft Excel para Windows.

1. Abra o Excel e crie uma **pasta de trabalho em branco**.
2. Salve como `vba\modelo_fechamento.xlsm` (dentro da pasta do projeto), tipo
   **Pasta de Trabalho Habilitada para Macro do Excel (\*.xlsm)**.
3. Pressione `Alt+F11` para abrir o Editor do VBA.
4. Menu **Arquivo > Importar Arquivo...** e importe, um por vez, `vba\ModuloLoja.bas`,
   `vba\ModuloVendedor.bas`, `vba\ModuloPDF.bas` e `vba\ModuloAtalhos.bas`. Na janela de projetos
   devem aparecer os quatro módulos em *Módulos*.
5. Menu **Depurar > Compilar VBAProject**. Não pode dar erro.
6. Volte ao Excel, salve (`Ctrl+B`) e feche. O conteúdo das abas do modelo não importa: o gerador
   as substitui.
7. Confira com `pytest tests/vba` (os dois testes do modelo deixam de ser pulados) e gere um
   relatório: `python -m src.relatorios fechamento` deve criar
   `data\processed\fechamento_AAAA-MM.xlsm`.

### Substituir um módulo que mudou (ou importar um novo)

Quando um `.bas` muda, só o módulo alterado precisa ser trocado no modelo:

1. Abra `vba\modelo_fechamento.xlsm` (habilite o conteúdo) e `Alt+F11`.
2. Na janela de projetos, clique com o botão direito no módulo antigo > **Remover**. Na pergunta
   "Deseja exportar o módulo antes de removê-lo?", responda **Não** (exportar sobrescreveria o `.bas`
   do repositório, que é o código certo).
3. **Arquivo > Importar Arquivo...** e escolha o `.bas` atualizado de `vba\`.
4. **Depurar > Compilar VBAProject**: não pode dar erro.
5. Salve (`Ctrl+B`) e feche o Excel. Depois gere o relatório de novo com `python -m src.relatorios
   fechamento`; o arquivo gerado só traz as macros novas se o modelo foi salvo.

Um módulo **novo** (como `ModuloVendedor`) só precisa do passo 3 (importar). Os módulos são
independentes na compilação; para a rodada do vendedor troque `ModuloLoja` e `ModuloAtalhos` (o
atalho novo) e importe `ModuloVendedor`.

## Usar as macros no arquivo gerado

1. Abra o `.xlsm`. O Excel mostra um aviso de segurança: clique em **Habilitar Conteúdo**. Se o
   arquivo veio da internet ou de outra máquina e o botão não aparece, feche, clique com o botão
   direito no arquivo > Propriedades > marque **Desbloquear** > OK e abra de novo.
2. `Ctrl+Shift+L`: digite o código da loja (a caixa lista os códigos disponíveis).
3. `Ctrl+Shift+V`: digite o código do vendedor (ex.: `V0001`; os códigos estão na aba `Vendedores`).
4. `Ctrl+Shift+P`: gera o PDF do resumo e mostra onde foi salvo.

Os atalhos são registrados ao abrir o arquivo e removidos ao fechá-lo, então não interferem em
outras pastas de trabalho.

## Como testamos

O CI não tem Excel, então a parte automática é estática (`tests/vba/test_modulos_vba.py`):

* cada `.bas` é ASCII, tem `Attribute VB_Name`, `Option Explicit` e quebras CRLF;
* as procedures públicas são exatamente as esperadas e os blocos (`Sub`, `If`, `For`, `With`) estão
  balanceados;
* nenhum caminho absoluto, `Shell`, `CreateObject`, ADODB, URL nem `Workbooks.Open`;
* os nomes de abas e de colunas que as macros procuram existem na planilha que o gerador produz
  (se alguém renomear uma aba ou coluna em `src/relatorios/planilha.py`, o teste quebra);
* os atalhos apontam para macros que existem;
* se o modelo existir: o `.xlsm` gerado ainda contém `xl/vbaProject.bin` e o tipo de conteúdo de
  macros, e o modelo tem os quatro módulos. Sem o modelo esses dois testes são **pulados**.

### Roteiro de teste manual (no Excel, depois de gerar o `.xlsm`)

| # | Passo | Resultado esperado |
|---|---|---|
| 1 | Abrir o `.xlsm` e habilitar o conteúdo | Abre na aba `Resumo da rede`, sem erro |
| 2 | `Ctrl+Shift+L`, digitar `L01` | Aparece a aba `Loja L01` com título, blocos Dia e Mês, vendedores, top 5 de produtos, "Quando a loja vende" (melhor dia e melhor faixa em verde-claro) e alertas, todos com título de seção azul e linha grossa embaixo; os números batem com a linha da loja na aba `Lojas`; coberturas e evolução com cor verde/vermelho; colunas Tipo e Vendedor dos alertas sem texto cortado |
| 3 | `Ctrl+Shift+L` de novo, `L01` | A aba é recriada (não duplica) |
| 4 | `Ctrl+Shift+L`, digitar `XXX` | Aviso "Loja 'XXX' nao encontrada", nada é criado |
| 5 | `Ctrl+Shift+L` e cancelar a caixa | Nada acontece |
| 6 | `Ctrl+Shift+V`, digitar `V0001` | Aparece a aba `Vendedor V0001` com os dez blocos na ordem: título, identificação, metas do dia/mês/ano (coberturas em verde/vermelho), dias que bateu a meta e tabela dia a dia, evolução com gráfico ao lado, top 10 de produtos, mix por setor, comportamento e alertas; números conferem com a linha do vendedor na aba `Vendedores`; fonte única (Calibri); explicação dos alertas com quebra de texto |
| 6a | `Ctrl+Shift+V`, digitar `XXXX` | Aviso "Vendedor 'XXXX' nao encontrado...", nada é criado; cancelar a caixa não faz nada |
| 6b | `Ctrl+Shift+V` de novo, `V0001` | A aba é recriada (não duplica) |
| 6c | Aba `Lojas`/`Loja L01`: tabela de vendedores | Traz a coluna "Ritmo necessário por dia" e a coluna de posição centralizada |
| 7 | `Ctrl+Shift+P` | PDF de uma página, paisagem, com indicadores e gráfico, na pasta do arquivo |
| 7a | `Alt+F8` | As três macros aparecem na lista e rodam |
| 8 | Fechar e abrir outra pasta de trabalho | `Ctrl+Shift+L` não faz nada nela |
