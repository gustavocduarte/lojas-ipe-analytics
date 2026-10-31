Attribute VB_Name = "ModuloAtalhos"
Option Explicit

' Atalhos de teclado das macros. O Excel executa Auto_Open ao abrir o arquivo (com macros
' habilitadas) e Auto_Close ao fechar. Sem os atalhos, use Alt+F8 e escolha a macro.
'   Ctrl+Shift+L -> GerarAbaDaLoja
'   Ctrl+Shift+P -> ExportarResumoPDF

Public Sub RegistrarAtalhos()
    Application.OnKey "^+L", "GerarAbaDaLoja"
    Application.OnKey "^+P", "ExportarResumoPDF"
End Sub

Public Sub RemoverAtalhos()
    Application.OnKey "^+L"
    Application.OnKey "^+P"
End Sub

Public Sub Auto_Open()
    RegistrarAtalhos
End Sub

Public Sub Auto_Close()
    RemoverAtalhos
End Sub
