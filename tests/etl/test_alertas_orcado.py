"""Despesa acima do orçado e alertas derivados (ligados aos alertas de origem)."""

import pytest

from tests.etl import base_alertas as b

pytestmark = pytest.mark.banco


@pytest.fixture
def base(banco_com_ddl):
    b.montar_base(banco_com_ddl)
    return banco_com_ddl


def _lancamentos(con, quantidade, valor, prefixo="N", centro="L01-TER"):
    for i in range(quantidade):
        b.despesa(con, f"{prefixo}{i}", valor, centro=centro, data=f"2024-03-{5 + i % 20:02d}")


def _orcado(alertas_):
    return [a for a in alertas_ if a["tipo_alerta"] == "despesa_acima_orcado"]


def _vinculos(con):
    return con.execute(
        "SELECT d.chave_alerta, o.chave_alerta, v.contribuicao FROM dw.alerta_vinculos v"
        " JOIN dw.alertas d ON d.sk_alerta = v.sk_alerta_derivado"
        " JOIN dw.alertas o ON o.sk_alerta = v.sk_alerta_origem ORDER BY 1, 2"
    ).fetchall()


class TestDespesaAcimaDoOrcado:
    def test_estouro_sem_origem_e_independente(self, base):
        b.orcamento(base, "L01-TER", 3, 1000)
        _lancamentos(base, 20, 150)  # 3.000 = 3x o orçado, tudo uniforme (sem atípico)
        b.gerar(base)
        (a,) = b.alertas(base, "despesa_acima_orcado")
        assert a["chave_alerta"] == "despesa_acima_orcado|L01-TER|2024-03"
        assert (a["independente"], a["severidade"]) == (True, "critica")
        assert a["explicacao"] == (
            "realizado de R$ 3.000,00 em 03/2024 no centro L01-TER = 3,0 vezes o orçado de "
            "R$ 1.000,00 (excesso de R$ 2.000,00)"
        )
        assert float(a["valor_envolvido"]) == 2000.0 and a["sk_tempo"] == 20240301
        assert a["detalhe"]["origens"] == 0 and _vinculos(base) == []

    @pytest.mark.parametrize(
        ("realizado", "severidade"),
        [(1300, None), (1310, "media"), (1600, "alta"), (1999, "alta"), (2000, "critica")],
    )
    def test_limites_e_faixas_de_severidade(self, base, realizado, severidade):
        b.orcamento(base, "L01-TER", 3, 1000)
        b.despesa(base, "D1", realizado, data="2024-03-05")
        b.gerar(base)
        achados = b.alertas(base, "despesa_acima_orcado")
        if severidade is None:
            assert achados == []
        else:
            assert achados[0]["severidade"] == severidade

    def test_sem_orcamento_ou_dentro_do_orcado_nao_alerta(self, base):
        b.despesa(base, "D1", 99999, centro="L01-PES", data="2024-03-05")  # sem orçamento
        b.orcamento(base, "L01-TER", 3, 1000)
        b.despesa(base, "D2", 900, data="2024-03-05")
        b.gerar(base)
        assert b.alertas(base, "despesa_acima_orcado") == []

    def test_centro_corporativo_sem_loja(self, base):
        b.orcamento(base, "COR-TI", 3, 1000)
        b.despesa(base, "D1", 2500, centro="COR-TI", data="2024-03-05")
        b.gerar(base)
        (a,) = b.alertas(base, "despesa_acima_orcado")
        assert a["sk_loja"] is None and a["sk_centro_custo"]

    def test_multiplo_e_parametro(self, base):
        b.orcamento(base, "L01-TER", 3, 1000)
        b.despesa(base, "D1", 1500, data="2024-03-05")
        b.gerar(base)
        assert len(b.alertas(base, "despesa_acima_orcado", vigentes=True)) == 1
        base.execute(
            "UPDATE etl.parametros_negocio SET valor = 2 WHERE chave = 'orcado_excesso_multiplo'"
        )
        b.gerar(base)
        assert b.alertas(base, "despesa_acima_orcado", vigentes=True) == []


class TestAlertasDerivados:
    def _mes_com_atipico(self, base, atipico=1500):
        b.orcamento(base, "L01-TER", 3, 1000)
        _lancamentos(base, 9, 100)  # 900
        b.despesa(base, "GRANDE", atipico, data="2024-03-25")  # mediana 100 -> atípico

    def test_estouro_causado_por_valor_atipico_e_derivado(self, base):
        self._mes_com_atipico(base)
        b.gerar(base)
        (orc,) = b.alertas(base, "despesa_acima_orcado")
        (atipico,) = b.alertas(base, "despesa_valor_atipico")
        assert orc["independente"] is False and orc["severidade"] == "baixa"
        assert "explicado por 1 alerta(s) de origem (R$ 1.400,00)" in orc["explicacao"]
        assert "sem eles seria R$ 1.000,00" in orc["explicacao"]
        assert atipico["independente"] is True
        assert _vinculos(base) == [(orc["chave_alerta"], atipico["chave_alerta"], 1400)]

    def test_estouro_maior_que_as_origens_e_independente_com_vinculo_parcial(self, base):
        self._mes_com_atipico(base)
        _lancamentos(base, 25, 100, prefixo="X")  # +2.500 que nenhuma regra explica
        b.gerar(base)
        (orc,) = b.alertas(base, "despesa_acima_orcado")
        assert orc["independente"] is True and orc["severidade"] == "critica"
        assert len(_vinculos(base)) == 1  # a origem continua ligada, em parte

    def test_documento_repetido_explica_o_estouro(self, base):
        b.orcamento(base, "L01-TER", 3, 1000)
        _lancamentos(base, 9, 100)
        b.despesa(base, "DUP", 300, data="2024-03-26")
        b.despesa(base, "DUP", 300, data="2024-03-26")  # realizado 1.500; repetido 300
        b.gerar(base)
        (orc,) = b.alertas(base, "despesa_acima_orcado")
        (doc,) = b.alertas(base, "despesa_documento_repetido")
        assert orc["independente"] is False
        assert _vinculos(base) == [(orc["chave_alerta"], doc["chave_alerta"], 300)]

    def test_lancamento_atipico_e_incompativel_ao_mesmo_tempo_conta_uma_vez(self, base):
        base.execute(
            "UPDATE etl.parametros_negocio SET valor = 3"
            " WHERE chave = 'centro_incompativel_min_ocorrencias'"
        )
        b.orcamento(base, "L01-TER", 3, 1000)
        _lancamentos(base, 15, 100)  # 1.500
        for i in range(9):  # "Folha" é lançada em centros Pessoal em 9 de 10 vezes
            b.despesa(base, f"F{i}", 50, centro="L01-PES", descricao="Folha", data="2024-03-05")
        b.despesa(
            base, "ERRADO", 700, descricao="Folha", data="2024-03-26"
        )  # atípico e incompatível
        b.gerar(base)
        assert len(b.alertas(base, "despesa_valor_atipico")) == 1
        assert len(b.alertas(base, "despesa_centro_incompativel")) == 1
        (orc,) = b.alertas(base, "despesa_acima_orcado")
        # realizado 2.200; excesso 1.200. Contado uma vez (700): sobram 1.500 > 1.300: independente.
        # Contado duas vezes (600 + 700) sobrariam 900 e viraria derivado por engano.
        assert orc["independente"] is True
        assert orc["detalhe"]["explicado_por_origens"] == 700

    def test_falso_positivo_da_origem_torna_o_estouro_independente(self, base):
        self._mes_com_atipico(base)
        b.gerar(base)
        (atipico,) = b.alertas(base, "despesa_valor_atipico")
        base.execute(
            "CALL dw.tratar_alerta(%s, 'falso_positivo', 'ana', 'compra legítima')",
            (atipico["sk_alerta"],),
        )
        b.gerar(base)
        (orc,) = b.alertas(base, "despesa_acima_orcado")
        assert orc["independente"] is True and orc["severidade"] == "critica"
        assert _vinculos(base) == []

    def test_origem_resolvida_continua_explicando(self, base):
        self._mes_com_atipico(base)
        b.gerar(base)
        (atipico,) = b.alertas(base, "despesa_valor_atipico")
        base.execute("CALL dw.tratar_alerta(%s, 'resolvido', 'ana')", (atipico["sk_alerta"],))
        b.gerar(base)
        (orc,) = b.alertas(base, "despesa_acima_orcado")
        assert orc["independente"] is False and len(_vinculos(base)) == 1

    def test_vinculos_nao_duplicam_ao_rodar_de_novo(self, base):
        self._mes_com_atipico(base)
        b.gerar(base)
        antes = _vinculos(base)
        b.gerar(base)
        b.gerar(base)
        assert _vinculos(base) == antes

    def test_origem_de_outro_mes_ou_de_outro_centro_nao_explica(self, base):
        b.orcamento(base, "L01-TER", 3, 1000)
        _lancamentos(base, 20, 150)  # março: 3.000, uniforme (nada atípico)
        _lancamentos(base, 9, 100, prefixo="A")
        b.despesa(base, "ABR", 5000, data="2024-04-10")  # atípico, mas em abril
        _lancamentos(base, 9, 100, prefixo="P", centro="L01-PES")
        b.despesa(base, "PES", 2500, centro="L01-PES", data="2024-03-10")  # atípico em outro centro
        b.gerar(base)
        achados = [a for a in b.alertas(base, "despesa_acima_orcado")]
        assert len(achados) == 1 and achados[0]["independente"] is True
        assert _vinculos(base) == []
