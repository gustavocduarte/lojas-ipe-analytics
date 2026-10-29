"""Base dos alertas: tabelas, parâmetros e formatação brasileira dos textos."""

from decimal import Decimal

import psycopg
import pytest

pytestmark = pytest.mark.banco


def _um(con, consulta, *parametros):
    return con.execute(consulta, parametros).fetchone()[0]


class TestFormatacao:
    @pytest.mark.parametrize(
        ("valor", "esperado"),
        [
            (Decimal("0"), "R$ 0,00"),
            (Decimal("7.5"), "R$ 7,50"),
            (Decimal("1234.5"), "R$ 1.234,50"),
            (Decimal("1234567.891"), "R$ 1.234.567,89"),
            (Decimal("-10"), "-R$ 10,00"),
            (Decimal("0.005"), "R$ 0,01"),
        ],
    )
    def test_reais(self, banco_compartilhado, valor, esperado):
        assert _um(banco_compartilhado, "SELECT etl.fmt_brl(%s)", valor) == esperado

    @pytest.mark.parametrize(
        ("fracao", "casas", "esperado"),
        [
            (Decimal("0.352"), 1, "35,2%"),
            (Decimal("0.18"), 0, "18%"),
            (Decimal("0.18"), 1, "18,0%"),
            (Decimal("0.3"), 1, "30,0%"),
            (Decimal("1.0612"), 1, "106,1%"),
            (Decimal("0.0333"), 2, "3,33%"),
        ],
    )
    def test_percentuais(self, banco_compartilhado, fracao, casas, esperado):
        assert _um(banco_compartilhado, "SELECT etl.fmt_pct(%s, %s)", fracao, casas) == esperado

    @pytest.mark.parametrize(
        ("valor", "casas", "esperado"),
        [
            (Decimal("1696"), 0, "1.696"),
            (Decimal("10.64"), 1, "10,6"),
            (Decimal("5"), 0, "5"),
            (Decimal("1234567.5"), 1, "1.234.567,5"),
        ],
    )
    def test_numeros(self, banco_compartilhado, valor, casas, esperado):
        assert _um(banco_compartilhado, "SELECT etl.fmt_num(%s, %s)", valor, casas) == esperado

    def test_data(self, banco_compartilhado):
        assert _um(banco_compartilhado, "SELECT etl.fmt_data(DATE '2024-03-09')") == "09/03/2024"


class TestParametros:
    def test_le_o_valor_da_tabela(self, banco_compartilhado):
        assert _um(banco_compartilhado, "SELECT etl.parametro('desconto_maximo')") == Decimal(
            "0.18"
        )

    def test_parametro_inexistente_falha_alto(self, banco_com_ddl):
        with pytest.raises(psycopg.errors.RaiseException, match="parâmetro de negócio inexistente"):
            banco_com_ddl.execute("SELECT etl.parametro('nao_existe')")

    def test_mudar_o_parametro_muda_o_valor(self, banco_com_ddl):
        banco_com_ddl.execute(
            "UPDATE etl.parametros_negocio SET valor = 0.25 WHERE chave = 'desconto_maximo'"
        )
        assert _um(banco_com_ddl, "SELECT etl.parametro('desconto_maximo')") == Decimal("0.25")


class TestEstrutura:
    def test_tabelas_de_alerta_existem_e_regras_estao_registradas(self, banco_compartilhado):
        regras = banco_compartilhado.execute(
            "SELECT tipo_alerta, versao, ordem, ativa FROM etl.regras_alerta ORDER BY ordem"
        ).fetchall()
        assert regras[0] == ("desconto_acima_limite", 1, 10, True)
        tipos = {
            t for (t,) in banco_compartilhado.execute("SELECT tipo_alerta FROM dw.dim_tipo_alerta")
        }
        assert {r[0] for r in regras} <= tipos

    def test_status_e_severidade_invalidos_sao_recusados(self, banco_com_ddl):
        con = banco_com_ddl
        con.execute("INSERT INTO etl.cargas (fonte, modo) VALUES ('t', 'completo')")
        base = (
            "INSERT INTO dw.alertas (chave_alerta, tipo_alerta, severidade, regra, explicacao,"
            " id_carga_origem, id_carga_ultima, status) VALUES ('c', 'desconto_acima_limite', %s,"
            " 'r', 'x', 1, 1, %s)"
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            con.execute(base, ("urgente", "novo"))
        con.rollback()
        con.execute("INSERT INTO etl.cargas (fonte, modo) VALUES ('t', 'completo')")
        with pytest.raises(psycopg.errors.CheckViolation):
            con.execute(base, ("alta", "ignorado"))

    def test_chave_do_alerta_e_unica(self, banco_com_ddl):
        con = banco_com_ddl
        con.execute("INSERT INTO etl.cargas (fonte, modo) VALUES ('t', 'completo')")
        comando = (
            "INSERT INTO dw.alertas (chave_alerta, tipo_alerta, severidade, regra, explicacao,"
            " id_carga_origem, id_carga_ultima) VALUES ('mesma', 'desconto_acima_limite', 'baixa',"
            " 'r', 'x', 1, 1)"
        )
        con.execute(comando)
        with pytest.raises(psycopg.errors.UniqueViolation):
            con.execute(comando)


class TestCalibracao:
    def test_faixas_de_valor_calibradas_com_os_dados_reais(self, banco_compartilhado):
        valores = dict(
            banco_compartilhado.execute(
                "SELECT chave, valor FROM etl.parametros_negocio WHERE chave IN"
                " ('fora_horario_valor_alto', 'cupom_duplicado_valor_alto',"
                "  'documento_repetido_valor_alto')"
            ).fetchall()
        )
        assert valores == {
            "fora_horario_valor_alto": 250,
            "cupom_duplicado_valor_alto": 250,
            "documento_repetido_valor_alto": 1600,
        }
