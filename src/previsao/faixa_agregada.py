"""Faixa baixa/alta no nível agregado: total de cada loja (soma dos setores) e total da rede.

A soma das faixas de cada loja e setor é bem mais larga que a faixa real do total, porque os erros
das séries se compensam. Aqui a faixa é calibrada nos resíduos do backtest no próprio nível: a razão
real / previsto do total da rede, e a do total de cada loja (as lojas dividem a mesma faixa).
"""

import numpy as np
import pandas as pd

from src import config
from src.previsao.faixa import _por_granularidade

# (nivel, granularidade) -> (fator baixo, fator alto)
FaixasAgregadas = dict[tuple[str, str], tuple[float, float]]


def agregar(matriz: np.ndarray, lojas: np.ndarray, nivel: str) -> tuple[list, np.ndarray]:
    """Soma as séries por loja ("loja") ou todas juntas ("rede"). Devolve (rótulos, matriz)."""
    if nivel == "rede":
        return [None], matriz.sum(axis=0, keepdims=True)
    unicas = sorted(set(lojas.tolist()))
    return unicas, np.stack([matriz[lojas == loja].sum(axis=0) for loja in unicas])


def calibrar(
    real: np.ndarray, previsto: np.ndarray, lojas: np.ndarray, datas: pd.DatetimeIndex
) -> FaixasAgregadas:
    """Percentis da razão real/previsto no total da rede e no total de cada loja."""
    faixas: FaixasAgregadas = {}
    for granularidade, (r, p) in _por_granularidade(real, previsto, datas).items():
        for nivel in ("loja", "rede"):
            r_n, p_n = agregar(r, lojas, nivel)[1].ravel(), agregar(p, lojas, nivel)[1].ravel()
            usados = p_n > 0
            if not usados.any():
                continue
            baixo, alto = np.quantile(
                r_n[usados] / p_n[usados],
                [config.PREVISAO_QUANTIL_BAIXO, config.PREVISAO_QUANTIL_ALTO],
            )
            faixas[(nivel, granularidade)] = (float(baixo), float(alto))
    return faixas


def aplicar(previsto: np.ndarray, faixa: tuple[float, float]) -> tuple[np.ndarray, np.ndarray]:
    """Baixo e alto de totais já somados (a faixa sempre envolve o previsto)."""
    return np.minimum(previsto, previsto * faixa[0]), np.maximum(previsto, previsto * faixa[1])


def cobertura(
    real, previsto, lojas, faixas: FaixasAgregadas, datas, granularidade: str
) -> dict[tuple[str, int | None], float]:
    """Fração dos totais reais dentro da faixa: {("rede", None): x, ("loja", sk_loja): y, ...}."""
    r, p = _por_granularidade(real, previsto, datas)[granularidade]
    saida = {}
    for nivel in ("rede", "loja"):
        if (nivel, granularidade) not in faixas:
            continue
        rotulos, r_n = agregar(r, lojas, nivel)
        p_n = agregar(p, lojas, nivel)[1]
        baixo, alto = aplicar(p_n, faixas[(nivel, granularidade)])
        dentro = ((r_n >= baixo - 1e-9) & (r_n <= alto + 1e-9)).mean(axis=1)
        for rotulo, valor in zip(rotulos, dentro, strict=True):
            saida[(nivel, None if rotulo is None else int(rotulo))] = float(valor)
    return saida
