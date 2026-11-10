"""Cortes diários para a probabilidade de bater a meta: realizado até o dia, previsto do resto do
mês (modelo reajustado só com o que se sabia naquele dia) e, se o mês já fechou, o real do resto.

Regra de "sem base": a loja que tem série com menos de config.PREVISAO_DIAS_MINIMOS_SERIE dias de
venda (loja nova) fica sem probabilidade naquele corte. A rede soma só as lojas COM base (e meta)
naquele corte: realizado, previsto e meta são sempre das mesmas lojas, e `lojas_incluidas` x
`lojas_total` mostra quantas ficaram de fora.
"""

import calendar
from collections.abc import Callable
from datetime import date

import numpy as np
import pandas as pd
import psycopg

from src import config
from src.previsao.modelos import MODELOS, _series_previsiveis
from src.previsao.painel import Painel
from src.previsao.probabilidade import REDE, faixa_de_dias

COLUNAS_CORTES = [
    "nivel", "sk_loja", "corte", "mes", "dias_restantes", "faixa", "realizado_ate",
    "prev_resto", "real_resto", "meta", "base", "motivo", "lojas_incluidas", "lojas_total",
]  # fmt: skip

CONSULTA_METAS = """
    SELECT m.sk_loja, t.data AS mes, SUM(m.valor_meta) AS meta
    FROM dw.fato_meta_vendas m
    JOIN dw.dim_tempo t ON t.sk_tempo = m.sk_tempo
    GROUP BY m.sk_loja, t.data
"""


def ler_metas(conexao: psycopg.Connection) -> dict[tuple[int, pd.Timestamp], float]:
    """Meta do mês de cada loja: {(sk_loja, 1º dia do mês): meta}."""
    return {
        (int(sk), pd.Timestamp(mes)): float(meta)
        for sk, mes, meta in conexao.execute(CONSULTA_METAS).fetchall()
    }


def _soma(valores: np.ndarray, de: int, ate: int) -> np.ndarray:
    """Soma por série dos dias [de, ate) do painel; NaN (antes da 1ª venda) conta como zero."""
    if ate <= de:
        return np.zeros(valores.shape[0])
    return np.nansum(valores[:, de:ate], axis=1)


def montar_cortes(
    painel: Painel,
    metas: dict[tuple[int, pd.Timestamp], float],
    inicio: date,
    fim: date,
    *,
    modelo: Callable[[Painel, pd.DatetimeIndex], np.ndarray] | None = None,
) -> pd.DataFrame:
    """Uma linha por (loja ou rede) e dia de corte entre `inicio` e `fim`. Cada corte treina o
    modelo só com o painel até aquele dia (nada do futuro) e prevê o resto do mês."""
    prever = modelo or MODELOS[config.PROB_MODELO]
    lojas = np.array([sk for sk, _ in painel.chaves])
    ultimo_do_painel = painel.datas[-1]
    linhas = []
    for dia in pd.date_range(inicio, fim, freq="D"):
        mes_ini = dia.replace(day=1)
        mes_fim = pd.Timestamp(dia.year, dia.month, calendar.monthrange(dia.year, dia.month)[1])
        k = (mes_fim - dia).days
        pos, pos_ini, pos_fim = (
            painel.posicao(dia),
            painel.posicao(mes_ini),
            painel.posicao(mes_fim),
        )
        recorte = painel.ate(dia.date())
        existe = recorte.dias_com_historico() > 0
        previsivel = _series_previsiveis(recorte)
        previsto = None
        if k >= 1:
            alvo = pd.date_range(dia + pd.Timedelta(days=1), mes_fim, freq="D")
            previsto = np.maximum(prever(recorte, alvo), 0.0)  # séries sem base ficam NaN
        realizado = _soma(painel.valores, max(pos_ini, 0), pos + 1)
        fechado = ultimo_do_painel >= mes_fim
        real_resto = _soma(painel.valores, pos + 1, pos_fim + 1) if fechado else None
        faixa = faixa_de_dias(k)
        incluidas, soma_rede, lojas_total = [], np.zeros(3), 0
        for sk in sorted(set(lojas.tolist())):
            idx = (lojas == sk) & existe
            if not idx.any():
                continue  # loja ainda não abriu
            lojas_total += 1
            base = bool(previsivel[idx].all())
            prev = np.nan
            if base and previsto is not None:
                base = bool(np.isfinite(previsto[idx]).all())
                prev = float(previsto[idx].sum()) if base else np.nan
            elif base:
                prev = 0.0
            meta = metas.get((int(sk), mes_ini), np.nan)
            real_ate = float(realizado[idx].sum())
            real_r = float(real_resto[idx].sum()) if real_resto is not None else np.nan
            linhas.append(
                _linha("loja", int(sk), dia, mes_ini, k, faixa, real_ate, prev, real_r, meta,
                       base, None if base else "loja_nova")
            )  # fmt: skip
            if base and meta == meta and meta > 0:
                incluidas.append(sk)
                soma_rede += (real_ate, prev, meta)
        if lojas_total:
            real_r_rede = np.nan
            if real_resto is not None:
                real_r_rede = float(
                    sum(real_resto[(lojas == sk) & existe].sum() for sk in incluidas)
                )
            base_rede = bool(incluidas)
            linha = _linha(
                "rede", REDE, dia, mes_ini, k, faixa, soma_rede[0] if base_rede else 0.0,
                soma_rede[1] if base_rede else np.nan, real_r_rede if base_rede else np.nan,
                soma_rede[2] if base_rede else np.nan, base_rede,
                None if base_rede else "loja_nova",
            )  # fmt: skip
            linha["lojas_incluidas"], linha["lojas_total"] = len(incluidas), lojas_total
            linhas.append(linha)
    quadro = pd.DataFrame(linhas, columns=COLUNAS_CORTES)
    quadro["mes"] = pd.to_datetime(quadro["mes"])
    quadro["corte"] = pd.to_datetime(quadro["corte"])
    return quadro


def _linha(nivel, sk, dia, mes_ini, k, faixa, realizado, prev, real_resto, meta, base, motivo):
    return {
        "nivel": nivel, "sk_loja": sk, "corte": dia, "mes": mes_ini, "dias_restantes": k,
        "faixa": faixa, "realizado_ate": realizado, "prev_resto": prev, "real_resto": real_resto,
        "meta": meta, "base": base, "motivo": motivo, "lojas_incluidas": None,
        "lojas_total": None,
    }  # fmt: skip


def resumo_sem_base(cortes: pd.DataFrame) -> dict:
    """Lojas e cortes sem base (loja nova) e cortes da rede que deixam alguma loja de fora."""
    lojas = cortes[cortes["nivel"] == "loja"]
    sem = lojas[~lojas["base"]]
    rede = cortes[cortes["nivel"] == "rede"]
    incompleta = rede[rede["lojas_incluidas"] < rede["lojas_total"]]
    return {
        "cortes_loja": len(lojas),
        "cortes_loja_sem_base": len(sem),
        "lojas_afetadas": sorted(sem["sk_loja"].unique().tolist()),
        "cortes_por_loja": sem.groupby("sk_loja").size().to_dict(),
        "primeiro_ultimo_por_loja": {
            int(sk): (g["corte"].min().date(), g["corte"].max().date())
            for sk, g in sem.groupby("sk_loja")
        },
        "cortes_rede": len(rede),
        "cortes_rede_com_loja_de_fora": len(incompleta),
    }
