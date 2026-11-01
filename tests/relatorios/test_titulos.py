"""Varredura dos títulos de seção, linhas de grupo e títulos de gráfico de todas as abas: um único
estilo (planilha.titulo_de_secao, linha_de_grupo e titulo_do_grafico)."""

import pandas as pd
import pytest

from src.relatorios import planilha
from src.relatorios.planilha import montar_pasta
from tests.relatorios.test_planilha import _dados, achar

TITULOS_DE_SECAO = {
    planilha.ABA_RESUMO: (
        "Lojas — maior e menor cobertura da meta até o dia",
        "Alertas abertos por severidade",
        "Top 5 produtos do mês",
    ),
    planilha.ABA_PRODUTOS: (
        "Top 20 produtos da rede no mês (até 15/03/2025)",
        "Receita por setor no mês",
    ),
}
LINHAS_DE_GRUPO = {planilha.ABA_RESUMO: ("Maiores coberturas", "Menores coberturas")}
TITULOS_DE_GRAFICO = {
    planilha.ABA_RESUMO: "Venda por dia x meta do dia",
    planilha.ABA_PRODUTOS: "Participação por setor na receita do mês",
    planilha.ABA_PREVISAO_DIARIA: "Previsão diária da rede, com a faixa baixa e alta",
}
# abas de uma tabela só (cabeçalho congelado na linha 1): não têm título de seção
ABAS_SEM_TITULO = (
    planilha.ABA_DIARIO, planilha.ABA_LOJAS, planilha.ABA_VENDEDORES, planilha.ABA_ALERTAS,
    planilha.ABA_PREVISAO, planilha.ABA_PREVISAO_DIARIA,
)  # fmt: skip


@pytest.fixture(scope="module")
def pasta():
    """A pasta em memória: o openpyxl não relê o estilo das células internas de uma mesclagem."""
    dados = _dados()
    base = dados.lojas.iloc[[0]]  # 12 lojas: as duas pontas do Resumo (5 + 5) aparecem
    dados.lojas = pd.concat(
        [base.assign(cod_loja=f"L{i:02d}", cobertura_ate_o_dia=i / 10) for i in range(12)],
        ignore_index=True,
    )
    return montar_pasta(dados)


def _cor(celula_cor) -> str:
    return celula_cor.rgb[-6:]


def _intervalo_mesclado(ws, celula):
    return next(r for r in ws.merged_cells.ranges if celula.coordinate in r)


def _ultima_coluna_do_cabecalho(ws, linha: int, coluna: int) -> int:
    ultima = coluna
    while _cor(ws.cell(linha + 1, ultima + 1).fill.fgColor) == planilha.COR_CABECALHO:
        ultima += 1
    return ultima


@pytest.mark.parametrize("aba,texto", [(a, t) for a, ts in TITULOS_DE_SECAO.items() for t in ts])
def test_titulo_de_secao_tem_o_estilo_unico_e_cola_na_tabela(pasta, aba, texto):
    ws = pasta[aba]
    linha, coluna = achar(ws, texto)
    celula = ws.cell(linha, coluna)
    assert celula.font.sz == planilha.TAMANHO_TITULO_SECAO == 13
    assert celula.font.b and _cor(celula.font.color) == planilha.COR_CABECALHO
    faixa = _intervalo_mesclado(ws, celula)
    ultima = _ultima_coluna_do_cabecalho(ws, linha, coluna)  # cabeçalho na linha de baixo, sem vão
    assert (faixa.min_col, faixa.max_col) == (coluna, ultima)  # mesma largura da tabela
    for c in range(coluna, ultima + 1):
        borda = ws.cell(linha, c).border.bottom
        assert borda.style == "thick" and _cor(borda.color) == planilha.COR_CABECALHO
        if linha > 1:  # uma linha de espaço entre este bloco e o anterior
            assert ws.cell(linha - 1, c).value is None
    assert ws.row_dimensions[linha].height == planilha.ALTURA_TITULO_SECAO


@pytest.mark.parametrize("texto", LINHAS_DE_GRUPO[planilha.ABA_RESUMO])
def test_subtitulo_da_tabela_vira_linha_de_grupo_cinza_na_largura_da_tabela(pasta, texto):
    ws = pasta[planilha.ABA_RESUMO]
    linha, coluna = achar(ws, texto)
    celula = ws.cell(linha, coluna)
    assert celula.font.b and not celula.font.i
    faixa = _intervalo_mesclado(ws, celula)
    assert (faixa.min_col, faixa.max_col) == (1, 6)  # a largura da tabela de lojas
    assert all(
        _cor(ws.cell(linha, c).fill.fgColor) == planilha.COR_FUNDO_GRUPO for c in range(1, 7)
    )


@pytest.mark.parametrize("aba,texto", TITULOS_DE_GRAFICO.items())
def test_titulo_do_grafico_tem_o_tamanho_e_a_cor_dos_titulos_de_secao(pasta, aba, texto):
    grafico = pasta[aba]._charts[0]
    execucao = grafico.title.tx.rich.p[0].r[0]
    assert execucao.t == texto
    assert execucao.rPr.sz == planilha.TAMANHO_TITULO_SECAO * 100 and execucao.rPr.b
    assert _cor_do_desenho(execucao.rPr.solidFill) == planilha.COR_CABECALHO
    assert grafico.title.overlay is False


def _cor_do_desenho(preenchimento) -> str:
    cor = preenchimento.srgbClr
    return str(getattr(cor, "val", cor))[-6:]


def test_varredura_nenhum_titulo_ficou_no_estilo_antigo(pasta):
    assert not hasattr(planilha, "_titulo_de_tabela")
    encontrados = set()
    for ws in pasta.worksheets:
        for linha in ws.iter_rows():
            for celula in linha:
                if celula.font.i:
                    raise AssertionError(
                        f"texto em itálico (estilo antigo): {ws.title}!{celula.coordinate}"
                    )
                titulo_pequeno = (
                    celula.value
                    and celula.font.b
                    and celula.font.color is not None
                    and _cor(celula.font.color) == planilha.COR_CABECALHO
                    and celula.font.sz <= planilha.TAMANHO_TITULO_SECAO
                )
                if titulo_pequeno:  # só o estilo novo tem esta combinação
                    assert celula.font.sz == planilha.TAMANHO_TITULO_SECAO, celula.coordinate
                    assert any(celula.coordinate in r for r in ws.merged_cells.ranges)
                    encontrados.add((ws.title, celula.value))
    esperados = {(aba, t) for aba, ts in TITULOS_DE_SECAO.items() for t in ts}
    assert encontrados == esperados


@pytest.mark.parametrize("aba", ABAS_SEM_TITULO)
def test_abas_de_uma_tabela_so_comecam_pelo_cabecalho_na_linha_1(pasta, aba):
    ws = pasta[aba]
    assert ws.freeze_panes == "A2" and ws["A1"].fill.fgColor.rgb[-6:] == planilha.COR_CABECALHO
