# Macros VBA do relatório de fechamento

O relatório de fechamento (`python -m src.relatorios fechamento`) pode sair como `.xlsx` simples
ou como `.xlsm` com duas macros:

| Macro | O que faz | Atalho |
|---|---|---|
| `GerarAbaDaLoja` | Pergunta o código da loja (ex.: `L01`) e cria a aba `Loja L01` com os indicadores da loja, os vendedores dela e os alertas abertos dela, tudo copiado das abas do próprio arquivo. | `Ctrl+Shift+L` |
| `ExportarResumoPDF` | Exporta a aba `Resumo da rede` para PDF (paisagem, uma página), na mesma pasta do arquivo: `Resumo_da_rede_AAAA-MM-DD.pdf`. | `Ctrl+Shift+P` |

As macros só leem o que já está na planilha: **não abrem conexão com o banco, não acessam a rede e
não têm senha nem caminho fixo**. Sem os atalhos (ou se preferir), use `Alt+F8`, escolha a macro e
clique em Executar.

## Como os arquivos ficam no repositório

```
vba/ModuloLoja.bas      código de GerarAbaDaLoja (texto, ASCII, quebra CRLF)
vba/ModuloPDF.bas       código de ExportarResumoPDF
vba/ModuloAtalhos.bas   registra os atalhos (Auto_Open) e os remove ao fechar (Auto_Close)
vba/modelo_fechamento.xlsm   pasta de trabalho com os três módulos já importados (binário pequeno)
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
   `vba\ModuloPDF.bas` e `vba\ModuloAtalhos.bas`. Na janela de projetos devem aparecer os três
   módulos em *Módulos*.
5. Menu **Depurar > Compilar VBAProject**. Não pode dar erro.
6. Volte ao Excel, salve (`Ctrl+B`) e feche. O conteúdo das abas do modelo não importa: o gerador
   as substitui.
7. Confira com `pytest tests/vba` (os dois testes do modelo deixam de ser pulados) e gere um
   relatório: `python -m src.relatorios fechamento` deve criar
   `data\processed\fechamento_AAAA-MM.xlsm`.

Se mudar uma macro: edite o `.bas`, abra o modelo, remova o módulo antigo (clique direito >
*Remover*, "Não" para exportar), importe o `.bas` de novo, compile e salve.

## Usar as macros no arquivo gerado

1. Abra o `.xlsm`. O Excel mostra um aviso de segurança: clique em **Habilitar Conteúdo**. Se o
   arquivo veio da internet ou de outra máquina e o botão não aparece, feche, clique com o botão
   direito no arquivo > Propriedades > marque **Desbloquear** > OK e abra de novo.
2. `Ctrl+Shift+L`: digite o código da loja (a caixa lista os códigos disponíveis).
3. `Ctrl+Shift+P`: gera o PDF do resumo e mostra onde foi salvo.

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
  macros, e o modelo tem os três módulos. Sem o modelo esses dois testes são **pulados**.

### Roteiro de teste manual (no Excel, depois de gerar o `.xlsm`)

| # | Passo | Resultado esperado |
|---|---|---|
| 1 | Abrir o `.xlsm` e habilitar o conteúdo | Abre na aba `Resumo da rede`, sem erro |
| 2 | `Ctrl+Shift+L`, digitar `L01` | Aparece a aba `Loja L01` com indicadores, vendedores e alertas; os números batem com a linha da loja na aba `Lojas` |
| 3 | `Ctrl+Shift+L` de novo, `L01` | A aba é recriada (não duplica) |
| 4 | `Ctrl+Shift+L`, digitar `XXX` | Aviso "Loja 'XXX' nao encontrada", nada é criado |
| 5 | `Ctrl+Shift+L` e cancelar a caixa | Nada acontece |
| 6 | `Ctrl+Shift+P` | PDF de uma página, paisagem, com indicadores e gráfico, na pasta do arquivo |
| 7 | `Alt+F8` | As duas macros aparecem na lista e rodam |
| 8 | Fechar e abrir outra pasta de trabalho | `Ctrl+Shift+L` não faz nada nela |
