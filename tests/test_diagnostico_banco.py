"""Diagnóstico da loja no dw: parâmetros, referência da rede (sem loja) e indicadores."""

from datetime import date

import pytest

from src import config, diagnostico
from tests.etl import base_alertas as b

pytestmark = pytest.mark.banco

CHAVES = {
    "diag_cupons_queda": 0.05,
    "diag_ticket_minimo": 0.90,
    "diag_ticket_forte": 1.10,
    "diag_desconto_pp": 0.005,
    "diag_setor_fraco": 0.70,
    "diag_setor_forte": 1.30,
    "diag_equipe_abaixo": 0.50,
    "diag_equipe_acima": 0.75,
    "diag_meta_folga": 0.10,
}
ATE = date(2024, 3, 15)


@pytest.fixture
def base(banco_com_ddl):
    b.montar_base(banco_com_ddl, ano=2024)
    # L01: 2 cupons (C1 com 2 itens, C2); L02: 1 cupom; 1 item cancelado de L01 não conta
    b.item(banco_com_ddl, "A1", cupom="C1", numero_item=1, loja="L01", vendedor="V1", desconto=10)
    b.item(banco_com_ddl, "A2", cupom="C1", numero_item=2, loja="L01", vendedor="V1")
    b.item(banco_com_ddl, "A3", cupom="C2", data="2024-03-06", loja="L01", vendedor="V1")
    b.item(banco_com_ddl, "A4", cupom="C3", loja="L02", vendedor="V2", preco=200.0, desconto=20)
    b.item(banco_com_ddl, "A5", cupom="C4", loja="L01", vendedor="V1", status="Cancelada")
    b.item(banco_com_ddl, "A6", cupom="C5", data="2024-03-20", loja="L01", vendedor="V1")  # depois
    return banco_com_ddl


def test_view_de_parametros_traz_so_as_chaves_do_diagnostico(base):
    linhas = base.execute("SELECT chave, valor FROM dw.vw_parametros_diagnostico").fetchall()
    assert dict(linhas) == CHAVES
    assert all(d for (d,) in base.execute("SELECT descricao FROM dw.vw_parametros_diagnostico"))


def test_reaplicar_o_ddl_nao_sobrescreve_um_valor_alterado(base):
    base.execute("UPDATE etl.parametros_negocio SET valor = 0.65 WHERE chave = 'diag_setor_fraco'")
    script = config.DIR_DDL / "25_parametros_diagnostico.sql"
    base.execute(script.read_text(encoding="utf-8"))
    assert diagnostico.ler_parametros(base)["setor_fraco"] == 0.65


def test_referencia_da_rede_soma_as_lojas_e_conta_cupons_distintos(base):
    colunas = [
        c for (c,) in base.execute(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_schema = 'dw' AND table_name = 'vw_referencia_rede_dia'"
        )
    ]  # fmt: skip
    assert "sk_loja" not in colunas  # sem loja: é isso que a deixa pronta para o RLS
    dia = base.execute(
        "SELECT receita, cupons, unidades, desconto, receita_bruta"
        " FROM dw.vw_referencia_rede_dia WHERE data = '2024-03-05'"
    ).fetchone()
    # A1 (90) + A2 (100) em C1, A4 (180) em C3; o cancelado A5 fica de fora
    assert dia == (370.0, 2, 3, 30.0, 400.0)
    # a margem da rede (receita - custo) vem da view, não de ALLSELECTED(Lojas)
    custo = base.execute(
        "SELECT custo FROM dw.vw_referencia_rede_dia WHERE data = '2024-03-05'"
    ).fetchone()[0]
    esperado = base.execute(
        "SELECT SUM(f.custo) FROM dw.fato_vendas f JOIN dw.dim_tempo t USING (sk_tempo)"
        " WHERE f.status = 'Concluída' AND t.data = '2024-03-05'"
    ).fetchone()[0]
    assert custo == pytest.approx(float(esperado))


def test_indicadores_do_banco_para_uma_loja(base):
    base.execute(
        "INSERT INTO dw.fato_meta_vendas (sk_tempo, sk_loja, setor, valor_meta)"
        " SELECT 20240301, sk_loja, 'Alimentos', 3100 FROM dw.dim_loja WHERE cod_loja = 'L01'"
    )
    base.execute(
        "INSERT INTO dw.fato_meta_vendedor (sk_tempo, sk_vendedor, valor_meta)"
        " SELECT 20240301, sk_vendedor, 3100 FROM dw.dim_vendedor WHERE cod_vendedor = 'V1'"
    )
    ind = diagnostico.calcular_indicadores(base, "L01", ATE)
    assert ind.nome_loja == "Ipê L01"
    assert ind.receita == pytest.approx(90 + 100 + 100)  # só até 15/03, só concluídas
    assert ind.cupons == 2
    assert ind.meta == pytest.approx(3100 * 15 / 31, rel=0.2)  # 15 dos 31 dias, com os pesos
    assert ind.cupons_ano_anterior is None and ind.venda_ano_anterior is None  # sem 2023
    assert ind.ticket == pytest.approx(145.0)
    assert ind.ticket_rede == pytest.approx(470.0 / 3)  # a rede inclui L01 e L02
    assert ind.desconto == pytest.approx(10 / 300)
    assert ind.desconto_rede == pytest.approx(30 / 500)
    assert set(ind.setores) == {"Alimentos"}
    assert len(ind.vendedores) == 1
    res = diagnostico.diagnosticar(ind, diagnostico.ler_parametros(base))
    assert res.veredito.startswith("Abaixo da meta")
