"""Faixa baixa/alta da previsão, calibrada nos erros do backtest.

Para cada (granularidade, setor) olha-se a razão real / previsto de todos os pontos do backtest. O
percentil 10 dessa razão vira o fator da faixa baixa e o 90, o da faixa alta; assim ~80% dos valores
reais devem cair dentro da faixa. Os setores têm ruído muito diferente, por isso a calibração é por
setor; já as lojas de um mesmo setor compartilham a faixa.
"""

import numpy as np
import pandas as pd

from src import config

Faixas = dict[tuple[str, str], tuple[float, float]]  # (granularidade, setor) -> (fator baixo, alto)


def somar_por_mes(matriz: np.ndarray, datas: pd.DatetimeIndex) -> np.ndarray:
    """Soma as colunas de cada mês civil (colunas em ordem cronológica)."""
    meses = datas.year.to_numpy() * 12 + datas.month.to_numpy()
    unicos = np.unique(meses)
    return np.stack([matriz[:, meses == m].sum(axis=1) for m in unicos], axis=1)


def _por_granularidade(real, previsto, datas):
    return {
        "dia": (real, previsto),
        "mes": (somar_por_mes(real, datas), somar_por_mes(previsto, datas)),
    }


def calibrar_faixas(
    real: np.ndarray, previsto: np.ndarray, setores: list[str], datas: pd.DatetimeIndex
) -> Faixas:
    """Fatores da faixa a partir de um backtest (matrizes de séries válidas x dias)."""
    setores_arr = np.array(setores)
    faixas: Faixas = {}
    for granularidade, (r, p) in _por_granularidade(real, previsto, datas).items():
        for setor in sorted(set(setores)):
            linhas = setores_arr == setor
            r_s, p_s = r[linhas].ravel(), p[linhas].ravel()
            usados = p_s > 0
            if not usados.any():
                continue
            razao = r_s[usados] / p_s[usados]
            baixo, alto = np.quantile(
                razao, [config.PREVISAO_QUANTIL_BAIXO, config.PREVISAO_QUANTIL_ALTO]
            )
            faixas[(granularidade, setor)] = (float(baixo), float(alto))
    return faixas


def aplicar_faixa(
    previsto: np.ndarray, setores: list[str], faixas: Faixas, granularidade: str
) -> tuple[np.ndarray, np.ndarray]:
    """Valores baixo e alto de cada ponto previsto (a faixa sempre envolve o previsto)."""
    baixo = np.empty_like(previsto)
    alto = np.empty_like(previsto)
    for i, setor in enumerate(setores):
        fator_baixo, fator_alto = faixas[(granularidade, setor)]
        baixo[i] = np.minimum(previsto[i], previsto[i] * fator_baixo)
        alto[i] = np.maximum(previsto[i], previsto[i] * fator_alto)
    return baixo, alto


def cobertura(real, previsto, setores, faixas, datas, granularidade: str) -> np.ndarray:
    """Para cada série, a fração dos pontos reais que ficou dentro da faixa."""
    r, p = _por_granularidade(real, previsto, datas)[granularidade]
    baixo, alto = aplicar_faixa(p, setores, faixas, granularidade)
    return ((r >= baixo - 1e-9) & (r <= alto + 1e-9)).mean(axis=1)
