"""Gravação da probabilidade de bater a meta no dw (idempotente: cada procedure substitui o seu)."""

from datetime import date

import pandas as pd
import psycopg

from src import config
from src.previsao import geracao
from src.previsao.modelos import versao_do_modelo
from src.previsao.probabilidade import REDE


def versao() -> str:
    """Ex.: decomposicao@1/prob@1 (modelo de previsão + versão do método de probabilidade)."""
    return f"{versao_do_modelo(config.PROB_MODELO)}/prob@{config.PROB_VERSAO}"


COLUNAS_PROBABILIDADE = [
    "nivel", "sk_loja", "data_referencia", "mes", "dias_restantes", "realizado_ate",
    "previsto_resto", "projecao", "meta_mes", "probabilidade", "motivo_sem_base",
    "lojas_incluidas", "lojas_total",
]  # fmt: skip
COLUNAS_CALIBRACAO = [
    "esquema", "nivel", "faixa_dias", "tipo", "prob_inicio", "prob_fim", "previsto_medio",
    "observado", "n", "n_unidades", "ic_baixo", "ic_alto", "brier", "brier_50",
    "brier_frequencia", "ece",
]  # fmt: skip
COLUNAS_ERRO = [
    "nivel", "sk_loja", "faixa_dias", "posicao", "meses_ate", "n_meses", "n_amostras",
    "mu_bruto", "sigma_bruto", "peso", "mu", "sigma", "z",
]  # fmt: skip


def formatar_probabilidades(com_p: pd.DataFrame) -> pd.DataFrame:
    """Do resultado de `calcular_probabilidades` para as colunas da tabela (rede: sk_loja vazio)."""
    q = com_p.copy()
    q["sk_loja"] = q["sk_loja"].where(q["nivel"] != "rede", None)
    q = q.rename(
        columns={"corte": "data_referencia", "prev_resto": "previsto_resto", "meta": "meta_mes"}
    )
    for c in ("realizado_ate", "previsto_resto", "projecao", "meta_mes", "probabilidade"):
        q[c] = q[c].astype(float)
    q["realizado_ate"] = q["realizado_ate"].fillna(0.0)
    q["probabilidade"] = q["probabilidade"].round(4)
    return q[COLUNAS_PROBABILIDADE]


def _linhas(quadro: pd.DataFrame, colunas: list[str]):
    for linha in quadro[colunas].itertuples(index=False, name=None):
        valores = [None if pd.isna(v) else geracao._python(v) for v in linha]
        yield [v.date() if isinstance(v, pd.Timestamp) else v for v in valores]


def _inteiros(linhas, posicoes: tuple[int, ...]):
    for linha in linhas:
        for p in posicoes:
            if linha[p] is not None:
                linha[p] = int(linha[p])
        yield linha


def gravar_probabilidades(
    conexao: psycopg.Connection, com_p: pd.DataFrame, inicio: date, fim: date
) -> int:
    """Substitui as probabilidades de [inicio, fim] desta versão. Devolve as linhas gravadas."""
    quadro = formatar_probabilidades(com_p)
    quadro = quadro[
        (quadro["data_referencia"] >= pd.Timestamp(inicio))
        & (quadro["data_referencia"] <= pd.Timestamp(fim))
    ]
    try:
        conexao.execute(
            "CREATE TEMP TABLE tmp_prob_meta (nivel VARCHAR(4), sk_loja INTEGER,"
            " data_referencia DATE, mes DATE, dias_restantes INTEGER, realizado_ate NUMERIC(14, 2),"
            " previsto_resto NUMERIC(14, 2), projecao NUMERIC(14, 2), meta_mes NUMERIC(14, 2),"
            " probabilidade NUMERIC(6, 4), motivo_sem_base VARCHAR(30), lojas_incluidas INTEGER,"
            " lojas_total INTEGER) ON COMMIT DROP"
        )
        linhas = _inteiros(_linhas(quadro, COLUNAS_PROBABILIDADE), (1, 4, 11, 12))
        geracao._copiar(conexao, "tmp_prob_meta", COLUNAS_PROBABILIDADE, linhas)
        conexao.execute("CALL dw.gravar_probabilidade_meta(%s, %s, %s)", (versao(), inicio, fim))
        conexao.commit()
    except Exception:
        conexao.rollback()
        raise
    return len(quadro)


def gravar_calibracao(conexao: psycopg.Connection, calibracao: pd.DataFrame) -> int:
    try:
        conexao.execute(
            "CREATE TEMP TABLE tmp_prob_calibracao (esquema VARCHAR(20), nivel VARCHAR(5),"
            " faixa_dias SMALLINT, tipo VARCHAR(7), prob_inicio NUMERIC(4, 2),"
            " prob_fim NUMERIC(4, 2), previsto_medio NUMERIC(6, 4), observado NUMERIC(6, 4),"
            " n INTEGER, n_unidades INTEGER, ic_baixo NUMERIC(6, 4), ic_alto NUMERIC(6, 4),"
            " brier NUMERIC(8, 6), brier_50 NUMERIC(8, 6), brier_frequencia NUMERIC(8, 6),"
            " ece NUMERIC(8, 6)) ON COMMIT DROP"
        )
        linhas = _inteiros(_linhas(calibracao, COLUNAS_CALIBRACAO), (2, 8, 9))
        geracao._copiar(conexao, "tmp_prob_calibracao", COLUNAS_CALIBRACAO, linhas)
        conexao.execute("CALL dw.gravar_probabilidade_calibracao(%s)", (versao(),))
        conexao.commit()
    except Exception:
        conexao.rollback()
        raise
    return len(calibracao)


def gravar_erro_resto(conexao: psycopg.Connection, ajuste: pd.DataFrame) -> int:
    quadro = ajuste.copy()
    quadro["sk_loja"] = quadro["sk_loja"].where(quadro["sk_loja"] != REDE, None)
    try:
        conexao.execute(
            "CREATE TEMP TABLE tmp_prob_erro (nivel VARCHAR(8), sk_loja INTEGER,"
            " faixa_dias SMALLINT, posicao SMALLINT, meses_ate DATE, n_meses INTEGER,"
            " n_amostras INTEGER, mu_bruto NUMERIC(10, 6), sigma_bruto NUMERIC(10, 6),"
            " peso NUMERIC(10, 6), mu NUMERIC(10, 6), sigma NUMERIC(10, 6), z NUMERIC(10, 6))"
            " ON COMMIT DROP"
        )
        linhas = _inteiros(_linhas(quadro, COLUNAS_ERRO), (1, 2, 3, 5, 6))
        geracao._copiar(conexao, "tmp_prob_erro", COLUNAS_ERRO, linhas)
        conexao.execute("CALL dw.gravar_erro_resto(%s)", (versao(),))
        conexao.commit()
    except Exception:
        conexao.rollback()
        raise
    return len(quadro)
