"""Aba oculta "Dados por vendedor" (formato longo): montagem a partir de quadros sintéticos, sem
banco. A macro GerarAbaDoVendedor lê exatamente estas linhas."""

from datetime import date

import pandas as pd
import pytest

from src import config
from src.relatorios import por_vendedor as pv
from src.relatorios.planilha import montar_pasta

MES, DIA = date(2025, 3, 1), date(2025, 3, 5)


def _quadros():
    vendedores = pd.DataFrame(
        {
            "posicao": [1, 2, 3], "cod_vendedor": ["V1", "V2", "V3"],
            "nome_vendedor": ["Ana", "Bia", "Caio"], "cod_loja": ["L01", "L01", "L02"],
            "nome_loja": ["Ipê 1", "Ipê 1", "Ipê 2"],
            "acumulado_mes": [900.0, 600.0, 300.0], "meta_acumulada": [500.0, 600.0, 400.0],
            "cobertura_ate_o_dia": [1.8, 1.0, 0.75], "meta_mes": [3000.0, 3000.0, 3000.0],
            "cobertura_mes": [0.3, 0.2, 0.1], "ritmo_necessario_dia": [1500.0, 2000.0, None],
            "setor_principal": ["Eletro", "Alimentos", None],
            "percentual_setor_principal": [0.6, 1.0, None],
            "setor_lotacao": ["Eletro", "Casa", None],
            "percentual_setor_lotacao": [0.5, 0.25, None],
        }
    )  # fmt: skip
    dias = pd.DataFrame(
        {
            "cod_vendedor": ["V1"] * 5 + ["V2"],
            "dia": [date(2025, 3, d) for d in range(1, 6)] + [date(2025, 3, 5)],
            "venda": [100.0, 0.0, 300.0, 200.0, 300.0, 600.0],
            "meta_dia": [100.0, 100.0, 100.0, 250.0, 100.0, 120.0],
        }
    )
    evolucao = pd.DataFrame(
        {
            "cod_vendedor": ["V1"] * 3,
            "mes_ref": [date(2024, 12, 1), date(2025, 1, 1), date(2025, 3, 1)],
            "venda": [500.0, 700.0, 900.0], "meta": [600.0, 700.0, 500.0],
        }
    )  # fmt: skip
    produtos = pd.DataFrame(
        {
            "cod_vendedor": ["V1", "V1"], "posicao": [1, 2], "descricao": ["Tv", "Arroz"],
            "setor": ["Eletro", "Alimentos"], "quantidade": [1, 9], "receita": [540.0, 360.0],
        }
    )  # fmt: skip
    mix = pd.DataFrame(
        {
            "cod_vendedor": ["V1", "V1"], "setor": ["Eletro", "Alimentos"],
            "receita": [540.0, 360.0], "participacao": [0.6, 0.4],
        }
    )  # fmt: skip
    comportamento = pd.DataFrame(
        {
            "cod_vendedor": ["V1", "V2", "V3"], "cod_loja": ["L01", "L01", "L02"],
            "cupons": [3, 1, 2], "itens": [6, 1, 4], "bruto": [1000.0, 100.0, 400.0],
            "desconto": [100.0, 0.0, 40.0], "receita": [900.0, 100.0, 360.0],
            "cancelados": [1, 0, 0],
        }
    )  # fmt: skip
    alertas = pd.DataFrame(
        {
            "cod_vendedor": ["V1", "V3"], "severidade": ["Alta", "Baixa"],
            "tipo": ["Desconto acima do limite", "Cupom duplicado"],
            "data": [date(2025, 3, 2), date(2025, 3, 3)], "valor_envolvido": [40.0, 10.0],
            "status": ["Novo", "Novo"], "explicacao": ["Desconto de 40%", "Duplicado"],
        }
    )  # fmt: skip
    return vendedores, dias, evolucao, produtos, mix, comportamento, alertas


@pytest.fixture(scope="module")
def dados():
    return pv.montar_dados_por_vendedor(*_quadros(), MES, DIA)


def _bloco(dados, cod, bloco):
    return dados[(dados.cod_vendedor == cod) & (dados.bloco == bloco)].sort_values("ordem")


def _pares(dados, cod, bloco):
    quadro = _bloco(dados, cod, bloco)
    quadro = quadro[quadro.ordem > 0]
    return dict(zip(quadro.col_1, quadro.col_2, strict=True))


def test_dias_que_bateu_a_meta_conta_so_dias_com_venda_e_meta_batida():
    dias = pd.DataFrame(
        {"venda": [100.0, 0.0, 50.0, 200.0], "meta_dia": [100.0, 100.0, None, 150.0]}
    )
    assert pv.dias_que_bateu_a_meta(dias) == (2, 3)  # 100>=100 e 200>=150; sem meta não conta


def test_vendedor_sem_nenhuma_meta_no_mes_nao_bate_meta_nenhuma():
    dias = pd.DataFrame({"venda": [100.0, 50.0], "meta_dia": [None, None]})  # coluna de objetos
    assert pv.dias_que_bateu_a_meta(dias) == (0, 2)


def test_formato_longo_tem_as_colunas_e_todos_os_blocos_de_cada_vendedor(dados):
    assert list(dados.columns) == list(pv.COLUNAS)
    for cod in ("V1", "V2", "V3"):
        assert set(dados[dados.cod_vendedor == cod].bloco) == set(pv.BLOCOS)
        # cada bloco abre com a linha de ordem 0, que carrega o título da seção
        zeros = dados[(dados.cod_vendedor == cod) & (dados.ordem == 0)]
        assert list(zeros.bloco) == list(pv.BLOCOS) and (zeros.titulo != "").all()
    assert (dados.formatos.str.len() == pv.COLUNAS_DE_VALOR).all()
    assert set("".join(dados.formatos)) <= set(pv.FORMATOS)


def test_titulos_de_tabela_trazem_os_cabecalhos_separados_por_barra(dados):
    zeros = dados[(dados.cod_vendedor == "V1") & (dados.ordem == 0)].set_index("bloco")
    for bloco in (pv.BLOCO_DIA_A_DIA, pv.BLOCO_EVOLUCAO, pv.BLOCO_PRODUTOS, pv.BLOCO_MIX,
                  pv.BLOCO_COMPORTAMENTO, pv.BLOCO_ALERTAS):  # fmt: skip
        assert zeros.at[bloco, "cabecalhos"]
    for bloco in (pv.BLOCO_CABECALHO, pv.BLOCO_DIA, pv.BLOCO_MES, pv.BLOCO_ANO):
        assert zeros.at[bloco, "cabecalhos"] == ""  # rótulo e valor, sem linha de cabeçalho
    # um título por coluna usada (letra diferente de "-" nas linhas de dados)
    for bloco in (pv.BLOCO_DIA_A_DIA, pv.BLOCO_EVOLUCAO, pv.BLOCO_PRODUTOS, pv.BLOCO_ALERTAS):
        usadas = len(_bloco(dados, "V1", bloco).formatos.iloc[-1].replace("-", ""))
        assert len(zeros.at[bloco, "cabecalhos"].split("|")) == usadas


def test_cabecalho_do_vendedor_com_posicao_na_loja_e_na_rede(dados):
    assert _bloco(dados, "V1", pv.BLOCO_TITULO).titulo.iloc[0] == "Vendedor V1 - Ana (L01)"
    c = _pares(dados, "V2", pv.BLOCO_CABECALHO)
    assert c["Nome"] == "Bia" and c["Loja"] == "L01 - Ipê 1"
    assert c["Setor principal"] == "Alimentos (100,0% da receita)"
    assert c["Posição na loja"] == "2 de 2" and c["Posição na rede"] == "2 de 3"
    assert _pares(dados, "V3", pv.BLOCO_CABECALHO)["Posição na loja"] == "1 de 1"
    assert _pares(dados, "V3", pv.BLOCO_CABECALHO)["Setor principal"] == "-"
    assert c["Setor de lotação"] == "Casa (25,0% da receita)"
    assert _pares(dados, "V3", pv.BLOCO_CABECALHO)["Setor de lotação"] == "-"


def test_metas_do_dia_do_mes_e_do_ano(dados):
    dia = _pares(dados, "V1", pv.BLOCO_DIA)
    assert dia["Venda do dia"] == 300.0 and dia["Meta do dia"] == 100.0
    assert dia[pv.TITULO_COBERTURA_DIA] == pytest.approx(3.0)
    mes = _pares(dados, "V1", pv.BLOCO_MES)
    assert mes["Acumulado do mês"] == 900.0 and mes["Meta acumulada até o dia"] == 500.0
    assert mes[pv.TITULO_COBERTURA_ATE_O_DIA] == pytest.approx(1.8)
    assert mes[pv.TITULO_META_DO_MES_ATINGIDO] == pytest.approx(0.3)
    assert mes[pv.TITULO_RITMO] == 1500.0
    assert _pares(dados, "V3", pv.BLOCO_MES)[pv.TITULO_RITMO] is None  # sem meta restante
    ano = _pares(dados, "V1", pv.BLOCO_ANO)  # só os meses de 2025 (o de 12/2024 fica de fora)
    assert ano["Acumulado no ano"] == 1600.0 and ano["Meta do ano até a posição"] == 1200.0
    assert ano["Cobertura do ano"] == pytest.approx(1600 / 1200)


def test_vendedor_sem_venda_no_dia_tem_venda_zero_e_cobertura_zero(dados):
    dia = _pares(dados, "V3", pv.BLOCO_DIA)  # V3 não tem linha em `dias`
    assert dia["Venda do dia"] == 0.0 and dia["Meta do dia"] is None
    assert dia[pv.TITULO_COBERTURA_DIA] is None


def test_dias_que_bateu_a_meta_titulo_e_tabela_dia_a_dia(dados):
    zero = _bloco(dados, "V1", pv.BLOCO_DIA_A_DIA).iloc[0]
    # vendeu em 4 dias (o dia 2 teve venda 0): bateu a meta em 1, 3 e 5, não bateu no dia 4
    assert zero.titulo == "Dias que bateu a meta no mês: 3 de 4 dias com venda"
    linhas = _bloco(dados, "V1", pv.BLOCO_DIA_A_DIA).iloc[1:]
    assert list(linhas.col_1) == [date(2025, 3, d) for d in (1, 3, 4, 5)]
    assert list(linhas.col_4) == pytest.approx([1.0, 3.0, 0.8, 3.0])
    assert set(linhas.formatos) == {"DRRP--"}


def test_evolucao_traz_os_meses_do_vendedor_com_venda_meta_e_cobertura(dados):
    linhas = _bloco(dados, "V1", pv.BLOCO_EVOLUCAO).iloc[1:]
    assert list(linhas.col_1) == [date(2024, 12, 1), date(2025, 1, 1), date(2025, 3, 1)]
    assert list(linhas.col_2) == [500.0, 700.0, 900.0]
    assert list(linhas.col_4) == pytest.approx([500 / 600, 1.0, 1.8])
    titulo = _bloco(dados, "V1", pv.BLOCO_EVOLUCAO).titulo.iloc[0]
    assert str(config.RELATORIO_MESES_EVOLUCAO_VENDEDOR) in titulo and "05/03/2025" in titulo


def test_top_de_produtos_e_mix_por_setor(dados):
    produtos = _bloco(dados, "V1", pv.BLOCO_PRODUTOS).iloc[1:]
    assert list(produtos.col_1) == ["Tv", "Arroz"] and list(produtos.col_3) == [1, 9]
    assert list(produtos.col_4) == [540.0, 360.0]
    mix = _bloco(dados, "V1", pv.BLOCO_MIX).iloc[1:]
    assert list(mix.col_1) == ["Eletro", "Alimentos"] and list(mix.col_3) == [0.6, 0.4]
    assert _bloco(dados, "V2", pv.BLOCO_PRODUTOS).shape[0] == 1  # só o título: sem produtos


def test_comportamento_do_vendedor_ao_lado_da_media_da_loja(dados):
    c = _bloco(dados, "V1", pv.BLOCO_COMPORTAMENTO).iloc[1:]
    por_indicador = {r.col_1: (r.col_2, r.col_3) for r in c.itertuples()}
    assert list(por_indicador) == list(pv.INDICADORES_COMPORTAMENTO)
    # V1: 3 cupons, 900 de receita; a loja L01 (V1 + V2): 4 cupons, 1000 de receita
    assert por_indicador["Ticket médio"] == pytest.approx((900 / 3, 1000 / 4))
    assert por_indicador["Itens por cupom"] == pytest.approx((6 / 3, 7 / 4))
    assert por_indicador["Desconto médio"] == pytest.approx((100 / 1000, 100 / 1100))
    # cancelamento = cupons cancelados ÷ (concluídos + cancelados)
    assert por_indicador["Taxa de cancelamento"] == pytest.approx((1 / 4, 1 / 5))


def test_alertas_do_vendedor_sao_so_os_dele(dados):
    a = _bloco(dados, "V1", pv.BLOCO_ALERTAS).iloc[1:]
    assert list(a.col_2) == ["Desconto acima do limite"] and list(a.col_3) == [date(2025, 3, 2)]
    assert _bloco(dados, "V2", pv.BLOCO_ALERTAS).shape[0] == 1
    assert list(_bloco(dados, "V3", pv.BLOCO_ALERTAS).iloc[1:].col_2) == ["Cupom duplicado"]


def test_aba_oculta_da_pasta_tem_o_cabecalho_e_as_linhas_do_formato_longo(tmp_path, dados):
    from openpyxl import load_workbook

    from tests.relatorios.test_planilha import _dados

    d = _dados()
    d.dados_por_vendedor = dados
    montar_pasta(d).save(tmp_path / "f.xlsx")
    ws = load_workbook(tmp_path / "f.xlsx")["Dados por vendedor"]
    assert ws.sheet_state == "hidden"
    assert [c.value for c in ws[1]] == list(pv.COLUNAS)
    assert ws.max_row == len(dados) + 1
