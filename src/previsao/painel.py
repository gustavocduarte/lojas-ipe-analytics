"""Painel de séries diárias: uma linha por (loja, setor), uma coluna por dia, tudo em numpy."""

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd


@dataclass
class Painel:
    """`valores[i, j]` é a receita da série `chaves[i]` no dia `datas[j]`.

    Antes da primeira venda da série o valor é NaN (a loja/setor ainda não existia); depois dela,
    dia sem venda vale 0.
    """

    datas: pd.DatetimeIndex  # contínuo, um dia por posição
    chaves: list[tuple[int, str]]  # (sk_loja, setor)
    valores: np.ndarray  # (n_series, n_dias)

    def posicao(self, dia: date | pd.Timestamp) -> int:
        """Posição do dia no painel (negativa ou além do fim se estiver fora)."""
        return (pd.Timestamp(dia) - self.datas[0]).days

    def ate(self, dia: date) -> "Painel":
        """Painel cortado no dia (inclusive)."""
        fim = self.posicao(dia) + 1
        return Painel(self.datas[:fim], self.chaves, self.valores[:, :fim])

    def dias_com_historico(self) -> np.ndarray:
        """Quantos dias cada série existe (dias não-NaN)."""
        return np.isfinite(self.valores).sum(axis=1)


def montar_painel(linhas: pd.DataFrame, inicio: date, fim: date) -> Painel:
    """Monta o painel a partir de linhas (data, sk_loja, setor, valor) já somadas por dia."""
    datas = pd.date_range(inicio, fim, freq="D")
    if linhas.empty:
        return Painel(datas, [], np.empty((0, len(datas))))
    linhas = linhas.assign(data=pd.to_datetime(linhas["data"]))
    pares = zip(linhas["sk_loja"], linhas["setor"], strict=True)
    chaves = sorted({(int(loja), setor) for loja, setor in pares})
    posicao_serie = {chave: i for i, chave in enumerate(chaves)}
    valores = np.zeros((len(chaves), len(datas)))
    primeiro_dia = np.full(len(chaves), len(datas))
    for loja, setor, data, valor in zip(
        linhas["sk_loja"], linhas["setor"], linhas["data"], linhas["valor"], strict=True
    ):
        i = posicao_serie[(int(loja), setor)]
        j = (data - datas[0]).days
        if 0 <= j < len(datas):
            valores[i, j] += float(valor)
            primeiro_dia[i] = min(primeiro_dia[i], j)
    for i, j0 in enumerate(primeiro_dia):
        valores[i, :j0] = np.nan
    return Painel(datas, chaves, valores)
