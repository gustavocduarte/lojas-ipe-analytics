"""Montagem do .xlsx de fechamento (openpyxl): abas, formatos brasileiros, filtros e gráficos.

Os números entram como valores (nunca fórmulas), já calculados no dw: assim o arquivo é igual em
qualquer Excel e os testes conseguem lê-lo sem recalcular. Os formatos de número usam a notação
interna do Excel (vírgula de milhar, ponto decimal); quem abre em português do Brasil enxerga
"R$ 1.234,56" e "12,5%", e as datas aparecem como dd/mm/aaaa.
"""

from dataclasses import dataclass, field
from datetime import date, datetime

import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.chart.layout import Layout, ManualLayout
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.page import PageMargins
from openpyxl.worksheet.properties import PageSetupProperties

from src import config

FORMATO_REAL = '"R$" #,##0.00'
FORMATO_PERCENTUAL = "0.0%"
FORMATO_DATA = "dd/mm/yyyy"
FORMATO_MES = "mm/yyyy"
FORMATO_INTEIRO = "#,##0"
FORMATO_EVOLUCAO = "+0.0%;-0.0%;0.0%"

COR_CABECALHO = "1F4E78"
COR_VERDE = "C6EFCE"
COR_VERMELHO = "FFC7CE"
COR_TEXTO_VERDE = "006100"
COR_TEXTO_VERMELHO = "9C0006"
COR_TEXTO = "262626"
COR_CINZA = "595959"
COR_BORDA = "BFBFBF"
COR_FUNDO_CARTAO = "F2F2F2"
COR_FAIXA_SUBTITULO = "DDEBF7"
COR_STATUS_VERDE = "2E7D32"
COR_STATUS_VERMELHO = "C00000"
FONTE = "Calibri"

ABA_RESUMO = "Resumo da rede"
ABA_DIARIO = "Diário"
ABA_LOJAS = "Lojas"
ABA_VENDEDORES = "Vendedores"
ABA_PRODUTOS = "Produtos"
ABA_ALERTAS = "Alertas abertos"
ABA_PREVISAO = "Previsão"
ABA_PREVISAO_DIARIA = "Previsão diária"
ABA_DADOS_POR_LOJA = "Dados por loja"  # oculta: a macro GerarAbaDaLoja lê só o próprio arquivo
NOME_DATA_POSICAO = "DataPosicao"  # nome definido lido pela macro ExportarResumoPDF
FONTE_RODAPE = "Fonte: dw lojas_ipe_dw"

# layout da aba Resumo (1 página A4 paisagem): 12 colunas iguais
COLUNAS_DO_RESUMO, LARGURA_COLUNA_RESUMO = 12, 16
COLUNAS_POR_CARTAO, COLUNAS_POR_INDICADOR = 3, 2
LINHA_DO_GRAFICO, LINHAS_DO_GRAFICO = 12, 17
COR_PROJECAO = "BFBFBF"  # barras da venda projetada, cinza-claro
ALTURA_GRAFICO_CM, LARGURA_GRAFICO_CM = 9, 37  # a largura total das 12 colunas
LOJAS_POR_PONTA = 5
ORDEM_SEVERIDADE = ("Crítica", "Alta", "Média", "Baixa")
TITULO_VENDA_ACUMULADA = "Venda acumulada no mês"
TITULO_PROJECAO = "Projeção de fechamento"
TITULO_EVOLUCAO = "Evolução vs mesmo período do ano anterior"

# largura (em caracteres) que cabe o maior valor de cada formato: "R$ 9.999.999,99" e semelhantes
LARGURA_POR_FORMATO = {
    FORMATO_REAL: 18, FORMATO_PERCENTUAL: 10, FORMATO_DATA: 12, FORMATO_MES: 10,
    FORMATO_INTEIRO: 10,
}  # fmt: skip
LARGURA_TEXTO_MINIMA, LARGURA_TEXTO_MAXIMA = 12, 60
ALTURA_CABECALHO = 45  # até três linhas de título

# A cobertura que manda (e tem cor de status) compara com a meta acumulada até o dia; a razão com a
# meta do mês inteiro só informa quanto da meta mensal já foi feito.
TITULO_COBERTURA_ATE_O_DIA = "Cobertura da meta até o dia"
TITULO_META_DO_MES_ATINGIDO = "% da meta do mês atingido"

# nome da coluna na consulta -> (título na planilha, formato)
COLUNAS_LOJAS = {
    "cod_loja": ("Loja", None), "nome_loja": ("Nome", None), "uf": ("UF", None),
    "venda_dia": ("Venda do dia", FORMATO_REAL), "meta_dia": ("Meta do dia", FORMATO_REAL),
    "cobertura_dia": ("Cobertura do dia", FORMATO_PERCENTUAL),
    "acumulado_mes": ("Acumulado do mês", FORMATO_REAL),
    "meta_acumulada": ("Meta acumulada até o dia", FORMATO_REAL),
    "cobertura_ate_o_dia": (TITULO_COBERTURA_ATE_O_DIA, FORMATO_PERCENTUAL),
    "meta_mes": ("Meta do mês", FORMATO_REAL),
    "cobertura_mes": (TITULO_META_DO_MES_ATINGIDO, FORMATO_PERCENTUAL),
    "acumulado_ano_anterior": ("Mesmo período do ano anterior", FORMATO_REAL),
    "evolucao_ano_anterior": ("Evolução vs ano anterior", FORMATO_PERCENTUAL),
    "projecao_fechamento": ("Projeção de fechamento", FORMATO_REAL),
    "cobertura_projetada": ("Cobertura projetada", FORMATO_PERCENTUAL),
}  # fmt: skip
COLUNAS_VENDEDORES = {
    "posicao": ("Posição na rede", FORMATO_INTEIRO), "cod_vendedor": ("Vendedor", None),
    "nome_vendedor": ("Nome", None), "cod_loja": ("Loja", None),
    "nome_loja": ("Nome da loja", None),
    "acumulado_mes": ("Acumulado do mês", FORMATO_REAL),
    "meta_acumulada": ("Meta acumulada até o dia", FORMATO_REAL),
    "cobertura_ate_o_dia": (TITULO_COBERTURA_ATE_O_DIA, FORMATO_PERCENTUAL),
    "meta_mes": ("Meta do mês", FORMATO_REAL),
    "cobertura_mes": (TITULO_META_DO_MES_ATINGIDO, FORMATO_PERCENTUAL),
    "setor_principal": ("Setor principal", None),
    "percentual_setor_principal": ("% no setor principal", FORMATO_PERCENTUAL),
}  # fmt: skip
COLUNAS_ALERTAS = {
    "severidade": ("Severidade", None), "tipo": ("Tipo", None), "data": ("Data", FORMATO_DATA),
    "loja_ou_centro": ("Loja ou centro de custo", None), "vendedor": ("Vendedor", None),
    "valor_envolvido": ("Valor envolvido", FORMATO_REAL), "status": ("Status", None),
    "explicacao": ("Explicação", None),
}  # fmt: skip
COLUNAS_DIARIO = {
    "dia": ("Dia", FORMATO_DATA), "venda": ("Venda", FORMATO_REAL),
    "meta_dia": ("Meta do dia", FORMATO_REAL),
    "cobertura_dia": ("Cobertura do dia", FORMATO_PERCENTUAL),
    "venda_acumulada": ("Venda acumulada", FORMATO_REAL),
    "meta_acumulada": ("Meta acumulada", FORMATO_REAL),
    "projecao": ("Projeção", FORMATO_REAL),  # venda prevista dos dias depois da posição
}  # fmt: skip
COLUNAS_PRODUTOS = {
    "cod_produto": ("Código", None), "descricao": ("Descrição", None), "setor": ("Setor", None),
    "quantidade": ("Quantidade", FORMATO_INTEIRO), "receita": ("Receita", FORMATO_REAL),
    "margem_percentual": ("Margem %", FORMATO_PERCENTUAL),
    "participacao": ("Participação na receita", FORMATO_PERCENTUAL),
    "participacao_acumulada": ("Participação acumulada", FORMATO_PERCENTUAL),
    "classe": ("Classe ABC", None),
}  # fmt: skip
COLUNAS_SETORES = {
    "setor": ("Setor", None), "receita": ("Receita", FORMATO_REAL),
    "participacao": ("Participação na receita", FORMATO_PERCENTUAL),
    "margem_percentual": ("Margem %", FORMATO_PERCENTUAL),
    "evolucao": ("Evolução vs ano anterior", FORMATO_PERCENTUAL),
}  # fmt: skip
COLUNAS_DADOS_PRODUTOS_LOJA = {
    "cod_loja": ("Loja", None), "posicao": ("Posição", FORMATO_INTEIRO),
    "descricao": ("Produto", None), "setor": ("Setor", None), "receita": ("Receita", FORMATO_REAL),
    "participacao": ("Participação na receita da loja", FORMATO_PERCENTUAL),
}  # fmt: skip
COLUNAS_DADOS_DIA_DA_SEMANA = {
    "cod_loja": ("Loja", None), "dia_da_semana": ("Dia da semana", None),
    "receita_media": ("Receita média por dia", FORMATO_REAL),
    "participacao": ("Participação na receita", FORMATO_PERCENTUAL),
    "destaque": ("Destaque", None),
}  # fmt: skip
COLUNAS_DADOS_FAIXA = {
    "cod_loja": ("Loja", None), "faixa": ("Faixa horária", None),
    "receita_media": ("Receita média por dia", FORMATO_REAL),
    "participacao": ("Participação na receita", FORMATO_PERCENTUAL),
    "destaque": ("Destaque", None),
}  # fmt: skip
# Os três blocos da aba de apoio lado a lado, com uma coluna em branco entre eles; a macro
# GerarAbaDaLoja repete estas posições (ModuloLoja: COL_*/COLS_*; um teste confere).
COLUNA_DADOS_PRODUTOS = 1
COLUNA_DADOS_DIA_DA_SEMANA = COLUNA_DADOS_PRODUTOS + len(COLUNAS_DADOS_PRODUTOS_LOJA) + 1
COLUNA_DADOS_FAIXA = COLUNA_DADOS_DIA_DA_SEMANA + len(COLUNAS_DADOS_DIA_DA_SEMANA) + 1
COLUNAS_PREVISAO = {
    "mes": ("Mês", FORMATO_MES), "cod_loja": ("Loja", None), "nome_loja": ("Nome", None),
    "previsto": ("Previsto", FORMATO_REAL), "faixa_baixa": ("Faixa baixa", FORMATO_REAL),
    "faixa_alta": ("Faixa alta", FORMATO_REAL),
    "wape_backtest_loja": ("Erro (WAPE) no backtest da loja", FORMATO_PERCENTUAL),
}  # fmt: skip
COLUNAS_PREVISAO_DIARIA = {
    "dia": ("Dia", FORMATO_DATA), "previsto": ("Previsto da rede", FORMATO_REAL),
    "faixa_baixa": ("Faixa baixa", FORMATO_REAL), "faixa_alta": ("Faixa alta", FORMATO_REAL),
}  # fmt: skip


@dataclass
class DadosFechamento:
    """Tudo o que o relatório mostra, já consultado no dw."""

    mes: date  # primeiro dia do mês
    dia: date  # dia de posição
    lojas: pd.DataFrame
    indicadores: dict
    vendas_por_dia: pd.DataFrame
    vendedores: pd.DataFrame
    alertas: pd.DataFrame
    previsao_mensal: pd.DataFrame
    previsao_diaria: pd.DataFrame
    gerado_em: datetime = field(default_factory=datetime.now)
    produtos: pd.DataFrame = field(  # os maiores da rede, já com a classe ABC
        default_factory=lambda: pd.DataFrame(columns=list(COLUNAS_PRODUTOS))
    )
    setores: pd.DataFrame = field(
        default_factory=lambda: pd.DataFrame(columns=list(COLUNAS_SETORES))
    )
    produtos_por_loja: pd.DataFrame = field(  # alimentam a macro da aba da loja
        default_factory=lambda: pd.DataFrame(columns=list(COLUNAS_DADOS_PRODUTOS_LOJA))
    )
    dia_da_semana_por_loja: pd.DataFrame = field(
        default_factory=lambda: pd.DataFrame(columns=list(COLUNAS_DADOS_DIA_DA_SEMANA))
    )
    faixa_por_loja: pd.DataFrame = field(
        default_factory=lambda: pd.DataFrame(columns=list(COLUNAS_DADOS_FAIXA))
    )
    projecao_por_dia: pd.DataFrame = field(  # venda prevista da rede, dia a dia, depois da posição
        default_factory=lambda: pd.DataFrame(columns=["dia", "projecao"])
    )


def _valor(v):
    """NaN/NaT/None viram célula vazia; datas do pandas viram date."""
    if v is None or (not isinstance(v, str | date) and pd.isna(v)):
        return None
    return v.date() if isinstance(v, pd.Timestamp) else v


def _escrever_tabela(
    ws, quadro: pd.DataFrame, colunas: dict, linha_cabecalho: int, coluna: int = 1
):
    """Cabeçalho + linhas com formato por coluna; devolve a última linha escrita."""
    estilo = {
        "font": Font(bold=True, color="FFFFFF"),
        "fill": PatternFill("solid", fgColor=COR_CABECALHO),
        "alignment": Alignment(horizontal="center", vertical="center", wrap_text=True),
    }
    for j, (titulo, _) in enumerate(colunas.values()):
        celula = ws.cell(linha_cabecalho, coluna + j, titulo)
        celula.font, celula.fill, celula.alignment = (
            estilo["font"], estilo["fill"], estilo["alignment"],
        )  # fmt: skip
    ws.row_dimensions[linha_cabecalho].height = ALTURA_CABECALHO
    for i, linha in enumerate(quadro.itertuples(index=False), start=1):
        valores = dict(zip(quadro.columns, linha, strict=True))
        for j, (nome, (_, formato)) in enumerate(colunas.items()):
            celula = ws.cell(linha_cabecalho + i, coluna + j, _valor(valores[nome]))
            if formato:
                celula.number_format = formato
    for j, (nome, (titulo, formato)) in enumerate(colunas.items()):
        dimensao = ws.column_dimensions[get_column_letter(coluna + j)]
        nova = largura_da_coluna(titulo, formato, quadro[nome])
        dimensao.width = max(dimensao.width or 0, nova)  # nunca estreita o que outra tabela pediu
    return linha_cabecalho + len(quadro)


def largura_da_coluna(titulo: str, formato: str | None, valores) -> float:
    """Única regra de largura das colunas, por tipo: números e datas têm largura fixa por formato
    (cabem o maior valor); texto acompanha o maior conteúdo, entre um mínimo e um máximo."""
    if formato in LARGURA_POR_FORMATO:
        return LARGURA_POR_FORMATO[formato]
    maior = max([len(titulo) / 1.6] + [len(str(_valor(v) or "")) for v in valores][:200])
    return min(max(LARGURA_TEXTO_MINIMA, maior + 2), LARGURA_TEXTO_MAXIMA)


def _acabamento_do_grafico(
    grafico, formato_x: str, formato_y: str = "#,##0", titulo_y: str = "R$"
) -> None:
    """Eixos visíveis (o openpyxl os grava como removidos), sem suavização, legenda embaixo e
    espaço entre o título e a área do gráfico."""
    for eixo in (grafico.x_axis, grafico.y_axis):
        eixo.delete = False
    grafico.x_axis.number_format = formato_x
    grafico.y_axis.number_format = formato_y
    grafico.y_axis.title = titulo_y
    for serie in grafico.series:
        serie.smooth = False
    if grafico.title is None:  # série acrescentada a outro gráfico: só eixos e linhas
        return
    grafico.title.overlay = False
    grafico.legend.position = "b"
    grafico.layout = Layout(
        manualLayout=ManualLayout(
            layoutTarget="inner", xMode="edge", yMode="edge", x=0.1, y=0.17, w=0.86, h=0.55
        )
    )


def _fixar_e_filtrar(ws, ultima_linha: int, ultima_coluna: int) -> None:
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(ultima_coluna)}{max(ultima_linha, 2)}"


def _verde_vermelho(ws, intervalo: str, limite: float = 1.0) -> None:
    """Verde a partir do limite (inclusive), vermelho abaixo dele."""
    verde = PatternFill("solid", bgColor=COR_VERDE, fgColor=COR_VERDE)
    vermelho = PatternFill("solid", bgColor=COR_VERMELHO, fgColor=COR_VERMELHO)
    ws.conditional_formatting.add(
        intervalo,
        CellIsRule(operator="greaterThanOrEqual", formula=[str(limite)], fill=verde,
                   font=Font(color=COR_TEXTO_VERDE)),
    )  # fmt: skip
    ws.conditional_formatting.add(
        intervalo,
        CellIsRule(operator="lessThan", formula=[str(limite)], fill=vermelho,
                   font=Font(color=COR_TEXTO_VERMELHO)),
    )  # fmt: skip


def _coluna_de(colunas: dict, nome: str) -> str:
    return get_column_letter(list(colunas).index(nome) + 1)


def _aba_lojas(wb: Workbook, dados: DadosFechamento) -> None:
    ws = wb.create_sheet(ABA_LOJAS)
    ultima = _escrever_tabela(ws, dados.lojas, COLUNAS_LOJAS, 1)
    _fixar_e_filtrar(ws, ultima, len(COLUNAS_LOJAS))
    for nome in ("cobertura_dia", "cobertura_ate_o_dia", "cobertura_projetada"):
        letra = _coluna_de(COLUNAS_LOJAS, nome)
        _verde_vermelho(ws, f"{letra}2:{letra}{max(ultima, 2)}")
    letra = _coluna_de(COLUNAS_LOJAS, "evolucao_ano_anterior")
    _verde_vermelho(ws, f"{letra}2:{letra}{max(ultima, 2)}", 0.0)


def _aba_vendedores(wb: Workbook, dados: DadosFechamento) -> None:
    ws = wb.create_sheet(ABA_VENDEDORES)
    ultima = _escrever_tabela(ws, dados.vendedores, COLUNAS_VENDEDORES, 1)
    _fixar_e_filtrar(ws, ultima, len(COLUNAS_VENDEDORES))
    letra = _coluna_de(COLUNAS_VENDEDORES, "cobertura_ate_o_dia")
    _verde_vermelho(ws, f"{letra}2:{letra}{max(ultima, 2)}")


def _aba_alertas(wb: Workbook, dados: DadosFechamento) -> None:
    ws = wb.create_sheet(ABA_ALERTAS)
    ultima = _escrever_tabela(ws, dados.alertas, COLUNAS_ALERTAS, 1)
    _fixar_e_filtrar(ws, ultima, len(COLUNAS_ALERTAS))
    ws.column_dimensions[_coluna_de(COLUNAS_ALERTAS, "explicacao")].width = 90
    cores = {"Crítica": "FF9999", "Alta": "FFC7CE", "Média": "FFEB9C", "Baixa": "E2EFDA"}
    coluna = _coluna_de(COLUNAS_ALERTAS, "severidade")
    for severidade, cor in cores.items():
        ws.conditional_formatting.add(
            f"{coluna}2:{coluna}{max(ultima, 2)}",
            CellIsRule(operator="equal", formula=[f'"{severidade}"'],
                       fill=PatternFill("solid", bgColor=cor, fgColor=cor)),
        )  # fmt: skip


def _aba_previsao(wb: Workbook, dados: DadosFechamento) -> None:
    ws = wb.create_sheet(ABA_PREVISAO)
    ultima = _escrever_tabela(ws, dados.previsao_mensal, COLUNAS_PREVISAO, 1)
    _fixar_e_filtrar(ws, ultima, len(COLUNAS_PREVISAO))


def _aba_previsao_diaria(wb: Workbook, dados: DadosFechamento) -> None:
    """Previsão diária da rede com a faixa baixa e alta calibrada no total da rede, e o gráfico."""
    ws = wb.create_sheet(ABA_PREVISAO_DIARIA)
    diaria = dados.previsao_diaria
    ultima = _escrever_tabela(ws, diaria, COLUNAS_PREVISAO_DIARIA, 1)
    _fixar_e_filtrar(ws, ultima, len(COLUNAS_PREVISAO_DIARIA))
    if diaria.empty:
        return
    grafico = LineChart()
    grafico.title = "Previsão diária da rede, com a faixa baixa e alta"
    grafico.height, grafico.width = 9, 24
    grafico.add_data(
        Reference(ws, min_col=2, max_col=4, min_row=1, max_row=ultima), titles_from_data=True
    )
    grafico.set_categories(Reference(ws, min_col=1, min_row=2, max_row=ultima))
    _acabamento_do_grafico(grafico, "dd/mm")
    for serie in grafico.series[1:]:  # a faixa fica tracejada e cinza, o previsto em destaque
        serie.graphicalProperties.line.solidFill = COR_PROJECAO
        serie.graphicalProperties.line.dashStyle = "dash"
    ws.add_chart(grafico, f"{get_column_letter(len(COLUNAS_PREVISAO_DIARIA) + 2)}2")


def _aba_produtos(wb: Workbook, dados: DadosFechamento) -> None:
    """Top produtos da rede com curva ABC, receita por setor e o gráfico da participação."""
    ws = wb.create_sheet(ABA_PRODUTOS)
    n = config.RELATORIO_TOP_PRODUTOS
    colunas = len(COLUNAS_PRODUTOS)
    _titulo_de_tabela(
        ws, 1, 1, colunas, f"Top {n} produtos da rede no mês (até {dados.dia:%d/%m/%Y})"
    )
    ultima = _escrever_tabela(ws, dados.produtos, COLUNAS_PRODUTOS, 2)
    ws.auto_filter.ref = f"A2:{get_column_letter(colunas)}{max(ultima, 3)}"
    topo = max(ultima, 2) + 2  # uma linha em branco entre os blocos
    _titulo_de_tabela(ws, topo, 1, len(COLUNAS_SETORES), "Receita por setor no mês")
    setores = dados.setores
    fim = _escrever_tabela(ws, setores, COLUNAS_SETORES, topo + 1)
    if setores.empty:
        return
    letra = _coluna_de(COLUNAS_SETORES, "evolucao")
    _verde_vermelho(ws, f"{letra}{topo + 2}:{letra}{fim}", 0.0)
    grafico = BarChart()
    grafico.title = "Participação por setor na receita do mês"
    grafico.height, grafico.width = 9, 18
    coluna = list(COLUNAS_SETORES).index("participacao") + 1
    grafico.add_data(
        Reference(ws, min_col=coluna, min_row=topo + 1, max_row=fim), titles_from_data=True
    )
    grafico.set_categories(Reference(ws, min_col=1, min_row=topo + 2, max_row=fim))
    _acabamento_do_grafico(grafico, "General", "0%", "% da receita")
    grafico.legend = None  # uma série só
    grafico.y_axis.scaling.min = 0
    rotulos = DataLabelList(numFmt="0.0%")
    rotulos.showVal = True
    rotulos.showSerName = rotulos.showCatName = rotulos.showLegendKey = False
    rotulos.showPercent = False
    grafico.dataLabels = rotulos
    ws.add_chart(grafico, f"{get_column_letter(len(COLUNAS_SETORES) + 2)}{topo}")


def _aba_dados_por_loja(wb: Workbook, dados: DadosFechamento) -> None:
    """Aba oculta de apoio da macro GerarAbaDaLoja: três blocos com os dados de cada loja. Linha 1 =
    título do bloco (a macro o copia para a aba da loja), linha 2 = cabeçalho, dados abaixo."""
    ws = wb.create_sheet(ABA_DADOS_POR_LOJA)
    janela = f"{config.RELATORIO_DIAS_QUANDO_A_LOJA_VENDE} dias até {dados.dia:%d/%m/%Y}"
    top = config.RELATORIO_TOP_PRODUTOS_LOJA
    blocos = [
        (COLUNA_DADOS_PRODUTOS, dados.produtos_por_loja, COLUNAS_DADOS_PRODUTOS_LOJA,
         f"Top {top} produtos da loja no mês (até {dados.dia:%d/%m/%Y})"),
        (COLUNA_DADOS_DIA_DA_SEMANA, dados.dia_da_semana_por_loja, COLUNAS_DADOS_DIA_DA_SEMANA,
         f"Quando a loja vende: receita média por dia da semana ({janela})"),
        (COLUNA_DADOS_FAIXA, dados.faixa_por_loja, COLUNAS_DADOS_FAIXA,
         f"Quando a loja vende: receita média por dia, por faixa horária ({janela})"),
    ]  # fmt: skip
    for coluna, quadro, colunas, titulo in blocos:
        ws.cell(1, coluna, titulo)
        _escrever_tabela(ws, quadro, colunas, 2, coluna)
    ws.sheet_state = "hidden"


def _brl(valor: float) -> str:
    """R$ no padrão brasileiro, para os textos de contexto dos cartões."""
    texto = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {texto}"


def _pct(valor: float, sinal: bool = False) -> str:
    return f"{valor * 100:{'+' if sinal else ''}.1f}".replace(".", ",") + "%"


def _fonte(tamanho: float = 10, negrito: bool = False, cor: str = COR_TEXTO, italico: bool = False):
    return Font(name=FONTE, size=tamanho, bold=negrito, color=cor, italic=italico)


def _mesclar(ws, linha: int, coluna: int, ate_coluna: int, ate_linha: int | None = None):
    """Mescla o bloco e devolve a célula de cima à esquerda (a que guarda o valor)."""
    ate_linha = ate_linha or linha
    if (ate_linha, ate_coluna) != (linha, coluna):
        ws.merge_cells(
            start_row=linha, start_column=coluna, end_row=ate_linha, end_column=ate_coluna
        )
    return ws.cell(linha, coluna)


def _borda_do_bloco(ws, l1: int, c1: int, l2: int, c2: int, fundo: str | None = None) -> None:
    """Contorno fino em volta do bloco (e fundo opcional em todas as células dele)."""
    lado = Side(style="thin", color=COR_BORDA)
    for linha in range(l1, l2 + 1):
        for coluna in range(c1, c2 + 1):
            celula = ws.cell(linha, coluna)
            celula.border = Border(
                left=lado if coluna == c1 else None, right=lado if coluna == c2 else None,
                top=lado if linha == l1 else None, bottom=lado if linha == l2 else None,
            )  # fmt: skip
            if fundo:
                celula.fill = PatternFill("solid", fgColor=fundo)


def _cor_do_status(valor: float | None, limite: float) -> str:
    if valor is None or pd.isna(valor):
        return COR_TEXTO
    return COR_STATUS_VERDE if valor >= limite else COR_STATUS_VERMELHO


def _cartao(ws, linha: int, coluna: int, rotulo: str, valor, formato: str, cor: str, contexto: str):
    """Cartão de 3 colunas: rótulo pequeno, número grande (2 linhas) e uma linha de contexto.
    O número fica na linha logo abaixo do rótulo; o contexto, 3 linhas abaixo."""
    ate = coluna + COLUNAS_POR_CARTAO - 1
    topo = _mesclar(ws, linha, coluna, ate)
    topo.value, topo.font = rotulo, _fonte(9, cor=COR_CINZA)
    topo.alignment = Alignment(horizontal="center", vertical="center")
    numero = _mesclar(ws, linha + 1, coluna, ate, linha + 2)
    numero.value = None if valor is None or pd.isna(valor) else valor
    numero.number_format = formato
    numero.font = _fonte(22, negrito=True, cor=cor)
    numero.alignment = Alignment(horizontal="center", vertical="center")
    base = _mesclar(ws, linha + 3, coluna, ate)
    base.value, base.font = contexto, _fonte(9, cor=COR_CINZA)
    base.alignment = Alignment(horizontal="center", vertical="center")
    _borda_do_bloco(ws, linha, coluna, linha + 3, ate, COR_FUNDO_CARTAO)


def _indicador_pequeno(ws, linha: int, coluna: int, rotulo: str, valor, formato: str) -> None:
    """Rótulo pequeno em cima e valor logo abaixo, em 2 colunas."""
    ate = coluna + COLUNAS_POR_INDICADOR - 1
    r = _mesclar(ws, linha, coluna, ate)
    r.value, r.font = rotulo, _fonte(8, cor=COR_CINZA)
    r.alignment = Alignment(horizontal="center")
    v = _mesclar(ws, linha + 1, coluna, ate)
    v.value = None if valor is None or pd.isna(valor) else valor
    v.number_format, v.font = formato, _fonte(11, negrito=True)
    v.alignment = Alignment(horizontal="center")


def _titulo_de_tabela(ws, linha: int, coluna: int, ate_coluna: int, texto: str) -> None:
    c = _mesclar(ws, linha, coluna, ate_coluna)
    c.value, c.font = texto, _fonte(11, negrito=True, cor=COR_CABECALHO)
    c.alignment = Alignment(vertical="center")
    for k in range(coluna, ate_coluna + 1):
        ws.cell(linha, k).border = Border(bottom=Side(style="medium", color=COR_CABECALHO))


def _cabecalho_compacto(ws, linha: int, blocos: list[tuple[int, int, str]]) -> None:
    for coluna, ate, texto in blocos:
        c = _mesclar(ws, linha, coluna, ate)
        c.value, c.font = texto, _fonte(9, negrito=True, cor="FFFFFF")
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        for k in range(coluna, ate + 1):
            ws.cell(linha, k).fill = PatternFill("solid", fgColor=COR_CABECALHO)
    ws.row_dimensions[linha].height = 26


def _celula_de_tabela(ws, linha, coluna, ate, valor, formato=None, negrito=False, alinha=None):
    c = _mesclar(ws, linha, coluna, ate)
    c.value = None if valor is None or pd.isna(valor) else valor
    c.font = _fonte(9, negrito=negrito)
    if formato:
        c.number_format = formato
    if alinha:
        c.alignment = Alignment(horizontal=alinha)
    for k in range(coluna, ate + 1):
        ws.cell(linha, k).border = Border(bottom=Side(style="hair", color=COR_BORDA))
    return c


def lojas_extremas(lojas: pd.DataFrame, quantas: int = LOJAS_POR_PONTA) -> tuple:
    """(maiores, menores): as lojas de maior e de menor cobertura da meta até o dia. Lojas sem meta
    acumulada ficam de fora; com poucas lojas as duas pontas não se repetem."""
    com_meta = lojas.dropna(subset=["cobertura_ate_o_dia"]).sort_values(
        ["cobertura_ate_o_dia", "cod_loja"], ascending=[False, True]
    )
    maiores = com_meta.head(quantas)
    menores = com_meta.iloc[len(maiores) :].tail(quantas).iloc[::-1]
    return maiores, menores


def alertas_por_severidade(alertas: pd.DataFrame, mes: date | None = None) -> pd.DataFrame:
    """Quantidade e valor envolvido dos alertas abertos, por severidade (do mais grave ao menos):
    o total em aberto e, à parte, os do mês de `mes` (data de alerta a partir do primeiro dia dele;
    os alertas já vêm limitados à data de posição)."""
    datas = alertas["data"].map(lambda d: d.date() if isinstance(d, pd.Timestamp) else d)
    no_mes = datas >= mes if mes is not None else pd.Series(False, index=alertas.index)
    linhas = []
    for severidade in ORDEM_SEVERIDADE:
        sel = alertas[alertas["severidade"] == severidade]
        do_mes = sel[no_mes[sel.index]]
        linhas.append(
            (
                severidade, len(sel), float(sel["valor_envolvido"].fillna(0).sum()),
                len(do_mes), float(do_mes["valor_envolvido"].fillna(0).sum()),
            )
        )  # fmt: skip
    return pd.DataFrame(
        linhas,
        columns=["severidade", "quantidade", "valor", "quantidade_no_mes", "valor_no_mes"],
    )


def _aba_diario(ws, dados: DadosFechamento) -> int:
    """Dia a dia do mês: venda, meta do dia, cobertura e acumulados. Devolve a última linha."""
    dia = dados.vendas_por_dia.copy()
    dia[["venda", "meta_dia"]] = dia[["venda", "meta_dia"]].apply(pd.to_numeric)
    dia["cobertura_dia"] = dia["venda"] / dia["meta_dia"].where(dia["meta_dia"] > 0)
    dia["venda_acumulada"] = dia["venda"].cumsum(skipna=True).where(dia["venda"].notna())
    dia["meta_acumulada"] = dia["meta_dia"].cumsum()
    previsto = dict(
        zip(dados.projecao_por_dia["dia"], dados.projecao_por_dia["projecao"], strict=True)
    )
    dia["projecao"] = pd.to_numeric(dia["dia"].map(previsto)).where(dia["dia"] > dados.dia)
    ultima = _escrever_tabela(ws, dia, COLUNAS_DIARIO, 1)
    _fixar_e_filtrar(ws, ultima, len(COLUNAS_DIARIO))
    letra = _coluna_de(COLUNAS_DIARIO, "cobertura_dia")
    _verde_vermelho(ws, f"{letra}2:{letra}{max(ultima, 2)}")
    return ultima


def _aba_resumo(ws, dados: DadosFechamento, ws_diario, ultima_linha_diario: int) -> None:
    """Uma página A4 paisagem: título, 4 cartões, linha secundária, gráfico e duas tabelas."""
    ws.sheet_view.showGridLines = False
    for coluna in range(1, COLUNAS_DO_RESUMO + 1):
        ws.column_dimensions[get_column_letter(coluna)].width = LARGURA_COLUNA_RESUMO
    lojas, ind = dados.lojas, dados.indicadores
    soma = lambda coluna: float(lojas[coluna].fillna(0).sum())  # noqa: E731
    razao = lambda a, b: a / b if b else None  # noqa: E731
    venda_dia, meta_dia = soma("venda_dia"), soma("meta_dia")
    acumulado, meta_mes = soma("acumulado_mes"), soma("meta_mes")
    meta_acumulada, anterior = soma("meta_acumulada"), soma("acumulado_ano_anterior")
    cobertura_ate_o_dia = razao(acumulado, meta_acumulada)
    evolucao = acumulado / anterior - 1 if anterior else None
    projecao = lojas["projecao_fechamento"].sum(min_count=1)
    projecao = None if pd.isna(projecao) else float(projecao)
    cobertura_projetada = None if projecao is None else razao(projecao, meta_mes)

    # a) faixa de título
    for linha, altura, preenchimento in ((1, 34, COR_CABECALHO), (2, 20, COR_FAIXA_SUBTITULO)):
        _mesclar(ws, linha, 1, COLUNAS_DO_RESUMO)
        ws.row_dimensions[linha].height = altura
        for coluna in range(1, COLUNAS_DO_RESUMO + 1):
            ws.cell(linha, coluna).fill = PatternFill("solid", fgColor=preenchimento)
    titulo = ws["A1"]
    mes = config.NOMES_MESES[dados.mes.month - 1].lower()
    titulo.value = f"Lojas Ipê — Fechamento de {mes}/{dados.mes.year}"
    titulo.font = _fonte(16, negrito=True, cor="FFFFFF")
    titulo.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    subtitulo = ws["A2"]
    subtitulo.value = (
        f"Posição em {dados.dia:%d/%m/%Y} · valores em R$ (receita líquida de vendas concluídas)"
    )
    subtitulo.font = _fonte(10, cor=COR_CABECALHO)
    subtitulo.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[3].height = 8

    # b) cartões de destaque (rótulo na linha 4, número nas 5-6, contexto na 7)
    cartoes = [
        (TITULO_VENDA_ACUMULADA, acumulado, FORMATO_REAL, COR_CABECALHO,
         f"Meta acumulada até o dia: {_brl(meta_acumulada)}"),
        (TITULO_COBERTURA_ATE_O_DIA, cobertura_ate_o_dia, FORMATO_PERCENTUAL,
         _cor_do_status(cobertura_ate_o_dia, 1.0),
         f"{_pct(razao(acumulado, meta_mes) or 0)} da meta do mês atingido"),
        (TITULO_PROJECAO, projecao, FORMATO_REAL, _cor_do_status(cobertura_projetada, 1.0),
         "Sem previsão para o mês" if cobertura_projetada is None
         else f"Cobertura projetada da meta do mês: {_pct(cobertura_projetada)}"),
        (TITULO_EVOLUCAO, evolucao, FORMATO_EVOLUCAO, _cor_do_status(evolucao, 0.0),
         f"Mesmo período do ano anterior: {_brl(anterior)}"),
    ]  # fmt: skip
    for k, (rotulo, valor, formato, cor, contexto) in enumerate(cartoes):
        _cartao(ws, 4, 1 + k * COLUNAS_POR_CARTAO, rotulo, valor, formato, cor, contexto)
    ws.row_dimensions[4].height = 18
    ws.row_dimensions[5].height = ws.row_dimensions[6].height = 20
    ws.row_dimensions[7].height = 18
    ws.row_dimensions[8].height = 8

    # c) linha secundária
    pequenos = [
        ("Venda do dia", venda_dia, FORMATO_REAL),
        ("Cobertura do dia", razao(venda_dia, meta_dia), FORMATO_PERCENTUAL),
        ("Margem do mês", ind["margem"], FORMATO_REAL),
        ("Margem sobre a receita", ind["margem_percentual"], FORMATO_PERCENTUAL),
        ("Cupons do mês", ind["cupons"], FORMATO_INTEIRO),
        ("Ticket médio", ind["ticket_medio"], FORMATO_REAL),
    ]  # fmt: skip
    for k, (rotulo, valor, formato) in enumerate(pequenos):
        _indicador_pequeno(ws, 9, 1 + k * COLUNAS_POR_INDICADOR, rotulo, valor, formato)
    ws.row_dimensions[11].height = 8

    # d) gráfico em largura total (os dados estão na aba Diário)
    barras = BarChart()
    barras.title = "Venda por dia x meta do dia"
    barras.height, barras.width = ALTURA_GRAFICO_CM, LARGURA_GRAFICO_CM
    for coluna in (2, list(COLUNAS_DIARIO).index("projecao") + 1):  # venda e projeção
        barras.add_data(
            Reference(ws_diario, min_col=coluna, min_row=1, max_row=ultima_linha_diario),
            titles_from_data=True,
        )
    projecao_barras = barras.series[1].graphicalProperties
    projecao_barras.solidFill = projecao_barras.line.solidFill = COR_PROJECAO
    barras.overlap = 100  # venda e projeção nunca coincidem no mesmo dia: dividem o espaço
    barras.set_categories(Reference(ws_diario, min_col=1, min_row=2, max_row=ultima_linha_diario))
    linha = LineChart()
    linha.add_data(
        Reference(ws_diario, min_col=3, min_row=1, max_row=ultima_linha_diario),
        titles_from_data=True,
    )
    _acabamento_do_grafico(barras, "dd/mm")
    _acabamento_do_grafico(linha, "dd/mm")
    barras += linha
    ws.add_chart(barras, f"A{LINHA_DO_GRAFICO}")

    # e) tabelas lado a lado
    topo = LINHA_DO_GRAFICO + LINHAS_DO_GRAFICO + 1
    _titulo_de_tabela(ws, topo, 1, 6, "Lojas — maior e menor cobertura da meta até o dia")
    _cabecalho_compacto(
        ws, topo + 1,
        [(1, 1, "Loja"), (2, 3, "Nome"), (4, 4, "Acumulado do mês"),
         (5, 5, "Meta acumulada até o dia"), (6, 6, "Cobertura")],
    )  # fmt: skip
    maiores, menores = lojas_extremas(lojas)
    linha_atual = topo + 2
    cobertura_celulas = []
    for rotulo, grupo in (("Maiores coberturas", maiores), ("Menores coberturas", menores)):
        if grupo.empty:
            continue
        sub = _mesclar(ws, linha_atual, 1, 6)
        sub.value, sub.font = rotulo, _fonte(8, cor=COR_CINZA, italico=True)
        linha_atual += 1
        for loja in grupo.itertuples():
            _celula_de_tabela(ws, linha_atual, 1, 1, loja.cod_loja)
            _celula_de_tabela(ws, linha_atual, 2, 3, loja.nome_loja)
            _celula_de_tabela(ws, linha_atual, 4, 4, loja.acumulado_mes, FORMATO_REAL)
            _celula_de_tabela(ws, linha_atual, 5, 5, loja.meta_acumulada, FORMATO_REAL)
            c = _celula_de_tabela(
                ws, linha_atual, 6, 6, loja.cobertura_ate_o_dia, FORMATO_PERCENTUAL, True, "center"
            )
            cobertura_celulas.append(c.coordinate)
            linha_atual += 1
    for coordenada in cobertura_celulas:
        _verde_vermelho(ws, coordenada)
    fim_esquerda = linha_atual

    _titulo_de_tabela(ws, topo, 8, 12, "Alertas abertos por severidade")
    _cabecalho_compacto(
        ws, topo + 1, [(8, 8, "Severidade"), (9, 10, "No mês"), (11, 12, "Total em aberto")]
    )
    _cabecalho_compacto(
        ws, topo + 2,
        [(8, 8, ""), (9, 9, "Quantidade"), (10, 10, "Valor"), (11, 11, "Quantidade"),
         (12, 12, "Valor")],
    )  # fmt: skip
    _mesclar(ws, topo + 1, 8, 8, topo + 2)  # "Severidade" ocupa as duas linhas do cabeçalho
    ws.row_dimensions[topo + 2].height = 16
    por_severidade = alertas_por_severidade(dados.alertas, dados.mes)
    linha_atual = topo + 3
    colunas_alerta = ("quantidade_no_mes", "valor_no_mes", "quantidade", "valor")
    for item in por_severidade.itertuples():
        _celula_de_tabela(ws, linha_atual, 8, 8, item.severidade)
        for k, nome in enumerate(colunas_alerta):
            eh_qtd = nome.startswith("quantidade")
            _celula_de_tabela(
                ws, linha_atual, 9 + k, 9 + k, getattr(item, nome),
                FORMATO_INTEIRO if eh_qtd else FORMATO_REAL, False, "center" if eh_qtd else None,
            )  # fmt: skip
        linha_atual += 1
    _celula_de_tabela(ws, linha_atual, 8, 8, "Total", None, True)
    for k, nome in enumerate(colunas_alerta):
        eh_qtd = nome.startswith("quantidade")
        soma = por_severidade[nome].sum()
        _celula_de_tabela(
            ws, linha_atual, 9 + k, 9 + k, int(soma) if eh_qtd else float(soma),
            FORMATO_INTEIRO if eh_qtd else FORMATO_REAL, True, "center" if eh_qtd else None,
        )  # fmt: skip
    linha_atual += 2  # uma linha em branco antes do próximo bloco

    n = config.RELATORIO_TOP_PRODUTOS_RESUMO
    _titulo_de_tabela(ws, linha_atual, 8, 12, f"Top {n} produtos do mês")
    _cabecalho_compacto(
        ws, linha_atual + 1,
        [(8, 9, "Produto"), (10, 10, "Setor"), (11, 11, "Receita"), (12, 12, "Participação")],
    )  # fmt: skip
    linha_atual += 2
    for produto in dados.produtos.head(n).itertuples():
        c = _celula_de_tabela(ws, linha_atual, 8, 9, produto.descricao)
        c.alignment = Alignment(shrink_to_fit=True)
        c = _celula_de_tabela(ws, linha_atual, 10, 10, produto.setor)
        c.alignment = Alignment(shrink_to_fit=True)
        _celula_de_tabela(ws, linha_atual, 11, 11, produto.receita, FORMATO_REAL)
        _celula_de_tabela(
            ws, linha_atual, 12, 12, produto.participacao, FORMATO_PERCENTUAL, False, "center"
        )
        linha_atual += 1
    fim_direita = linha_atual + 1

    # f) rodapé (a data de posição é lida pela macro do PDF, pelo nome definido)
    rodape = max(fim_esquerda, fim_direita) + 1
    texto = _mesclar(ws, rodape, 1, COLUNAS_DO_RESUMO - 2)
    texto.value = f"{FONTE_RODAPE} · gerado em {dados.gerado_em:%d/%m/%Y %H:%M}"
    texto.font = _fonte(8, cor=COR_CINZA)
    rotulo = ws.cell(rodape, COLUNAS_DO_RESUMO - 1, "Data de posição")
    rotulo.font, rotulo.alignment = _fonte(8, cor=COR_CINZA), Alignment(horizontal="right")
    data = ws.cell(rodape, COLUNAS_DO_RESUMO, dados.dia)
    data.font, data.number_format = _fonte(8, cor=COR_CINZA), FORMATO_DATA
    data.alignment = Alignment(horizontal="left")
    ws.parent.defined_names[NOME_DATA_POSICAO] = DefinedName(
        NOME_DATA_POSICAO,
        attr_text=f"'{ws.title}'!${get_column_letter(COLUNAS_DO_RESUMO)}${rodape}",
    )

    # impressão: 1 página A4 paisagem, margens estreitas, centralizada
    ws.print_area = f"A1:{get_column_letter(COLUNAS_DO_RESUMO)}{rodape}"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = ws.page_setup.fitToHeight = 1
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.page_margins = PageMargins(left=0.3, right=0.3, top=0.3, bottom=0.3, header=0.1, footer=0.1)
    ws.print_options.horizontalCentered = True


def montar_pasta(dados: DadosFechamento, modelo: Workbook | None = None) -> Workbook:
    """Cria as nove abas (a última, de apoio às macros, fica oculta). Com `modelo` (ex.: o .xlsm
    com as macros), as abas antigas dele saem."""
    wb = modelo or Workbook()
    temporaria = wb.create_sheet("_temporaria", 0)
    for aba in [a for a in wb.worksheets if a is not temporaria]:
        wb.remove(aba)
    resumo, diario = wb.create_sheet(ABA_RESUMO), wb.create_sheet(ABA_DIARIO)
    ultima_linha_diario = _aba_diario(diario, dados)
    _aba_resumo(resumo, dados, diario, ultima_linha_diario)
    _aba_lojas(wb, dados)
    _aba_vendedores(wb, dados)
    _aba_produtos(wb, dados)
    _aba_alertas(wb, dados)
    _aba_previsao(wb, dados)
    _aba_previsao_diaria(wb, dados)
    _aba_dados_por_loja(wb, dados)
    wb.remove(temporaria)
    wb.active = 0
    return wb
