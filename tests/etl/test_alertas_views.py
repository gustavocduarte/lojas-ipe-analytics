"""Views da página Alertas do Power BI: colunas, rótulos, contagens e tendência mensal."""

import pytest

from src import banco
from tests.etl import base_alertas as b

pytestmark = pytest.mark.banco

VIEWS = (
    "vw_alertas_detalhe",
    "vw_alertas_por_tipo",
    "vw_alertas_por_loja",
    "vw_alertas_tendencia_mensal",
    "vw_alertas_resumo",
)


@pytest.fixture
def base(banco_com_ddl):
    b.montar_base(banco_com_ddl)
    return banco_com_ddl


@pytest.fixture
def com_alertas(base):
    # descontos: março (alta e baixa) e maio (baixa); margem negativa em março
    b.item(base, "VD1", cupom="C1", data="2024-03-05", desconto=32)
    b.item(base, "VD2", cupom="C2", data="2024-03-12", desconto=20)
    b.item(base, "VD3", cupom="C3", data="2024-05-07", desconto=19)
    b.item(base, "VD4", cupom="C4", data="2024-03-08", preco=100, custo=130)
    # centro de loja: estouro causado por um valor atípico (alerta derivado)
    b.orcamento(base, "L01-TER", 3, 1000)
    for i in range(9):
        b.despesa(
            base, f"N{i}", 100, data=f"2024-03-{11 + i:02d}"
        )  # 11 a 19: dias úteis e fim de semana
    b.despesa(base, "GRANDE", 1500, data="2024-03-25")
    # centro corporativo: estouro independente, sem loja
    b.orcamento(base, "COR-TI", 5, 1000)
    b.despesa(base, "TI1", 2500, centro="COR-TI", data="2024-05-06")
    b.gerar(base)
    return base


def _um(con, consulta, *parametros):
    return con.execute(consulta, parametros).fetchone()[0]


def _colunas(con, view):
    return [
        c
        for (c,) in con.execute(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_schema = 'dw' AND table_name = %s ORDER BY ordinal_position",
            (view,),
        )
    ]


class TestEstrutura:
    def test_views_sao_reaplicaveis_e_existem(self, base):
        banco.aplicar_views(base)
        banco.aplicar_views(base)
        existentes = {
            v
            for (v,) in base.execute(
                "SELECT table_name FROM information_schema.views WHERE table_schema = 'dw'"
            )
        }
        assert set(VIEWS) <= existentes

    def test_views_funcionam_sem_nenhum_alerta(self, base):
        assert _um(base, "SELECT count(*) FROM dw.vw_alertas_detalhe") == 0
        assert _um(base, "SELECT count(*) FROM dw.vw_alertas_tendencia_mensal") == 0
        resumo = base.execute("SELECT * FROM dw.vw_alertas_resumo").fetchone()
        assert all(valor == 0 for valor in resumo)

    def test_colunas_do_detalhe_para_o_power_bi(self, base):
        colunas = _colunas(base, "vw_alertas_detalhe")
        for esperada in (
            "tipo_alerta", "nome_tipo_alerta", "severidade_nome", "severidade_ordem", "data_alerta",
            "cod_loja", "nome_loja", "uf", "cod_vendedor", "cod_centro_custo", "valor_envolvido",
            "explicacao", "status_nome", "conta_no_painel", "origem_do_alerta",
            "alerta_origem_principal", "id_carga_origem",
        ):  # fmt: skip
            assert esperada in colunas, esperada


class TestDetalhe:
    def test_uma_linha_por_alerta_com_rotulos_em_portugues(self, com_alertas):
        con = com_alertas
        assert _um(con, "SELECT count(*) FROM dw.vw_alertas_detalhe") == _um(
            con, "SELECT count(*) FROM dw.alertas"
        )
        linha = con.execute(
            "SELECT severidade_nome, severidade_ordem, status_nome, nome_loja, uf, cod_vendedor,"
            " nome_tipo_alerta, data_alerta, categoria FROM dw.vw_alertas_detalhe"
            " WHERE chave_alerta = 'desconto_acima_limite|VD1'"
        ).fetchone()
        assert linha[:7] == ("Alta", 3, "Novo", "Ipê L01", "SP", "V1", "Desconto acima do limite")
        assert str(linha[7]) == "2024-03-05" and linha[8] == "vendas"

    def test_alerta_corporativo_nao_tem_loja(self, com_alertas):
        linha = com_alertas.execute(
            "SELECT cod_loja, nome_loja, cod_centro_custo FROM dw.vw_alertas_detalhe"
            " WHERE chave_alerta = 'despesa_acima_orcado|COR-TI|2024-05'"
        ).fetchone()
        assert linha == (None, None, "COR-TI")

    def test_derivado_aponta_para_a_origem(self, com_alertas):
        linha = com_alertas.execute(
            "SELECT origem_do_alerta, conta_no_painel, qtd_alertas_de_origem,"
            " alerta_origem_principal, severidade FROM dw.vw_alertas_detalhe"
            " WHERE chave_alerta = 'despesa_acima_orcado|L01-TER|2024-03'"
        ).fetchone()
        assert linha[0] == "Derivado" and linha[1] is False and linha[2] == 1
        assert linha[3].startswith("despesa_valor_atipico|despesas.csv|") and linha[4] == "baixa"

    def test_status_tratado_aparece_no_detalhe(self, com_alertas):
        con = com_alertas
        sk = _um(con, "SELECT sk_alerta FROM dw.alertas WHERE chave_alerta = 'margem_negativa|VD4'")
        con.execute("CALL dw.tratar_alerta(%s, 'resolvido', 'ana', 'ok')", (sk,))
        linha = con.execute(
            "SELECT status_nome, tratado_por, observacao FROM dw.vw_alertas_detalhe"
            " WHERE chave_alerta = 'margem_negativa|VD4'"
        ).fetchone()
        assert linha == ("Resolvido", "ana", "ok")


class TestAgregacoes:
    def test_por_tipo_so_tem_vigentes_e_separa_derivados(self, com_alertas):
        con = com_alertas
        con.execute(
            "UPDATE dw.fato_vendas SET desconto = 0, receita_liquida = 100"
            " WHERE id_venda_erp = 'VD3'"
        )
        b.gerar(con)  # VD3 deixa de vigorar
        total = _um(con, "SELECT sum(quantidade) FROM dw.vw_alertas_por_tipo")
        assert total == _um(con, "SELECT count(*) FROM dw.alertas WHERE vigente")
        independentes = _um(
            con, "SELECT sum(quantidade) FROM dw.vw_alertas_por_tipo WHERE independente"
        )
        assert independentes == _um(
            con, "SELECT count(*) FROM dw.alertas WHERE vigente AND independente"
        )
        assert (
            _um(
                con,
                "SELECT sum(quantidade) FROM dw.vw_alertas_por_tipo"
                " WHERE tipo_alerta = 'desconto_acima_limite'",
            )
            == 2
        )

    def test_por_loja_ignora_derivados_e_agrupa_corporativo(self, com_alertas):
        con = com_alertas
        assert _um(con, "SELECT sum(quantidade) FROM dw.vw_alertas_por_loja") == _um(
            con, "SELECT count(*) FROM dw.alertas WHERE vigente AND independente"
        )
        corporativo = con.execute(
            "SELECT cod_loja, nome_loja, tipo_alerta, quantidade, valor_envolvido_total"
            " FROM dw.vw_alertas_por_loja WHERE cod_loja = 'CORP'"
        ).fetchall()
        assert corporativo == [("CORP", "Corporativo (sem loja)", "despesa_acima_orcado", 1, 1500)]
        assert (
            _um(con, "SELECT sum(quantidade) FROM dw.vw_alertas_por_loja WHERE cod_loja = 'L01'")
            > 0
        )

    def test_tendencia_preenche_meses_sem_alerta_e_calcula_media_movel(self, com_alertas):
        con = com_alertas
        meses = [
            m
            for (m,) in con.execute(
                "SELECT DISTINCT mes_inicio FROM dw.vw_alertas_tendencia_mensal ORDER BY 1"
            )
        ]
        assert [str(m) for m in meses] == ["2024-03-01", "2024-04-01", "2024-05-01"]
        serie = dict(
            con.execute(
                "SELECT mes_inicio, quantidade FROM dw.vw_alertas_tendencia_mensal"
                " WHERE tipo_alerta = 'desconto_acima_limite' ORDER BY 1"
            ).fetchall()
        )
        assert [serie[m] for m in meses] == [2, 0, 1]
        medias = [
            float(x)
            for (x,) in con.execute(
                "SELECT media_movel_3m FROM dw.vw_alertas_tendencia_mensal"
                " WHERE tipo_alerta = 'desconto_acima_limite' ORDER BY mes_inicio"
            )
        ]
        assert medias == [2.0, 1.0, 1.0]  # (2) ; (2+0)/2 ; (2+0+1)/3
        # um registro por mês e tipo, inclusive tipos sem nenhum alerta
        assert _um(con, "SELECT count(*) FROM dw.vw_alertas_tendencia_mensal") == 3 * _um(
            con, "SELECT count(*) FROM dw.dim_tipo_alerta"
        )

    def test_resumo_bate_com_a_tabela(self, com_alertas):
        con = com_alertas
        sk = _um(con, "SELECT sk_alerta FROM dw.alertas WHERE chave_alerta = 'margem_negativa|VD4'")
        con.execute("CALL dw.tratar_alerta(%s, 'falso_positivo', 'ana')", (sk,))
        (painel, novos, analise, resolvidos, falsos, derivados, sumiram, crit, altos, medios,
         baixos, valor) = con.execute("SELECT * FROM dw.vw_alertas_resumo").fetchone()  # fmt: skip
        esperado = _um(con, "SELECT count(*) FROM dw.alertas WHERE vigente AND independente")
        assert painel == esperado
        assert (falsos, resolvidos, analise) == (1, 0, 0) and novos == esperado - 1
        assert derivados == 1 and sumiram == 0
        assert crit + altos + medios + baixos == esperado
        assert float(valor) == float(
            _um(con, "SELECT sum(valor_envolvido) FROM dw.alertas WHERE vigente AND independente")
        )
