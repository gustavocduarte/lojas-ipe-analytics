Attribute VB_Name = "ModuloVendedor"
Option Explicit

' Cria a aba "Vendedor XXXX" com os numeros do vendedor escolhido: identificacao, metas do dia, do
' mes e do ano, dias que bateu a meta, evolucao mensal (com grafico), top 10 de produtos, mix por
' setor, comportamento no mes e alertas abertos. Os dados vem da aba oculta "Dados por vendedor"
' (o Python grava la todos os vendedores em formato longo) deste mesmo arquivo; esta macro so
' filtra pelo codigo e formata. Nao acessa banco, rede nem nenhum outro arquivo.
' Atalho: Ctrl+Shift+V (veja ModuloAtalhos) ou Alt+F8 > GerarAbaDoVendedor.
'
' Formato da aba de apoio (cabecalho na linha 1; uma linha por item de cada bloco):
'   vendedor | bloco | ordem | titulo | cabecalhos | formatos | col_1 ... col_6
' A linha de ordem 0 de cada bloco traz o titulo da secao e, nas tabelas, os titulos das colunas
' separados por "|". "formatos" tem uma letra por coluna de valor; "-" e coluna sem uso.

Private Const ABA_DADOS As String = "Dados por vendedor"
Private Const COL_VENDEDOR As Long = 1
Private Const COL_BLOCO As Long = 2
Private Const COL_ORDEM As Long = 3
Private Const COL_TITULO As Long = 4
Private Const COL_CABECALHOS As Long = 5
Private Const COL_FORMATOS As Long = 6
Private Const COL_VALORES As Long = 7
Private Const QTD_VALORES As Long = 6
Private Const BLOCO_TITULO As String = "titulo"
Private Const BLOCO_EVOLUCAO As String = "evolucao"
Private Const BLOCO_ALERTAS As String = "alertas"
Private Const PREFIXO_COBERTURA As String = "Cobertura"   ' cobertura: verde a partir de 100%
Private Const FONTE_ABA As String = "Calibri"             ' uma unica fonte em toda a aba
Private Const TAMANHO_FONTE As Long = 11
' Estilo unico de titulo de secao (o mesmo do Python, titulo_de_secao em planilha.py).
Private Const TAMANHO_TITULO As Long = 13
Private Const ALTURA_TITULO As Long = 22
Private Const COR_TITULO As Long = 7884319           ' RGB(31, 78, 120), o azul do cabecalho
Private Const COR_META As Long = 1137349             ' RGB(197, 90, 17), laranja-escuro da meta
Private Const COLUNAS_DO_TITULO As Long = 6          ' largura do titulo da aba e das tabelas
Private Const LARGURA_MINIMA As Double = 14          ' cabe "R$ 9.999.999,99"
Private Const LARGURA_MAXIMA As Double = 45
Private Const LARGURA_EXPLICACAO As Double = 60      ' ultima coluna dos alertas, com quebra de texto
Private Const COL_GRAFICO As Long = 8                ' o grafico da evolucao fica ao lado da tabela
Private Const LARGURA_GRAFICO As Long = 480
Private Const ALTURA_GRAFICO As Long = 240

Public Sub GerarAbaDoVendedor()
    Dim wsDados As Worksheet, wsNova As Worksheet
    Dim dados As Variant, escolhidas() As Long
    Dim codigo As String, ultimaLinha As Long, qtd As Long, i As Long, k As Long
    Dim blocos As Variant, b As Long, nomeDoBloco As String
    Dim linha As Long, linhaInicial As Long, linhaFinal As Long, tabelaPronta As Boolean

    On Error GoTo TrataErro
    Set wsDados = ThisWorkbook.Worksheets(ABA_DADOS)

    codigo = UCase$(Trim$(InputBox("Codigo do vendedor (exemplo: V0001):", "Gerar aba do vendedor")))
    If Len(codigo) = 0 Then Exit Sub

    ultimaLinha = wsDados.Cells(wsDados.Rows.Count, COL_VENDEDOR).End(xlUp).Row
    dados = wsDados.Range(wsDados.Cells(1, 1), wsDados.Cells(ultimaLinha, COL_VALORES + QTD_VALORES - 1)).Value

    For i = 2 To ultimaLinha
        If UCase$(CStr(dados(i, COL_VENDEDOR))) = codigo Then qtd = qtd + 1
    Next i
    If qtd = 0 Then
        MsgBox "Vendedor '" & codigo & "' nao encontrado. Confira o codigo na aba Vendedores " & _
               "(exemplo: V0001) e tente de novo.", vbExclamation, "Gerar aba do vendedor"
        Exit Sub
    End If
    ReDim escolhidas(1 To qtd)
    For i = 2 To ultimaLinha
        If UCase$(CStr(dados(i, COL_VENDEDOR))) = codigo Then
            k = k + 1
            escolhidas(k) = i
        End If
    Next i

    Set wsNova = CriarAbaVazia("Vendedor " & codigo)
    wsNova.Cells.Font.Size = TAMANHO_FONTE
    PadronizarFonte wsNova

    blocos = Array(BLOCO_TITULO, "cabecalho", "dia", "mes", "ano", "dia_a_dia", BLOCO_EVOLUCAO, _
                   "produtos", "mix", "comportamento", BLOCO_ALERTAS)
    linha = 1
    For b = LBound(blocos) To UBound(blocos)
        nomeDoBloco = CStr(blocos(b))
        linhaInicial = linha
        linha = EscreverBloco(wsNova, dados, escolhidas, qtd, nomeDoBloco, linhaInicial)
        linhaFinal = linha - 2
        If nomeDoBloco = BLOCO_EVOLUCAO Then
            ' cabecalho na linha de baixo do titulo; dados a partir da seguinte
            tabelaPronta = (linhaFinal >= linhaInicial + 2) And IsNumeric(wsNova.Cells(linhaInicial + 2, 2).Value)
            If tabelaPronta Then CriarGraficoEvolucao wsNova, linhaInicial, linhaInicial + 2, linhaFinal
        End If
        If nomeDoBloco = BLOCO_ALERTAS Then AjustarAlertas wsNova, linhaInicial + 2, linhaFinal
    Next b

    AjustarLarguras wsNova, linha
    wsNova.Activate
    wsNova.Cells(1, 1).Select
    MsgBox "Aba '" & wsNova.Name & "' criada.", vbInformation, "Gerar aba do vendedor"
    Exit Sub

TrataErro:
    MsgBox "Nao foi possivel gerar a aba do vendedor: " & Err.Description, vbCritical
End Sub

' Escreve um bloco do vendedor a partir de linhaInicial: titulo da secao, cabecalho (nas tabelas) e
' uma linha por item. Devolve a proxima linha livre, ja com uma linha em branco depois do bloco.
Private Function EscreverBloco(ws As Worksheet, dados As Variant, escolhidas() As Long, qtd As Long, _
                               bloco As String, linhaInicial As Long) As Long
    Dim i As Long, r As Long, p As Long, c As Long, linha As Long, colunas As Long
    Dim titulo As String, cabecalhos As String, formatos As String, letra As String
    Dim partes As Variant, achou As Boolean, linhaCabecalho As Long, primeiraLinha As Long
    Dim linhasDeDados As Long

    For i = 1 To qtd
        r = escolhidas(i)
        If CStr(dados(r, COL_BLOCO)) = bloco And CLng(dados(r, COL_ORDEM)) = 0 Then
            titulo = CStr(dados(r, COL_TITULO))
            cabecalhos = CStr(dados(r, COL_CABECALHOS))
            achou = True
            Exit For
        End If
    Next i
    If Not achou Then
        EscreverBloco = linhaInicial
        Exit Function
    End If

    If bloco = BLOCO_TITULO Then
        TituloDeSecao ws, 1, 1, COLUNAS_DO_TITULO, titulo
        EscreverBloco = 3
        Exit Function
    End If

    ' Sem cabecalho: rotulo na coluna A e valor na B (como os indicadores da aba da loja).
    colunas = 2
    If Len(cabecalhos) > 0 Then
        partes = Split(cabecalhos, "|")
        colunas = UBound(partes) + 1
    End If
    TituloDeSecao ws, linhaInicial, 1, colunas, titulo
    linha = linhaInicial + 1
    If Len(cabecalhos) > 0 Then
        For c = 0 To UBound(partes)
            ws.Cells(linha, c + 1).Value = partes(c)
        Next c
        EstiloCabecalho ws.Range(ws.Cells(linha, 1), ws.Cells(linha, colunas))
        linhaCabecalho = linha
        linha = linha + 1
    End If
    primeiraLinha = linha

    For i = 1 To qtd
        r = escolhidas(i)
        If CStr(dados(r, COL_BLOCO)) = bloco And CLng(dados(r, COL_ORDEM)) > 0 Then
            formatos = CStr(dados(r, COL_FORMATOS))
            c = 0
            For p = 1 To QTD_VALORES
                letra = Mid$(formatos, p, 1)
                If letra <> "-" Then
                    c = c + 1
                    ws.Cells(linha, c).Value = dados(r, COL_VALORES + p - 1)
                    ws.Cells(linha, c).NumberFormat = FormatoDaLetra(letra)
                    If letra = "I" Or letra = "D" Or letra = "M" Then ws.Cells(linha, c).HorizontalAlignment = xlCenter
                End If
            Next p
            If linhaCabecalho = 0 And Left$(CStr(ws.Cells(linha, 1).Value), Len(PREFIXO_COBERTURA)) = PREFIXO_COBERTURA Then
                CorDeStatus ws.Cells(linha, 2), 1
            End If
            linha = linha + 1
            linhasDeDados = linhasDeDados + 1
        End If
    Next i

    If linhasDeDados = 0 Then
        ws.Cells(linha, 1).Value = "Sem registros."
        ws.Cells(linha, 1).Font.Italic = True
        linha = linha + 1
    Else
        If linhaCabecalho > 0 Then ColorirCoberturas ws, linhaCabecalho, primeiraLinha, linha - 1, colunas
    End If
    EscreverBloco = linha + 1
End Function

' Colunas cujo titulo comeca por "Cobertura" levam a cor de status (verde a partir de 100%).
Private Sub ColorirCoberturas(ws As Worksheet, linhaCabecalho As Long, primeiraLinha As Long, _
                              ultimaLinha As Long, colunas As Long)
    Dim c As Long
    For c = 1 To colunas
        If Left$(CStr(ws.Cells(linhaCabecalho, c).Value), Len(PREFIXO_COBERTURA)) = PREFIXO_COBERTURA Then
            CorDeStatus ws.Range(ws.Cells(primeiraLinha, c), ws.Cells(ultimaLinha, c)), 1
        End If
    Next c
End Sub

' Grafico nativo da evolucao: barras da venda e linha da meta, mes a mes. Se o Excel recusar algum
' passo, a tabela continua pronta e a macro avisa que o grafico nao foi criado.
Private Sub CriarGraficoEvolucao(ws As Worksheet, linhaTitulo As Long, primeira As Long, ultima As Long)
    Dim objeto As ChartObject, serie As Series, falhou As Boolean
    Dim linhaCabecalho As Long
    linhaCabecalho = linhaTitulo + 1

    On Error Resume Next
    Set objeto = ws.ChartObjects.Add(ws.Cells(linhaTitulo, COL_GRAFICO).Left, _
                                     ws.Cells(linhaTitulo, COL_GRAFICO).Top, LARGURA_GRAFICO, ALTURA_GRAFICO)
    If objeto Is Nothing Then falhou = True
    If Not falhou Then
        With objeto.Chart
            .ChartType = xlColumnClustered
            Do While .SeriesCollection.Count > 0
                .SeriesCollection(1).Delete
            Loop
            Set serie = .SeriesCollection.NewSeries
            serie.Name = CStr(ws.Cells(linhaCabecalho, 2).Value)
            serie.Values = ws.Range(ws.Cells(primeira, 2), ws.Cells(ultima, 2))
            serie.XValues = ws.Range(ws.Cells(primeira, 1), ws.Cells(ultima, 1))
            serie.Format.Fill.ForeColor.RGB = COR_TITULO
            Set serie = .SeriesCollection.NewSeries
            serie.Name = CStr(ws.Cells(linhaCabecalho, 3).Value)
            serie.Values = ws.Range(ws.Cells(primeira, 3), ws.Cells(ultima, 3))
            serie.XValues = ws.Range(ws.Cells(primeira, 1), ws.Cells(ultima, 1))
            serie.ChartType = xlLine
            serie.Format.Line.ForeColor.RGB = COR_META
            serie.Format.Line.Weight = 2.25
            .HasTitle = True
            .ChartTitle.Text = "Venda e meta por m" & ChrW(234) & "s"
            .ChartTitle.Font.Size = TAMANHO_TITULO
            .ChartTitle.Font.Bold = True
            .ChartTitle.Font.Color = COR_TITULO
            .HasLegend = True
            .Legend.Position = xlLegendPositionBottom
            .Axes(xlCategory).CategoryType = xlCategoryScale
            .Axes(xlCategory).TickLabels.NumberFormat = "mm/yyyy"
            .Axes(xlValue).TickLabels.NumberFormat = "#,##0"
        End With
    End If
    If Err.Number <> 0 Then falhou = True
    On Error GoTo 0
    If falhou Then
        MsgBox "O grafico da evolucao nao pode ser criado; a tabela dele esta pronta na aba.", vbInformation
    End If
End Sub

' O texto longo da explicacao quebra linha e a altura de cada alerta acompanha o texto.
Private Sub AjustarAlertas(ws As Worksheet, primeiraLinha As Long, ultimaLinha As Long)
    Dim linha As Long
    If ultimaLinha < primeiraLinha Then Exit Sub
    With ws.Range(ws.Cells(primeiraLinha, COLUNAS_DO_TITULO), ws.Cells(ultimaLinha, COLUNAS_DO_TITULO))
        .WrapText = True
        .VerticalAlignment = xlTop
    End With
    ws.Range(ws.Cells(primeiraLinha, 1), ws.Cells(ultimaLinha, COLUNAS_DO_TITULO - 1)).VerticalAlignment = xlTop
End Sub

' Cada coluna ocupa o que o maior texto dela pede (entre o minimo e o maximo); a explicacao dos
' alertas tem largura propria. Depois disso as linhas com quebra de texto se ajustam.
Private Sub AjustarLarguras(ws As Worksheet, ultimaLinha As Long)
    Dim coluna As Long, linha As Long, necessaria As Double
    PadronizarFonte ws   ' de novo, antes de medir: a largura depende da fonte
    For coluna = 1 To COLUNAS_DO_TITULO - 1
        necessaria = LarguraDoTexto(ws, coluna, ultimaLinha)
        If necessaria < LARGURA_MINIMA Then necessaria = LARGURA_MINIMA
        If necessaria > LARGURA_MAXIMA Then necessaria = LARGURA_MAXIMA
        ws.Columns(coluna).ColumnWidth = necessaria
    Next coluna
    ws.Columns(COLUNAS_DO_TITULO).ColumnWidth = LARGURA_EXPLICACAO
    For linha = 2 To ultimaLinha
        If ws.Cells(linha, COLUNAS_DO_TITULO).WrapText Then ws.Rows(linha).AutoFit
    Next linha
End Sub

' Largura (em caracteres) que o maior texto da coluna precisa. Ignora o titulo da aba (linha 1),
' celulas mescladas e cabecalhos em negrito (eles quebram linha); numeros cabem na largura minima.
Private Function LarguraDoTexto(ws As Worksheet, coluna As Long, ultimaLinha As Long) As Double
    Dim linha As Long, maior As Long
    For linha = 2 To ultimaLinha
        With ws.Cells(linha, coluna)
            If VarType(.Value) = vbString And Not .MergeCells And Not .Font.Bold Then
                If Len(.Value) > maior Then maior = Len(.Value)
            End If
        End With
    Next linha
    LarguraDoTexto = maior * 1.15 + 2
End Function

' Uma letra por formato (a mesma tabela do Python, FORMATOS em por_vendedor.py).
Private Function FormatoDaLetra(letra As String) As String
    Select Case letra
        Case "R"
            FormatoDaLetra = """R$"" #,##0.00"
        Case "P"
            FormatoDaLetra = "0.0%"
        Case "I"
            FormatoDaLetra = "#,##0"
        Case "D"
            FormatoDaLetra = "dd/mm/yyyy"
        Case "M"
            FormatoDaLetra = "mm/yyyy"
        Case "N"
            FormatoDaLetra = "0.00"
        Case Else
            FormatoDaLetra = "General"
    End Select
End Function

' Titulo de secao: 13 pt, negrito, azul do cabecalho, mesclado na largura da tabela e com borda
' inferior grossa azul, colado ao cabecalho dela (sem linha em branco entre o titulo e a tabela).
Private Sub TituloDeSecao(ws As Worksheet, linha As Long, colInicial As Long, colFinal As Long, texto As String)
    Dim faixa As Range
    Set faixa = ws.Range(ws.Cells(linha, colInicial), ws.Cells(linha, colFinal))
    ws.Cells(linha, colInicial).Value = texto
    faixa.Merge
    With faixa
        .Font.Bold = True
        .Font.Size = TAMANHO_TITULO
        .Font.Color = COR_TITULO
        .HorizontalAlignment = xlLeft
        .VerticalAlignment = xlCenter
        .Borders(xlEdgeBottom).LineStyle = xlContinuous
        .Borders(xlEdgeBottom).Weight = xlThick
        .Borders(xlEdgeBottom).Color = COR_TITULO
    End With
    ws.Rows(linha).RowHeight = ALTURA_TITULO
End Sub

' Verde a partir do limite (inclusive) e vermelho abaixo dele: as mesmas cores do Python.
Private Sub CorDeStatus(faixa As Range, limite As Long)
    Dim regra As FormatCondition
    faixa.FormatConditions.Delete
    Set regra = faixa.FormatConditions.Add(Type:=xlCellValue, Operator:=xlGreaterEqual, _
                                           Formula1:="=" & CStr(limite))
    regra.Interior.Color = RGB(198, 239, 206)
    regra.Font.Color = RGB(0, 97, 0)
    Set regra = faixa.FormatConditions.Add(Type:=xlCellValue, Operator:=xlLess, _
                                           Formula1:="=" & CStr(limite))
    regra.Interior.Color = RGB(255, 199, 206)
    regra.Font.Color = RGB(156, 0, 6)
End Sub

Private Sub EstiloCabecalho(faixa As Range)
    faixa.Font.Bold = True
    faixa.Font.Color = RGB(255, 255, 255)
    faixa.Interior.Color = RGB(31, 78, 120)
    faixa.WrapText = True
    faixa.HorizontalAlignment = xlCenter
    faixa.VerticalAlignment = xlCenter
End Sub

' O Excel usa a fonte do estilo Normal da pasta; aqui a aba inteira usa sempre a mesma.
Private Sub PadronizarFonte(ws As Worksheet)
    ws.Cells.Font.Name = FONTE_ABA
End Sub

Private Function CriarAbaVazia(nome As String) As Worksheet
    Dim ws As Worksheet
    Application.DisplayAlerts = False
    For Each ws In ThisWorkbook.Worksheets
        If ws.Name = nome Then
            ws.Delete
            Exit For
        End If
    Next ws
    Application.DisplayAlerts = True
    Set ws = ThisWorkbook.Worksheets.Add(After:=ThisWorkbook.Worksheets(ThisWorkbook.Worksheets.Count))
    ws.Name = nome
    Set CriarAbaVazia = ws
End Function
