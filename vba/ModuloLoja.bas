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

Public Sub GerarAbaDaLoja()
    Dim wsLojas As Worksheet, wsVendedores As Worksheet, wsAlertas As Worksheet, wsNova As Worksheet
    Dim codigo As String, nomeLoja As String
    Dim linhaLoja As Long, linha As Long, coluna As Long
    Dim qtdVendedores As Long, qtdAlertas As Long

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

    Set wsNova = CriarAbaVazia("Loja " & codigo)
    wsNova.Cells(1, 1).Value = "Loja " & codigo & " - " & nomeLoja
    wsNova.Cells(1, 1).Font.Bold = True
    wsNova.Cells(1, 1).Font.Size = 14

    ' Indicadores da loja: um por linha (titulo na coluna A, valor na B, com o mesmo formato).
    linha = 3
    For coluna = 1 To UltimaColuna(wsLojas)
        wsNova.Cells(linha, 1).Value = wsLojas.Cells(1, coluna).Value
        wsNova.Cells(linha, 1).Font.Bold = True
        wsNova.Cells(linha, 2).Value = wsLojas.Cells(linhaLoja, coluna).Value
        wsNova.Cells(linha, 2).NumberFormat = wsLojas.Cells(linhaLoja, coluna).NumberFormat
        linha = linha + 1
    Next coluna

    linha = linha + 1
    qtdVendedores = CopiarLinhasDaLoja(wsVendedores, TITULO_CODIGO_LOJA, codigo, wsNova, linha, "Vendedores")
    linha = linha + qtdVendedores + 3
    qtdAlertas = CopiarLinhasDaLoja(wsAlertas, TITULO_LOJA_NOS_ALERTAS, nomeLoja, wsNova, linha, "Alertas abertos")

    wsNova.Columns("A:B").ColumnWidth = 32
    wsNova.Activate
    wsNova.Cells(1, 1).Select
    MsgBox "Aba '" & wsNova.Name & "' criada: " & qtdVendedores & " vendedor(es) e " & _
           qtdAlertas & " alerta(s) aberto(s).", vbInformation, "Gerar aba da loja"
    Exit Sub

TrataErro:
    MsgBox "Nao foi possivel gerar a aba da loja: " & Err.Description, vbCritical
End Sub

' Copia para wsDestino (a partir de linhaInicial) o titulo da secao, o cabecalho e as linhas de
' wsOrigem em que a coluna tituloFiltro vale valorFiltro. Devolve quantas linhas foram copiadas.
Private Function CopiarLinhasDaLoja(wsOrigem As Worksheet, tituloFiltro As String, valorFiltro As String, _
                                    wsDestino As Worksheet, linhaInicial As Long, secao As String) As Long
    Dim colunaFiltro As Long, ultimaLinha As Long, ultimaCol As Long
    Dim linhaOrigem As Long, linhaDestino As Long, coluna As Long, copiadas As Long

    colunaFiltro = ColunaDoTitulo(wsOrigem, tituloFiltro)
    ultimaLinha = wsOrigem.Cells(wsOrigem.Rows.Count, 1).End(xlUp).Row
    ultimaCol = UltimaColuna(wsOrigem)

    wsDestino.Cells(linhaInicial, 1).Value = secao
    wsDestino.Cells(linhaInicial, 1).Font.Bold = True
    linhaDestino = linhaInicial + 1
    For coluna = 1 To ultimaCol
        wsDestino.Cells(linhaDestino, coluna).Value = wsOrigem.Cells(1, coluna).Value
    Next coluna
    EstiloCabecalho wsDestino.Range(wsDestino.Cells(linhaDestino, 1), wsDestino.Cells(linhaDestino, ultimaCol))

    For linhaOrigem = 2 To ultimaLinha
        If CStr(wsOrigem.Cells(linhaOrigem, colunaFiltro).Value) = valorFiltro Then
            linhaDestino = linhaDestino + 1
            For coluna = 1 To ultimaCol
                wsDestino.Cells(linhaDestino, coluna).Value = wsOrigem.Cells(linhaOrigem, coluna).Value
                wsDestino.Cells(linhaDestino, coluna).NumberFormat = wsOrigem.Cells(linhaOrigem, coluna).NumberFormat
            Next coluna
            copiadas = copiadas + 1
        End If
    Next linhaOrigem
    CopiarLinhasDaLoja = copiadas
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
