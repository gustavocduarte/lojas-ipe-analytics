"""O .xlsx de fechamento precisa bater com consultas independentes ao dw (precisa de PostgreSQL)."""

from datetime import date, timedelta
from decimal import Decimal

import pandas as pd
import pytest
from openpyxl import load_workbook

from src import config
from src.relatorios import consultas, fechamento
from src.relatorios.__main__ import principal
from src.relatorios.planilha import (
    ABA_ALERTAS,
    ABA_DADOS_POR_LOJA,
    ABA_DADOS_POR_VENDEDOR,
    ABA_DIARIO,
    ABA_LOJAS,
    ABA_PREVISAO,
    ABA_PREVISAO_DIARIA,
    ABA_PRODUTOS,
    ABA_RESUMO,
    ABA_VENDEDORES,
    TITULO_COBERTURA_ATE_O_DIA,
    TITULO_META_DO_MES_ATINGIDO,
    TITULO_PROJECAO,
    TITULO_VENDA_ACUMULADA,
)
from tests.etl import base_alertas as b
from tests.relatorios.test_planilha import contexto_do_cartao, indicadores_do_resumo

pytestmark = pytest.mark.banco

MES, DIA = date(2025, 3, 1), date(2025, 3, 15)


def _dim_tempo(con, inicio: date, fim: date):
    dia = inicio
    while dia <= fim:
        con.execute(
            "INSERT INTO dw.dim_tempo (sk_tempo, data, dia, semana, mes, trimestre, ano, nome_mes,"
            " nome_dia_semana, feriado_nacional)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE)",
            (
                int(dia.strftime("%Y%m%d")), dia, dia.day, dia.isocalendar()[1], dia.month,
                (dia.month - 1) // 3 + 1, dia.year, b.MESES[dia.month - 1], b.DIAS[dia.weekday()],
            ),
        )  # fmt: skip
        dia += timedelta(days=1)


@pytest.fixture
def dw(banco_com_ddl):
    con = banco_com_ddl
    b.montar_base(con, ano=2025)
    _dim_tempo(con, date(2024, 3, 1), date(2024, 3, 31))
    n = 0
    for dia in range(1, 21):  # março de 2025 até o dia 20 (depois do dia de posição, de propósito)
        for loja, base in (("L01", 100), ("L02", 50)):
            n += 1
            b.item(con, f"A{n}", cupom=f"A{n}", data=f"2025-03-{dia:02d}", loja=loja,
                   vendedor="V1" if loja == "L01" else "V2", receita=base * dia)  # fmt: skip
    for dia in range(1, 16):  # março de 2024, mesmo período
        b.item(con, f"P{dia}", cupom=f"P{dia}", data=f"2024-03-{dia:02d}", receita=80 * dia)
    b.item(con, "CANC", cupom="CANC", data="2025-03-05", receita=9999, status="Cancelada")
    b.item(con, "OUTRO", cupom="OUTRO", data="2025-04-02", receita=7777)  # outro mês
    for cod, valor in (("L01", 6000), ("L02", 4000)):
        con.execute(
            "INSERT INTO dw.fato_meta_vendas (sk_tempo, sk_loja, setor, valor_meta)"
            " SELECT 20250301, sk_loja, 'Alimentos', %s FROM dw.dim_loja WHERE cod_loja = %s",
            (valor, cod),
        )
    for cod, valor in (("V1", 5000), ("V2", 3000)):
        con.execute(
            "INSERT INTO dw.fato_meta_vendedor (sk_tempo, sk_vendedor, valor_meta)"
            " SELECT 20250301, sk_vendedor, %s FROM dw.dim_vendedor WHERE cod_vendedor = %s",
            (valor, cod),
        )
    # alertas: desconto muito acima do limite (um novo, um já classificado como falso positivo)
    b.item(con, "DESC1", cupom="DESC1", data="2025-03-07", preco=100, desconto=40, receita=60)
    b.item(con, "DESC2", cupom="DESC2", data="2025-03-08", preco=100, desconto=45, receita=55)
    con.commit()
    b.gerar(con)
    con.execute(
        "UPDATE dw.alertas SET status = 'falso_positivo' WHERE sk_alerta ="
        " (SELECT min(sk_alerta) FROM dw.alertas WHERE tipo_alerta = 'desconto_acima_limite')"
    )
    # previsão (como se tivesse sido gerada em 15/03/2025, o dia de posição do relatório)
    con.execute(
        "INSERT INTO dw.previsao_vendas (granularidade, data, sk_loja, setor, valor_previsto,"
        " valor_baixo, valor_alto, versao_modelo, treino_ate)"
        " SELECT 'mes', '2026-01-01', sk_loja, 'Alimentos', 20000, 17000, 23000, 'x@1',"
        " '2025-03-15'"
        " FROM dw.dim_loja"
    )
    con.execute(
        "INSERT INTO dw.previsao_vendas (granularidade, data, sk_loja, setor, valor_previsto,"
        " valor_baixo, valor_alto, versao_modelo, treino_ate)"
        " SELECT 'dia', make_date(2026, 1, d), sk_loja, 'Alimentos', 600, 500, 700, 'x@1',"
        " '2025-03-15' FROM dw.dim_loja, generate_series(1, 31) d"
    )
    con.execute(
        "INSERT INTO dw.previsao_backtest (versao_modelo, nivel, granularidade, sk_loja,"
        " treino_ate,"
        " teste_inicio, teste_fim, wape, vies, escolhido)"
        " SELECT 'x@1', 'loja', 'mes', sk_loja, '2025-06-30', '2025-07-01', '2025-12-31', 0.1234,"
        " 0, TRUE FROM dw.dim_loja WHERE cod_loja = 'L01'"
    )
    con.commit()
    return con


@pytest.fixture
def pasta(dw, tmp_path):
    caminho, _ = fechamento.gerar(dw, MES, DIA, tmp_path / "f.xlsx", modelo=None)
    return load_workbook(caminho)


@pytest.fixture
def pasta_com_produtos(dw, tmp_path):
    """Produto 2 (Eletro) vende na L02; o produto 1 (Alimentos) vende na L01."""
    dw.execute(
        "INSERT INTO dw.dim_produto (sku, nome_produto, marca, setor, categoria, custo_unitario,"
        " preco_lista) VALUES ('P2', 'Produto 2', 'Marca', 'Eletro', 'Eletro', 60, 100)"
    )
    dw.execute(
        "UPDATE dw.fato_vendas SET sk_produto = (SELECT sk_produto FROM dw.dim_produto"
        " WHERE sku = 'P2') WHERE sk_loja ="
        " (SELECT sk_loja FROM dw.dim_loja WHERE cod_loja = 'L02')"
    )
    dw.commit()
    caminho, _ = fechamento.gerar(dw, MES, DIA, tmp_path / "p.xlsx", modelo=None)
    return load_workbook(caminho)


@pytest.fixture
def pasta_com_setor_do_vendedor(dw, tmp_path):
    """V1 vende Alimentos (produto 1) e um pouco de Eletro; V2 o contrário. Há também Eletro
    cancelado e depois do dia de posição, que não podem contar."""
    dw.execute(
        "INSERT INTO dw.dim_produto (sku, nome_produto, marca, setor, categoria, custo_unitario,"
        " preco_lista) VALUES ('P2', 'Produto 2', 'Marca', 'Eletro', 'Eletro', 60, 100)"
    )
    eletro = "(SELECT sk_produto FROM dw.dim_produto WHERE sku = 'P2')"
    l02 = "(SELECT sk_loja FROM dw.dim_loja WHERE cod_loja = 'L02')"
    dw.execute(
        f"UPDATE dw.fato_vendas SET sk_produto = {eletro} WHERE sk_loja = {l02}"
        " AND id_venda_erp NOT IN ('A2', 'A4', 'A6')"  # V2: 300 em Alimentos, o resto em Eletro
    )
    dw.execute(
        f"UPDATE dw.fato_vendas SET sk_produto = {eletro}"
        " WHERE id_venda_erp IN ('A1', 'A3', 'CANC')"
    )  # V1: 300 em Eletro dentro da posição, mais uma cancelada
    dw.execute(  # V1 depois do dia 15: 100 x (16..20) em Eletro
        f"UPDATE dw.fato_vendas SET sk_produto = {eletro} WHERE sk_tempo > 20250315"
        " AND sk_tempo < 20250401 AND sk_loja = (SELECT sk_loja FROM dw.dim_loja WHERE cod_loja"
        " = 'L01')"
    )
    dw.commit()
    caminho, _ = fechamento.gerar(dw, MES, DIA, tmp_path / "sv.xlsx", modelo=None)
    return load_workbook(caminho)


def _escalar(con, sql, *params):
    valor = con.execute(sql, params).fetchone()[0]
    return float(valor) if isinstance(valor, Decimal) else valor


def _tabela(ws):
    return _tabela_a_partir(ws, 1)


def _tabela_a_partir(ws, linha_cabecalho: int):
    titulos = [c.value for c in ws[linha_cabecalho]]
    return [
        dict(zip(titulos, [c.value for c in linha], strict=True))
        for linha in ws.iter_rows(min_row=linha_cabecalho + 1)
    ]


class TestLojas:
    def test_venda_acumulado_e_meta_de_cada_loja_batem_com_o_dw(self, dw, pasta):
        linhas = {linha["Loja"]: linha for linha in _tabela(pasta[ABA_LOJAS])}
        assert set(linhas) == {"L01", "L02"}
        for cod in ("L01", "L02"):
            sql = (
                "SELECT {} FROM dw.fato_vendas v JOIN dw.dim_tempo t USING (sk_tempo)"
                " JOIN dw.dim_loja l USING (sk_loja) WHERE l.cod_loja = %s"
                " AND v.status = 'Concluída'"
                " AND t.data {}"
            )
            acumulado = _escalar(
                dw,
                sql.format("sum(v.receita_liquida)", "BETWEEN '2025-03-01' AND '2025-03-15'"),
                cod,
            )
            dia = _escalar(dw, sql.format("sum(v.receita_liquida)", "= '2025-03-15'"), cod)
            anterior = _escalar(
                dw,
                sql.format("sum(v.receita_liquida)", "BETWEEN '2024-03-01' AND '2024-03-15'"),
                cod,
            )
            meta = _escalar(
                dw, "SELECT sum(valor_meta) FROM dw.fato_meta_vendas m JOIN dw.dim_loja l"
                " USING (sk_loja) WHERE l.cod_loja = %s AND m.sk_tempo = 20250301", cod,
            )  # fmt: skip
            linha = linhas[cod]
            assert linha["Acumulado do mês"] == pytest.approx(acumulado)
            assert linha["Venda do dia"] == pytest.approx(dia)
            assert linha["Meta do mês"] == pytest.approx(meta)
            assert linha[TITULO_META_DO_MES_ATINGIDO] == pytest.approx(acumulado / meta)
            meta_ate_dia = _escalar(
                dw, "SELECT sum(m.valor_meta_dia) FROM dw.vw_meta_vendas_diaria m JOIN dw.dim_loja"
                " l USING (sk_loja) WHERE l.cod_loja = %s AND m.data BETWEEN '2025-03-01' AND"
                " '2025-03-15'", cod,
            )  # fmt: skip
            assert linha[TITULO_COBERTURA_ATE_O_DIA] == pytest.approx(acumulado / meta_ate_dia)
            assert linha["Mesmo período do ano anterior"] == (
                pytest.approx(anterior) if anterior else None
            )
            if anterior:
                assert linha["Evolução vs ano anterior"] == pytest.approx(acumulado / anterior - 1)

    def test_valores_conhecidos_a_mao(self, pasta):
        l01 = next(x for x in _tabela(pasta[ABA_LOJAS]) if x["Loja"] == "L01")
        assert l01["Acumulado do mês"] == pytest.approx(100 * sum(range(1, 16)) + 60 + 55)
        assert l01["Mesmo período do ano anterior"] == pytest.approx(80 * sum(range(1, 16)))
        assert l01["Venda do dia"] == 1500

    def test_meta_do_dia_vem_da_meta_diaria_e_soma_com_a_do_mes(self, dw, pasta):
        soma_ate_dia = _escalar(
            dw, "SELECT sum(valor_meta_dia) FROM dw.vw_meta_vendas_diaria"
            " WHERE data BETWEEN '2025-03-01' AND '2025-03-15'",
        )  # fmt: skip
        linhas = _tabela(pasta[ABA_LOJAS])
        assert sum(x["Meta acumulada até o dia"] for x in linhas) == pytest.approx(soma_ate_dia)
        assert all(x["Meta do dia"] > 0 for x in linhas)


class TestResumo:
    def test_totais_da_rede_batem_com_o_dw(self, dw, pasta):
        ws = pasta[ABA_RESUMO]
        valores = indicadores_do_resumo(ws)
        receita = _escalar(
            dw, "SELECT sum(receita_liquida) FROM dw.fato_vendas v JOIN dw.dim_tempo t USING"
            " (sk_tempo) WHERE status = 'Concluída'"
            " AND t.data BETWEEN '2025-03-01' AND '2025-03-15'",
        )  # fmt: skip
        margem = _escalar(
            dw, "SELECT sum(margem) FROM dw.fato_vendas v JOIN dw.dim_tempo t USING (sk_tempo)"
            " WHERE status = 'Concluída' AND t.data BETWEEN '2025-03-01' AND '2025-03-15'",
        )  # fmt: skip
        cupons = _escalar(
            dw, "SELECT count(DISTINCT (sk_loja, numero_cupom)) FROM dw.fato_vendas v JOIN"
            " dw.dim_tempo t USING (sk_tempo) WHERE status = 'Concluída'"
            " AND t.data BETWEEN '2025-03-01' AND '2025-03-15'",
        )  # fmt: skip
        meta = _escalar(
            dw, "SELECT sum(valor_meta) FROM dw.fato_meta_vendas WHERE sk_tempo = 20250301"
        )
        assert valores[TITULO_VENDA_ACUMULADA] == pytest.approx(receita)
        assert valores["Margem do mês"] == pytest.approx(margem)
        assert valores["Cupons do mês"] == cupons
        assert valores["Ticket médio"] == pytest.approx(receita / cupons)
        meta_ate_dia = _escalar(
            dw, "SELECT sum(valor_meta_dia) FROM dw.vw_meta_vendas_diaria"
            " WHERE data BETWEEN '2025-03-01' AND '2025-03-15'",
        )  # fmt: skip
        atingido = f"{receita / meta * 100:.1f}".replace(".", ",")
        assert contexto_do_cartao(ws, TITULO_COBERTURA_ATE_O_DIA) == (
            f"{atingido}% da meta do mês atingido"
        )
        assert valores[TITULO_COBERTURA_ATE_O_DIA] == pytest.approx(receita / meta_ate_dia)

    def test_realizado_mais_projecao_por_dia_bate_com_o_cartao_de_projecao(self, dw, tmp_path):
        dw.execute(
            "INSERT INTO dw.previsao_vendas (granularidade, data, sk_loja, setor, valor_previsto,"
            " valor_baixo, valor_alto, versao_modelo, treino_ate)"
            " SELECT 'dia', make_date(2025, 3, d), sk_loja, 'Alimentos', 100, 90, 110, 'y@1',"
            " '2025-03-15' FROM dw.dim_loja, generate_series(16, 31) d"
        )
        dw.commit()
        caminho, _ = fechamento.gerar(dw, MES, DIA, tmp_path / "pj.xlsx", modelo=None)
        wb = load_workbook(caminho)
        diario = wb[ABA_DIARIO]
        vendas = [diario.cell(i, 2).value for i in range(2, 33)]
        projecao = [diario.cell(i, 7).value for i in range(2, 33)]
        assert all(p is None for p in projecao[:15]) and all(v is None for v in vendas[15:])
        assert projecao[15:] == [200.0] * 16  # 2 lojas x 100, de 16 a 31
        cartao = indicadores_do_resumo(wb[ABA_RESUMO])[TITULO_PROJECAO]
        assert sum(v for v in vendas if v) + sum(p for p in projecao if p) == pytest.approx(cartao)

    def test_sem_previsao_para_a_posicao_a_projecao_diaria_fica_vazia(self, pasta):
        diario = pasta[ABA_DIARIO]
        assert all(diario.cell(i, 7).value is None for i in range(2, 33))

    def test_venda_por_dia_ignora_canceladas_e_para_no_dia_de_posicao(self, pasta):
        ws = pasta[ABA_DIARIO]
        dias = [(ws.cell(k, 2).value, ws.cell(k, 3).value) for k in range(2, 33)]
        assert dias[0][0] == pytest.approx(150)  # 100 + 50 no dia 1
        assert dias[14][0] == pytest.approx(150 * 15)
        assert dias[4][0] == pytest.approx(150 * 5)  # a cancelada de 9.999 não entra
        assert all(venda is None for venda, _ in dias[15:])  # depois do dia 15 não há venda
        assert all(meta and meta > 0 for _, meta in dias)


class TestProdutos:
    def test_top_de_produtos_so_ate_o_dia_e_so_vendas_concluidas(self, pasta_com_produtos):
        ws = pasta_com_produtos[ABA_PRODUTOS]
        linhas = {x["Código"]: x for x in _tabela_a_partir(ws, 2) if x["Código"] in ("P1", "P2")}
        p1, p2 = linhas["P1"], linhas["P2"]
        assert p1["Receita"] == pytest.approx(
            100 * sum(range(1, 16)) + 60 + 55
        )  # sem os dias 16-20
        assert p2["Receita"] == pytest.approx(50 * sum(range(1, 16)))  # sem a cancelada nem abril
        assert p1["Quantidade"] == 17 and p2["Quantidade"] == 15
        total = p1["Receita"] + p2["Receita"]
        assert p1["Participação na receita"] == pytest.approx(p1["Receita"] / total)
        assert p2["Participação acumulada"] == pytest.approx(1.0)
        assert p1["Margem %"] == pytest.approx((p1["Receita"] - 17 * 60) / p1["Receita"])
        assert (p1["Classe ABC"], p2["Classe ABC"]) == ("A", "C")  # acumulado de 66,9% e 100%

    def test_setores_com_evolucao_contra_o_mesmo_periodo_do_ano_anterior(self, pasta_com_produtos):
        ws = pasta_com_produtos[ABA_PRODUTOS]
        topo = next(i for i in range(3, 40) if ws.cell(i, 1).value == "Receita por setor no mês")
        setores = {
            ws.cell(i, 1).value: [ws.cell(i, c).value for c in range(2, 6)]
            for i in range(topo + 2, topo + 4)
        }
        receita_alimentos = 100 * sum(range(1, 16)) + 60 + 55
        assert setores["Alimentos"][0] == pytest.approx(receita_alimentos)
        assert setores["Alimentos"][3] == pytest.approx(receita_alimentos / (80 * 120) - 1)
        assert setores["Eletro"][3] is None  # sem venda de Eletro no ano anterior
        assert sum(v[1] for v in setores.values()) == pytest.approx(1.0)


def _bloco_da_loja(ws, coluna: int, quantas: int, loja: str = "L01") -> list[dict]:
    """Linhas da loja num bloco da aba oculta "Dados por loja" (cabeçalho na linha 2)."""
    titulos = [ws.cell(2, coluna + k).value for k in range(quantas)]
    return [
        dict(zip(titulos, [ws.cell(i, coluna + k).value for k in range(quantas)], strict=True))
        for i in range(3, ws.max_row + 1)
        if ws.cell(i, coluna).value == loja
    ]


class TestDadosPorLoja:
    def test_top_5_produtos_da_loja_no_mes_ate_o_dia(self, dw, tmp_path):
        for k in range(1, 7):  # seis produtos pequenos (10..60) na L01, em 10/03
            dw.execute(
                "INSERT INTO dw.dim_produto (sku, nome_produto, marca, setor, categoria,"
                " custo_unitario, preco_lista) VALUES (%s, %s, 'Marca', 'Limpeza', 'Cat', 1, 2)",
                (f"Q{k}", f"Produto Q{k}"),
            )
            b.item(dw, f"Q{k}", cupom=f"Q{k}", data="2025-03-10", receita=10 * k)
            dw.execute(
                "UPDATE dw.fato_vendas SET sk_produto = (SELECT sk_produto FROM dw.dim_produto"
                " WHERE sku = %s) WHERE id_venda_erp = %s",
                (f"Q{k}", f"Q{k}"),
            )
        dw.commit()
        caminho, _ = fechamento.gerar(dw, MES, DIA, tmp_path / "t.xlsx", modelo=None)
        ws = load_workbook(caminho)[ABA_DADOS_POR_LOJA]
        linhas = _bloco_da_loja(ws, 1, 6)
        assert [x["Posição"] for x in linhas] == [1, 2, 3, 4, 5]  # só os 5 maiores
        assert [x["Produto"] for x in linhas] == [
            "Produto 1", "Produto Q6", "Produto Q5", "Produto Q4", "Produto Q3",
        ]  # fmt: skip
        grande = 100 * sum(range(1, 16)) + 60 + 55  # sem os dias 16-20 nem a cancelada
        assert linhas[0]["Receita"] == pytest.approx(grande)
        total = grande + sum(10 * k for k in range(1, 7))
        assert linhas[1]["Participação na receita da loja"] == pytest.approx(60 / total)
        assert {x["Setor"] for x in linhas[1:]} == {"Limpeza"}
        assert [x["Loja"] for x in _bloco_da_loja(ws, 1, 6, "L02")] == ["L02"]

    @pytest.fixture
    def quando_vende(self, dw, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "RELATORIO_DIAS_QUANDO_A_LOJA_VENDE", 30)  # de 14/02 a 15/03
        b.item(dw, "NOITE", cupom="NOITE", data="2025-03-15", hora="20:00:00", receita=20000)
        b.item(dw, "FORA", cupom="FORA", data="2025-02-10", receita=9999)  # antes da janela
        b.item(dw, "DENTRO", cupom="DENTRO", data="2025-02-20", receita=700)  # quinta, na janela
        dw.commit()
        caminho, _ = fechamento.gerar(dw, MES, DIA, tmp_path / "q.xlsx", modelo=None)
        totais = {date(2025, 3, d): 100.0 * d for d in range(1, 16)}  # a L01, dia a dia
        totais[date(2025, 3, 7)] += 60
        totais[date(2025, 3, 8)] += 55
        totais[date(2025, 3, 15)] += 20000
        totais[date(2025, 2, 20)] = 700.0
        return load_workbook(caminho)[ABA_DADOS_POR_LOJA], totais

    def test_receita_media_por_dia_da_semana_na_janela_e_o_melhor_dia(self, quando_vende):
        ws, totais = quando_vende
        por_dia: dict[int, list[float]] = {}
        for dia, valor in totais.items():
            por_dia.setdefault(dia.weekday(), []).append(valor)
        linhas = _bloco_da_loja(ws, 8, 5)
        assert [x["Dia da semana"] for x in linhas] == [b.DIAS[k] for k in sorted(por_dia)]
        for linha, k in zip(linhas, sorted(por_dia), strict=True):
            assert linha["Receita média por dia"] == pytest.approx(
                sum(por_dia[k]) / len(por_dia[k])
            )
            assert linha["Participação na receita"] == pytest.approx(
                sum(por_dia[k]) / sum(totais.values())
            )
        melhor = max(por_dia, key=lambda k: sum(por_dia[k]) / len(por_dia[k]))
        assert [x["Dia da semana"] for x in linhas if x["Destaque"]] == [b.DIAS[melhor]]
        assert melhor == date(2025, 3, 15).weekday()  # o sábado da venda grande
        assert "Melhor dia" in {x["Destaque"] for x in linhas}

    def test_receita_media_por_faixa_horaria_e_a_melhor_faixa(self, quando_vende):
        ws, totais = quando_vende
        linhas = {x["Faixa horária"]: x for x in _bloco_da_loja(ws, 14, 5)}
        assert list(linhas) == ["Manhã", "Noite"]  # na ordem do dia
        dias_com_venda = len(totais)
        assert linhas["Noite"]["Receita média por dia"] == pytest.approx(20000 / dias_com_venda)
        manha = sum(totais.values()) - 20000
        assert linhas["Manhã"]["Receita média por dia"] == pytest.approx(manha / dias_com_venda)
        assert linhas["Noite"]["Destaque"] == "Melhor faixa" and linhas["Manhã"]["Destaque"] is None
        assert sum(x["Participação na receita"] for x in linhas.values()) == pytest.approx(1.0)


class TestPorVendedor:
    """Aba oculta "Dados por vendedor": cada número bate com uma consulta independente ao dw, só
    até o dia de posição e só com vendas concluídas (as canceladas entram só na taxa)."""

    @staticmethod
    def _dados(caminho):
        ws = load_workbook(caminho)[ABA_DADOS_POR_VENDEDOR]
        linhas = list(ws.iter_rows(values_only=True))
        return pd.DataFrame(linhas[1:], columns=linhas[0])

    @pytest.fixture
    def dados(self, dw, tmp_path):
        caminho, _ = fechamento.gerar(dw, MES, DIA, tmp_path / "f.xlsx", modelo=None)
        return self._dados(caminho)

    @staticmethod
    def _bloco(dados, cod, bloco):
        quadro = dados[(dados.cod_vendedor == cod) & (dados.bloco == bloco)]
        return quadro[quadro.ordem > 0].sort_values("ordem")

    def test_dia_a_dia_para_na_posicao_ignora_cancelada_e_conta_os_dias_com_venda(self, dw, dados):
        dias = self._bloco(dados, "V1", "dia_a_dia")
        datas = [d.date() for d in dias.col_1]
        assert datas == [date(2025, 3, d) for d in range(1, 16)]  # nada de 16 a 20
        venda = dict(zip(datas, dias.col_2, strict=True))
        assert venda[date(2025, 3, 5)] == 500  # a cancelada de 9999 ficou de fora
        assert venda[date(2025, 3, 7)] == 700 + 60 and venda[date(2025, 3, 8)] == 800 + 55
        meta_do_dia = _escalar(
            dw, "SELECT m.valor_meta_dia FROM dw.vw_meta_vendedor_diaria m JOIN dw.dim_vendedor d"
            " USING (sk_vendedor) WHERE d.cod_vendedor = 'V1' AND m.data = '2025-03-05'",
        )  # fmt: skip
        assert dict(zip(datas, dias.col_3, strict=True))[date(2025, 3, 5)] == meta_do_dia
        zero = dados[(dados.cod_vendedor == "V1") & (dados.bloco == "dia_a_dia")].iloc[0]
        bateu = sum(
            1 for v, m in zip(dias.col_2, dias.col_3, strict=True) if m is not None and v >= m
        )
        assert bateu >= 1  # o V1 vende 100 x dia contra uma meta diária pequena
        assert zero.titulo.endswith(f": {bateu} de 15 dias com venda")

    def test_evolucao_tem_o_mes_corrente_ate_o_dia_e_os_meses_anteriores(self, dw, dados):
        meses = {m.date(): (v, meta) for m, v, meta in self._bloco(dados, "V1", "evolucao")[
            ["col_1", "col_2", "col_3"]].itertuples(index=False)}  # fmt: skip
        assert meses[date(2025, 3, 1)][0] == 100 * sum(range(1, 16)) + 60 + 55  # sem 16 a 20
        assert meses[date(2024, 3, 1)] == (80 * sum(range(1, 16)), None)  # sem meta cadastrada
        assert date(2025, 4, 1) not in meses  # o item de abril fica depois da posição

    def test_comportamento_conta_a_cancelada_so_na_taxa(self, dw, dados):
        linhas = self._bloco(dados, "V1", "comportamento").itertuples()
        c = {r.col_1: (r.col_2, r.col_3) for r in linhas}
        receita, cupons, itens = 100 * sum(range(1, 16)) + 60 + 55, 17, 17
        assert c["Ticket médio"][0] == pytest.approx(receita / cupons)
        assert c["Itens por cupom"][0] == pytest.approx(itens / cupons)
        bruto = 100 * 15 + 100 + 100
        assert c["Desconto médio"][0] == pytest.approx((40 + 45) / bruto)
        assert c["Taxa de cancelamento"][0] == pytest.approx(1 / (cupons + 1))
        # a média da loja L01 é a do V1 (o V2 vende na L02)
        assert c["Ticket médio"][1] == pytest.approx(receita / cupons)

    def test_posicao_e_mix_e_produtos(self, dw, dados):
        c = dict(zip(self._bloco(dados, "V2", "cabecalho").col_1,
                     self._bloco(dados, "V2", "cabecalho").col_2, strict=True))  # fmt: skip
        assert c["Posição na rede"] == "2 de 2" and c["Posição na loja"] == "1 de 1"
        produtos = self._bloco(dados, "V1", "produtos")
        assert list(produtos.col_3) == [17]  # um produto só; a cancelada não entra
        mix = self._bloco(dados, "V1", "mix")
        assert list(mix.col_1) == ["Alimentos"] and list(mix.col_3) == [1.0]

    def test_ritmo_necessario_usa_os_dias_restantes_ponderados_pela_meta_diaria(self, dw, tmp_path):
        dw.execute(
            "UPDATE dw.fato_meta_vendedor SET valor_meta = 20000 WHERE sk_vendedor ="
            " (SELECT sk_vendedor FROM dw.dim_vendedor WHERE cod_vendedor = 'V2')"
        )
        dw.commit()
        caminho, _ = fechamento.gerar(dw, MES, DIA, tmp_path / "r.xlsx", modelo=None)
        linhas = {x["Vendedor"]: x for x in _tabela(load_workbook(caminho)[ABA_VENDEDORES])}
        restante = _escalar(
            dw, "SELECT sum(m.valor_meta_dia) FROM dw.vw_meta_vendedor_diaria m JOIN"
            " dw.dim_vendedor d USING (sk_vendedor) WHERE d.cod_vendedor = 'V2'"
            " AND m.data BETWEEN '2025-03-16' AND '2025-03-31'",
        )  # fmt: skip
        falta = 20000 - 50 * sum(range(1, 16))
        dias_medios = restante / (20000 / 31)  # os 16 dias que restam, em dias de meta média
        assert linhas["V2"]["Ritmo necessário por dia"] == pytest.approx(falta / dias_medios)
        assert 16 > dias_medios > 0  # março tem 31 dias; os 16 restantes não são dias "médios"
        assert linhas["V1"]["Ritmo necessário por dia"] == 0  # a meta do V1 já foi batida


class TestVendedoresAlertasPrevisao:
    def test_ranking_de_vendedores(self, dw, pasta):
        linhas = _tabela(pasta[ABA_VENDEDORES])
        assert [x["Vendedor"] for x in linhas] == ["V1", "V2"]
        assert [x["Posição na rede"] for x in linhas] == [1, 2]
        for x in linhas:
            esperado = _escalar(
                dw, "SELECT sum(receita_liquida) FROM dw.fato_vendas v JOIN dw.dim_tempo t USING"
                " (sk_tempo) JOIN dw.dim_vendedor d USING (sk_vendedor) WHERE d.cod_vendedor = %s"
                " AND status = 'Concluída' AND t.data BETWEEN '2025-03-01' AND '2025-03-15'",
                x["Vendedor"],
            )  # fmt: skip
            assert x["Acumulado do mês"] == pytest.approx(esperado)
            meta_ate_dia = _escalar(
                dw, "SELECT sum(m.valor_meta_dia) FROM dw.vw_meta_vendedor_diaria m JOIN"
                " dw.dim_vendedor d USING (sk_vendedor) WHERE d.cod_vendedor = %s"
                " AND m.data BETWEEN '2025-03-01' AND '2025-03-15'", x["Vendedor"],
            )  # fmt: skip
            assert x[TITULO_COBERTURA_ATE_O_DIA] == pytest.approx(esperado / meta_ate_dia)
        assert linhas[0]["Meta do mês"] == 5000

    def test_setor_principal_do_vendedor_ignora_cancelada_e_dias_depois_da_posicao(
        self, pasta_com_setor_do_vendedor
    ):
        linhas = {x["Vendedor"]: x for x in _tabela(pasta_com_setor_do_vendedor[ABA_VENDEDORES])}
        total_v1 = 100 * sum(range(1, 16)) + 60 + 55
        assert linhas["V1"]["Setor principal"] == "Alimentos"
        assert linhas["V1"]["% no setor principal"] == pytest.approx((total_v1 - 300) / total_v1)
        total_v2 = 50 * sum(range(1, 16))
        assert linhas["V2"]["Setor principal"] == "Eletro"
        assert linhas["V2"]["% no setor principal"] == pytest.approx((total_v2 - 300) / total_v2)

    def test_setor_de_lotacao_e_percentual_contam_so_o_que_foi_vendido_lotado_no_setor(
        self, dw, tmp_path, pasta_com_setor_do_vendedor
    ):
        # V1 foi lotado em Eletro até 08/03 e em Alimentos a partir de 09/03; V2 só em Alimentos
        for cod, setor, ini, fim in (
            ("V1", "Eletro", "2025-01-01", "2025-03-08"),
            ("V1", "Alimentos", "2025-03-09", None),
            ("V2", "Alimentos", "2025-01-01", None),
        ):
            dw.execute(
                "INSERT INTO dw.vendedor_setor_historico (sk_vendedor, setor, data_inicio,"
                " data_fim, motivo) VALUES ((SELECT sk_vendedor FROM dw.dim_vendedor"
                " WHERE cod_vendedor = %s), %s, %s, %s, 'Lotação inicial')",
                (cod, setor, ini, fim),
            )
        dw.commit()
        caminho, _ = fechamento.gerar(dw, MES, DIA, tmp_path / "lot.xlsx", modelo=None)
        linhas = {x["Vendedor"]: x for x in _tabela(load_workbook(caminho)[ABA_VENDEDORES])}
        vendas = dw.execute(
            "SELECT d.cod_vendedor, p.setor, t.data, v.receita_liquida FROM dw.fato_vendas v"
            " JOIN dw.dim_tempo t USING (sk_tempo) JOIN dw.dim_produto p USING (sk_produto)"
            " JOIN dw.dim_vendedor d USING (sk_vendedor) WHERE v.status = 'Concluída'"
            " AND t.data BETWEEN '2025-03-01' AND '2025-03-15'"
        ).fetchall()
        for cod, setor_hoje in (("V1", "Alimentos"), ("V2", "Alimentos")):
            total = sum(float(r) for c, _, _, r in vendas if c == cod)
            lotado = sum(
                float(r) for c, st, dia, r in vendas if c == cod and st == "Alimentos"
                and (cod == "V2" or dia.day >= 9)
            ) + sum(
                float(r) for c, st, dia, r in vendas
                if c == cod == "V1" and st == "Eletro" and dia.day <= 8
            )  # fmt: skip
            assert linhas[cod]["Setor de lotação"] == setor_hoje
            assert linhas[cod]["% no setor de lotação"] == pytest.approx(lotado / total)

    def test_so_alertas_independentes_abertos_e_do_mais_grave_ao_menos(self, dw, pasta):
        esperado = _escalar(
            dw, "SELECT count(*) FROM dw.alertas WHERE vigente AND independente"
            " AND status IN ('novo', 'em_analise')",
        )  # fmt: skip
        linhas = _tabela(pasta[ABA_ALERTAS])
        assert len(linhas) == esperado >= 1
        assert all(x["Status"] in ("Novo", "Em análise") for x in linhas)
        ordem = {"Crítica": 4, "Alta": 3, "Média": 2, "Baixa": 1}
        graus = [ordem[x["Severidade"]] for x in linhas]
        assert graus == sorted(graus, reverse=True)
        falsos = _escalar(dw, "SELECT count(*) FROM dw.alertas WHERE status = 'falso_positivo'")
        assert falsos == 1  # existe um falso positivo e ele ficou de fora

    def test_nenhum_alerta_depois_do_dia_de_posicao_e_um_cancelamento_por_vendedor(
        self, dw, tmp_path
    ):
        base = (
            "SELECT %s, %s, 'alta', %s, a.sk_loja, a.sk_vendedor, 10, 'x@1', %s, a.id_carga_origem,"
            " a.id_carga_ultima FROM dw.alertas a WHERE a.tipo_alerta = 'desconto_acima_limite'"
            " AND a.status = 'novo' LIMIT 1"
        )
        cabecalho = (
            "INSERT INTO dw.alertas (chave_alerta, tipo_alerta, severidade, sk_tempo, sk_loja,"
            " sk_vendedor, valor_envolvido, regra, explicacao, id_carga_origem, id_carga_ultima) "
        )
        cancelamento = "vendedor_cancelamento_alto"
        # janelas de jan, fev e mar (a de março termina depois do dia 15: não vale) + um desconto
        # com data depois do dia de posição
        for mes, sk in (("2025-01", 20250131), ("2025-02", 20250228), ("2025-03", 20250331)):
            dw.execute(cabecalho + base, (f"{cancelamento}|V1|{mes}", cancelamento, sk, "janela"))
        dw.execute(
            cabecalho + base,
            ("desconto_acima_limite|depois", "desconto_acima_limite", 20250320, "depois"),
        )
        dw.commit()
        caminho, _ = fechamento.gerar(dw, MES, DIA, tmp_path / "g.xlsx", modelo=None)
        linhas = _tabela(load_workbook(caminho)[ABA_ALERTAS])
        assert linhas and all(x["Data"].date() <= DIA for x in linhas)
        cancel = [x for x in linhas if x["Tipo"] == "Cancelamento alto por vendedor"]
        assert len(cancel) == 1
        assert cancel[0]["Data"].date() == date(2025, 2, 28)
        assert cancel[0]["Explicação"].endswith("2 janelas seguidas desde 01/2025")

    def test_previsao_mensal_e_diaria_da_execucao_mais_recente(self, dw, pasta):
        ws = pasta[ABA_PREVISAO]
        linhas = _tabela(ws)
        assert len([x for x in linhas if x["Loja"]]) == 2
        l01 = next(x for x in linhas if x["Loja"] == "L01")
        assert (
            l01["Previsto"] == 20000 and l01["Faixa baixa"] == 17000 and l01["Faixa alta"] == 23000
        )
        assert l01["Erro (WAPE) no backtest da loja"] == pytest.approx(0.1234)
        l02 = next(x for x in linhas if x["Loja"] == "L02")
        assert l02["Erro (WAPE) no backtest da loja"] is None
        assert ws.max_column == 7 and len(ws._charts) == 0
        diaria = pasta[ABA_PREVISAO_DIARIA]
        assert [diaria.cell(i, 2).value for i in range(2, 33)] == [1200.0] * 31  # 2 lojas x 600
        assert len(diaria._charts) == 1

    def test_faixa_diaria_da_rede_usa_a_calibrada_no_total_e_nao_a_soma_das_series(
        self, dw, tmp_path
    ):
        # sem linhas de nível "rede": cai na soma das faixas das séries (2 x 500 e 2 x 700)
        sem_rede = _tabela(
            load_workbook(fechamento.gerar(dw, MES, DIA, tmp_path / "a.xlsx", modelo=None)[0])[
                ABA_PREVISAO_DIARIA
            ]
        )
        assert (sem_rede[0]["Faixa baixa"], sem_rede[0]["Faixa alta"]) == (1000.0, 1400.0)
        dw.execute(
            "INSERT INTO dw.previsao_vendas (nivel, granularidade, data, sk_loja, setor,"
            " valor_previsto, valor_baixo, valor_alto, versao_modelo, treino_ate)"
            " SELECT 'rede', 'dia', make_date(2026, 1, d), NULL, NULL, 1200, 1100, 1350, 'x@1',"
            " '2025-03-15' FROM generate_series(1, 31) d"
        )
        dw.commit()
        com_rede = _tabela(
            load_workbook(fechamento.gerar(dw, MES, DIA, tmp_path / "b.xlsx", modelo=None)[0])[
                ABA_PREVISAO_DIARIA
            ]
        )
        assert len(com_rede) == 31  # as linhas de rede não duplicam os dias
        assert (com_rede[0]["Faixa baixa"], com_rede[0]["Faixa alta"]) == (1100.0, 1350.0)
        assert com_rede[0]["Previsto da rede"] == 1200.0

    def test_corte_depois_da_data_do_relatorio_e_ignorado(self, dw, tmp_path):
        # um corte gerado DEPOIS do dia do relatório (e mais recente no banco) não pode aparecer
        dw.execute(
            "INSERT INTO dw.previsao_vendas (granularidade, data, sk_loja, setor, valor_previsto,"
            " valor_baixo, valor_alto, versao_modelo, treino_ate)"
            " SELECT 'mes', '2025-05-01', sk_loja, 'Alimentos', 99999, 90000, 109999, 'z@1',"
            " '2025-04-30' FROM dw.dim_loja"
        )
        dw.commit()
        mensal = consultas.previsao_mensal(dw, DIA)
        assert set(mensal["treino_ate"]) == {date(2025, 3, 15)} and set(
            mensal["versao_modelo"]
        ) == {"x@1"}
        assert consultas.previsao_mensal(dw, date(2025, 4, 30))["treino_ate"].unique().tolist() == [
            date(2025, 4, 30)
        ]
        assert consultas.previsao_mensal(dw)["treino_ate"].unique().tolist() == [date(2025, 4, 30)]
        aba = load_workbook(fechamento.gerar(dw, MES, DIA, tmp_path / "c.xlsx", modelo=None)[0])
        linhas = [x for x in _tabela(aba[ABA_PREVISAO]) if x["Loja"]]
        assert {x["Previsto"] for x in linhas} == {20000}

    def test_sem_corte_ate_a_data_do_relatorio_as_abas_de_previsao_saem_vazias_com_aviso(
        self, dw, tmp_path, caplog
    ):
        antes_de_tudo = date(2025, 3, 14)  # o único corte é 15/03/2025
        assert consultas.previsao_mensal(dw, antes_de_tudo).empty
        assert consultas.previsao_diaria_da_rede(dw, antes_de_tudo).empty
        with caplog.at_level("WARNING", logger="src.relatorios.fechamento"):
            caminho, _ = fechamento.gerar(dw, MES, antes_de_tudo, tmp_path / "v.xlsx", modelo=None)
        assert "nenhum corte de previsão até 14/03/2025" in caplog.text
        pasta = load_workbook(caminho)
        assert [x for x in _tabela(pasta[ABA_PREVISAO]) if x["Loja"]] == []
        assert (
            pasta[ABA_PREVISAO_DIARIA].max_row == 1 and len(pasta[ABA_PREVISAO_DIARIA]._charts) == 0
        )


class TestComando:
    def test_gera_o_arquivo_padrao_e_informa_o_caminho(self, dw, tmp_path, capsys):
        saida = tmp_path / "sub" / "fechamento.xlsx"
        codigo = principal(
            ["fechamento", "--sem-macros", "--mes", "2025-03", "--dia", "2025-03-15",
             "--saida", str(saida)],
            conexao=dw, verificar_memoria=None,
        )  # fmt: skip
        assert codigo == 0 and saida.exists()
        texto = capsys.readouterr().out
        assert "fechamento de 03/2025 (posição 15/03/2025)" in texto and "sem macros" in texto

    def test_sem_argumentos_usa_o_ultimo_dia_com_venda(self, dw, tmp_path, capsys):
        saida = tmp_path / "f.xlsx"
        assert (
            principal(
                ["fechamento", "--sem-macros", "--saida", str(saida)],
                conexao=dw,
                verificar_memoria=None,
            )
            == 0
        )
        assert "posição 02/04/2025" in capsys.readouterr().out

    def test_dia_fora_do_mes_sai_com_2(self, dw, tmp_path):
        argumentos = ["fechamento", "--mes", "2025-03", "--dia", "2025-04-02"]
        assert principal(argumentos, conexao=dw, verificar_memoria=None) == 2

    def test_extensao_xlsm_sem_modelo_sai_com_2(self, dw, tmp_path):
        argumentos = ["fechamento", "--sem-macros", "--saida", str(tmp_path / "f.xlsm")]
        assert principal(argumentos, conexao=dw, verificar_memoria=None) == 2

    def test_data_invalida_sai_com_2(self, dw):
        assert principal(["fechamento", "--dia", "ontem"], conexao=dw, verificar_memoria=None) == 2


class TestModeloDeMacros:
    """Com um modelo .xlsm presente a saída é .xlsm; o modelo de verdade é testado em tests/vba."""

    @pytest.fixture
    def modelo(self, tmp_path):
        from openpyxl import Workbook

        caminho = tmp_path / "modelo.xlsm"
        Workbook().save(caminho)  # sem VBA de verdade: só exercita o caminho de código
        return caminho

    def test_com_modelo_a_saida_e_xlsm_e_traz_as_seis_abas(self, dw, tmp_path, modelo):
        destino, desempenho = fechamento.gerar(dw, MES, DIA, tmp_path / "f.xlsm", modelo=modelo)
        assert desempenho["com_macros"] is True
        assert load_workbook(destino, keep_vba=True).sheetnames[0] == ABA_RESUMO

    def test_caminho_padrao_depende_do_modelo(self, tmp_path):
        assert fechamento.caminho_padrao(MES, False, tmp_path).name == "fechamento_2025-03.xlsx"
        assert fechamento.caminho_padrao(MES, True, tmp_path).name == "fechamento_2025-03.xlsm"

    def test_com_modelo_saida_xlsx_e_recusada(self, dw, tmp_path, modelo):
        with pytest.raises(ValueError, match="xlsm"):
            fechamento.gerar(dw, MES, DIA, tmp_path / "f.xlsx", modelo=modelo)

    def test_modelo_inexistente_gera_xlsx_sem_macros(self, dw, tmp_path):
        destino, desempenho = fechamento.gerar(
            dw, MES, DIA, tmp_path / "f.xlsx", modelo=tmp_path / "nao_existe.xlsm"
        )
        assert desempenho["com_macros"] is False and destino.suffix == ".xlsx"
