"""Modelos de previsão com séries sintéticas de resultado conhecido (sem banco, sem arquivos)."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from src import config
from src.previsao import modelos
from src.previsao.painel import Painel, montar_painel

SEMANA = np.array([0.9, 0.88, 0.92, 0.95, 1.10, 1.25, 0.70])  # segunda..domingo
FATOR_MES = {1: 0.9, 2: 0.95, 3: 1.0, 4: 1.0, 5: 1.1, 6: 1.0, 7: 1.0, 8: 1.0, 9: 1.0,
             10: 1.0, 11: 1.15, 12: 1.3}  # fmt: skip


def _painel(datas, linhas) -> Painel:
    return Painel(datas, [(i + 1, "Alimentos") for i in range(len(linhas))], np.array(linhas))


def _serie_conhecida(inicio: str, fim: str, nivel: float, crescimento_mensal: float = 0.0):
    datas = pd.date_range(inicio, fim)
    meses = np.arange(len(datas)) / modelos.DIAS_POR_MES
    mes = np.array([FATOR_MES[d.month] for d in datas])
    return datas, nivel * np.exp(crescimento_mensal * meses) * SEMANA[datas.day_of_week] * mes


class TestPainel:
    def test_antes_da_primeira_venda_e_nan_e_depois_dia_sem_venda_e_zero(self):
        linhas = pd.DataFrame(
            {
                "data": [date(2024, 1, 3), date(2024, 1, 3), date(2024, 1, 5), date(2024, 1, 2)],
                "sk_loja": [1, 1, 1, 2],
                "setor": ["Casa", "Casa", "Casa", "Casa"],
                "valor": [10.0, 5.0, 7.0, 3.0],
            }
        )
        painel = montar_painel(linhas, date(2024, 1, 1), date(2024, 1, 6))
        assert painel.chaves == [(1, "Casa"), (2, "Casa")]
        assert np.isnan(painel.valores[0, :2]).all()
        assert painel.valores[0, 2:].tolist() == [15.0, 0.0, 7.0, 0.0]
        assert np.isnan(painel.valores[1, 0]) and painel.valores[1, 1] == 3.0

    def test_ate_corta_no_dia_inclusive(self):
        painel = _painel(pd.date_range("2024-01-01", "2024-01-10"), [np.arange(10.0)])
        assert painel.ate(date(2024, 1, 4)).valores.shape == (1, 4)
        assert painel.posicao(date(2024, 1, 4)) == 3


class TestIngenua:
    def test_repete_o_mesmo_dia_da_semana_de_364_dias_antes(self):
        datas, y = _serie_conhecida("2024-01-01", "2025-06-30", 100.0)
        painel = _painel(datas, [y])
        alvo = pd.date_range("2025-07-01", "2025-07-14")
        previsto = modelos.prever_ingenua(painel, alvo)[0]
        esperado = [y[painel.posicao(d - pd.Timedelta(days=364))] for d in alvo]
        assert previsto == pytest.approx(esperado)
        assert all(d.day_of_week == (d - pd.Timedelta(days=364)).day_of_week for d in alvo)

    def test_sem_ano_anterior_usa_a_media_dos_ultimos_28_dias(self):
        datas = pd.date_range("2025-03-01", "2025-06-30")
        y = np.full(len(datas), 50.0)
        previsto = modelos.prever_ingenua(
            _painel(datas, [y]), pd.date_range("2025-07-01", periods=3)
        )
        assert previsto[0].tolist() == [50.0, 50.0, 50.0]

    def test_serie_curta_demais_nao_e_prevista(self):
        datas = pd.date_range("2025-06-01", "2025-06-30")
        y = np.r_[np.full(10, np.nan), np.full(20, 5.0)]
        previsto = modelos.prever_ingenua(
            _painel(datas, [y]), pd.date_range("2025-07-01", periods=3)
        )
        assert np.isnan(previsto).all()

    def test_horizonte_alem_de_um_ano_recua_mais_um_ano(self):
        datas, y = _serie_conhecida("2024-01-01", "2024-12-31", 100.0)
        painel = _painel(datas, [y])
        dia = pd.Timestamp("2025-12-29")  # 364 dias antes (2024-12-30) ainda cai no treino
        assert modelos.prever_ingenua(painel, pd.DatetimeIndex([dia]))[0, 0] == pytest.approx(
            y[painel.posicao("2024-12-30")]
        )
        dia = pd.Timestamp("2026-01-05")  # recua 728 dias
        assert modelos.prever_ingenua(painel, pd.DatetimeIndex([dia]))[0, 0] == pytest.approx(
            y[painel.posicao(dia - pd.Timedelta(days=728))]
        )


class TestHoltWinters:
    def test_padrao_semanal_puro_e_reproduzido_sem_erro(self):
        datas = pd.date_range("2025-01-06", periods=140)  # começa numa segunda
        y = 200.0 + np.tile([-20, -25, -10, 0, 30, 50, -25], 20)
        previsto = modelos.ajustar_holt_winters(y, 14)
        assert previsto == pytest.approx(np.tile(y[:7], 2), abs=1e-6)
        assert len(datas) == len(y)

    def test_tendencia_linear_sem_amortecimento_e_extrapolada_com_exatidao(self):
        padrao = np.tile([-20.0, -25, -10, 0, 30, 50, -25], 20)
        y = 100.0 + 2.0 * np.arange(140) + padrao
        previsto = modelos.ajustar_holt_winters(y, 7, phi=1.0)
        esperado = 100.0 + 2.0 * np.arange(140, 147) + padrao[:7]
        assert previsto == pytest.approx(esperado, abs=1e-6)

    def test_nunca_preve_valor_negativo(self):
        y = np.tile([0.0, 0, 0, 0, 0, 0, 100], 12)
        assert (modelos.ajustar_holt_winters(y, 14) >= 0).all()

    def test_modelo_usa_o_painel_e_devolve_a_forma_certa(self):
        datas, y = _serie_conhecida("2024-01-01", "2025-06-30", 100.0)
        painel = _painel(datas, [y, y * 2])
        alvo = pd.date_range("2025-07-01", "2025-07-31")
        previsto = modelos.prever_holt_winters(painel, alvo)
        assert previsto.shape == (2, 31)
        assert previsto[1] == pytest.approx(previsto[0] * 2, rel=1e-6)


class TestDecomposicao:
    def test_fatores_de_dia_da_semana_e_crescimento_sao_recuperados(self):
        datas, y = _serie_conhecida("2024-01-01", "2025-06-30", 1000.0, crescimento_mensal=0.01)
        fatores = modelos.estimar_fatores(datas, y)
        assert fatores.dia_semana == pytest.approx(SEMANA / SEMANA.mean(), rel=0.02)
        assert fatores.crescimento_mensal == pytest.approx(0.01, abs=0.003)

    def test_fator_de_natal_e_recuperado_e_melhora_a_previsao_da_janela(self):
        datas, y = _serie_conhecida("2024-01-01", "2025-12-31", 1000.0)
        janela = modelos._janela_natal(datas)
        y = np.where(janela, y * 1.4, y)
        fatores = modelos.estimar_fatores(
            datas[datas <= "2024-12-31"], y[: (datas <= "2024-12-31").sum()]
        )
        assert fatores.natal == pytest.approx(1.4, rel=0.03)
        painel = _painel(datas, [y]).ate(date(2025, 12, 14))
        alvo = pd.date_range("2025-12-15", "2025-12-24")
        previsto = modelos.prever_decomposicao(painel, alvo)[0]
        assert previsto.sum() == pytest.approx(y[-17:-7].sum(), rel=0.08)

    def test_sem_janela_de_natal_completa_o_fator_e_neutro(self):
        datas, y = _serie_conhecida("2024-01-01", "2024-12-20", 1000.0)
        assert modelos.estimar_fatores(datas, y).natal == 1.0

    def test_fator_do_mes_sai_normalizado_e_ordenado(self):
        datas, y = _serie_conhecida("2024-01-01", "2025-06-30", 1000.0)
        fatores = modelos.estimar_fatores(datas, y)
        assert fatores.mes.mean() == pytest.approx(1.0)
        assert fatores.mes[4] > fatores.mes[0]  # maio acima de janeiro

    def test_preve_o_total_dos_meses_seguintes_perto_do_real(self):
        datas, y = _serie_conhecida("2024-01-01", "2025-09-30", 1000.0, crescimento_mensal=0.01)
        corte = pd.Timestamp("2025-06-30")
        painel = _painel(datas, [y, y * 0.5]).ate(corte.date())
        alvo = pd.date_range("2025-07-01", "2025-09-30")
        previsto = modelos.prever_decomposicao(painel, alvo)
        real = np.array([y, y * 0.5])[:, -len(alvo) :]
        for mes in (7, 8, 9):
            sel = alvo.month == mes
            assert previsto[:, sel].sum() == pytest.approx(real[:, sel].sum(), rel=0.08)

    def test_serie_recem_aberta_usa_os_fatores_do_setor_e_o_nivel_proprio(self):
        datas, y = _serie_conhecida("2024-01-01", "2025-06-30", 1000.0)
        nova = y.copy()
        nova[: len(y) - 120] = np.nan  # abriu há 120 dias, com metade do volume
        nova = nova * 0.5
        painel = _painel(datas, [y, nova])
        previsto = modelos.prever_decomposicao(painel, pd.date_range("2025-07-01", periods=30))
        assert previsto[1].sum() == pytest.approx(previsto[0].sum() * 0.5, rel=0.05)

    def test_serie_sem_historico_suficiente_volta_nan(self):
        datas, y = _serie_conhecida("2024-01-01", "2025-06-30", 1000.0)
        curta = np.full(len(y), np.nan)
        curta[-10:] = 5.0
        previsto = modelos.prever_decomposicao(
            _painel(datas, [y, curta]), pd.date_range("2025-07-01", periods=7)
        )
        assert np.isnan(previsto[1]).all() and np.isfinite(previsto[0]).all()


class TestHoltWintersMensal:
    def test_aplica_o_fator_do_mes_sobre_o_holt_winters(self):
        datas, y = _serie_conhecida("2024-01-01", "2025-10-31", 1000.0)
        painel = _painel(datas, [y]).ate(date(2025, 10, 31))
        alvo = pd.date_range("2025-11-01", "2025-12-31")
        puro = modelos.prever_holt_winters(painel, alvo)[0]
        ajustado = modelos.prever_holt_winters_mensal(painel, alvo)[0]
        razao = ajustado.sum() / puro.sum()
        assert razao > 1.1  # novembro e dezembro têm fatores bem acima de outubro


def test_registro_tem_os_quatro_modelos_e_a_versao():
    assert set(modelos.MODELOS) == {
        "ingenua", "decomposicao", "holt_winters", "holt_winters_mensal"
    }  # fmt: skip
    assert modelos.versao_do_modelo("ingenua") == f"ingenua@{config.PREVISAO_VERSAO_MODELO}"
