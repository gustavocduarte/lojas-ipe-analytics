"""Fechamento do mês (vendas) e do ano (despesas): funções e views com dados escritos à mão."""

from datetime import date
from decimal import Decimal

import pytest

from tests.etl import base_alertas as b

pytestmark = pytest.mark.banco


@pytest.fixture
def base(banco_com_ddl):
    b.montar_base(banco_com_ddl, ano=2024)
    return banco_com_ddl


# --- despesas ------------------------------------------------------------------------------------
def _despesas_do_ano(
    con, centro="L01-TER", orcado=100, realizado_ate_jun=150, realizado_jul_dez=120
):
    for mes in range(1, 13):
        b.orcamento(con, centro, mes, orcado)
        valor = realizado_ate_jun if mes <= 6 else realizado_jul_dez
        b.despesa(con, f"{centro}-{mes}", valor, centro=centro, data=f"2024-{mes:02d}-10")


def _projecao(con, ref, centro="L01-TER"):
    colunas = [
        "ano", "orcado_ano", "orcado_ate_ref", "realizado_ate_ref", "fator", "orcado_restante",
        "previsto_restante", "projecao_ano", "desvio_vs_orcado", "realizado_ano_completo",
    ]  # fmt: skip
    linha = con.execute(
        f"SELECT {', '.join('f.' + c for c in colunas)} FROM dw.fn_projecao_despesas_ano(%s) f"
        " JOIN dw.dim_centro_custo c USING (sk_centro_custo) WHERE c.cod_centro_custo = %s",
        (ref, centro),
    ).fetchone()
    return dict(zip(colunas, linha, strict=True))


class TestDespesasAno:
    def test_corte_no_fim_do_semestre_aplica_o_fator_limitado_ao_teto(self, base):
        _despesas_do_ano(base)
        p = _projecao(base, date(2024, 6, 30))
        assert p["ano"] == 2024
        assert p["orcado_ano"] == 1200 and p["orcado_ate_ref"] == 600
        assert p["realizado_ate_ref"] == 900
        assert p["fator"] == Decimal("1.3")  # 900/600 = 1,5 acima do teto
        assert p["orcado_restante"] == 600 and p["previsto_restante"] == 780
        assert p["projecao_ano"] == 1680 and p["desvio_vs_orcado"] == 480
        assert p["realizado_ano_completo"] == 900 + 720

    def _normal_com_um_lancamento_estranho(self, con, valor=1500, **extra):
        _despesas_do_ano(con, realizado_ate_jun=100, realizado_jul_dez=100)
        b.despesa(con, "ESTRANHO-1", valor, data="2024-03-20", **extra)
        b.gerar(con)

    def test_valor_atipico_fica_fora_do_fator_mas_conta_no_realizado(self, base):
        self._normal_com_um_lancamento_estranho(base)
        assert b.alertas(base, "despesa_valor_atipico", vigentes=True)
        p = _projecao(base, date(2024, 6, 30))
        assert p["fator"] == 1  # sem o lançamento: 600/600 (com ele seria 2100/600, no teto)
        assert p["realizado_ate_ref"] == 2100
        assert p["projecao_ano"] == 2100 + 600

    def test_falso_positivo_volta_a_entrar_no_fator(self, base):
        self._normal_com_um_lancamento_estranho(base)
        sk = b.alertas(base, "despesa_valor_atipico")[0]["sk_alerta"]
        base.execute("CALL dw.tratar_alerta(%s, 'falso_positivo', 'teste', 'ok')", (sk,))
        assert _projecao(base, date(2024, 6, 30))["fator"] == Decimal("1.3")

    def test_alerta_que_deixou_de_valer_nao_exclui(self, base):
        self._normal_com_um_lancamento_estranho(base)
        base.execute("UPDATE dw.alertas SET vigente = FALSE")
        assert _projecao(base, date(2024, 6, 30))["fator"] == Decimal("1.3")

    def test_documento_repetido_exclui_so_a_copia(self, base):
        _despesas_do_ano(base, realizado_ate_jun=100, realizado_jul_dez=100)
        b.despesa(base, "L01-TER-3", 100, data="2024-03-11")  # a cópia do documento de março
        b.gerar(base)
        assert b.alertas(base, "despesa_documento_repetido", vigentes=True)
        p = _projecao(base, date(2024, 6, 30))
        assert p["fator"] == 1 and p["realizado_ate_ref"] == 700

    def test_centro_incompativel_tambem_fica_fora_do_fator(self, base):
        _despesas_do_ano(base, realizado_ate_jun=100, realizado_jul_dez=100)
        base.execute(  # L01-TER é do tipo Terceiros; folha de pagamento deveria ser Pessoal
            "INSERT INTO etl.excecoes_centro_descricao (descricao, tipo_esperado)"
            " VALUES ('Folha de pagamento', 'Pessoal')"
        )
        b.despesa(base, "FOLHA-1", 500, descricao="Folha de pagamento", data="2024-03-20")
        b.gerar(base)
        assert b.alertas(base, "despesa_centro_incompativel", vigentes=True)
        p = _projecao(base, date(2024, 6, 30))
        assert p["fator"] == 1 and p["realizado_ate_ref"] == 1100

    def test_fator_dentro_dos_limites_e_usado_como_esta(self, base):
        _despesas_do_ano(base, realizado_ate_jun=110)
        p = _projecao(base, date(2024, 6, 30))
        assert p["fator"] == pytest.approx(Decimal("1.1"))
        assert p["projecao_ano"] == pytest.approx(Decimal(660 + 600 * 1.1))

    def test_fator_abaixo_do_piso_sobe_para_o_piso(self, base):
        _despesas_do_ano(base, realizado_ate_jun=50)
        assert _projecao(base, date(2024, 6, 30))["fator"] == Decimal("0.7")

    def test_corte_no_meio_do_mes_reparte_o_orcado_do_mes_pelos_dias(self, base):
        _despesas_do_ano(base)  # lançamento de junho no dia 10: entra no realizado até 15/06
        p = _projecao(base, date(2024, 6, 15))
        assert p["orcado_ate_ref"] == 550  # 5 meses x 100 + metade de junho
        assert p["orcado_restante"] == 650
        assert p["realizado_ate_ref"] == 900

    def test_corte_no_fim_do_ano_nao_projeta_nada_a_mais(self, base):
        _despesas_do_ano(base)
        p = _projecao(base, date(2024, 12, 31))
        assert p["orcado_restante"] == 0 and p["previsto_restante"] == 0
        assert p["projecao_ano"] == p["realizado_ate_ref"] == p["realizado_ano_completo"]

    def test_centro_sem_orcamento_projeta_so_o_realizado(self, base):
        b.despesa(base, "SO-REAL", 200, centro="COR-TI", data="2024-02-02")
        p = _projecao(base, date(2024, 6, 30), "COR-TI")
        assert p["fator"] == 1 and p["projecao_ano"] == 200 and p["orcado_ano"] == 0

    def test_centro_sem_despesa_projeta_o_orcado_restante(self, base):
        for mes in range(1, 13):
            b.orcamento(base, "COR-TI", mes, 100)
        p = _projecao(base, date(2024, 6, 30), "COR-TI")
        assert p["realizado_ate_ref"] == 0 and p["fator"] == Decimal("0.7")
        assert p["projecao_ano"] == pytest.approx(Decimal(600 * 0.7))

    def test_outro_ano_nao_entra(self, base):
        _despesas_do_ano(base)
        assert (
            base.execute(
                "SELECT count(*) FROM dw.fn_projecao_despesas_ano(%s)", (date(2023, 6, 30),)
            ).fetchone()[0]
            == 0
        )


# --- vendas ---------------------------------------------------------------------------------------
def _meta_marco(con, valor):
    con.execute(
        "INSERT INTO dw.fato_meta_vendas (sk_tempo, sk_loja, setor, valor_meta)"
        " SELECT 20240301, sk_loja, 'Alimentos', %s FROM dw.dim_loja WHERE cod_loja = 'L01'",
        (valor,),
    )


def _vender_ate(con, ultimo_dia, valor=100):
    for dia in range(1, ultimo_dia + 1):
        b.item(con, f"V{dia}", cupom=f"C{dia}", data=f"2024-03-{dia:02d}", receita=valor)


def _prever_resto(con, treino_ate, versao="x@1", valor=50, baixo=None, alto=None, gerado=None):
    baixo = valor * 0.6 if baixo is None else baixo
    alto = valor * 1.6 if alto is None else alto
    primeiro = treino_ate.day + 1
    for dia in range(primeiro, 32):
        con.execute(
            "INSERT INTO dw.previsao_vendas (granularidade, data, sk_loja, setor, valor_previsto,"
            " valor_baixo, valor_alto, versao_modelo, treino_ate, gerado_em)"
            " SELECT 'dia', make_date(2024, 3, %s), sk_loja, 'Alimentos', %s, %s, %s, %s, %s,"
            " COALESCE(%s, now()) FROM dw.dim_loja WHERE cod_loja = 'L01'",
            (dia, valor, baixo, alto, versao, treino_ate, gerado),
        )


COLUNAS_FECHAMENTO = (
    "realizado_ate_ref, previsto_restante, projecao_fechamento, faixa_baixa, faixa_alta,"
    " meta_mes, cobertura_projetada, dias_restantes, tem_previsao"
)


def _fechamento(con, ref):
    return con.execute(
        f"SELECT {COLUNAS_FECHAMENTO} FROM dw.fn_projecao_fechamento_mes(%s) WHERE sk_loja = 1",
        (ref,),
    ).fetchall()


class TestFechamentoDoMes:
    def test_realizado_mais_previsto_dos_dias_restantes(self, base):
        _vender_ate(base, 10)
        _meta_marco(base, 5000)
        _prever_resto(base, date(2024, 3, 10), baixo=30, alto=80)
        (linha,) = _fechamento(base, date(2024, 3, 10))
        realizado, restante, projecao, baixo, alto, meta, cobertura, dias, tem = linha
        assert realizado == 1000 and restante == 21 * 50 and projecao == 2050
        assert baixo == 1000 + 21 * 30 and alto == 1000 + 21 * 80
        assert meta == 5000 and cobertura == Decimal("2050") / 5000 and dias == 21 and tem

    def test_sem_previsao_para_o_corte_a_projecao_fica_nula(self, base):
        _vender_ate(base, 10)
        _meta_marco(base, 5000)
        _prever_resto(base, date(2024, 3, 9))  # previsão de outro corte não vale
        (linha,) = _fechamento(base, date(2024, 3, 10))
        assert linha[0] == 1000 and linha[1] is None and linha[2] is None and linha[8] is False

    def test_no_ultimo_dia_do_mes_nao_ha_o_que_prever(self, base):
        _vender_ate(base, 31)
        _meta_marco(base, 5000)
        (linha,) = _fechamento(base, date(2024, 3, 31))
        assert linha[1] == 0 and linha[2] == 3100 and linha[7] == 0 and linha[8] is True

    def test_usa_a_previsao_gerada_por_ultimo_quando_ha_duas_versoes(self, base):
        _vender_ate(base, 10)
        _prever_resto(base, date(2024, 3, 10), "velha@1", valor=10, gerado="2024-03-10 08:00")
        _prever_resto(base, date(2024, 3, 10), "nova@1", valor=60, gerado="2024-03-10 09:00")
        (linha,) = _fechamento(base, date(2024, 3, 10))
        assert linha[1] == 21 * 60

    def test_serie_so_com_previsao_ou_so_com_meta_tambem_aparece(self, base):
        _meta_marco(base, 5000)
        _prever_resto(base, date(2024, 3, 10))
        (linha,) = _fechamento(base, date(2024, 3, 10))
        assert linha[0] == 0 and linha[2] == 21 * 50 and linha[5] == 5000

    def test_vendas_canceladas_nao_entram_no_realizado(self, base):
        _vender_ate(base, 2)
        b.item(base, "CAN", cupom="CC", data="2024-03-02", receita=900, status="Cancelada")
        (linha,) = _fechamento(base, date(2024, 3, 2))
        assert linha[0] == 200

    def test_view_usa_o_ultimo_dia_com_venda_como_referencia(self, base):
        _vender_ate(base, 10)
        _meta_marco(base, 5000)
        _prever_resto(base, date(2024, 3, 10))
        assert base.execute("SELECT dw.data_referencia()").fetchone()[0] == date(2024, 3, 10)
        linha = base.execute(
            f"SELECT {COLUNAS_FECHAMENTO} FROM dw.vw_projecao_fechamento_mes WHERE sk_loja = 1"
        ).fetchone()
        assert linha[2] == 2050

    def test_view_de_despesas_usa_a_mesma_referencia(self, base):
        _vender_ate(base, 31)
        _despesas_do_ano(base)
        linha = base.execute(
            "SELECT projecao_ano FROM dw.vw_projecao_despesas_ano v"
            " JOIN dw.dim_centro_custo c USING (sk_centro_custo)"
            " WHERE c.cod_centro_custo = 'L01-TER'"
        ).fetchone()
        assert linha[0] > 0
