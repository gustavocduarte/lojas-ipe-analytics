"""Black Friday no modelo de decomposição: só a data do calendário; o efeito de cada dia é estimado
do histórico (sem os parâmetros do gerador). Séries sintéticas de efeito conhecido."""

import ast
import pathlib
from datetime import date

import numpy as np
import pandas as pd
import pytest

from src import config
from src.calendario import black_friday
from src.previsao import modelos
from src.previsao.painel import Painel

SEMANA = np.array([0.9, 0.88, 0.92, 0.95, 1.10, 1.25, 0.70])
# efeito inventado do teste (dias desde a sexta-feira -> multiplicador); nada a ver com o gerador
EFEITO_BF = {-2: 1.3, -1: 1.6, 0: 3.0, 1: 2.0, 2: 1.4}


def _serie(inicio, fim, anos_com_efeito):
    datas = pd.date_range(inicio, fim)
    y = 1000.0 * SEMANA[datas.day_of_week]
    for ano in anos_com_efeito:
        for k, mult in EFEITO_BF.items():
            dia = pd.Timestamp(black_friday(ano)) + pd.Timedelta(days=k)
            if dia in datas:
                y[datas.get_loc(dia)] *= mult
    return datas, y


def _fator(datas, y, ano=2024):
    f = modelos.estimar_fatores(datas, y)
    sexta = pd.Timestamp(black_friday(ano))
    return {
        k: f.fator_black_friday(pd.DatetimeIndex([sexta + pd.Timedelta(days=k)]))[0]
        for k in EFEITO_BF
    }


@pytest.mark.parametrize("anos", [[2024], [2023, 2024]])
def test_com_k_zero_o_efeito_e_a_razao_inteira_do_historico(anos, monkeypatch):
    monkeypatch.setattr(config, "PREVISAO_BLACK_FRIDAY_K", 0.0)
    # o histórico começa no primeiro ano com efeito (um ano sem efeito também contaria como ano)
    datas, y = _serie(f"{min(anos)}-01-01", "2024-12-31", anos)
    for k, mult in EFEITO_BF.items():
        assert _fator(datas, y)[k] == pytest.approx(mult, rel=0.03), k


@pytest.mark.parametrize("anos", [[2024], [2023, 2024]])
def test_com_k_positivo_o_efeito_encolhe_com_n_sobre_n_mais_k(anos, monkeypatch):
    monkeypatch.setattr(config, "PREVISAO_BLACK_FRIDAY_K", 1.0)
    datas, y = _serie(f"{min(anos)}-01-01", "2024-12-31", anos)
    peso = len(anos) / (len(anos) + 1.0)
    for k, mult in EFEITO_BF.items():
        assert _fator(datas, y)[k] == pytest.approx(mult**peso, rel=0.03), k


def test_dia_sem_efeito_dentro_da_janela_e_dia_fora_dela_valem_um(monkeypatch):
    monkeypatch.setattr(config, "PREVISAO_BLACK_FRIDAY_K", 0.0)
    datas, y = _serie("2024-01-01", "2024-12-31", [2024])
    f = modelos.estimar_fatores(datas, y)
    sexta = pd.Timestamp(black_friday(2025))
    assert f.fator_black_friday(pd.DatetimeIndex([sexta + pd.Timedelta(days=5)]))[0] == (
        pytest.approx(1.0, rel=0.03)
    )
    assert f.fator_black_friday(pd.DatetimeIndex(["2025-10-10"]))[0] == 1.0
    assert f.fator_black_friday(pd.DatetimeIndex([sexta]))[0] == pytest.approx(3.0, rel=0.03)


def test_sem_historico_do_evento_o_fator_e_um():
    datas, y = _serie("2024-01-01", "2024-10-31", [])
    f = modelos.estimar_fatores(datas, y)
    assert f.black_friday == {}
    assert (f.fator_black_friday(pd.date_range("2025-11-15", "2025-12-05")) == 1.0).all()


def test_janela_incompleta_nos_dados_nao_gera_fator():
    # os dados acabam no meio da janela da Black Friday: o ano não conta
    datas, y = _serie("2024-01-01", "2024-11-30", [2024])
    assert modelos.estimar_fatores(datas, y).black_friday == {}


def test_janela_da_black_friday_fica_fora_do_fator_do_dia_da_semana():
    datas, y_com = _serie("2023-01-01", "2024-12-31", [2023, 2024])
    _, y_sem = _serie("2023-01-01", "2024-12-31", [])
    com = modelos.estimar_fatores(datas, y_com)
    sem = modelos.estimar_fatores(datas, y_sem)
    assert com.dia_semana == pytest.approx(sem.dia_semana, rel=0.01)


def test_black_friday_sai_do_nivel_recente_e_a_previsao_nao_e_inflada(monkeypatch):
    monkeypatch.setattr(config, "PREVISAO_BLACK_FRIDAY_K", 0.0)
    # origem 12 dias depois da Black Friday de 2025: os últimos 56 dias contêm o pico, que o fator
    # aprendido em 2023-2024 desconta; os dias seguintes (sem efeito) voltam ao patamar normal
    datas, y = _serie("2023-01-01", "2025-12-10", [2023, 2024, 2025])
    painel = Painel(datas, [(1, "Alimentos")], np.array([y]))
    alvo = pd.date_range("2025-12-11", "2025-12-12")
    previsto = modelos.prever_decomposicao(painel, alvo)[0]
    real = 1000.0 * SEMANA[alvo.day_of_week]
    assert previsto == pytest.approx(real, rel=0.12)


def test_a_previsao_da_black_friday_usa_o_efeito_aprendido(monkeypatch):
    monkeypatch.setattr(config, "PREVISAO_BLACK_FRIDAY_K", 0.0)
    datas, y = _serie("2024-01-01", "2025-11-30", [2024, 2025])
    painel = Painel(datas, [(1, "Alimentos")], np.array([y])).ate(date(2025, 10, 31))
    alvo = pd.date_range("2025-11-20", "2025-12-05")
    alvo = alvo[alvo <= "2025-11-30"]
    previsto = modelos.prever_decomposicao(painel, alvo)[0]
    real = y[datas.get_indexer(alvo)]
    sem_efeito = 1000.0 * SEMANA[alvo.day_of_week]
    assert abs(previsto.sum() - real.sum()) < abs(sem_efeito.sum() - real.sum()) * 0.3


# --- nada do gerador entra no módulo de previsão -------------------------------------------------
PARAMETROS_DO_GERADOR = {
    "FATOR_SAZONAL_MES", "FATOR_DIA_SEMANA", "BLACK_FRIDAY_FATORES", "NATAL_JANELA_DIAS",
    "NATAL_FATOR_JANELA", "NATAL_FATOR_DIA", "FATOR_FERIADO_NACIONAL", "MULT_SETOR_MES",
    "MULT_SETOR_BLACK_FRIDAY", "FATOR_ORCAMENTO_PESSOAL_MES", "campanhas_do_ano",
}  # fmt: skip
MODULOS_PROIBIDOS = ("src.gerador", "src.calendario_comercial")


def _usos_proibidos(caminho: pathlib.Path) -> list[str]:
    arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    achados = []
    for no in ast.walk(arvore):
        if isinstance(no, ast.ImportFrom):
            modulo = no.module or ""
            if modulo.startswith(MODULOS_PROIBIDOS):
                achados.append(f"{caminho.name}: from {modulo}")
            achados += [
                f"{caminho.name}: importa {a.name}"
                for a in no.names
                if a.name in PARAMETROS_DO_GERADOR
            ]
        elif isinstance(no, ast.Import):
            achados += [
                f"{caminho.name}: import {a.name}"
                for a in no.names
                if a.name.startswith(MODULOS_PROIBIDOS)
            ]
        elif isinstance(no, ast.Attribute) and no.attr in PARAMETROS_DO_GERADOR:
            achados.append(f"{caminho.name}: usa {no.attr}")
        elif isinstance(no, ast.Name) and no.id in PARAMETROS_DO_GERADOR:
            achados.append(f"{caminho.name}: usa {no.id}")
    return achados


def test_o_modulo_de_previsao_nao_usa_parametros_do_gerador():
    raiz = pathlib.Path(__file__).resolve().parents[2] / "src" / "previsao"
    arquivos = sorted(raiz.glob("*.py"))
    assert len(arquivos) > 5
    achados = [x for arquivo in arquivos for x in _usos_proibidos(arquivo)]
    assert achados == []


def test_o_detector_de_uso_proibido_funciona(tmp_path):
    ruim = tmp_path / "ruim.py"
    ruim.write_text(
        "from src import config\nx = config.BLACK_FRIDAY_FATORES\n"
        "from src.gerador.catalogo import SETORES\n",
        encoding="utf-8",
    )
    achados = _usos_proibidos(ruim)
    assert len(achados) == 2 and any("BLACK_FRIDAY_FATORES" in a for a in achados)


def test_a_data_da_black_friday_vem_do_calendario():
    assert black_friday(2025) == date(2025, 11, 28)
    assert black_friday(2024) == date(2024, 11, 29)
