Attribute VB_Name = "ModuloLoja"
Option Explicit

' Cria a aba "Loja XX" com os numeros da loja escolhida, copiados das abas Lojas, Vendedores e
' Alertas abertos deste mesmo arquivo. Nao acessa banco, rede nem nenhum outro arquivo.
' Atalho: Ctrl+Shift+L (veja ModuloAtalhos) ou Alt+F8 > GerarAbaDaLoja.

Private Const ABA_LOJAS As String = "Lojas"
Private Const ABA_VENDEDORES As String = "Vendedores"
Private Const ABA_ALERTAS As String = "Alertas abertos"
Private Const TITULO_CODIGO_LOJA As String = "Loja"
Private Const TITULO_NOME_LOJA As String = "Nome"
Private Const TITULO_LOJA_NOS_ALERTAS As String = "Loja ou centro de custo"
Private Const TITULO_NOME_DA_LOJA As String = "Nome da loja"
Private Const LARGURA_MINIMA As Double = 14      ' cabe "R$ 9.999.999,99"
Private Const LARGURA_MAXIMA As Double = 40
Private Const COLUNAS_DA_EXPLICACAO As Long = 5   ' a Explicacao ocupa colunas mescladas
Private Const CARACTERES_POR_LINHA As Long = 75
Private Const PRIMEIRA_COLUNA_INDICADOR As Long = 4   ' Lojas: colunas 1 a 3 = Loja, Nome, UF
Private Const COLUNAS_DO_DIA As Long = 3              ' Venda do dia, Meta do dia, Cobertura do dia

Public Sub GerarAbaDaLoja()
    Dim wsLojas As Worksheet, wsVendedores As Worksheet, wsAlertas As Worksheet, wsNova As Worksheet
    Dim codigo As String, nomeLoja As String, uf As String
    Dim linhaLoja As Long, linha As Long
    Dim qtdVendedores As Long, qtdAlertas As Long, linhaAlertas As Long

    On Error GoTo TrataErro
    Set wsLojas = ThisWorkbook.Worksheets(ABA_LOJAS)
    Set wsVendedores = ThisWorkbook.Worksheets(ABA_VENDEDORES)
    Set wsAlertas = ThisWorkbook.Worksheets(ABA_ALERTAS)

    codigo = UCase$(Trim$(InputBox("Codigo da loja (" & ListaDeLojas(wsLojas) & "):", _
                                   "Gerar aba da loja")))
    If Len(codigo) = 0 Then Exit Sub

    linhaLoja = LinhaDoValor(wsLojas, ColunaDoTitulo(wsLojas, TITULO_CODIGO_LOJA), codigo)
    If linhaLoja = 0 Then
        MsgBox "Loja '" & codigo & "' nao encontrada na aba " & ABA_LOJAS & ".", vbExclamation
        Exit Sub
    End If
    nomeLoja = CStr(wsLojas.Cells(linhaLoja, ColunaDoTitulo(wsLojas, TITULO_NOME_LOJA)).Value)
    uf = CStr(wsLojas.Cells(linhaLoja, PRIMEIRA_COLUNA_INDICADOR - 1).Value)

    Set wsNova = CriarAbaVazia("Loja " & codigo)
    wsNova.Cells(1, 1).Value = "Loja " & codigo & " - " & nomeLoja & " (" & uf & ")"
    wsNova.Cells(1, 1).Font.Bold = True
    wsNova.Cells(1, 1).Font.Size = 14

    ' Indicadores em dois blocos, "Dia" e "Mes": titulo na coluna A, valor na B, mesmo formato.
    linha = 3
    linha = CopiarIndicadores(wsLojas, linhaLoja, wsNova, linha, "Dia", _
                              PRIMEIRA_COLUNA_INDICADOR, PRIMEIRA_COLUNA_INDICADOR + COLUNAS_DO_DIA - 1)
    linha = CopiarIndicadores(wsLojas, linhaLoja, wsNova, linha + 1, "M" & ChrW(234) & "s", _
                              PRIMEIRA_COLUNA_INDICADOR + COLUNAS_DO_DIA, UltimaColuna(wsLojas))

    ' Nas tabelas a loja e o nome dela (repetidos em toda linha) ficam de fora.
    linha = linha + 1
    qtdVendedores = CopiarLinhasDaLoja(wsVendedores, TITULO_CODIGO_LOJA, codigo, wsNova, linha, _
                                       "Vendedores", TITULO_CODIGO_LOJA, TITULO_NOME_DA_LOJA)
    linha = linha + qtdVendedores + 3
    linhaAlertas = linha
    qtdAlertas = CopiarLinhasDaLoja(wsAlertas, TITULO_LOJA_NOS_ALERTAS, nomeLoja, wsNova, linha, _
                                    "Alertas abertos", "", "")

    AjustarLarguras wsNova, ColunaDoTitulo(wsAlertas, TituloExplicacao()), linhaAlertas + 2, qtdAlertas
    wsNova.Activate
    wsNova.Cells(1, 1).Select
    MsgBox "Aba '" & wsNova.Name & "' criada: " & qtdVendedores & " vendedor(es) e " & _
           qtdAlertas & " alerta(s) aberto(s).", vbInformation, "Gerar aba da loja"
    Exit Sub

TrataErro:
    MsgBox "Nao foi possivel gerar a aba da loja: " & Err.Description, vbCritical
End Sub

' Escreve um bloco de indicadores (cabecalho do bloco e um indicador por linha) das colunas
' colInicial a colFinal da linha da loja; devolve a proxima linha livre.
Private Function CopiarIndicadores(wsLojas As Worksheet, linhaLoja As Long, wsDestino As Worksheet, _
                                   linhaInicial As Long, bloco As String, colInicial As Long, _
                                   colFinal As Long) As Long
    Dim coluna As Long, linha As Long
    wsDestino.Cells(linhaInicial, 1).Value = bloco
    EstiloCabecalho wsDestino.Range(wsDestino.Cells(linhaInicial, 1), wsDestino.Cells(linhaInicial, 2))
    linha = linhaInicial + 1
    For coluna = colInicial To colFinal
        wsDestino.Cells(linha, 1).Value = wsLojas.Cells(1, coluna).Value
        wsDestino.Cells(linha, 2).Value = wsLojas.Cells(linhaLoja, coluna).Value
        wsDestino.Cells(linha, 2).NumberFormat = wsLojas.Cells(linhaLoja, coluna).NumberFormat
        linha = linha + 1
    Next coluna
    CopiarIndicadores = linha
End Function

' Copia para wsDestino (a partir de linhaInicial) o titulo da secao, o cabecalho e as linhas de
' wsOrigem em que a coluna tituloFiltro vale valorFiltro, sem as colunas de titulo omitir1/omitir2.
' Devolve quantas linhas foram copiadas.
Private Function CopiarLinhasDaLoja(wsOrigem As Worksheet, tituloFiltro As String, valorFiltro As String, _
                                    wsDestino As Worksheet, linhaInicial As Long, secao As String, _
                                    omitir1 As String, omitir2 As String) As Long
    Dim colunaFiltro As Long, ultimaLinha As Long, ultimaCol As Long
    Dim linhaOrigem As Long, linhaDestino As Long, coluna As Long, colDestino As Long, copiadas As Long
    Dim titulo As String

    colunaFiltro = ColunaDoTitulo(wsOrigem, tituloFiltro)
    ultimaLinha = wsOrigem.Cells(wsOrigem.Rows.Count, 1).End(xlUp).Row
    ultimaCol = UltimaColuna(wsOrigem)

    wsDestino.Cells(linhaInicial, 1).Value = secao
    wsDestino.Cells(linhaInicial, 1).Font.Bold = True
    linhaDestino = linhaInicial + 1
    For coluna = 1 To ultimaCol
        titulo = CStr(wsOrigem.Cells(1, coluna).Value)
        If titulo <> omitir1 And titulo <> omitir2 Then
            colDestino = colDestino + 1
            wsDestino.Cells(linhaDestino, colDestino).Value = titulo
        End If
    Next coluna
    EstiloCabecalho wsDestino.Range(wsDestino.Cells(linhaDestino, 1), wsDestino.Cells(linhaDestino, colDestino))

    For linhaOrigem = 2 To ultimaLinha
        If CStr(wsOrigem.Cells(linhaOrigem, colunaFiltro).Value) = valorFiltro Then
            linhaDestino = linhaDestino + 1
            colDestino = 0
            For coluna = 1 To ultimaCol
                titulo = CStr(wsOrigem.Cells(1, coluna).Value)
                If titulo <> omitir1 And titulo <> omitir2 Then
                    colDestino = colDestino + 1
                    wsDestino.Cells(linhaDestino, colDestino).Value = wsOrigem.Cells(linhaOrigem, coluna).Value
                    wsDestino.Cells(linhaDestino, colDestino).NumberFormat = wsOrigem.Cells(linhaOrigem, coluna).NumberFormat
                End If
            Next coluna
            copiadas = copiadas + 1
        End If
    Next linhaOrigem
    CopiarLinhasDaLoja = copiadas
End Function

' A Explicacao (texto longo) ocupa colunas mescladas, com quebra de texto, para nenhuma coluna de
' numeros ficar larga; as demais colunas usam AutoFit com minimo e maximo.
Private Sub AjustarLarguras(ws As Worksheet, colunaExplicacao As Long, primeiraLinhaAlertas As Long, _
                            qtdAlertas As Long)
    Dim coluna As Long, linha As Long, linhas As Long, ultimaCol As Long
    ultimaCol = colunaExplicacao + COLUNAS_DA_EXPLICACAO - 1
    For linha = primeiraLinhaAlertas - 1 To primeiraLinhaAlertas + qtdAlertas - 1
        ws.Range(ws.Cells(linha, colunaExplicacao), ws.Cells(linha, ultimaCol)).Merge
    Next linha
    EstiloCabecalho ws.Range(ws.Cells(primeiraLinhaAlertas - 1, 1), ws.Cells(primeiraLinhaAlertas - 1, ultimaCol))
    ws.UsedRange.Columns.AutoFit
    For coluna = 1 To ultimaCol
        If ws.Columns(coluna).ColumnWidth < LARGURA_MINIMA Then ws.Columns(coluna).ColumnWidth = LARGURA_MINIMA
        If ws.Columns(coluna).ColumnWidth > LARGURA_MAXIMA Then ws.Columns(coluna).ColumnWidth = LARGURA_MAXIMA
    Next coluna
    For linha = primeiraLinhaAlertas To primeiraLinhaAlertas + qtdAlertas - 1
        With ws.Cells(linha, colunaExplicacao)
            .WrapText = True
            .VerticalAlignment = xlTop
        End With
        linhas = Len(CStr(ws.Cells(linha, colunaExplicacao).Value)) \ CARACTERES_POR_LINHA + 1
        ws.Rows(linha).RowHeight = 15 * linhas
    Next linha
End Sub

' O titulo "Explicacao" tem acentos; montado por codigo para o arquivo continuar em ASCII puro.
Private Function TituloExplicacao() As String
    TituloExplicacao = "Explica" & ChrW(231) & ChrW(227) & "o"
End Function

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

Private Function ListaDeLojas(ws As Worksheet) As String
    Dim coluna As Long, linha As Long, ultimaLinha As Long, texto As String
    coluna = ColunaDoTitulo(ws, TITULO_CODIGO_LOJA)
    ultimaLinha = ws.Cells(ws.Rows.Count, coluna).End(xlUp).Row
    For linha = 2 To ultimaLinha
        If Len(texto) > 0 Then texto = texto & ", "
        texto = texto & CStr(ws.Cells(linha, coluna).Value)
    Next linha
    ListaDeLojas = texto
End Function

Private Function ColunaDoTitulo(ws As Worksheet, titulo As String) As Long
    Dim coluna As Long
    For coluna = 1 To UltimaColuna(ws)
        If CStr(ws.Cells(1, coluna).Value) = titulo Then
            ColunaDoTitulo = coluna
            Exit Function
        End If
    Next coluna
    Err.Raise vbObjectError + 1, , "Coluna '" & titulo & "' nao encontrada na aba " & ws.Name
End Function

Private Function LinhaDoValor(ws As Worksheet, coluna As Long, valor As String) As Long
    Dim linha As Long, ultimaLinha As Long
    ultimaLinha = ws.Cells(ws.Rows.Count, coluna).End(xlUp).Row
    For linha = 2 To ultimaLinha
        If UCase$(CStr(ws.Cells(linha, coluna).Value)) = valor Then
            LinhaDoValor = linha
            Exit Function
        End If
    Next linha
End Function

Private Function UltimaColuna(ws As Worksheet) As Long
    UltimaColuna = ws.Cells(1, ws.Columns.Count).End(xlToLeft).Column
End Function

Private Sub EstiloCabecalho(faixa As Range)
    faixa.Font.Bold = True
    faixa.Font.Color = RGB(255, 255, 255)
    faixa.Interior.Color = RGB(31, 78, 120)
    faixa.WrapText = True
    faixa.VerticalAlignment = xlCenter
End Sub
