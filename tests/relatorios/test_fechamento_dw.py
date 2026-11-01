"""O .xlsx de fechamento precisa bater com consultas independentes ao dw (precisa de PostgreSQL)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from openpyxl import load_workbook

from src.relatorios import fechamento
from src.relatorios.__main__ import principal
from src.relatorios.planilha import (
    ABA_ALERTAS,
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
    # previsão (como se tivesse sido gerada em 31/12/2025)
    con.execute(
        "INSERT INTO dw.previsao_vendas (granularidade, data, sk_loja, setor, valor_previsto,"
        " valor_baixo, valor_alto, versao_modelo, treino_ate)"
        " SELECT 'mes', '2026-01-01', sk_loja, 'Alimentos', 20000, 17000, 23000, 'x@1',"
        " '2025-12-31'"
        " FROM dw.dim_loja"
    )
    con.execute(
        "INSERT INTO dw.previsao_vendas (granularidade, data, sk_loja, setor, valor_previsto,"
        " valor_baixo, valor_alto, versao_modelo, treino_ate)"
        " SELECT 'dia', make_date(2026, 1, d), sk_loja, 'Alimentos', 600, 500, 700, 'x@1',"
        " '2025-12-31' FROM dw.dim_loja, generate_series(1, 31) d"
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
            " '2025-12-31' FROM generate_series(1, 31) d"
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
