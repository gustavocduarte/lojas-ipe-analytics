"""Motor de alertas: idempotência, preservação do status, vigência e histórico.
Usa a regra de desconto como exemplo (dados escritos à mão, sem ETL)."""

import psycopg
import pytest

from tests.etl import base_alertas as b

pytestmark = pytest.mark.banco


@pytest.fixture
def base(banco_com_ddl):
    b.montar_base(banco_com_ddl)
    return banco_com_ddl


def _desconto_alto(con, id_venda="VD1", pct=0.32, **extra):
    b.item(con, id_venda, desconto=100 * pct, **extra)


class TestRegraDeDesconto:
    def test_gera_alerta_com_explicacao_legivel_e_vinculos(self, base):
        _desconto_alto(base)
        id_carga = b.gerar(base)
        (a,) = b.alertas(base)
        assert a["chave_alerta"] == "desconto_acima_limite|VD1"
        assert a["explicacao"] == "desconto de 32,0% acima do limite de 18% (item P1, cupom C1)"
        assert (a["severidade"], a["status"], a["vigente"], a["independente"]) == (
            "alta",
            "novo",
            True,
            True,
        )
        assert float(a["valor_envolvido"]) == 32.0
        assert a["sk_tempo"] == 20240305 and a["sk_loja"] and a["sk_vendedor"]
        assert a["sk_centro_custo"] is None
        assert a["regra"] == "desconto_acima_limite@1"
        assert a["detalhe"]["percentual"] == 0.32 and a["detalhe"]["limite"] == 0.18
        assert a["id_carga_origem"] == a["id_carga_ultima"] == id_carga

    def test_dentro_do_limite_ou_da_tolerancia_nao_alerta(self, base):
        b.item(base, "VD1", desconto=18.0)  # exatamente o limite
        b.item(base, "VD2", cupom="C2", desconto=18.01)  # dentro da tolerância de R$ 0,01
        b.item(base, "VD3", cupom="C3", desconto=0.0)
        b.gerar(base)
        assert b.alertas(base) == []

    @pytest.mark.parametrize(
        ("pct", "severidade"),
        [(0.20, "baixa"), (0.23, "baixa"), (0.2301, "media"), (0.28, "media"), (0.2801, "alta")],
    )
    def test_faixas_de_severidade_vem_dos_parametros(self, base, pct, severidade):
        _desconto_alto(base, pct=pct)
        b.gerar(base)
        assert b.alertas(base)[0]["severidade"] == severidade

    def test_mudar_parametro_muda_o_resultado(self, base):
        _desconto_alto(base, pct=0.20)
        b.gerar(base)
        assert len(b.alertas(base, vigentes=True)) == 1
        base.execute(
            "UPDATE etl.parametros_negocio SET valor = 0.25 WHERE chave = 'desconto_maximo'"
        )
        b.gerar(base)
        (a,) = b.alertas(base)
        assert a["vigente"] is False
        base.execute(
            "UPDATE etl.parametros_negocio SET valor = 0.10 WHERE chave = 'desconto_maximo'"
        )
        b.gerar(base)
        (a,) = b.alertas(base)
        assert a["vigente"] is True
        assert "limite de 10%" in a["explicacao"]


class TestIdempotencia:
    def test_rodar_de_novo_nao_duplica_nem_altera(self, base):
        _desconto_alto(base, "VD1")
        _desconto_alto(base, "VD2", cupom="C2")
        b.gerar(base)
        antes = b.alertas(base)
        b.gerar(base)
        b.gerar(base)
        assert b.alertas(base) == antes  # nem atualizado_em muda: nada foi reescrito

    def test_contagens_por_carga(self, base):
        _desconto_alto(base, "VD1")
        primeira = b.gerar(base)
        _desconto_alto(base, "VD2", cupom="C2")
        segunda = b.gerar(base)
        linhas = base.execute(
            "SELECT id_carga, detectados, novos, atualizados, inalterados, reativados,"
            " deixaram_de_vigorar FROM etl.carga_alertas ORDER BY id_carga"
        ).fetchall()
        assert linhas == [(primeira, 1, 1, 0, 0, 0, 0), (segunda, 2, 1, 0, 1, 0, 0)]

    def test_valor_que_muda_atualiza_o_texto_e_a_severidade_sem_tocar_no_status(self, base):
        _desconto_alto(base, pct=0.20)
        primeira = b.gerar(base)
        (a,) = b.alertas(base)
        base.execute("CALL dw.tratar_alerta(%s, 'em_analise', 'ana', 'olhando')", (a["sk_alerta"],))
        base.execute("UPDATE dw.fato_vendas SET desconto = 40, receita_liquida = 60")
        segunda = b.gerar(base)
        (novo,) = b.alertas(base)
        assert novo["explicacao"].startswith("desconto de 40,0%")
        assert novo["severidade"] == "alta"
        assert (novo["status"], novo["tratado_por"], novo["observacao"]) == (
            "em_analise",
            "ana",
            "olhando",
        )
        assert (novo["id_carga_origem"], novo["id_carga_ultima"]) == (primeira, segunda)
        assert base.execute(
            "SELECT atualizados FROM etl.carga_alertas WHERE id_carga = %s", (segunda,)
        ).fetchone() == (1,)


class TestTratamentoDeAlertas:
    @pytest.mark.parametrize("status", ["resolvido", "falso_positivo"])
    def test_alerta_tratado_nao_volta_como_novo(self, base, status):
        _desconto_alto(base)
        b.gerar(base)
        (a,) = b.alertas(base)
        base.execute("CALL dw.tratar_alerta(%s, %s, 'ana', 'conferido')", (a["sk_alerta"], status))
        for _ in range(2):
            b.gerar(base)
        (depois,) = b.alertas(base)
        assert depois["status"] == status and depois["sk_alerta"] == a["sk_alerta"]
        assert base.execute("SELECT count(*) FROM dw.alertas").fetchone()[0] == 1

    def test_alerta_que_some_fica_nao_vigente_e_ao_voltar_mantem_o_status(self, base):
        _desconto_alto(base)
        b.gerar(base)
        (a,) = b.alertas(base)
        base.execute("CALL dw.tratar_alerta(%s, 'falso_positivo', 'ana')", (a["sk_alerta"],))
        base.execute("UPDATE dw.fato_vendas SET desconto = 0, receita_liquida = 100")
        segunda = b.gerar(base)
        (sumiu,) = b.alertas(base)
        assert sumiu["vigente"] is False and sumiu["status"] == "falso_positivo"
        assert sumiu["id_carga_ultima"] == segunda
        assert base.execute(
            "SELECT deixaram_de_vigorar FROM etl.carga_alertas WHERE id_carga = %s", (segunda,)
        ).fetchone() == (1,)

        base.execute("UPDATE dw.fato_vendas SET desconto = 32, receita_liquida = 68")
        terceira = b.gerar(base)
        (voltou,) = b.alertas(base)
        assert voltou["vigente"] is True and voltou["status"] == "falso_positivo"
        assert base.execute(
            "SELECT reativados, atualizados FROM etl.carga_alertas WHERE id_carga = %s", (terceira,)
        ).fetchone() == (1, 0)

    def test_regra_desligada_torna_os_alertas_dela_nao_vigentes(self, base):
        _desconto_alto(base)
        b.gerar(base)
        base.execute(
            "UPDATE etl.regras_alerta SET ativa = FALSE WHERE tipo_alerta = 'desconto_acima_limite'"
        )
        b.gerar(base)
        assert b.alertas(base)[0]["vigente"] is False

    def test_tratar_alerta_grava_historico(self, base):
        _desconto_alto(base)
        b.gerar(base)
        (a,) = b.alertas(base)
        base.execute("CALL dw.tratar_alerta(%s, 'em_analise', 'ana', 'abri')", (a["sk_alerta"],))
        base.execute("CALL dw.tratar_alerta(%s, 'resolvido', 'bruno', 'ok')", (a["sk_alerta"],))
        historico = base.execute(
            "SELECT status_anterior, status_novo, usuario, observacao FROM dw.alerta_historico"
            " ORDER BY sk_historico"
        ).fetchall()
        assert historico == [
            ("novo", "em_analise", "ana", "abri"),
            ("em_analise", "resolvido", "bruno", "ok"),
        ]
        assert b.alertas(base)[0]["status_em"] is not None

    @pytest.mark.parametrize(
        ("argumentos", "mensagem"),
        [
            (("ignorado", "ana"), "status inválido"),
            (("resolvido", ""), "informe quem"),
            (("novo", "ana"), "já está com o status"),
        ],
    )
    def test_tratar_alerta_valida_os_argumentos(self, base, argumentos, mensagem):
        _desconto_alto(base)
        b.gerar(base)
        (a,) = b.alertas(base)
        with pytest.raises(psycopg.errors.RaiseException, match=mensagem):
            base.execute("CALL dw.tratar_alerta(%s, %s, %s)", (a["sk_alerta"], *argumentos))

    def test_alerta_inexistente(self, base):
        with pytest.raises(psycopg.errors.RaiseException, match="alerta inexistente"):
            base.execute("CALL dw.tratar_alerta(999, 'resolvido', 'ana')")
