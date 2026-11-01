"""Teste estático dos módulos VBA (o CI não tem Excel): estrutura, segurança e consistência com a
planilha gerada. O roteiro de teste manual está em docs/macro_vba.md."""

import re
import zipfile
from pathlib import Path

import pytest
from openpyxl import load_workbook

from src import config
from src.relatorios import planilha
from src.relatorios.planilha import montar_pasta
from tests.relatorios.test_planilha import _dados

MODULOS = {
    "ModuloLoja": {"GerarAbaDaLoja"},
    "ModuloPDF": {"ExportarResumoPDF"},
    "ModuloAtalhos": {"RegistrarAtalhos", "RemoverAtalhos", "Auto_Open", "Auto_Close"},
}
PROIBIDOS = [
    r"\bShell\b", r"\bKill\b", r"\bCreateObject\b", r"\bADODB\b", r"Provider\s*=", r"\bhttps?:",
    r"\bWorkbooks\.Open\b", r"\bDeclare\b", r"\bSendKeys\b", r"\bURLDownload",
]  # fmt: skip
ABAS_CONHECIDAS = {
    planilha.ABA_RESUMO, planilha.ABA_LOJAS, planilha.ABA_VENDEDORES, planilha.ABA_ALERTAS,
    planilha.ABA_PREVISAO, planilha.ABA_DADOS_POR_LOJA,
}  # fmt: skip


def _ler(nome: str) -> str:
    return (config.DIR_VBA / f"{nome}.bas").read_bytes().decode("ascii")


def _codigo(nome: str) -> list[str]:
    """Linhas sem comentário (o apóstrofo dentro de texto entre aspas não ocorre nestes módulos)."""
    return [re.sub(r"'.*$", "", linha).rstrip() for linha in _ler(nome).splitlines()]


@pytest.mark.parametrize("modulo", MODULOS)
def test_arquivo_pronto_para_importar_no_editor_do_vba(modulo):
    texto = _ler(modulo)  # ASCII puro: importa igual em qualquer página de código do Windows
    linhas = texto.split("\r\n")
    assert linhas[0] == f'Attribute VB_Name = "{modulo}"'
    assert "Option Explicit" in linhas[:3]
    assert "\n" not in texto.replace("\r\n", "")  # só quebras CRLF


@pytest.mark.parametrize("modulo,esperadas", MODULOS.items())
def test_procedimentos_publicos_esperados(modulo, esperadas):
    publicas = set(re.findall(r"^Public Sub (\w+)\(", _ler(modulo), flags=re.M))
    assert publicas == esperadas


@pytest.mark.parametrize("modulo", MODULOS)
def test_blocos_balanceados(modulo):
    codigo = "\n".join(_codigo(modulo))
    aberturas = len(re.findall(r"^\s*(?:Public |Private )?(?:Sub|Function)\s", codigo, flags=re.M))
    assert aberturas == len(re.findall(r"^\s*End (?:Sub|Function)\b", codigo, flags=re.M))
    assert len(re.findall(r"\bThen\s*$", codigo, flags=re.M)) == len(
        re.findall(r"^\s*End If\b", codigo, flags=re.M)
    )
    assert len(re.findall(r"^\s*For\b", codigo, flags=re.M)) == len(
        re.findall(r"^\s*Next\b", codigo, flags=re.M)
    )
    assert len(re.findall(r"^\s*With\b", codigo, flags=re.M)) == len(
        re.findall(r"^\s*End With\b", codigo, flags=re.M)
    )


@pytest.mark.parametrize("modulo", MODULOS)
def test_sem_caminho_absoluto_rede_banco_ou_comando_do_sistema(modulo):
    codigo = "\n".join(_codigo(modulo))
    assert not re.search(r"[A-Za-z]:\\|\\\\\w|/Users/|/home/", codigo)  # caminhos fixos
    for padrao in PROIBIDOS:
        assert not re.search(padrao, codigo, flags=re.I), padrao


def test_abas_citadas_nas_macros_existem_na_planilha_gerada():
    citadas = set()
    for modulo in MODULOS:
        citadas |= set(re.findall(r'Const ABA_\w+ As String = "([^"]+)"', _ler(modulo)))
    assert citadas and citadas <= ABAS_CONHECIDAS


def test_titulos_de_coluna_citados_nas_macros_existem_nas_abas():
    texto = _ler("ModuloLoja")
    titulos = dict(re.findall(r'Const (TITULO_\w+) As String = "([^"]+)"', texto))
    de = lambda colunas: {t for t, _ in colunas.values()}  # noqa: E731
    assert titulos["TITULO_CODIGO_LOJA"] in de(planilha.COLUNAS_LOJAS)
    assert titulos["TITULO_CODIGO_LOJA"] in de(planilha.COLUNAS_VENDEDORES)
    assert titulos["TITULO_NOME_LOJA"] in de(planilha.COLUNAS_LOJAS)
    assert titulos["TITULO_LOJA_NOS_ALERTAS"] in de(planilha.COLUNAS_ALERTAS)
    assert titulos["TITULO_NOME_DA_LOJA"] in de(planilha.COLUNAS_VENDEDORES)


def test_atalhos_apontam_para_macros_que_existem():
    texto = _ler("ModuloAtalhos")
    alvos = re.findall(r'Application\.OnKey "[^"]+", "(\w+)"', texto)
    publicas = {nome for esperadas in MODULOS.values() for nome in esperadas}
    assert alvos and set(alvos) <= publicas
    assert len(re.findall(r'Application\.OnKey "[^"]+"\s*$', texto, flags=re.M)) == len(alvos)


MODELO = Path(config.ARQ_MODELO_XLSM)


@pytest.mark.skipif(not MODELO.exists(), reason="vba/modelo_fechamento.xlsm ainda não foi criado")
def test_xlsm_gerado_a_partir_do_modelo_mantem_o_projeto_vba(tmp_path):
    destino = tmp_path / "fechamento.xlsm"
    montar_pasta(_dados(), load_workbook(MODELO, keep_vba=True)).save(destino)
    with zipfile.ZipFile(destino) as pacote:
        nomes = pacote.namelist()
        assert "xl/vbaProject.bin" in nomes
        assert "macroEnabled" in pacote.read("[Content_Types].xml").decode("utf-8")
    assert load_workbook(destino).sheetnames[0] == planilha.ABA_RESUMO


@pytest.mark.skipif(not MODELO.exists(), reason="vba/modelo_fechamento.xlsm ainda não foi criado")
def test_modelo_traz_os_tres_modulos_importados():
    with zipfile.ZipFile(MODELO) as pacote:
        projeto = pacote.read("xl/vbaProject.bin")
    for modulo in MODULOS:
        assert modulo.encode("utf-16-le") in projeto  # nome do fluxo no arquivo OLE


def test_pdf_usa_a_data_de_posicao_e_nao_a_de_hoje():
    codigo = "\n".join(_codigo("ModuloPDF")).replace("As Date", "")
    assert f'"{planilha.NOME_DATA_POSICAO}"' in _ler("ModuloPDF")
    assert not re.search(r"\bDate\b|\bNow\b|\bToday\b", codigo)


def test_loja_ajusta_larguras_e_usa_o_titulo_certo_da_explicacao():
    texto = _ler("ModuloLoja")
    assert "AutoFit" in texto and "WrapText = True" in texto
    # titulo com acento montado por codigo (arquivo em ASCII puro): "Explica" + ç + ã + "o"
    assert "ChrW(231) & ChrW(227)" in texto
    titulo = "Explica" + chr(231) + chr(227) + "o"
    assert titulo in {t for t, _ in planilha.COLUNAS_ALERTAS.values()}


def test_blocos_dia_e_mes_da_aba_da_loja_seguem_a_ordem_das_colunas_de_lojas():
    texto = _ler("ModuloLoja")
    primeira = int(re.search(r"PRIMEIRA_COLUNA_INDICADOR As Long = (\d+)", texto).group(1))
    do_dia = int(re.search(r"COLUNAS_DO_DIA As Long = (\d+)", texto).group(1))
    titulos = [titulo for titulo, _ in planilha.COLUNAS_LOJAS.values()]
    assert titulos[primeira - 3 : primeira - 1] == [
        "Nome",
        "UF",
    ]  # o título da aba usa o nome e a UF
    assert titulos[primeira - 1 : primeira - 1 + do_dia] == [
        "Venda do dia", "Meta do dia", "Cobertura do dia",
    ]  # fmt: skip
    assert "dia" not in titulos[primeira - 1 + do_dia]  # o bloco do mês começa depois


def test_explicacao_nao_alarga_coluna_de_numeros():
    texto = _ler("ModuloLoja")
    assert ".Merge" in texto  # texto longo em colunas mescladas, não em uma coluna só
    assert "LARGURA_EXPLICACAO" not in texto


def _constantes_longas(texto: str) -> dict:
    return {k: int(v) for k, v in re.findall(r"Const (\w+) As Long = (\d+)", texto)}


def test_blocos_da_aba_de_apoio_estao_nas_colunas_que_a_macro_espera(tmp_path):
    consts = _constantes_longas(_ler("ModuloLoja"))
    destaque = re.search(r'TITULO_DESTAQUE As String = "([^"]+)"', _ler("ModuloLoja")).group(1)
    caminho = tmp_path / "f.xlsx"
    montar_pasta(_dados()).save(caminho)
    ws = load_workbook(caminho)[planilha.ABA_DADOS_POR_LOJA]
    assert ws.sheet_state == "hidden"  # a macro lê aba oculta sem problema
    blocos = {
        "PRODUTOS": (planilha.COLUNAS_DADOS_PRODUTOS_LOJA, False),
        "DIA_SEMANA": (planilha.COLUNAS_DADOS_DIA_DA_SEMANA, True),
        "FAIXA": (planilha.COLUNAS_DADOS_FAIXA, True),
    }
    for nome, (colunas, com_destaque) in blocos.items():
        inicio, quantas = consts[f"COL_{nome}"], consts[f"COLS_{nome}"]
        assert quantas == len(colunas)
        assert ws.cell(2, inicio).value == "Loja"  # a macro filtra por esta coluna
        assert ws.cell(2, inicio + quantas).value is None  # coluna em branco depois do bloco
        assert (
            "mês" in ws.cell(1, inicio).value or "Quando a loja vende" in ws.cell(1, inicio).value
        )
        assert (ws.cell(2, inicio + quantas - 1).value == destaque) is com_destaque


def test_cor_de_status_da_macro_segue_as_regras_das_abas_geradas(tmp_path):
    texto = _ler("ModuloLoja")
    cobertura = re.search(r'PREFIXO_COBERTURA As String = "([^"]+)"', texto).group(1)
    evolucao = re.search(r'PREFIXO_EVOLUCAO As String = "([^"]+)"', texto).group(1)
    caminho = tmp_path / "f.xlsx"
    montar_pasta(_dados()).save(caminho)
    pasta = load_workbook(caminho)
    for aba, colunas in (
        (planilha.ABA_LOJAS, planilha.COLUNAS_LOJAS),
        (planilha.ABA_VENDEDORES, planilha.COLUNAS_VENDEDORES),
    ):
        titulos = [t for t, _ in colunas.values()]
        coloridos = {
            titulos[openpyxl_coluna(str(regra.sqref)) - 1]
            for regra in pasta[aba].conditional_formatting
        }
        pela_macro = {t for t in titulos if t.startswith((cobertura, evolucao))}
        assert coloridos == pela_macro, aba
    # os dois verdes: o 1 (100%) das coberturas e o 0 (0%) da evolução
    assert "Operator:=xlGreaterEqual" in texto and "RGB(198, 239, 206)" in texto
    assert "RGB(255, 199, 206)" in texto
    assert "CorDeStatus celula, 1" in texto and "CorDeStatus celula, 0" in texto


def openpyxl_coluna(intervalo: str) -> int:
    from openpyxl.utils import column_index_from_string

    return column_index_from_string(re.match(r"[A-Z]+", intervalo).group(0))


def test_aba_da_loja_inclui_produtos_quando_a_loja_vende_e_larguras_pelo_texto():
    texto = _ler("ModuloLoja")
    assert texto.count("= CopiarDadosDaLoja(wsDados") == 3  # produtos, dia da semana e faixa
    assert "LarguraDoTexto" in texto
    assert re.search(r"LARGURA_MAXIMA As Double = (\d+)", texto).group(1) == "45"


def test_titulo_de_secao_da_macro_tem_o_mesmo_estilo_do_python():
    texto = _ler("ModuloLoja")
    consts = _constantes_longas(texto)
    assert consts["TAMANHO_TITULO"] == planilha.TAMANHO_TITULO_SECAO
    assert consts["ALTURA_TITULO"] == planilha.ALTURA_TITULO_SECAO
    r, g, b = (int(planilha.COR_CABECALHO[i : i + 2], 16) for i in (0, 2, 4))
    assert consts["COR_TITULO"] == r + g * 256 + b * 65536  # o azul do cabeçalho do Python
    corpo = texto.split("Private Sub TituloDeSecao(")[1].split("End Sub")[0]
    for trecho in (".Merge", "xlThick", "Font.Size = TAMANHO_TITULO", "Font.Bold = True", "xlLeft"):
        assert trecho in corpo, trecho
    assert "Borders(xlEdgeBottom).Color = COR_TITULO" in corpo


def test_todo_titulo_da_aba_da_loja_passa_pelo_procedimento_unico():
    texto = _ler("ModuloLoja")
    chamadas = re.findall(r"^\s+TituloDeSecao \w+, ", texto, flags=re.M)
    assert len(chamadas) == 4  # título da aba, Dia/Mês, Vendedores/Alertas e os blocos de apoio
    assert "Font.Size = 14" not in texto  # o título solto da aba, em estilo antigo, não existe mais
    assert ".Font.Bold = True\r\n    linhaDestino" not in texto
    assert "EstiloCabecalho wsDestino.Range(wsDestino.Cells(linhaInicial, 1)" not in texto


def test_aba_da_loja_usa_uma_fonte_so_e_centraliza_a_posicao():
    texto = _ler("ModuloLoja")
    assert re.search(r'FONTE_ABA As String = "Calibri"', texto)
    assert texto.count("PadronizarFonte ") >= 2  # ao criar a aba e antes do AutoFit
    assert texto.index("PadronizarFonte ws") < texto.index("ws.UsedRange.Columns.AutoFit")
    prefixo = re.search(r'PREFIXO_POSICAO As String = "([^"]+)"', texto).group(1)
    assert planilha.COLUNAS_VENDEDORES["posicao"][0].startswith(prefixo)
    assert planilha.COLUNAS_DADOS_PRODUTOS_LOJA["posicao"][0].startswith(prefixo)
    assert texto.count("CentralizarPosicao wsDestino") == 2  # tabelas copiadas e blocos de apoio
    assert "HorizontalAlignment = xlCenter" in texto.split("Sub CentralizarPosicao")[1]
