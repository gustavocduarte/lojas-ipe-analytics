"""Estimador da fatia semanal do simulador v2 (sem banco)."""

import numpy as np
import pandas as pd
import pytest

from src import config
from src.simulador import fatias


def test_sem_historico_proprio_vale_a_media_dos_lotados_e_o_percentil_do_conjunto():
    conjunto = np.array([0.1, 0.2, 0.3, 0.4])
    central, conservadora = fatias.estimar(np.empty(0), conjunto, k=4, percentil=0.25)
    assert central == pytest.approx(0.25)
    assert conservadora == pytest.approx(np.percentile(conjunto, 25))


def test_encolhimento_e_media_ponderada_por_semanas_e_k():
    proprias = np.array([0.4, 0.4, 0.4, 0.4])  # n = 4
    conjunto = np.array([0.1, 0.1])
    central, _ = fatias.estimar(proprias, conjunto, k=4, percentil=0.5)
    assert central == pytest.approx((4 * 0.4 + 4 * 0.1) / 8)
    assert fatias.estimar(proprias, conjunto, k=0, percentil=0.5)[0] == pytest.approx(0.4)


def test_conservadora_usa_a_distribuicao_das_fatias_ja_encolhidas():
    proprias = np.array([0.0, 0.2, 0.4, 0.6])
    conjunto = np.array([0.3])
    _, conservadora = fatias.estimar(proprias, conjunto, k=4, percentil=0.25)
    encolhidas = (4 * proprias + 4 * 0.3) / 8
    assert conservadora == pytest.approx(np.percentile(encolhidas, 25))
    central, maior = fatias.estimar(proprias, conjunto, k=4, percentil=0.9)
    assert maior > conservadora and central == pytest.approx(0.3)


def test_sem_nenhuma_base_nao_ha_estimativa_e_sem_conjunto_vale_o_proprio():
    assert fatias.estimar(np.empty(0), np.empty(0), k=4, percentil=0.5) is None
    assert fatias.estimar(np.array([0.2, 0.4]), np.empty(0), 4, 0.5)[0] == pytest.approx(0.3)


def test_k_escolhido_e_o_maior_dentro_da_tolerancia_do_menor_wape():
    tolerancia = config.SIMULADOR_TOLERANCIA_K
    tabela = pd.DataFrame(
        {"k": [0, 2, 4, 8], "wape_todos": [0.70, 0.70 + tolerancia / 2, 0.70 + tolerancia, 0.80]}
    )
    assert fatias.k_escolhido(tabela) == 4
