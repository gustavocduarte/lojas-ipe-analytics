"""Orquestra a probabilidade de bater a meta: lê o dw, monta os cortes, calcula nos dois esquemas,
mede a calibração e (opcional) grava."""

import time
from dataclasses import dataclass
from datetime import date

import pandas as pd
import psycopg

from src import config
from src.previsao import dados
from src.previsao import probabilidade as prob
from src.previsao import probabilidade_cortes as cortes_mod
from src.previsao import probabilidade_gravacao as gravacao


@dataclass
class ResultadoProbabilidade:
    inicio: date
    fim: date
    cortes: pd.DataFrame
    so_passado: pd.DataFrame
    leave_one_month_out: pd.DataFrame
    modelos: dict
    calibracao: pd.DataFrame
    nomes_lojas: dict[int, str]
    duracao_s: float


def nomes_das_lojas(conexao: psycopg.Connection) -> dict[int, str]:
    return {
        int(sk): nome for sk, nome in conexao.execute("SELECT sk_loja, nome_loja FROM dw.dim_loja")
    }


def executar(
    conexao: psycopg.Connection, inicio: date | None = None, fim: date | None = None
) -> ResultadoProbabilidade:
    t0 = time.perf_counter()
    ultimo = dados.ultimo_dia_com_venda(conexao)
    inicio = inicio or config.PROB_PRIMEIRO_CORTE
    fim = min(fim or ultimo, ultimo)
    if fim < inicio:
        raise ValueError("o período da probabilidade não tem nenhum dia com venda")
    primeiro = dados.primeiro_dia_com_venda(conexao)
    painel = dados.ler_painel(conexao, primeiro, ultimo)
    metas = cortes_mod.ler_metas(conexao)
    cortes = cortes_mod.montar_cortes(painel, metas, inicio, fim)
    passado, modelos = prob.calcular_probabilidades(cortes, "so_passado")
    lomo, _ = prob.calcular_probabilidades(cortes, "leave_one_month_out")
    calibracao = pd.concat(
        [prob.avaliar(passado, "so_passado"), prob.avaliar(lomo, "leave_one_month_out")],
        ignore_index=True,
    )
    return ResultadoProbabilidade(
        inicio, fim, cortes, passado, lomo, modelos, calibracao, nomes_das_lojas(conexao),
        time.perf_counter() - t0,
    )  # fmt: skip


def gravar(conexao: psycopg.Connection, r: ResultadoProbabilidade) -> dict[str, int]:
    """Grava as três tabelas (substitui o que for desta versão no período)."""
    return {
        "probabilidades": gravacao.gravar_probabilidades(conexao, r.so_passado, r.inicio, r.fim),
        "calibracao": gravacao.gravar_calibracao(conexao, r.calibracao),
        "erro_resto": gravacao.gravar_erro_resto(conexao, prob.linhas_do_ajuste(r.modelos)),
    }
