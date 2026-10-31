Attribute VB_Name = "ModuloPDF"
Option Explicit

' Exporta a aba "Resumo da rede" para PDF (paisagem, uma pagina), na mesma pasta do arquivo.
' Atalho: Ctrl+Shift+P (veja ModuloAtalhos) ou Alt+F8 > ExportarResumoPDF.

Private Const ABA_RESUMO As String = "Resumo da rede"

Public Sub ExportarResumoPDF()
    Dim ws As Worksheet
    Dim pasta As String, arquivo As String

    On Error GoTo TrataErro
    Set ws = ThisWorkbook.Worksheets(ABA_RESUMO)

    pasta = ThisWorkbook.Path
    If Len(pasta) = 0 Then pasta = Environ$("USERPROFILE")   ' arquivo ainda nao salvo
    arquivo = pasta & Application.PathSeparator & "Resumo_da_rede_" & Format$(Date, "yyyy-mm-dd") & ".pdf"

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
