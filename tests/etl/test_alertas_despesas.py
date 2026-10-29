"""Regras de alerta de despesas: dispara, não dispara, limites, severidade, texto e parâmetros."""

from datetime import date

import pytest

from tests.etl import base_alertas as b

pytestmark = pytest.mark.banco

FERIADOS = {date(2024, 4, 21): "Tiradentes"}


@pytest.fixture
def base(banco_com_ddl):
    b.montar_base(banco_com_ddl, feriados=FERIADOS)
    return banco_com_ddl


def _param(con, chave, valor):
    con.execute("UPDATE etl.parametros_negocio SET valor = %s WHERE chave = %s", (valor, chave))


def _unico(con, tipo):
    achados = b.alertas(con, tipo)
    assert len(achados) == 1, achados
    return achados[0]


class TestDocumentoRepetido:
    def test_documento_lancado_duas_vezes(self, base):
        b.despesa(base, "DOC1", 679.79, centro="L01-TER", data="2024-03-05")
        b.despesa(base, "DOC1", 679.79, centro="L01-TER", data="2024-03-05")
        b.despesa(base, "DOC2", 100, data="2024-03-06")
        b.gerar(base)
        a = _unico(base, "despesa_documento_repetido")
        assert a["chave_alerta"] == "despesa_documento_repetido|DOC1"
        assert a["explicacao"] == (
            "documento DOC1 lançado 2 vezes (R$ 679,79 a mais; "
            "primeiro lançamento no centro L01-TER)"
        )
        assert float(a["valor_envolvido"]) == 679.79 and a["severidade"] == "media"
        assert a["sk_centro_custo"] and a["sk_loja"] and a["sk_tempo"] == 20240305

    def test_tres_vezes_soma_as_repeticoes(self, base):
        for _ in range(3):
            b.despesa(base, "DOC1", 6000)
        b.gerar(base)
        a = _unico(base, "despesa_documento_repetido")
        assert float(a["valor_envolvido"]) == 12000.0 and a["severidade"] == "alta"
        assert "lançado 3 vezes" in a["explicacao"]

    def test_documentos_distintos_nao_alertam(self, base):
        b.despesa(base, "DOC1", 100)
        b.despesa(base, "DOC2", 100)
        b.gerar(base)
        assert b.alertas(base, "despesa_documento_repetido") == []


class TestFimDeSemanaOuFeriado:
    def test_sabado_domingo_e_feriado(self, base):
        b.despesa(base, "D1", 100, data="2024-03-09")  # sábado
        b.despesa(base, "D2", 200, data="2024-03-10")  # domingo
        b.despesa(base, "D3", 300, data="2024-04-21")  # Tiradentes (domingo e feriado)
        b.despesa(base, "D4", 400, data="2024-03-11")  # segunda: normal
        b.gerar(base)
        achados = {a["valor_envolvido"]: a for a in b.alertas(base, "despesa_fim_semana_feriado")}
        assert sorted(float(v) for v in achados) == [100.0, 200.0, 300.0]
        textos = {float(v): a["explicacao"] for v, a in achados.items()}
        assert textos[100.0] == "lançamento de R$ 100,00 em 09/03/2024 (sábado), no centro L01-TER"
        assert textos[200.0].endswith("(domingo), no centro L01-TER")
        assert textos[300.0] == (
            "lançamento de R$ 300,00 em 21/04/2024, feriado nacional (Tiradentes), "
            "no centro L01-TER"
        )
        assert {a["severidade"] for a in achados.values()} == {"baixa"}

    def test_dia_util_nao_alerta_e_chave_usa_arquivo_e_linha(self, base):
        b.despesa(base, "D1", 100, data="2024-03-05")
        b.despesa(base, "D2", 100, data="2024-03-09", linha=77)
        b.gerar(base)
        (a,) = b.alertas(base, "despesa_fim_semana_feriado")
        assert a["chave_alerta"] == "despesa_fim_semana_feriado|despesas.csv|77"


class TestValorAtipico:
    def _centro_normal(self, base, n=9, valor=100.0):
        for i in range(n):
            b.despesa(base, f"N{i}", valor, data=f"2024-03-{5 + i:02d}")

    def test_lancamento_muito_acima_da_mediana(self, base):
        self._centro_normal(base)
        b.despesa(base, "GRANDE", 900, data="2024-03-20")  # mediana 100 -> 9 vezes
        b.gerar(base)
        a = _unico(base, "despesa_valor_atipico")
        assert a["explicacao"] == (
            "lançamento de R$ 900,00 equivale a 9,0 vezes a mediana (R$ 100,00) dos lançamentos "
            "do centro L01-TER"
        )
        assert a["severidade"] == "media" and float(a["valor_envolvido"]) == 900.0

    def test_exatamente_no_multiplo_nao_alerta_e_acima_de_dez_vezes_e_alta(self, base):
        self._centro_normal(base)
        b.despesa(base, "NO_LIMITE", 500, data="2024-03-20")  # 5x: não passa de 5x
        b.despesa(base, "ENORME", 1500, data="2024-03-21")  # 15x
        b.gerar(base)
        a = _unico(base, "despesa_valor_atipico")
        assert a["chave_alerta"].startswith("despesa_valor_atipico|despesas.csv|")
        assert a["severidade"] == "alta" and float(a["valor_envolvido"]) == 1500.0

    def test_multiplo_e_parametro(self, base):
        self._centro_normal(base)
        b.despesa(base, "G", 300, data="2024-03-20")
        b.gerar(base)
        assert b.alertas(base, "despesa_valor_atipico", vigentes=True) == []
        _param(base, "valor_atipico_multiplo", 2)
        b.gerar(base)
        assert len(b.alertas(base, "despesa_valor_atipico", vigentes=True)) == 1

    def test_mediana_e_por_centro(self, base):
        self._centro_normal(base)  # L01-TER mediana 100
        for i in range(9):
            b.despesa(base, f"P{i}", 5000, centro="L01-PES", data=f"2024-03-{5 + i:02d}")
        b.gerar(base)
        assert b.alertas(base, "despesa_valor_atipico") == []


def _lancar(base, descricao, centro, quantidade, prefixo):
    for i in range(quantidade):
        b.despesa(base, f"{prefixo}{i}", 100, centro=centro, descricao=descricao, data="2024-03-05")


class TestCentroIncompativel:
    def test_lancamento_em_centro_de_outro_tipo(self, base):
        _lancar(base, "Folha de pagamento", "L01-PES", 40, "F")
        b.despesa(base, "ERRADO", 321.5, centro="L01-TER", descricao="Folha de pagamento")
        b.gerar(base)
        a = _unico(base, "despesa_centro_incompativel")
        assert a["explicacao"] == (
            '"Folha de pagamento" lançada no centro L01-TER, do tipo Terceiros; 97,6% dos 41 '
            "lançamentos com essa descrição estão em centros Pessoal; valor R$ 321,50"
        )
        assert a["severidade"] == "media" and float(a["valor_envolvido"]) == 321.5
        assert (
            a["detalhe"]["tipo_esperado"] == "Pessoal"
            and a["detalhe"]["origem_da_regra"] == "aprendido"
        )

    def test_so_aprende_com_o_minimo_de_ocorrencias(self, base):
        _lancar(base, "Folha de pagamento", "L01-PES", 20, "F")
        b.despesa(base, "ERRADO", 100, centro="L01-TER", descricao="Folha de pagamento")
        b.gerar(base)
        assert b.alertas(base, "despesa_centro_incompativel") == []  # 21 < 30
        _param(base, "centro_incompativel_min_ocorrencias", 20)
        b.gerar(base)
        assert len(b.alertas(base, "despesa_centro_incompativel", vigentes=True)) == 1

    @pytest.mark.parametrize(("certos", "alerta"), [(36, True), (35, False)])
    def test_participacao_minima_de_90_por_cento(self, base, certos, alerta):
        _lancar(base, "Material de escritório", "L01-DIS", certos, "C")
        _lancar(base, "Material de escritório", "L01-TER", 40 - certos, "E")
        b.gerar(base)
        achados = b.alertas(base, "despesa_centro_incompativel")
        assert len(achados) == (40 - certos if alerta else 0)

    def test_os_proprios_erros_entram_no_aprendizado_e_ainda_sao_detectados(self, base):
        _lancar(base, "Folha de pagamento", "L01-PES", 388, "F")
        _lancar(base, "Folha de pagamento", "L01-TER", 12, "E")  # 3% contaminando
        b.gerar(base)
        assert len(b.alertas(base, "despesa_centro_incompativel")) == 12

    def test_descricao_espalhada_entre_tipos_nao_gera_alerta(self, base):
        _lancar(base, "Serviços diversos", "L01-PES", 20, "A")
        _lancar(base, "Serviços diversos", "L01-TER", 20, "B")
        b.gerar(base)
        assert b.alertas(base, "despesa_centro_incompativel") == []

    def test_nao_informado_nao_e_descricao(self, base):
        _lancar(base, "NAO INFORMADO", "L01-PES", 40, "A")
        _lancar(base, "NAO INFORMADO", "L01-TER", 2, "B")
        b.gerar(base)
        assert b.alertas(base, "despesa_centro_incompativel") == []

    def test_tabela_de_excecoes_vale_mais_que_o_aprendido(self, base):
        _lancar(
            base, "Licença de software", "L01-PES", 3, "L"
        )  # poucos lançamentos: nada aprendido
        base.execute(
            "INSERT INTO etl.excecoes_centro_descricao VALUES ('Licença de software', 'Terceiros')"
        )
        b.gerar(base)
        achados = b.alertas(base, "despesa_centro_incompativel")
        assert len(achados) == 3
        assert achados[0]["explicacao"].startswith(
            '"Licença de software" deve ser lançada em centros Terceiros (regra cadastrada)'
        )
        # a exceção também derruba o que seria aprendido ao contrário
        _lancar(base, "Folha de pagamento", "L01-PES", 40, "F")
        base.execute(
            "INSERT INTO etl.excecoes_centro_descricao VALUES ('Folha de pagamento', 'Terceiros')"
        )
        b.gerar(base)
        assert len(b.alertas(base, "despesa_centro_incompativel", vigentes=True)) == 43
