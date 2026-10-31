Attribute VB_Name = "ModuloPDF"
Option Explicit

' Exporta a aba "Resumo da rede" para PDF (paisagem, uma pagina), na mesma pasta do arquivo.
' O nome do arquivo usa a data de posicao do relatorio (nome definido DataPosicao, gravado pelo
' gerador), nao a data de hoje.
' Atalho: Ctrl+Shift+P (veja ModuloAtalhos) ou Alt+F8 > ExportarResumoPDF.

Private Const ABA_RESUMO As String = "Resumo da rede"
Private Const NOME_DATA_POSICAO As String = "DataPosicao"

Public Sub ExportarResumoPDF()
    Dim ws As Worksheet
    Dim pasta As String, arquivo As String
    Dim dataPosicao As Date

    On Error GoTo TrataErro
    Set ws = ThisWorkbook.Worksheets(ABA_RESUMO)

    dataPosicao = DataDePosicao()
    pasta = ThisWorkbook.Path
    If Len(pasta) = 0 Then pasta = Environ$("USERPROFILE")   ' arquivo ainda nao salvo
    arquivo = pasta & Application.PathSeparator & "Resumo_da_rede_" & Format$(dataPosicao, "yyyy-mm-dd") & ".pdf"

    With ws.PageSetup
        .Orientation = xlLandscape
        .Zoom = False
        .FitToPagesWide = 1
        .FitToPagesTall = 1
    End With

    ws.ExportAsFixedFormat Type:=xlTypePDF, Filename:=arquivo, Quality:=xlQualityStandard, _
                           IncludeDocProperties:=True, IgnorePrintAreas:=False, OpenAfterPublish:=False
    MsgBox "PDF salvo em:" & vbCrLf & arquivo, vbInformation, "Resumo da rede em PDF"
    Exit Sub

TrataErro:
    MsgBox "Nao foi possivel exportar o PDF: " & Err.Description, vbCritical
End Sub

' Data de posicao gravada pelo gerador na celula apontada pelo nome definido DataPosicao.
Private Function DataDePosicao() As Date
    Dim valor As Variant
    On Error Resume Next
    valor = ThisWorkbook.Names(NOME_DATA_POSICAO).RefersToRange.Value
    On Error GoTo 0
    If Not IsDate(valor) Then
        Err.Raise vbObjectError + 2, , "Nome '" & NOME_DATA_POSICAO & "' ausente ou sem data. " & _
                  "Gere o arquivo de novo pelo relatorio."
    End If
    DataDePosicao = CDate(valor)
End Function
