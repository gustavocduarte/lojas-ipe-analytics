Attribute VB_Name = "ModuloLoja"
Option Explicit

' Cria a aba "Loja XX" com os numeros da loja escolhida, copiados das abas Lojas, Vendedores e
' Alertas abertos deste mesmo arquivo. Nao acessa banco, rede nem nenhum outro arquivo.
' Atalho: Ctrl+Shift+L (veja ModuloAtalhos) ou Alt+F8 > GerarAbaDaLoja.

Private Const ABA_LOJAS As String = "Lojas"
Private Const ABA_VENDEDORES As String = "Vendedores"
Private Const ABA_ALERTAS As String = "Alertas abertos"
Private Const ABA_DADOS As String = "Dados por loja"   ' oculta; o Python grava nela os dados por loja
Private Const TITULO_CODIGO_LOJA As String = "Loja"
Private Const TITULO_NOME_LOJA As String = "Nome"
Private Const TITULO_LOJA_NOS_ALERTAS As String = "Loja ou centro de custo"
Private Const TITULO_NOME_DA_LOJA As String = "Nome da loja"
Private Const LARGURA_MINIMA As Double = 14      ' cabe "R$ 9.999.999,99"
Private Const LARGURA_MAXIMA As Double = 45
Private Const PREFIXO_COBERTURA As String = "Cobertura"   ' cobertura: verde a partir de 100%
Private Const PREFIXO_EVOLUCAO As String = "Evolu"        ' evolucao: verde a partir de 0%
Private Const TITULO_DESTAQUE As String = "Destaque"
Private Const FONTE_ABA As String = "Calibri"           ' uma unica fonte em toda a aba
Private Const TAMANHO_FONTE As Long = 11
Private Const PREFIXO_POSICAO As String = "Posi"        ' colunas de posicao (ranking): centralizadas
' Estilo unico de titulo de secao (o mesmo do Python, titulo_de_secao em planilha.py).
Private Const TAMANHO_TITULO As Long = 13
Private Const ALTURA_TITULO As Long = 22
Private Const COR_TITULO As Long = 7884319           ' RGB(31, 78, 120), o azul do cabecalho
Private Const COLUNAS_DO_TITULO As Long = 5          ' largura do titulo da aba (A1)
' Blocos da aba "Dados por loja": coluna inicial (a da Loja) e quantidade de colunas de cada um.
Private Const COL_PRODUTOS As Long = 1
Private Const COLS_PRODUTOS As Long = 6
Private Const COL_DIA_SEMANA As Long = 8
Private Const COLS_DIA_SEMANA As Long = 5
Private Const COL_FAIXA As Long = 14
Private Const COLS_FAIXA As Long = 5
Private Const COLUNAS_DA_EXPLICACAO As Long = 5   ' a Explicacao ocupa colunas mescladas
Private Const CARACTERES_POR_LINHA As Long = 75
Private Const PRIMEIRA_COLUNA_INDICADOR As Long = 4   ' Lojas: colunas 1 a 3 = Loja, Nome, UF
Private Const COLUNAS_DO_DIA As Long = 3              ' Venda do dia, Meta do dia, Cobertura do dia

Public Sub GerarAbaDaLoja()
    Dim wsLojas As Worksheet, wsVendedores As Worksheet, wsAlertas As Worksheet, wsNova As Worksheet
    Dim wsDados As Worksheet
    Dim qtdProdutos As Long, qtdDias As Long, qtdFaixas As Long, colFinalAlertas As Long
    Dim codigo As String, nomeLoja As String, uf As String
    Dim linhaLoja As Long, linha As Long
    Dim qtdVendedores As Long, qtdAlertas As Long, linhaAlertas As Long

    On Error GoTo TrataErro
    Set wsLojas = ThisWorkbook.Worksheets(ABA_LOJAS)
    Set wsVendedores = ThisWorkbook.Worksheets(ABA_VENDEDORES)
    Set wsAlertas = ThisWorkbook.Worksheets(ABA_ALERTAS)
    Set wsDados = ThisWorkbook.Worksheets(ABA_DADOS)

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
    wsNova.Cells.Font.Size = TAMANHO_FONTE
    PadronizarFonte wsNova
    TituloDeSecao wsNova, 1, 1, COLUNAS_DO_TITULO, "Loja " & codigo & " - " & nomeLoja & " (" & uf & ")"

    ' Indicadores em dois blocos, "Dia" e "Mes": titulo na coluna A, valor na B, mesmo formato.
    linha = 3
    linha = CopiarIndicadores(wsLojas, linhaLoja, wsNova, linha, "Dia", _
                              PRIMEIRA_COLUNA_INDICADOR, PRIMEIRA_COLUNA_INDICADOR + COLUNAS_DO_DIA - 1)
    linha = CopiarIndicadores(wsLojas, linhaLoja, wsNova, linha + 1, "M" & ChrW(234) & "s", _
                              PRIMEIRA_COLUNA_INDICADOR + COLUNAS_DO_DIA, UltimaColuna(wsLojas))

    ' Nas tabelas a loja e o nome dela (repetidos em toda linha) ficam de fora.
    linha = linha + 1
    qtdVendedores = CopiarLinhasDaLoja(wsVendedores, TITULO_CODIGO_LOJA, codigo, wsNova, linha, _
                                       "Vendedores", TITULO_CODIGO_LOJA, TITULO_NOME_DA_LOJA, 0)
    linha = linha + qtdVendedores + 3
    ' Produtos e "quando a loja vende" vem da aba de apoio; so as linhas desta loja sao copiadas.
    qtdProdutos = CopiarDadosDaLoja(wsDados, COL_PRODUTOS, COLS_PRODUTOS, codigo, wsNova, linha)
    linha = linha + qtdProdutos + 3
    qtdDias = CopiarDadosDaLoja(wsDados, COL_DIA_SEMANA, COLS_DIA_SEMANA, codigo, wsNova, linha)
    linha = linha + qtdDias + 3
    qtdFaixas = CopiarDadosDaLoja(wsDados, COL_FAIXA, COLS_FAIXA, codigo, wsNova, linha)
    linha = linha + qtdFaixas + 3
    linhaAlertas = linha
    ' O titulo dos alertas cobre a tabela inteira, ate a ultima coluna da Explicacao mesclada.
    colFinalAlertas = ColunaDoTitulo(wsAlertas, TituloExplicacao()) + COLUNAS_DA_EXPLICACAO - 1
    qtdAlertas = CopiarLinhasDaLoja(wsAlertas, TITULO_LOJA_NOS_ALERTAS, nomeLoja, wsNova, linha, _
                                    "Alertas abertos", "", "", colFinalAlertas)

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
    TituloDeSecao wsDestino, linhaInicial, 1, 2, bloco
    linha = linhaInicial + 1
    For coluna = colInicial To colFinal
        wsDestino.Cells(linha, 1).Value = wsLojas.Cells(1, coluna).Value
        wsDestino.Cells(linha, 2).Value = wsLojas.Cells(linhaLoja, coluna).Value
        wsDestino.Cells(linha, 2).NumberFormat = wsLojas.Cells(linhaLoja, coluna).NumberFormat
        CorDoIndicador wsDestino.Cells(linha, 2), CStr(wsDestino.Cells(linha, 1).Value)
        linha = linha + 1
    Next coluna
    CopiarIndicadores = linha
End Function

' Copia para wsDestino (a partir de linhaInicial) o titulo da secao, o cabecalho e as linhas de
' wsOrigem em que a coluna tituloFiltro vale valorFiltro, sem as colunas de titulo omitir1/omitir2.
' Devolve quantas linhas foram copiadas.
Private Function CopiarLinhasDaLoja(wsOrigem As Worksheet, tituloFiltro As String, valorFiltro As String, _
                                    wsDestino As Worksheet, linhaInicial As Long, secao As String, _
                                    omitir1 As String, omitir2 As String, ByVal colunasDoTitulo As Long) As Long
    Dim colunaFiltro As Long, ultimaLinha As Long, ultimaCol As Long
    Dim linhaOrigem As Long, linhaDestino As Long, coluna As Long, colDestino As Long, copiadas As Long
    Dim titulo As String, linhaCabecalho As Long, qtdColunas As Long

    colunaFiltro = ColunaDoTitulo(wsOrigem, tituloFiltro)
    ultimaLinha = wsOrigem.Cells(wsOrigem.Rows.Count, 1).End(xlUp).Row
    ultimaCol = UltimaColuna(wsOrigem)

    linhaDestino = linhaInicial + 1
    For coluna = 1 To ultimaCol
        titulo = CStr(wsOrigem.Cells(1, coluna).Value)
        If titulo <> omitir1 And titulo <> omitir2 Then
            colDestino = colDestino + 1
            wsDestino.Cells(linhaDestino, colDestino).Value = titulo
        End If
    Next coluna
    EstiloCabecalho wsDestino.Range(wsDestino.Cells(linhaDestino, 1), wsDestino.Cells(linhaDestino, colDestino))
    linhaCabecalho = linhaDestino
    qtdColunas = colDestino
    If colunasDoTitulo = 0 Then colunasDoTitulo = qtdColunas
    TituloDeSecao wsDestino, linhaInicial, 1, colunasDoTitulo, secao

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
    CentralizarPosicao wsDestino, linhaCabecalho, linhaDestino, qtdColunas
    If copiadas > 0 Then
        For coluna = 1 To qtdColunas
            titulo = CStr(wsDestino.Cells(linhaCabecalho, coluna).Value)
            If Left$(titulo, Len(PREFIXO_COBERTURA)) = PREFIXO_COBERTURA Then
                CorDeStatus wsDestino.Range(wsDestino.Cells(linhaCabecalho + 1, coluna), _
                                            wsDestino.Cells(linhaDestino, coluna)), 1
            End If
        Next coluna
    End If
    CopiarLinhasDaLoja = copiadas
End Function

' Copia de "Dados por loja" um bloco: titulo (linha 1 do bloco), cabecalho (linha 2) e as linhas
' da loja escolhida, sem a primeira coluna do bloco (a Loja). A linha em que a ultima coluna
' (Destaque) vem preenchida fica em negrito com fundo verde claro. Devolve quantas linhas copiou.
Private Function CopiarDadosDaLoja(wsDados As Worksheet, colInicial As Long, qtdColunas As Long, _
                                   codigo As String, wsDestino As Worksheet, linhaInicial As Long) As Long
    Dim ultimaLinha As Long, linhaOrigem As Long, linhaDestino As Long
    Dim coluna As Long, copiadas As Long, comDestaque As Boolean

    TituloDeSecao wsDestino, linhaInicial, 1, qtdColunas - 1, CStr(wsDados.Cells(1, colInicial).Value)
    linhaDestino = linhaInicial + 1
    For coluna = 1 To qtdColunas - 1
        wsDestino.Cells(linhaDestino, coluna).Value = wsDados.Cells(2, colInicial + coluna).Value
    Next coluna
    EstiloCabecalho wsDestino.Range(wsDestino.Cells(linhaDestino, 1), wsDestino.Cells(linhaDestino, qtdColunas - 1))
    comDestaque = (CStr(wsDados.Cells(2, colInicial + qtdColunas - 1).Value) = TITULO_DESTAQUE)

    ultimaLinha = wsDados.Cells(wsDados.Rows.Count, colInicial).End(xlUp).Row
    For linhaOrigem = 3 To ultimaLinha
        If CStr(wsDados.Cells(linhaOrigem, colInicial).Value) = codigo Then
            linhaDestino = linhaDestino + 1
            For coluna = 1 To qtdColunas - 1
                wsDestino.Cells(linhaDestino, coluna).Value = wsDados.Cells(linhaOrigem, colInicial + coluna).Value
                wsDestino.Cells(linhaDestino, coluna).NumberFormat = wsDados.Cells(linhaOrigem, colInicial + coluna).NumberFormat
            Next coluna
            If comDestaque Then
                If Len(CStr(wsDados.Cells(linhaOrigem, colInicial + qtdColunas - 1).Value)) > 0 Then
                    EstiloDestaque wsDestino.Range(wsDestino.Cells(linhaDestino, 1), wsDestino.Cells(linhaDestino, qtdColunas - 1))
                End If
            End If
            copiadas = copiadas + 1
        End If
    Next linhaOrigem
    CentralizarPosicao wsDestino, linhaInicial + 1, linhaDestino, qtdColunas - 1
    CopiarDadosDaLoja = copiadas
End Function

' A coluna de posicao (ranking) fica centralizada, cabecalho e numeros, para nao herdar o aspecto
' da coluna A, que e larga por causa dos rotulos dos indicadores.
Private Sub CentralizarPosicao(ws As Worksheet, linhaCabecalho As Long, ultimaLinha As Long, qtdColunas As Long)
    Dim coluna As Long
    For coluna = 1 To qtdColunas
        If Left$(CStr(ws.Cells(linhaCabecalho, coluna).Value), Len(PREFIXO_POSICAO)) = PREFIXO_POSICAO Then
            ws.Range(ws.Cells(linhaCabecalho, coluna), ws.Cells(ultimaLinha, coluna)).HorizontalAlignment = xlCenter
        End If
    Next coluna
End Sub

' O Excel usa a fonte do estilo Normal da pasta; aqui a aba inteira (inclusive o que vem copiado
' da aba Alertas abertos) usa sempre a mesma.
Private Sub PadronizarFonte(ws As Worksheet)
    ws.Cells.Font.Name = FONTE_ABA
End Sub

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

' Cobertura (verde a partir de 100%) e evolucao (verde a partir de 0%) levam a cor de status, como
' nas abas geradas pelo Python; "% da meta do mes atingido" so informa e nao leva cor.
Private Sub CorDoIndicador(celula As Range, titulo As String)
    If Left$(titulo, Len(PREFIXO_COBERTURA)) = PREFIXO_COBERTURA Then CorDeStatus celula, 1
    If Left$(titulo, Len(PREFIXO_EVOLUCAO)) = PREFIXO_EVOLUCAO Then CorDeStatus celula, 0
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

Private Sub EstiloDestaque(faixa As Range)
    faixa.Font.Bold = True
    faixa.Interior.Color = RGB(226, 239, 218)
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

' A Explicacao (texto longo) ocupa colunas mescladas, com quebra de texto, para nenhuma coluna de
' numeros ficar larga; as demais colunas usam AutoFit com minimo e maximo.
Private Sub AjustarLarguras(ws As Worksheet, colunaExplicacao As Long, primeiraLinhaAlertas As Long, _
                            qtdAlertas As Long)
    Dim coluna As Long, linha As Long, linhas As Long, ultimaCol As Long
    Dim ultimaLinha As Long, necessaria As Double
    ultimaCol = colunaExplicacao + COLUNAS_DA_EXPLICACAO - 1
    For linha = primeiraLinhaAlertas - 1 To primeiraLinhaAlertas + qtdAlertas - 1
        ws.Range(ws.Cells(linha, colunaExplicacao), ws.Cells(linha, ultimaCol)).Merge
    Next linha
    EstiloCabecalho ws.Range(ws.Cells(primeiraLinhaAlertas - 1, 1), ws.Cells(primeiraLinhaAlertas - 1, ultimaCol))
    PadronizarFonte ws   ' de novo, antes do AutoFit: a largura depende da fonte
    ws.UsedRange.Columns.AutoFit
    ' O AutoFit sozinho cortava textos longos (Tipo e Vendedor dos alertas): a coluna nunca fica
    ' mais estreita que o maior texto dela.
    ultimaLinha = ws.Cells(ws.Rows.Count, 1).End(xlUp).Row
    For coluna = 1 To ultimaCol
        necessaria = LarguraDoTexto(ws, coluna, ultimaLinha)
        If ws.Columns(coluna).ColumnWidth < necessaria Then ws.Columns(coluna).ColumnWidth = necessaria
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
