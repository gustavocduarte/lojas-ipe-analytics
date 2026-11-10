"""Probabilidade de bater a meta no dw: tabelas, procedures idempotentes, views e parâmetros."""

import numpy as np
import pandas as pd
import psycopg
import pytest

from src import config
from src.previsao import probabilidade as prob
from src.previsao import probabilidade_gravacao as gravacao
from tests.etl import base_alertas as b
from tests.previsao.test_probabilidade_meta import _cortes, _para_avaliar

pytestmark = pytest.mark.banco

INICIO, FIM = pd.Timestamp("2025-03-01"), pd.Timestamp("2025-03-10")


@pytest.fixture
def base(banco_com_ddl):
    b.montar_base(banco_com_ddl, ano=2025)
    return banco_com_ddl


def _lojas(con) -> list[int]:
    return [sk for (sk,) in con.execute("SELECT sk_loja FROM dw.dim_loja ORDER BY cod_loja")]


def _cortes_gravaveis(sks: list[int], probabilidade: float = 0.6) -> pd.DataFrame:
    """Dez dias de março para duas lojas e a rede, no formato de calcular_probabilidades."""
    linhas = []
    for dia in pd.date_range(INICIO, FIM, freq="D"):
        k = (pd.Timestamp("2025-03-31") - dia).days
        for nivel, sk in [("loja", sks[0]), ("loja", sks[1]), ("rede", prob.REDE)]:
            semBase = nivel == "loja" and sk == sks[1] and dia.day <= 2
            linhas.append(
                {
                    "nivel": nivel, "sk_loja": sk, "corte": dia, "mes": INICIO,
                    "dias_restantes": k, "faixa": prob.faixa_de_dias(k),
                    "realizado_ate": 100.0 * dia.day, "prev_resto": np.nan if semBase else 3000.0,
                    "real_resto": np.nan, "meta": 5000.0, "base": not semBase,
                    "motivo": "loja_nova" if semBase else None,
                    "lojas_incluidas": 2 if nivel == "rede" else None,
                    "lojas_total": 2 if nivel == "rede" else None,
                    "probabilidade": np.nan if semBase else probabilidade,
                    "motivo_sem_base": "loja_nova" if semBase else None,
                    "projecao": np.nan if semBase else 100.0 * dia.day + 3000.0,
                }
            )  # fmt: skip
    return pd.DataFrame(linhas)


def _n(con, tabela, onde="true") -> int:
    return con.execute(f"SELECT count(*) FROM dw.{tabela} WHERE {onde}").fetchone()[0]


# --- parâmetros ---------------------------------------------------------------------------------
def test_chaves_prob_de_cor_ficam_em_parametros_de_negocio(base):
    linhas = base.execute("SELECT chave, valor FROM dw.vw_parametros_probabilidade").fetchall()
    assert dict(linhas) == {"prob_verde_min": 0.70, "prob_ambar_min": 0.30}
    assert all(d for (d,) in base.execute("SELECT descricao FROM dw.vw_parametros_probabilidade"))
    # as chaves do diagnóstico não entram aqui, nem as daqui no diagnóstico
    assert not base.execute(
        "SELECT 1 FROM dw.vw_parametros_diagnostico WHERE chave LIKE 'prob%'"
    ).fetchall()


def test_reaplicar_os_parametros_nao_sobrescreve_um_valor_alterado(base):
    base.execute("UPDATE etl.parametros_negocio SET valor = 0.8 WHERE chave = 'prob_verde_min'")
    texto = (config.DIR_DDL / "26_probabilidade_meta.sql").read_text(encoding="utf-8")
    base.execute(texto[texto.index("INSERT INTO etl.parametros_negocio") :])
    valor = base.execute(
        "SELECT valor FROM dw.vw_parametros_probabilidade WHERE chave = 'prob_verde_min'"
    )
    assert valor.fetchone()[0] == 0.8


# --- restrições -------------------------------------------------------------------------------
def _inserir(con, **campos):
    padrao = {
        "nivel": "loja", "sk_loja": _lojas(con)[0], "data_referencia": "2025-03-05",
        "mes": "2025-03-01", "dias_restantes": 26, "realizado_ate": 1.0, "probabilidade": 0.5,
        "motivo_sem_base": None, "versao": "teste",
    }  # fmt: skip
    padrao.update(campos)
    con.execute(
        f"INSERT INTO dw.previsao_probabilidade_meta ({', '.join(padrao)})"
        f" VALUES ({', '.join(['%s'] * len(padrao))})",
        list(padrao.values()),
    )


@pytest.mark.parametrize(
    "campos",
    [
        {"probabilidade": 1.2},
        {"probabilidade": -0.1},
        {"probabilidade": None},  # sem probabilidade exige o motivo
        {"motivo_sem_base": "loja_nova"},  # com probabilidade não pode ter motivo
        {"probabilidade": None, "motivo_sem_base": "qualquer"},
        {"nivel": "rede"},  # rede não tem loja
        {"sk_loja": None},  # loja precisa de loja
        {"mes": "2025-03-02"},
        {"dias_restantes": -1},
    ],
)
def test_restricoes_da_tabela_de_probabilidade(base, campos):
    with pytest.raises(psycopg.errors.CheckViolation):
        _inserir(base, **campos)


def test_chave_unica_por_nivel_loja_dia_e_versao(base):
    _inserir(base)
    with pytest.raises(psycopg.errors.UniqueViolation):
        _inserir(base)
    base.rollback()


def test_rede_aceita_sk_loja_vazio_e_unica_por_dia(base):
    _inserir(base, nivel="rede", sk_loja=None, versao="r")
    with pytest.raises(psycopg.errors.UniqueViolation):
        _inserir(base, nivel="rede", sk_loja=None, versao="r")
    base.rollback()


# --- gravação idempotente ---------------------------------------------------------------------
def test_gravar_duas_vezes_nao_duplica(base):
    sks = _lojas(base)
    dados = _cortes_gravaveis(sks)
    n = gravacao.gravar_probabilidades(base, dados, INICIO.date(), FIM.date())
    assert n == 30 and _n(base, "previsao_probabilidade_meta") == 30
    gravacao.gravar_probabilidades(base, dados, INICIO.date(), FIM.date())
    assert _n(base, "previsao_probabilidade_meta") == 30
    assert _n(base, "previsao_probabilidade_meta", "nivel = 'rede' AND sk_loja IS NULL") == 10
    # sem base: probabilidade NULL e o motivo, nunca 50%
    sem = base.execute(
        "SELECT probabilidade, motivo_sem_base, previsto_resto FROM dw.previsao_probabilidade_meta"
        " WHERE sk_loja = %s AND data_referencia = '2025-03-01'", (sks[1],)
    ).fetchone()  # fmt: skip
    assert sem == (None, "loja_nova", None)
    ok = base.execute(
        "SELECT probabilidade FROM dw.previsao_probabilidade_meta WHERE sk_loja = %s"
        " AND data_referencia = '2025-03-05'", (sks[0],)
    ).fetchone()  # fmt: skip
    assert float(ok[0]) == 0.6


def test_gravar_so_substitui_o_intervalo_pedido(base):
    sks = _lojas(base)
    gravacao.gravar_probabilidades(base, _cortes_gravaveis(sks, 0.6), INICIO.date(), FIM.date())
    novo = _cortes_gravaveis(sks, 0.9)
    gravacao.gravar_probabilidades(base, novo, pd.Timestamp("2025-03-06").date(), FIM.date())
    antes = _n(
        base,
        "previsao_probabilidade_meta",
        "data_referencia < '2025-03-06' AND probabilidade = 0.6",
    )
    depois = _n(
        base,
        "previsao_probabilidade_meta",
        "data_referencia >= '2025-03-06' AND probabilidade = 0.9",
    )
    assert _n(base, "previsao_probabilidade_meta") == 30
    assert antes == 5 * 3 - 2 and depois == 5 * 3  # dias 1-2 da loja 2 são sem base (NULL)


def test_a_versao_mais_recente_e_a_das_views(base):
    sks = _lojas(base)
    _inserir(base, data_referencia="2025-03-05", versao="antiga", probabilidade=0.11)
    base.execute("UPDATE dw.previsao_probabilidade_meta SET gerado_em = '2020-01-01'")
    gravacao.gravar_probabilidades(base, _cortes_gravaveis(sks), INICIO.date(), FIM.date())
    valores = {
        p for (p,) in base.execute("SELECT probabilidade FROM dw.vw_probabilidade_meta_loja")
    }
    assert valores == {0.6, None}  # a linha da versão antiga (0,11) não aparece


# --- views ------------------------------------------------------------------------------------
def _colunas(con, view) -> list[str]:
    return [
        c for (c,) in con.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'dw'"
            " AND table_name = %s ORDER BY ordinal_position", (view,)
        )
    ]  # fmt: skip


def test_view_da_rede_nao_tem_sk_loja_e_a_da_loja_tem(base):
    assert "sk_loja" in _colunas(base, "vw_probabilidade_meta_loja")
    rede = _colunas(base, "vw_probabilidade_meta_rede")
    assert "sk_loja" not in rede  # é isso que a deixa pronta para o RLS
    assert {
        "sk_tempo",
        "probabilidade",
        "motivo_sem_base",
        "lojas_incluidas",
        "lojas_total",
    } <= set(rede)


def test_views_trazem_valores_prontos_para_o_power_bi(base):
    sks = _lojas(base)
    gravacao.gravar_probabilidades(base, _cortes_gravaveis(sks), INICIO.date(), FIM.date())
    rede = base.execute(
        "SELECT sk_tempo, data_referencia, probabilidade, projecao, meta_mes, lojas_incluidas,"
        " lojas_total FROM dw.vw_probabilidade_meta_rede WHERE data_referencia = '2025-03-05'"
    ).fetchone()
    assert rede[0] == 20250305 and rede[2] == 0.6 and rede[3] == 3500.0 and rede[4] == 5000.0
    assert rede[5:] == (2, 2)
    assert (
        _n(base, "vw_probabilidade_meta_rede") == 10
        and _n(base, "vw_probabilidade_meta_loja") == 20
    )


# --- calibração e ajuste -----------------------------------------------------------------------
def test_calibracao_grava_idempotente_e_a_soma_dos_n_bate(base):
    cal = pd.concat(
        [
            prob.avaliar(_para_avaliar(), "so_passado"),
            prob.avaliar(_para_avaliar(p=0.7), "leave_one_month_out"),
        ],
        ignore_index=True,
    )
    assert gravacao.gravar_calibracao(base, cal) == len(cal)
    assert gravacao.gravar_calibracao(base, cal) == len(cal)
    assert _n(base, "previsao_probabilidade_calibracao") == len(cal)
    soma = base.execute(
        "SELECT esquema, nivel, faixa_dias, sum(n) FILTER (WHERE tipo = 'faixa'),"
        " sum(n) FILTER (WHERE tipo = 'resumo') FROM dw.vw_probabilidade_calibracao"
        " GROUP BY esquema, nivel, faixa_dias"
    ).fetchall()
    assert soma and all(faixa == resumo for *_, faixa, resumo in soma)
    resumo = base.execute(
        "SELECT brier, brier_50, brier_frequencia, ece FROM dw.vw_probabilidade_calibracao"
        " WHERE esquema = 'so_passado' AND nivel = 'loja' AND faixa_dias = 0 AND tipo = 'resumo'"
    ).fetchone()
    assert resumo[1] == pytest.approx(0.25) and resumo[0] == pytest.approx(0.09)


def test_calibracao_recusa_linha_de_faixa_sem_limites(base):
    comum = ("so_passado", "loja", 0)
    with pytest.raises(psycopg.errors.CheckViolation):
        base.execute(
            "INSERT INTO dw.previsao_probabilidade_calibracao (esquema, nivel, faixa_dias, tipo, n,"
            " n_unidades, versao) VALUES (%s, %s, %s, 'faixa', 1, 1, 'v')", comum
        )  # fmt: skip


def test_erro_resto_grava_idempotente_com_101_quantis_por_ajuste(base):
    sks = _lojas(base)
    _, modelos = prob.calcular_probabilidades(_cortes(np.random.default_rng(31)), "so_passado")
    ajuste = prob.linhas_do_ajuste(modelos)
    # as lojas do teste de lógica são 1 e 2; no banco de teste as lojas têm os sk_loja do identity
    ajuste["sk_loja"] = ajuste["sk_loja"].map({1: sks[0], 2: sks[1]})
    esperado = len(ajuste)
    assert gravacao.gravar_erro_resto(base, ajuste) == esperado
    assert gravacao.gravar_erro_resto(base, ajuste) == esperado
    assert _n(base, "previsao_erro_resto") == esperado
    por_ajuste = base.execute(
        "SELECT meses_ate, count(*) FROM dw.previsao_erro_resto WHERE nivel = 'forma'"
        " GROUP BY meses_ate"
    ).fetchall()
    assert por_ajuste and all(n == config.PROB_QUANTIS_FORMA for _, n in por_ajuste)
    with pytest.raises(psycopg.errors.UniqueViolation):
        base.execute(
            "INSERT INTO dw.previsao_erro_resto (nivel, faixa_dias, meses_ate, n_meses,"
            " n_amostras, mu, sigma, versao) SELECT nivel, faixa_dias, meses_ate, n_meses,"
            " n_amostras, mu, sigma, versao"
            " FROM dw.previsao_erro_resto WHERE nivel = 'conjunto' LIMIT 1"
        )
    base.rollback()


def test_erro_resto_recusa_forma_sem_posicao(base):
    with pytest.raises(psycopg.errors.CheckViolation):
        base.execute(
            "INSERT INTO dw.previsao_erro_resto (nivel, meses_ate, n_meses, n_amostras, z, versao)"
            " VALUES ('forma', '2025-03-01', 3, 30, 0.1, 'v')"
        )
