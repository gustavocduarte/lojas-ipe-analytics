"""Classe ABC dos produtos (sem banco): limites em config, A até 80% e B até 95% (inclusive)."""

import pandas as pd
import pytest

from src import config
from src.relatorios.consultas import classificar_abc


def test_limites_vem_da_config():
    assert (config.RELATORIO_ABC_LIMITE_A, config.RELATORIO_ABC_LIMITE_B) == (0.80, 0.95)


@pytest.mark.parametrize(
    "acumulada,classe",
    [(0.30, "A"), (0.80, "A"), (0.8000001, "B"), (0.95, "B"), (0.9500001, "C"), (1.0, "C")],
)
def test_classe_pela_participacao_acumulada(acumulada, classe):
    assert classificar_abc(pd.Series([acumulada])).iloc[0] == classe


def test_soma_em_ponto_flutuante_no_limite_continua_na_classe_a():
    acumulada = pd.Series([0.1, 0.2, 0.3, 0.2]).cumsum()  # o último dá 0.8000000000000002
    assert list(classificar_abc(acumulada)) == ["A", "A", "A", "A"]
