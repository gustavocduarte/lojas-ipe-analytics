"""Estrutura e formatação do .xlsx de fechamento, com dados sintéticos (sem banco)."""

from datetime import date

import pandas as pd
import pytest
from openpyxl import load_workbook

from src.relatorios import planilha
from src.relatorios.planilha import DadosFechamento, montar_pasta


def _dados(com_previsao: bool = True, com_projecao: bool = True) -> DadosFechamento:
    lojas = pd.DataFrame(
        {
            "cod_loja": ["L01", "L02"], "nome_loja": ["Ipê 1", "Ipê 2"], "uf": ["SP", "RJ"],
            "venda_dia": [1500.0, 400.0], "meta_dia": [1000.0, 800.0],
            "cobertura_dia": [1.5, 0.5], "acumulado_mes": [12000.0, 6000.0],
            "meta_acumulada": [9000.0, 8000.0], "meta_mes": [20000.0, 16000.0],
            "cobertura_ate_o_dia": [4 / 3, 0.75],
            "cobertura_mes": [0.6, 0.375], "acumulado_ano_anterior": [10000.0, 7000.0],
            "evolucao_ano_anterior": [0.2, -0.142857],
            "projecao_fechamento": [24000.0, 13000.0] if com_projecao else [None, None],
            "cobertura_projetada": [1.2, 0.8125] if com_projecao else [None, None],
        }
    )  # fmt: skip
    dias = pd.date_range("2025-03-01", "2025-03-31")
    vendas = pd.DataFrame(
        {
            "dia": dias.date,
            "venda": [100.0 * i if i <= 15 else None for i in range(1, 32)],
            "meta_dia": [1000.0] * 31,
        }
    )
    vendedores = pd.DataFrame(
        {
            "posicao": [1, 2], "cod_vendedor": ["V1", "V2"], "nome_vendedor": ["Ana", "Bia"],
            "cod_loja": ["L01", "L02"], "nome_loja": ["Ipê 1", "Ipê 2"],
            "acumulado_mes": [12000.0, 6000.0], "meta_acumulada": [5000.0, 8000.0],
            "cobertura_ate_o_dia": [2.4, 0.75], "meta_mes": [10000.0, 9000.0],
            "cobertura_mes": [1.2, 0.6667],
            "setor_principal": ["Alimentos", "Eletro"],
            "percentual_setor_principal": [0.8, 0.55],
        }
    )  # fmt: skip
    alertas = pd.DataFrame(
        {
            "severidade": ["Crítica", "Baixa"], "tipo": ["Desconto acima do limite"] * 2,
            "data": [date(2025, 3, 5), date(2025, 3, 6)], "loja_ou_centro": ["Ipê 1", "Ipê 2"],
            "vendedor": ["Ana", None], "valor_envolvido": [350.5, 20.0],
            "status": ["Novo", "Em análise"], "explicacao": ["Desconto de 40%", "Desconto de 19%"],
        }
    )  # fmt: skip
    previsao = pd.DataFrame(
        {
            "mes": [date(2026, 1, 1), date(2026, 1, 1)], "cod_loja": ["L01", "L02"],
            "nome_loja": ["Ipê 1", "Ipê 2"], "previsto": [20000.0, 15000.0],
            "faixa_baixa": [17000.0, 12000.0], "faixa_alta": [23000.0, 18000.0],
            "wape_backtest_loja": [0.11, 0.14], "versao_modelo": ["x@1"] * 2,
            "treino_ate": [date(2025, 12, 31)] * 2,
        }
    )  # fmt: skip
    diaria = pd.DataFrame(
        {"dia": pd.date_range("2026-01-01", periods=31).date, "previsto": [1000.0] * 31}
    )
    produtos = pd.DataFrame(
        {
            "cod_produto": ["P1", "P2", "P3"], "descricao": ["Arroz", "Tv", "Sabão"],
            "setor": ["Alimentos", "Eletro", "Limpeza"], "quantidade": [100, 5, 40],
            "receita": [10000.0, 6000.0, 2000.0], "margem_percentual": [0.3, 0.2, 0.4],
            "participacao": [10000 / 18000, 6000 / 18000, 2000 / 18000],
            "participacao_acumulada": [10000 / 18000, 16000 / 18000, 1.0],
            "classe": ["B", "B", "C"],
        }
    )  # fmt: skip
    setores = pd.DataFrame(
        {
            "setor": ["Alimentos", "Eletro", "Limpeza"], "receita": [10000.0, 6000.0, 2000.0],
            "participacao": [10000 / 18000, 6000 / 18000, 2000 / 18000],
            "margem_percentual": [0.3, 0.2, 0.4], "evolucao": [0.1, -0.05, None],
        }
    )  # fmt: skip
    return DadosFechamento(
        mes=date(2025, 3, 1), dia=date(2025, 3, 15), lojas=lojas, produtos=produtos,
        setores=setores,
        indicadores={"receita": 18000.0, "margem": 7200.0, "margem_percentual": 0.4,
                     "cupons": 60, "ticket_medio": 300.0},
        vendas_por_dia=vendas, vendedores=vendedores, alertas=alertas,
        previsao_mensal=previsao if com_previsao else previsao.iloc[0:0],
        previsao_diaria=diaria if com_previsao else diaria.iloc[0:0],
    )  # fmt: skip


@pytest.fixture
def pasta(tmp_path):
    caminho = tmp_path / "f.xlsx"
    montar_pasta(_dados()).save(caminho)
    return load_workbook(caminho)


def indicadores_do_resumo(ws) -> dict:
    """{rótulo: valor}: no Resumo o valor fica logo abaixo do rótulo (cartões e linha pequena)."""
    saida = {}
    for linha in ws.iter_rows(min_row=4, max_row=10):
        for celula in linha:
            if isinstance(celula.value, str):
                saida[celula.value] = ws.cell(celula.row + 1, celula.column).value
    return saida


def contexto_do_cartao(ws, rotulo: str) -> str:
    """Linha de contexto do cartão: 3 linhas abaixo do rótulo."""
    celula = next(
        c for linha in ws.iter_rows(min_row=4, max_row=4) for c in linha if c.value == rotulo
    )
    return ws.cell(celula.row + 3, celula.column).value


def test_tem_as_sete_abas_na_ordem(pasta):
    assert pasta.sheetnames == [
        planilha.ABA_RESUMO, planilha.ABA_DIARIO, planilha.ABA_LOJAS, planilha.ABA_VENDEDORES,
        planilha.ABA_PRODUTOS, planilha.ABA_ALERTAS, planilha.ABA_PREVISAO,
    ]  # fmt: skip


def test_aba_produtos_traz_top_com_abc_setores_e_grafico_de_participacao(pasta):
    ws = pasta[planilha.ABA_PRODUTOS]
    assert "Top 20 produtos da rede" in ws["A1"].value and "15/03/2025" in ws["A1"].value
    titulos = [c.value for c in ws[2]]
    assert titulos == [t for t, _ in planilha.COLUNAS_PRODUTOS.values()]
    linha = dict(zip(titulos, [c.value for c in ws[3]], strict=True))
    assert linha["Código"] == "P1" and linha["Classe ABC"] == "B"
    assert linha["Quantidade"] == 100 and linha["Receita"] == 10000.0
    assert linha["Participação acumulada"] == pytest.approx(10000 / 18000)
    formatos = {t: ws.cell(3, i + 1).number_format for i, t in enumerate(titulos)}
    assert formatos["Receita"] == planilha.FORMATO_REAL
    assert formatos["Margem %"] == planilha.FORMATO_PERCENTUAL
    topo = next(i for i in range(4, 20) if ws.cell(i, 1).value == "Receita por setor no mês")
    assert topo == 7  # a linha 6 fica em branco entre os blocos
    setor = [c.value for c in ws[topo + 1]][:5]
    assert setor == [t for t, _ in planilha.COLUNAS_SETORES.values()]
    assert [ws.cell(topo + 2 + k, 1).value for k in range(3)] == ["Alimentos", "Eletro", "Limpeza"]
    assert ws.cell(topo + 4, 5).value is None  # sem receita no ano anterior: sem evolução
    assert len(ws._charts) == 1


def test_sem_vendas_a_aba_produtos_sai_so_com_cabecalhos(tmp_path):
    dados = _dados()
    dados.produtos, dados.setores = dados.produtos.iloc[0:0], dados.setores.iloc[0:0]
    montar_pasta(dados).save(tmp_path / "v.xlsx")
    ws = load_workbook(tmp_path / "v.xlsx")[planilha.ABA_PRODUTOS]
    assert ws["A2"].value == "Código" and ws.max_row <= 6 and len(ws._charts) == 0


@pytest.mark.parametrize(
    "aba",
    [
        planilha.ABA_DIARIO,
        planilha.ABA_LOJAS,
        planilha.ABA_VENDEDORES,
        planilha.ABA_ALERTAS,
        planilha.ABA_PREVISAO,
    ],
)
def test_abas_de_tabela_tem_cabecalho_fixo_e_filtro(pasta, aba):
    ws = pasta[aba]
    assert ws.freeze_panes == "A2"
    assert ws.auto_filter.ref and ws.auto_filter.ref.startswith("A1:")


def test_formatos_brasileiros_na_aba_lojas(pasta):
    ws = pasta[planilha.ABA_LOJAS]
    titulos = [c.value for c in ws[1]]
    linha = {t: ws.cell(2, i + 1) for i, t in enumerate(titulos)}
    assert linha["Venda do dia"].number_format == planilha.FORMATO_REAL
    assert linha[planilha.TITULO_META_DO_MES_ATINGIDO].number_format == planilha.FORMATO_PERCENTUAL
    assert linha["Venda do dia"].value == 1500.0
    assert planilha.FORMATO_REAL.startswith('"R$"')
    assert planilha.FORMATO_DATA == "dd/mm/yyyy"


def test_datas_de_alertas_e_previsao_usam_formato_de_data(pasta):
    alerta = pasta[planilha.ABA_ALERTAS].cell(2, 3)
    assert alerta.value.date() == date(2025, 3, 5) and alerta.number_format == "dd/mm/yyyy"
    mes = pasta[planilha.ABA_PREVISAO].cell(2, 1)
    assert mes.number_format == "mm/yyyy"


def test_formatacao_condicional_verde_e_vermelho_nas_coberturas(pasta):
    regras = pasta[planilha.ABA_LOJAS].conditional_formatting
    intervalos = {str(r.sqref): [x.operator for x in r.rules] for r in regras}
    letra = lambda nome: planilha._coluna_de(planilha.COLUNAS_LOJAS, nome)  # noqa: E731
    cor = ["greaterThanOrEqual", "lessThan"]
    assert intervalos[f"{letra('cobertura_dia')}2:{letra('cobertura_dia')}3"] == cor
    for nome in ("cobertura_ate_o_dia", "cobertura_projetada", "evolucao_ano_anterior"):
        assert f"{letra(nome)}2:{letra(nome)}3" in intervalos, nome
    # a razão com a meta do mês inteiro não tem cor de status (no meio do mês ficaria vermelha)
    assert f"{letra('cobertura_mes')}2:{letra('cobertura_mes')}3" not in intervalos
    vend = pasta[planilha.ABA_VENDEDORES].conditional_formatting
    letra_v = planilha._coluna_de(planilha.COLUNAS_VENDEDORES, "cobertura_ate_o_dia")
    assert [str(r.sqref) for r in vend] == [f"{letra_v}2:{letra_v}3"]
    resumo = pasta[planilha.ABA_RESUMO].conditional_formatting
    assert len(list(resumo)) >= 1  # a cobertura das lojas da tabela do Resumo


def test_alertas_ordenados_como_vieram_e_sem_formulas(pasta):
    ws = pasta[planilha.ABA_ALERTAS]
    assert [ws.cell(i, 1).value for i in (2, 3)] == ["Crítica", "Baixa"]
    for aba in pasta.worksheets:
        for linha in aba.iter_rows():
            for celula in linha:
                assert not (isinstance(celula.value, str) and celula.value.startswith("="))


def test_resumo_traz_indicadores_calculados_dos_dados(pasta):
    ws = pasta[planilha.ABA_RESUMO]
    valores = indicadores_do_resumo(ws)
    assert valores["Venda do dia"] == 1900.0
    assert valores["Cobertura do dia"] == pytest.approx(1900 / 1800)
    assert valores[planilha.TITULO_COBERTURA_ATE_O_DIA] == pytest.approx(18000 / 17000)
    assert valores[planilha.TITULO_VENDA_ACUMULADA] == 18000.0
    assert valores[planilha.TITULO_EVOLUCAO] == pytest.approx(18000 / 17000 - 1)
    assert valores[planilha.TITULO_PROJECAO] == 37000.0
    assert valores["Ticket médio"] == 300.0 and valores["Cupons do mês"] == 60
    assert valores["Margem do mês"] == 7200.0 and valores["Margem sobre a receita"] == 0.4
    contexto = contexto_do_cartao
    assert contexto(ws, planilha.TITULO_VENDA_ACUMULADA).endswith("R$ 17.000,00")
    assert contexto(ws, planilha.TITULO_COBERTURA_ATE_O_DIA) == "50,0% da meta do mês atingido"
    assert contexto(ws, planilha.TITULO_PROJECAO).endswith("102,8%")  # 37000 / 36000
    assert contexto(ws, planilha.TITULO_EVOLUCAO).endswith("R$ 17.000,00")
    assert "15/03/2025" in ws["A2"].value and "março/2025" in ws["A1"].value
    assert ws["A1"].value.startswith("Lojas Ipê — Fechamento de ")


def test_cartoes_so_o_numero_leva_cor_de_status(pasta):
    ws = pasta[planilha.ABA_RESUMO]
    cores = {
        rotulo.value: ws.cell(5, rotulo.column).font.color.rgb[-6:]
        for rotulo in ws[4]
        if isinstance(rotulo.value, str)
    }
    assert cores[planilha.TITULO_VENDA_ACUMULADA] == planilha.COR_CABECALHO  # sem status
    assert cores[planilha.TITULO_COBERTURA_ATE_O_DIA] == planilha.COR_STATUS_VERDE  # 106%
    assert cores[planilha.TITULO_PROJECAO] == planilha.COR_STATUS_VERDE  # 102,8%
    assert cores[planilha.TITULO_EVOLUCAO] == planilha.COR_STATUS_VERDE  # +5,9%


def test_resumo_cabe_numa_pagina_a4_paisagem_sem_grade(pasta):
    ws = pasta[planilha.ABA_RESUMO]
    assert ws.sheet_view.showGridLines is False
    assert ws.page_setup.orientation == "landscape" and ws.page_setup.paperSize == 9
    assert ws.page_setup.fitToWidth == 1 and ws.page_setup.fitToHeight == 1
    assert ws.sheet_properties.pageSetUpPr.fitToPage is True
    assert ws.print_options.horizontalCentered is True
    assert ws.page_margins.left <= 0.4 and ws.page_margins.top <= 0.4
    area = ws.print_area
    assert area.startswith("'Resumo da rede'!$A$1:$L$")
    assert str(ws.max_row) in area  # o rodapé é a última linha e está dentro da área


def test_rodape_com_fonte_e_geracao_e_a_data_de_posicao_esta_nele(pasta):
    ws = pasta[planilha.ABA_RESUMO]
    rodape = ws.max_row
    assert (
        planilha.FONTE_RODAPE in ws.cell(rodape, 1).value
        and "gerado em" in ws.cell(rodape, 1).value
    )
    assert ws.cell(rodape, 12).value.date() == date(2025, 3, 15)


def test_tabela_de_lojas_do_resumo_e_a_de_alertas_por_severidade():
    lojas = _dados().lojas
    maiores, menores = planilha.lojas_extremas(lojas, 1)
    assert list(maiores["cod_loja"]) == ["L01"] and list(menores["cod_loja"]) == ["L02"]
    maiores, menores = planilha.lojas_extremas(lojas)  # menos de 10 lojas: sem repetir
    assert list(maiores["cod_loja"]) == ["L01", "L02"] and menores.empty
    por = planilha.alertas_por_severidade(_dados().alertas)
    assert list(por["severidade"]) == ["Crítica", "Alta", "Média", "Baixa"]
    assert list(por["quantidade"]) == [1, 0, 0, 1]
    assert list(por["valor"]) == [350.5, 0.0, 0.0, 20.0]


def test_cinco_melhores_e_cinco_piores_sem_se_repetir():
    lojas = pd.DataFrame(
        {
            "cod_loja": [f"L{i:02d}" for i in range(12)],
            "cobertura_ate_o_dia": [i / 10 for i in range(12)],
        }
    )
    maiores, menores = planilha.lojas_extremas(lojas)
    assert list(maiores["cod_loja"]) == ["L11", "L10", "L09", "L08", "L07"]
    assert list(menores["cod_loja"]) == ["L00", "L01", "L02", "L03", "L04"]  # a pior primeiro
    assert set(maiores["cod_loja"]).isdisjoint(menores["cod_loja"])


def test_aba_diario_traz_venda_meta_cobertura_e_acumulado(pasta):
    ws = pasta[planilha.ABA_DIARIO]
    titulos = [c.value for c in ws[1]]
    assert titulos == [t for t, _ in planilha.COLUNAS_DIARIO.values()]
    linha = {t: ws.cell(16, i + 1).value for i, t in enumerate(titulos)}  # dia 15
    assert linha["Venda"] == 1500.0 and linha["Meta do dia"] == 1000.0
    assert linha["Cobertura do dia"] == pytest.approx(1.5)
    assert linha["Venda acumulada"] == pytest.approx(100 * sum(range(1, 16)))
    assert linha["Meta acumulada"] == 15000.0
    depois = {t: ws.cell(17, i + 1).value for i, t in enumerate(titulos)}  # dia 16
    assert depois["Venda"] is None and depois["Venda acumulada"] is None
    assert depois["Cobertura do dia"] is None
    assert ws.cell(32, 6).value == 31000.0  # meta acumulada de todos os dias


def test_ha_graficos_nativos_no_resumo_e_na_previsao(pasta):
    assert len(pasta[planilha.ABA_RESUMO]._charts) == 1
    assert len(pasta[planilha.ABA_PREVISAO]._charts) == 1
    assert len(pasta[planilha.ABA_LOJAS]._charts) == 0
    assert len(pasta[planilha.ABA_PRODUTOS]._charts) == 1  # participação por setor
    assert len(pasta[planilha.ABA_DIARIO]._charts) == 0  # o gráfico do Resumo lê os dados dele


def test_sem_projecao_nem_previsao_as_celulas_ficam_vazias(tmp_path):
    caminho = tmp_path / "g.xlsx"
    montar_pasta(_dados(com_previsao=False, com_projecao=False)).save(caminho)
    wb = load_workbook(caminho)
    ws = wb[planilha.ABA_RESUMO]
    valores = indicadores_do_resumo(ws)
    assert valores[planilha.TITULO_PROJECAO] is None
    assert contexto_do_cartao(ws, planilha.TITULO_PROJECAO) == "Sem previsão para o mês"
    assert wb[planilha.ABA_PREVISAO].max_row == 1
    assert len(wb[planilha.ABA_PREVISAO]._charts) == 0


def test_venda_depois_do_dia_de_posicao_fica_vazia(pasta):
    ws = pasta[planilha.ABA_DIARIO]
    assert ws.cell(16, 2).value == 1500.0
    assert ws.cell(17, 2).value is None


def test_usa_pasta_existente_e_remove_as_abas_antigas(tmp_path):
    from openpyxl import Workbook

    modelo = Workbook()
    modelo.active.title = "Lixo"
    modelo.create_sheet("Resumo da rede").append(["antigo"])
    montar_pasta(_dados(), modelo)
    assert modelo.sheetnames[0] == planilha.ABA_RESUMO and "Lixo" not in modelo.sheetnames
    assert modelo[planilha.ABA_RESUMO]["A1"].value != "antigo"
    assert len(modelo.sheetnames) == 7


def test_colunas_de_valores_cabem_r_999_999_99_em_todas_as_abas(pasta):
    cabe = len("R$ 9.999.999,99")
    for ws in pasta.worksheets:
        for linha in ws.iter_rows():
            for celula in linha:
                if celula.number_format == planilha.FORMATO_REAL and celula.value is not None:
                    largura = ws.column_dimensions[celula.column_letter].width
                    assert largura >= cabe, (ws.title, celula.coordinate, largura)


def test_largura_por_tipo_de_coluna():
    assert planilha.largura_da_coluna("Venda", planilha.FORMATO_REAL, []) >= 16
    assert planilha.largura_da_coluna("Dia", planilha.FORMATO_DATA, []) >= 12
    curto = planilha.largura_da_coluna("Loja", None, ["L01"])
    longo = planilha.largura_da_coluna("Nome", None, ["x" * 200])
    assert curto == planilha.LARGURA_TEXTO_MINIMA
    assert longo == planilha.LARGURA_TEXTO_MAXIMA


def _subgraficos(pasta):
    for ws in pasta.worksheets:
        for grafico in ws._charts:
            yield from grafico._charts


def test_graficos_com_eixos_visiveis_sem_suavizacao_e_legenda_embaixo(pasta):
    graficos = list(_subgraficos(pasta))
    # barras + linha da meta no resumo, linha na previsão, barras da participação por setor
    assert len(graficos) == 4
    for g in graficos:
        assert g.x_axis.delete is False and g.y_axis.delete is False
        assert all(s.smooth is not True for s in g.series)
    for ws in (pasta[planilha.ABA_RESUMO], pasta[planilha.ABA_PREVISAO]):
        principal = ws._charts[0]
        assert principal.legend.position == "b"
        assert principal.title.overlay is False
        assert principal.x_axis.numFmt.formatCode == "dd/mm"
        assert principal.y_axis.numFmt.formatCode == "#,##0"


def test_data_de_posicao_gravada_em_nome_definido(pasta):
    nome = pasta.defined_names[planilha.NOME_DATA_POSICAO]
    ((aba, endereco),) = nome.destinations
    assert aba == planilha.ABA_RESUMO
    valor = pasta[aba][endereco.replace("$", "")].value
    assert valor.date() == date(2025, 3, 15)


def achar(ws, texto: str) -> tuple[int, int]:
    """(linha, coluna) da primeira célula com este texto."""
    for linha in ws.iter_rows():
        for celula in linha:
            if celula.value == texto:
                return celula.row, celula.column
    raise AssertionError(f"texto não encontrado: {texto}")


def test_alertas_por_severidade_separam_o_mes_do_total_em_aberto():
    alertas = _dados().alertas
    extra = pd.DataFrame(
        {
            "severidade": ["Crítica", "Alta"], "tipo": ["x", "x"],
            "data": [date(2025, 2, 28), date(2025, 3, 1)], "loja_ou_centro": ["Ipê 1"] * 2,
            "vendedor": [None, None], "valor_envolvido": [100.0, 50.0],
            "status": ["Novo", "Novo"], "explicacao": ["a", "b"],
        }
    )  # fmt: skip
    por = planilha.alertas_por_severidade(
        pd.concat([alertas, extra], ignore_index=True), date(2025, 3, 1)
    )
    assert list(por["quantidade"]) == [2, 1, 0, 1] and list(por["quantidade_no_mes"]) == [
        1,
        1,
        0,
        1,
    ]
    assert list(por["valor"]) == [450.5, 50.0, 0.0, 20.0]
    assert list(por["valor_no_mes"]) == [350.5, 50.0, 0.0, 20.0]  # 28/02 fica fora do mês
    assert list(planilha.alertas_por_severidade(alertas)["quantidade_no_mes"]) == [0, 0, 0, 0]


def test_resumo_mostra_alertas_no_mes_e_total_em_aberto(pasta):
    ws = pasta[planilha.ABA_RESUMO]
    linha, coluna = achar(ws, "Alertas abertos por severidade")
    assert [ws.cell(linha + 1, coluna + k).value for k in (0, 1, 3)] == [
        "Severidade", "No mês", "Total em aberto",
    ]  # fmt: skip
    assert [ws.cell(linha + 2, coluna + k).value for k in (1, 2, 3, 4)] == [
        "Quantidade", "Valor", "Quantidade", "Valor",
    ]  # fmt: skip
    corpo = [[ws.cell(linha + 3 + i, coluna + k).value for k in range(5)] for i in range(5)]
    assert corpo[0] == ["Crítica", 1, 350.5, 1, 350.5]
    assert corpo[3] == ["Baixa", 1, 20.0, 1, 20.0]
    assert corpo[4] == ["Total", 2, 370.5, 2, 370.5]


def test_resumo_traz_o_top_5_de_produtos_do_mes(pasta):
    ws = pasta[planilha.ABA_RESUMO]
    linha, coluna = achar(ws, "Top 5 produtos do mês")
    assert [ws.cell(linha + 1, coluna + k).value for k in (0, 2, 3, 4)] == [
        "Produto", "Setor", "Receita", "Participação",
    ]  # fmt: skip
    produtos = [[ws.cell(linha + 2 + i, coluna + k).value for k in (0, 2, 3, 4)] for i in range(3)]
    assert produtos[0] == ["Arroz", "Alimentos", 10000.0, pytest.approx(10000 / 18000)]
    assert [p[0] for p in produtos] == ["Arroz", "Tv", "Sabão"]
    assert ws.cell(linha + 5, coluna).value is None  # só há 3 produtos
    assert ws.cell(linha + 2, coluna + 4).number_format == planilha.FORMATO_PERCENTUAL


def _dados_com_projecao_consistente():
    """Realizado do Diário = acumulado das lojas (18.000) e projeção diária somando o que falta
    para os 37.000 do cartão."""
    dados = _dados()
    dados.vendas_por_dia["venda"] = [1200.0 if i <= 15 else None for i in range(1, 32)]
    dias = pd.date_range("2025-03-16", "2025-03-31")
    dados.projecao_por_dia = pd.DataFrame({"dia": dias.date, "projecao": [1187.5] * len(dias)})
    return dados


def test_grafico_do_resumo_mostra_a_projecao_como_segunda_serie_de_barras_cinza(tmp_path):
    montar_pasta(_dados_com_projecao_consistente()).save(tmp_path / "p.xlsx")
    ws = load_workbook(tmp_path / "p.xlsx")[planilha.ABA_RESUMO]
    barras, linha = ws._charts[0]._charts
    assert len(barras.series) == 2 and len(linha.series) == 1
    assert barras.series[1].tx.strRef.f.endswith("!G1")  # coluna "Projeção" da aba Diário
    assert barras.series[1].graphicalProperties.solidFill.srgbClr == planilha.COR_PROJECAO
    assert barras.overlap == 100


def test_realizado_mais_projecao_bate_com_o_cartao_de_projecao(tmp_path):
    montar_pasta(_dados_com_projecao_consistente()).save(tmp_path / "p.xlsx")
    wb = load_workbook(tmp_path / "p.xlsx")
    diario = wb[planilha.ABA_DIARIO]
    titulos = [c.value for c in diario[1]]
    assert titulos[-1] == "Projeção"
    vendas = [diario.cell(i, 2).value for i in range(2, 33)]
    projecao = [diario.cell(i, 7).value for i in range(2, 33)]
    assert all(p is None for p in projecao[:15])  # até a posição só há venda
    assert all(v is None for v in vendas[15:])  # depois dela só há projeção
    total = sum(v for v in vendas if v) + sum(p for p in projecao if p)
    cartao = indicadores_do_resumo(wb[planilha.ABA_RESUMO])[planilha.TITULO_PROJECAO]
    assert total == pytest.approx(cartao) == pytest.approx(37000.0)


def test_sem_projecao_a_coluna_projecao_fica_vazia(tmp_path):
    dados = _dados(com_projecao=False)
    montar_pasta(dados).save(tmp_path / "s.xlsx")
    diario = load_workbook(tmp_path / "s.xlsx")[planilha.ABA_DIARIO]
    assert all(diario.cell(i, 7).value is None for i in range(2, 33))


def test_vendedores_trazem_o_setor_principal_e_a_participacao_dele(pasta):
    ws = pasta[planilha.ABA_VENDEDORES]
    titulos = [c.value for c in ws[1]]
    assert titulos[-2:] == ["Setor principal", "% no setor principal"]
    linha = dict(zip(titulos, [c.value for c in ws[3]], strict=True))
    assert linha["Setor principal"] == "Eletro" and linha["% no setor principal"] == 0.55
    assert ws.cell(3, len(titulos)).number_format == planilha.FORMATO_PERCENTUAL
