"""Regras de alerta de vendas: dispara, não dispara, limites, severidade, texto e parâmetros."""

import pytest

from tests.etl import base_alertas as b

pytestmark = pytest.mark.banco


@pytest.fixture
def base(banco_com_ddl):
    b.montar_base(banco_com_ddl)
    return banco_com_ddl


def _param(con, chave, valor):
    con.execute("UPDATE etl.parametros_negocio SET valor = %s WHERE chave = %s", (valor, chave))


def _unico(con, tipo):
    achados = b.alertas(con, tipo)
    assert len(achados) == 1, achados
    return achados[0]


class TestMargemNegativa:
    def test_alerta_com_prejuizo_e_texto(self, base):
        b.item(base, "VD1", preco=100, custo=130)  # receita 100 < custo 130
        b.gerar(base)
        a = _unico(base, "margem_negativa")
        assert a["chave_alerta"] == "margem_negativa|VD1"
        assert a["explicacao"] == (
            "item P1 vendido por R$ 100,00, abaixo do custo de R$ 130,00 "
            "(prejuízo de R$ 30,00, 23,1% do custo; cupom C1)"
        )
        assert float(a["valor_envolvido"]) == 30.0 and a["severidade"] == "media"

    def test_venda_no_custo_ou_acima_nao_alerta(self, base):
        b.item(base, "VD1", preco=100, custo=100)  # margem zero
        b.item(base, "VD2", cupom="C2", preco=100, custo=60)
        b.gerar(base)
        assert b.alertas(base, "margem_negativa") == []

    @pytest.mark.parametrize(
        ("custo", "severidade"), [(110, "baixa"), (117.6, "baixa"), (120, "media"), (143, "alta")]
    )
    def test_severidade_pelo_prejuizo_sobre_o_custo(self, base, custo, severidade):
        b.item(base, "VD1", preco=100, custo=custo)
        b.gerar(base)
        assert _unico(base, "margem_negativa")["severidade"] == severidade


class TestVendaForaDoHorario:
    @pytest.mark.parametrize(
        ("hora", "alerta"),
        [("07:59:59", True), ("08:00:00", False), ("19:59:59", False), ("20:00:00", True),
         ("03:12:00", True), ("12:00:00", False)],
    )  # fmt: skip
    def test_limites_do_horario(self, base, hora, alerta):
        b.item(base, "VD1", hora=hora)
        b.gerar(base)
        assert len(b.alertas(base, "venda_fora_horario")) == (1 if alerta else 0)

    def test_texto_e_um_alerta_por_cupom(self, base):
        b.item(base, "VD1", cupom="C9", numero_item=1, hora="03:12:00", data="2024-03-05")
        b.item(base, "VD2", cupom="C9", numero_item=2, hora="03:12:00", data="2024-03-05")
        b.gerar(base)
        a = _unico(base, "venda_fora_horario")
        assert a["chave_alerta"] == "venda_fora_horario|C9"
        assert a["explicacao"] == (
            "cupom C9 registrado às 03:12, fora do horário da loja (das 08:00 às 20:00, "
            "terça-feira); total R$ 200,00"
        )
        assert a["severidade"] == "media" and float(a["valor_envolvido"]) == 200.0

    def test_cupom_grande_e_alta(self, base):
        b.item(base, "VD1", hora="22:00:00", preco=600, custo=300)
        b.gerar(base)
        assert _unico(base, "venda_fora_horario")["severidade"] == "alta"

    def test_loja_sem_horario_cadastrado_nao_alerta(self, base):
        b.item(base, "VD1", loja="L02", vendedor="V2", hora="03:00:00")
        b.gerar(base)
        assert b.alertas(base, "venda_fora_horario") == []


class TestCupomDuplicado:
    def test_itens_repetidos_geram_um_alerta_por_cupom(self, base):
        b.item(base, "VD1", cupom="C1", numero_item=1)
        b.item(base, "VD2", cupom="C1", numero_item=2, preco=50, custo=30)
        b.item(base, "VD3", cupom="C1", numero_item=1)  # cópias
        b.item(base, "VD4", cupom="C1", numero_item=2, preco=50, custo=30)
        b.gerar(base)
        a = _unico(base, "cupom_duplicado")
        assert a["chave_alerta"] == "cupom_duplicado|C1"
        assert a["explicacao"] == (
            "cupom C1 lançado em duplicidade: 2 linha(s) repetida(s), R$ 150,00 a mais no total"
        )
        assert float(a["valor_envolvido"]) == 150.0 and a["severidade"] == "media"

    def test_cupom_normal_nao_alerta(self, base):
        b.item(base, "VD1", cupom="C1", numero_item=1)
        b.item(base, "VD2", cupom="C1", numero_item=2)
        b.gerar(base)
        assert b.alertas(base, "cupom_duplicado") == []

    def test_valor_repetido_alto_e_severidade_alta(self, base):
        b.item(base, "VD1", cupom="C1", preco=1200, custo=500)
        b.item(base, "VD2", cupom="C1", preco=1200, custo=500)
        b.gerar(base)
        assert _unico(base, "cupom_duplicado")["severidade"] == "alta"


class TestVendedorInativo:
    def test_antes_da_admissao_e_depois_do_desligamento(self, base):
        base.execute(
            "UPDATE dw.dim_vendedor SET data_admissao = '2024-03-10' WHERE cod_vendedor = 'V1'"
        )
        base.execute(
            "UPDATE dw.dim_vendedor SET data_desligamento = '2024-03-04' WHERE cod_vendedor = 'V2'"
        )
        b.item(base, "VD1", cupom="C1", data="2024-03-05")  # V1 ainda não admitido
        b.item(
            base, "VD2", cupom="C2", data="2024-03-05", loja="L02", vendedor="V2"
        )  # V2 desligado
        b.item(base, "VD3", cupom="C3", data="2024-03-10")  # V1 no dia da admissão: ok
        b.item(
            base, "VD4", cupom="C4", data="2024-03-04", loja="L02", vendedor="V2"
        )  # no dia do desligamento: ok
        b.gerar(base)
        achados = {a["chave_alerta"]: a for a in b.alertas(base, "venda_vendedor_inativo")}
        assert set(achados) == {"venda_vendedor_inativo|C1", "venda_vendedor_inativo|C2"}
        assert achados["venda_vendedor_inativo|C1"]["explicacao"] == (
            "cupom C1 vendido em 05/03/2024 antes da admissão do vendedor V1 "
            "(admitido em 10/03/2024); total R$ 100,00"
        )
        assert (
            "depois do desligamento do vendedor V2 (desligado em 04/03/2024)"
            in (achados["venda_vendedor_inativo|C2"]["explicacao"])
        )
        assert {a["severidade"] for a in achados.values()} == {"critica"}

    def test_vendedor_ativo_nao_alerta(self, base):
        b.item(base, "VD1")
        b.gerar(base)
        assert b.alertas(base, "venda_vendedor_inativo") == []


def _cupons(con, vendedor, loja, ano, mes, quantidade, cancelados, prefixo):
    """`quantidade` cupons de um item no mês; os primeiros `cancelados` são cancelados."""
    for n in range(quantidade):
        b.item(
            con, f"{prefixo}-{ano}{mes:02d}-{n}", cupom=f"{prefixo}-{ano}{mes:02d}-{n}",
            data=f"{ano}-{mes:02d}-{1 + n % 28:02d}", vendedor=vendedor, loja=loja,
            status="Cancelada" if n < cancelados else "Concluída",
        )  # fmt: skip


class TestCancelamentoAlto:
    """V1: 12 cupons por mês; V2 (a rede normal): 200 por mês com 3% cancelados. Janela de 3 meses.
    Com `c` cancelados de V1 por mês, a taxa de V1 é c/12 e a da rede (3c + 18)/636."""

    def _cenario(self, base, cancelados_v1=6, meses=(1, 2, 3)):
        _param(base, "cancelamento_min_cupons", 30)
        for mes in meses:
            _cupons(base, "V1", "L01", 2024, mes, 12, cancelados_v1, "A")
            _cupons(base, "V2", "L02", 2024, mes, 200, 6, "B")
        base.commit()

    def test_alerta_so_quando_a_janela_tem_o_minimo_de_cupons(self, base):
        self._cenario(base)
        b.gerar(base)
        achados = b.alertas(base, "vendedor_cancelamento_alto")
        # janelas: jan 12 cupons, fev 24 (< 30), mar 36 -> só março
        assert [a["chave_alerta"] for a in achados] == ["vendedor_cancelamento_alto|V1|2024-03"]
        a = achados[0]
        assert a["sk_tempo"] == 20240331 and a["sk_vendedor"] and a["sk_loja"]
        assert float(a["valor_envolvido"]) == 18 * 100.0
        assert a["explicacao"] == (
            "50,0% de cancelamento (18 de 36 cupons) de 01/2024 a 03/2024, "
            "8,8 vezes a taxa da rede (5,7%)"
        )
        assert a["severidade"] == "alta"
        assert a["detalhe"]["janela_meses"] == 3 and a["detalhe"]["cupons"] == 36

    def test_um_alerta_por_vendedor_e_mes_final_para_ver_a_evolucao(self, base):
        self._cenario(base, meses=(1, 2, 3, 4))
        b.gerar(base)
        chaves = [a["chave_alerta"] for a in b.alertas(base, "vendedor_cancelamento_alto")]
        assert chaves == [
            "vendedor_cancelamento_alto|V1|2024-03",
            "vendedor_cancelamento_alto|V1|2024-04",
        ]

    def test_taxa_normal_nao_alerta(self, base):
        self._cenario(base, cancelados_v1=0)
        _cupons(base, "V1", "L01", 2024, 5, 0, 0, "Z")
        b.gerar(base)
        assert b.alertas(base, "vendedor_cancelamento_alto") == []

    def test_so_a_taxa_acima_do_multiplo_da_rede_conta(self, base):
        self._cenario(base, cancelados_v1=1)  # 8,3% contra rede ~3,6%: abaixo de 3x
        b.gerar(base)
        assert b.alertas(base, "vendedor_cancelamento_alto") == []

    def test_minimo_de_cupons_e_multiplo_sao_parametros(self, base):
        self._cenario(base)
        _param(base, "cancelamento_min_cupons", 20)
        b.gerar(base)
        assert len(b.alertas(base, "vendedor_cancelamento_alto", vigentes=True)) == 2  # fev e mar
        _param(base, "cancelamento_min_cupons", 100)
        b.gerar(base)
        assert b.alertas(base, "vendedor_cancelamento_alto", vigentes=True) == []
        _param(base, "cancelamento_min_cupons", 30)
        _param(base, "cancelamento_multiplo", 20)
        b.gerar(base)
        assert b.alertas(base, "vendedor_cancelamento_alto", vigentes=True) == []

    def test_tamanho_da_janela_e_parametro(self, base):
        self._cenario(base)
        _param(base, "cancelamento_janela_meses", 1)
        _param(base, "cancelamento_min_cupons", 10)
        b.gerar(base)
        achados = b.alertas(base, "vendedor_cancelamento_alto", vigentes=True)
        assert len(achados) == 3
        assert "(6 de 12 cupons) de 01/2024 a 01/2024" in achados[0]["explicacao"]

    @pytest.mark.parametrize(
        ("cancelados", "severidade"), [(3, "media"), (4, "alta"), (8, "critica")]
    )
    def test_severidade_pelo_multiplo_da_taxa_da_rede(self, base, cancelados, severidade):
        self._cenario(base, cancelados_v1=cancelados)
        b.gerar(base)
        (a,) = b.alertas(base, "vendedor_cancelamento_alto")
        assert a["severidade"] == severidade
