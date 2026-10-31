"""Métricas, escolha da abordagem e faixa do backtest, com séries sintéticas."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from src import config
from src.previsao import backtest, faixa
from src.previsao.painel import Painel

DIAS = pd.date_range("2025-03-16", periods=2)  # os dois dias caem no mesmo mês


class TestAvaliar:
    def test_wape_e_vies_conferem_com_a_conta_feita_a_mao(self):
        real = np.array([[10.0, 20.0], [30.0, 40.0]])
        previsto = np.array([[12.0, 18.0], [30.0, 50.0]])
        chaves = [(1, "A"), (1, "B")]
        m = backtest.avaliar("x", real, previsto, chaves, DIAS)

        def pegar(nivel, gran, loja=None, setor=None, agregado=True):
            sel = m[(m.nivel == nivel) & (m.granularidade == gran) & (m.agregado == agregado)]
            if loja is not None:
                sel = sel[sel.sk_loja == loja]
            if setor is not None:
                sel = sel[sel.setor == setor]
            assert len(sel) == 1
            return sel.iloc[0]

        rede_dia = pegar("rede", "dia")
        assert rede_dia.wape == pytest.approx(10 / 100)  # totais do dia: 40x42 e 60x68
        assert rede_dia.vies == pytest.approx(0.10)
        assert pegar("rede", "mes").wape == pytest.approx(10 / 100)  # 30x30 e 70x80
        assert pegar("loja_setor", "dia", 1, "A", False).wape == pytest.approx(4 / 30)
        assert pegar("loja_setor", "mes", 1, "B", False).vies == pytest.approx(80 / 70 - 1)
        assert pegar("setor", "dia", setor="B", agregado=False).wape == pytest.approx(10 / 70)
        assert pegar("loja", "mes", loja=1, agregado=False).wape == pytest.approx(10 / 100)

    def test_agregado_do_nivel_junta_todos_os_pontos(self):
        real = np.array([[100.0, 100.0], [10.0, 10.0]])
        previsto = np.array([[100.0, 100.0], [20.0, 20.0]])
        m = backtest.avaliar("x", real, previsto, [(1, "A"), (2, "A")], DIAS)
        agregado = m[(m.nivel == "loja_setor") & (m.granularidade == "dia") & m.agregado]
        assert agregado.wape.iloc[0] == pytest.approx(20 / 220)

    def test_serie_sem_venda_no_periodo_nao_gera_linha(self):
        real = np.array([[0.0, 0.0], [5.0, 5.0]])
        m = backtest.avaliar("x", real, real, [(1, "A"), (2, "A")], DIAS)
        unidades = m[(m.nivel == "loja_setor") & ~m.agregado]
        assert unidades.sk_loja.tolist() == [2, 2]


def _painel_sintetico() -> Painel:
    datas = pd.date_range("2025-01-01", "2025-04-30")
    base = 100 + 10 * datas.day_of_week.to_numpy()
    valores = np.array([base, base * 2.0, base * 0.5])
    return Painel(datas, [(1, "A"), (1, "B"), (2, "A")], valores)


def _perfeito(painel_total: Painel):
    def modelo(treino, alvo):
        return painel_total.valores[:, [painel_total.posicao(d) for d in alvo]]

    return modelo


class TestExecutar:
    def _rodar(self, modelos, **extra):
        painel = _painel_sintetico()
        return backtest.executar(
            painel, date(2025, 3, 15), date(2025, 3, 16), date(2025, 4, 30),
            modelos=modelos, origem_calibracao=date(2025, 2, 15), **extra,
        )  # fmt: skip

    def test_escolhe_a_abordagem_de_menor_wape_mensal_por_loja_e_setor(self):
        painel = _painel_sintetico()
        modelos = {
            "perfeita": _perfeito(painel),
            "otimista": lambda t, a: _perfeito(painel)(t, a) * 1.2,
        }
        resultado = self._rodar(modelos)
        assert resultado.escolhido == "perfeita"
        m = resultado.metricas
        otimista = m[(m.modelo == "otimista") & (m.nivel == "rede") & (m.granularidade == "mes")]
        assert otimista.vies.iloc[0] == pytest.approx(0.2)
        assert resultado.ignoradas == []

    def test_serie_que_algum_modelo_nao_preve_sai_da_comparacao_de_todos(self):
        painel = _painel_sintetico()

        def sem_a_segunda(treino, alvo):
            previsto = _perfeito(painel)(treino, alvo).copy()
            previsto[1] = np.nan
            return previsto

        resultado = self._rodar({"a": _perfeito(painel), "b": sem_a_segunda})
        assert resultado.ignoradas == [(1, "B")]
        assert (1, "B") not in resultado.chaves
        assert set(resultado.metricas.modelo) == {"a", "b"}

    def test_cobertura_vem_dentro_e_fora_da_amostra_por_loja_e_na_rede(self):
        painel = _painel_sintetico()
        resultado = self._rodar({"perfeita": _perfeito(painel)})
        c = resultado.cobertura
        assert set(c.origem_faixa) == {"fora_da_amostra", "na_amostra"}
        assert set(c.granularidade) == {"dia", "mes"}
        rede = c[c.sk_loja.isna()]
        assert len(rede) == 4
        assert set(c.sk_loja.dropna().astype(int)) == {1, 2}
        assert (c.cobertura == 1.0).all()  # previsão perfeita: tudo dentro da faixa

    def test_sem_origem_de_calibracao_so_ha_cobertura_na_amostra(self):
        painel = _painel_sintetico()
        resultado = backtest.executar(
            painel, date(2025, 3, 15), date(2025, 3, 16), date(2025, 4, 30),
            modelos={"perfeita": _perfeito(painel)}, origem_calibracao=None,
        )  # fmt: skip
        assert set(resultado.cobertura.origem_faixa) == {"na_amostra"}

    def test_wape_da_serie_do_modelo_escolhido(self):
        painel = _painel_sintetico()
        resultado = self._rodar({"x": lambda t, a: _perfeito(painel)(t, a) * 1.1})
        assert resultado.wape_da_serie(1, "A", "mes") == pytest.approx(0.1)
        assert resultado.wape_da_serie(9, "Z", "mes") is None

    def test_registra_tempo_e_memoria(self):
        painel = _painel_sintetico()
        resultado = self._rodar({"x": _perfeito(painel)})
        assert resultado.duracao_s > 0 and resultado.pico_memoria_gb > 0


class TestFaixa:
    def _dados(self):
        rng = np.random.default_rng(7)
        datas = pd.date_range("2025-07-01", periods=184)
        previsto = np.full((6, len(datas)), 100.0)
        real = previsto * rng.uniform(0.5, 1.5, previsto.shape)
        return datas, real, previsto, ["A", "A", "A", "B", "B", "B"]

    def test_calibrada_nos_proprios_dados_cobre_perto_do_alvo(self):
        datas, real, previsto, setores = self._dados()
        faixas = faixa.calibrar_faixas(real, previsto, setores, datas)
        cobertura = faixa.cobertura(real, previsto, setores, faixas, datas, "dia")
        assert cobertura.mean() == pytest.approx(config.PREVISAO_COBERTURA_ALVO, abs=0.03)

    def test_faixa_sempre_envolve_o_previsto_mesmo_com_modelo_enviesado(self):
        datas = pd.date_range("2025-07-01", periods=10)
        previsto = np.full((1, 10), 100.0)
        real = previsto * 2.0  # o modelo prevê sempre metade do real
        faixas = faixa.calibrar_faixas(real, previsto, ["A"], datas)
        baixo, alto = faixa.aplicar_faixa(previsto, ["A"], faixas, "dia")
        assert (baixo <= previsto).all() and (alto >= previsto).all()
        assert (alto == 200.0).all()

    def test_mes_soma_os_dias_do_mes_civil(self):
        datas = pd.date_range("2025-07-30", periods=4)  # 2 dias em julho, 2 em agosto
        soma = faixa.somar_por_mes(np.array([[1.0, 2.0, 3.0, 4.0]]), datas)
        assert soma.tolist() == [[3.0, 7.0]]
