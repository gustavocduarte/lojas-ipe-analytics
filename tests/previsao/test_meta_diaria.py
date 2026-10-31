"""Meta mensal repartida pelos dias: soma exata, pesos e consistência com src/config.py."""

from datetime import date
from decimal import Decimal

import pytest

from src import config
from tests.etl import base_alertas as b

pytestmark = pytest.mark.banco

SEXTA_SANTA_2024 = date(2024, 3, 29)


@pytest.fixture
def base(banco_com_ddl):
    b.montar_base(banco_com_ddl, ano=2024, feriados={SEXTA_SANTA_2024: "Sexta-feira Santa"})
    return banco_com_ddl


def _meta_loja(con, valor, cod_loja="L01", setor="Alimentos", sk_tempo=20240301):
    con.execute(
        "INSERT INTO dw.fato_meta_vendas (sk_tempo, sk_loja, setor, valor_meta)"
        " SELECT %s, sk_loja, %s, %s FROM dw.dim_loja WHERE cod_loja = %s",
        (sk_tempo, setor, valor, cod_loja),
    )


def _dias(con, valor_meta=Decimal("10000.00")):
    _meta_loja(con, valor_meta)
    return dict(
        con.execute(
            "SELECT data, valor_meta_dia FROM dw.vw_meta_vendas_diaria ORDER BY data"
        ).fetchall()
    )


def test_pesos_do_banco_sao_os_da_config(base):
    pesos = dict(
        base.execute(
            "SELECT chave, valor FROM etl.parametros_negocio WHERE chave LIKE 'peso_%'"
        ).fetchall()
    )
    for dia, fator in config.FATOR_DIA_SEMANA.items():  # segunda = 0 na config, 1 no ISO
        assert float(pesos[f"peso_dia_semana_{dia + 1}"]) == fator
    assert float(pesos["peso_feriado"]) == config.FATOR_FERIADO_NACIONAL


def test_soma_dos_dias_bate_exatamente_com_a_meta_do_mes(base):
    dias = _dias(base)
    assert len(dias) == 31
    assert sum(dias.values()) == Decimal("10000.00")


@pytest.mark.parametrize("meta", ["1000.01", "7777.77", "0.05", "123456.78"])
def test_soma_bate_mesmo_quando_a_meta_nao_divide_em_centavos(base, meta):
    assert sum(_dias(base, Decimal(meta)).values()) == Decimal(meta)


def test_dias_pesam_conforme_o_dia_da_semana_e_o_feriado(base):
    dias = _dias(base)
    segunda, sabado = dias[date(2024, 3, 4)], dias[date(2024, 3, 9)]
    sexta_comum, sexta_santa = dias[date(2024, 3, 8)], dias[SEXTA_SANTA_2024]
    assert sabado / segunda == pytest.approx(
        Decimal(str(config.FATOR_DIA_SEMANA[5])) / Decimal(str(config.FATOR_DIA_SEMANA[0])),
        abs=Decimal("0.001"),
    )
    assert sexta_santa / sexta_comum == pytest.approx(
        Decimal(str(config.FATOR_FERIADO_NACIONAL)), abs=Decimal("0.001")
    )


def test_ultimo_dia_absorve_o_resto_do_arredondamento(base):
    dias = _dias(base, Decimal("1000.01"))
    ultimo = dias[date(2024, 3, 31)]
    ideal = (
        Decimal("1000.01")
        * Decimal("0.70")
        / sum(
            Decimal(str(config.FATOR_DIA_SEMANA[d.weekday()]))
            * (Decimal(str(config.FATOR_FERIADO_NACIONAL)) if d == SEXTA_SANTA_2024 else 1)
            for d in dias
        )
    )
    assert abs(ultimo - ideal) < Decimal("0.05")


def test_cada_loja_e_setor_e_cada_mes_somam_a_propria_meta(base):
    _meta_loja(base, Decimal("5000.50"), "L01", "Alimentos", 20240301)
    _meta_loja(base, Decimal("3000.33"), "L02", "Casa", 20240301)
    _meta_loja(base, Decimal("4200.00"), "L01", "Alimentos", 20240401)
    somas = base.execute(
        "SELECT sk_loja, setor, date_trunc('month', data)::DATE, sum(valor_meta_dia)"
        " FROM dw.vw_meta_vendas_diaria GROUP BY 1, 2, 3 ORDER BY 1, 3"
    ).fetchall()
    assert [s[3] for s in somas] == [Decimal("5000.50"), Decimal("4200.00"), Decimal("3000.33")]


def test_meta_por_vendedor_tambem_soma_a_meta_do_mes(base):
    base.execute(
        "INSERT INTO dw.fato_meta_vendedor (sk_tempo, sk_vendedor, valor_meta)"
        " SELECT 20240301, sk_vendedor, 1234.56 FROM dw.dim_vendedor WHERE cod_vendedor = 'V1'"
    )
    total, dias = base.execute(
        "SELECT sum(valor_meta_dia), count(*) FROM dw.vw_meta_vendedor_diaria"
    ).fetchone()
    assert total == Decimal("1234.56") and dias == 31


def test_mes_sem_meta_nao_gera_linhas(base):
    assert base.execute("SELECT count(*) FROM dw.vw_meta_vendas_diaria").fetchone()[0] == 0
