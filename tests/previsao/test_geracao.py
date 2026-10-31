"""Geração da previsão e gravação no dw (a gravação e o comando `gerar` precisam de PostgreSQL)."""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from src import config
from src.previsao import backtest, geracao
from src.previsao.__main__ import principal
from src.previsao.painel import Painel
from tests.etl import base_alertas as b


def _painel() -> Painel:
    datas = pd.date_range("2025-01-01", "2025-06-30")
    base = 100 + 10 * datas.day_of_week.to_numpy()
    return Painel(datas, [(1, "A"), (2, "B")], np.array([base, base * 2.0]))


def _constante(treino, alvo):
    """Modelo de teste: repete a última semana do treino."""
    ultima = treino.valores[:, -7:]
    return np.stack([ultima[:, (d - treino.datas[-1]).days % 7 - 1] for d in alvo], axis=1)


def _resultado(painel: Painel) -> backtest.ResultadoBacktest:
    completo = Painel(pd.date_range("2025-01-01", "2025-06-30"), painel.chaves, painel.valores)
    return backtest.executar(
        completo, date(2025, 5, 31), date(2025, 6, 1), date(2025, 6, 30),
        modelos={"constante": _constante}, origem_calibracao=date(2025, 4, 30),
    )  # fmt: skip


class TestGerar:
    def test_dia_e_mes_batem_entre_si_e_a_faixa_envolve_o_previsto(self):
        painel = _painel()
        resultado = _resultado(painel)
        previsao = geracao.gerar(
            painel, resultado, date(2025, 9, 30), modelos={"constante": _constante}
        )
        linhas = previsao.linhas
        dias = linhas[linhas.granularidade == "dia"]
        meses = linhas[linhas.granularidade == "mes"]
        assert len(dias) == 2 * 92 and len(meses) == 2 * 3
        assert sorted(meses.data.unique()) == [date(2025, 7, 1), date(2025, 8, 1), date(2025, 9, 1)]
        soma = (
            dias.assign(mes=[d.replace(day=1) for d in dias.data])
            .groupby(["sk_loja", "mes"])
            .valor_previsto.sum()
        )
        for linha in meses.itertuples():
            assert soma[(linha.sk_loja, linha.data)] == pytest.approx(linha.valor_previsto, abs=0.5)
        assert (linhas.valor_baixo <= linhas.valor_previsto).all()
        assert (linhas.valor_previsto <= linhas.valor_alto).all()
        assert previsao.versao == f"constante@{config.PREVISAO_VERSAO_MODELO}"
        assert previsao.inicio == date(2025, 7, 1) and previsao.treino_ate == date(2025, 6, 30)

    def test_mes_incompleto_nao_gera_linha_mensal(self):
        painel = _painel()
        previsao = geracao.gerar(
            painel, _resultado(painel), date(2025, 7, 20), modelos={"constante": _constante}
        )
        assert (previsao.linhas.granularidade == "dia").all()

    def test_meses_completos(self):
        assert geracao.meses_completos(date(2025, 12, 16), date(2026, 2, 28)) == [
            date(2026, 1, 1),
            date(2026, 2, 1),
        ]
        assert geracao.meses_completos(date(2026, 1, 1), date(2026, 1, 31)) == [date(2026, 1, 1)]
        assert geracao.meses_completos(date(2026, 1, 2), date(2026, 1, 31)) == []

    def test_serie_que_o_modelo_nao_preve_fica_de_fora_e_e_informada(self):
        painel = _painel()
        resultado = _resultado(painel)

        def falha_na_segunda(treino, alvo):
            previsto = _constante(treino, alvo).copy()
            previsto[1] = np.nan
            return previsto

        previsao = geracao.gerar(
            painel, resultado, date(2025, 7, 31), modelos={"constante": falha_na_segunda}
        )
        assert previsao.sem_previsao == [(2, "B")]
        assert set(previsao.linhas.sk_loja) == {1}


pytestmark_banco = pytest.mark.banco


@pytest.fixture
def base(banco_com_ddl):
    b.montar_base(banco_com_ddl, ano=2025)
    return banco_com_ddl


def _vender_o_ano(con, loja="L01"):
    dia = date(2025, 1, 1)
    n = 0
    while dia.year == 2025:
        n += 1
        valor = 100.0 * (1 + 0.1 * dia.weekday())
        b.item(
            con, f"{loja}-{n}", cupom=f"{loja}-C{n}", data=dia.isoformat(), loja=loja, receita=valor
        )
        dia += timedelta(days=1)
    con.commit()


def _contar(con, tabela="dw.previsao_vendas", where="TRUE") -> int:
    return con.execute(f"SELECT count(*) FROM {tabela} WHERE {where}").fetchone()[0]


@pytestmark_banco
class TestGravacao:
    def _previsao_e_resultado(self, base, fim=date(2026, 3, 31)):
        _vender_o_ano(base)
        from src.previsao import dados

        painel = dados.ler_painel(base, date(2025, 1, 1), date(2025, 12, 31))
        resultado = backtest.executar(painel)
        return painel, resultado, geracao.gerar(painel, resultado, fim)

    def test_grava_dia_e_mes_e_regravar_nao_duplica(self, base):
        _, _, previsao = self._previsao_e_resultado(base)
        n = geracao.gravar_previsao(base, previsao)
        assert n == len(previsao.linhas) == 90 + 3
        assert _contar(base) == 93 and _contar(base, where="granularidade = 'mes'") == 3
        geracao.gravar_previsao(base, previsao)
        assert _contar(base) == 93

    def test_horizonte_menor_substitui_o_anterior_e_cortes_diferentes_convivem(self, base):
        painel, resultado, longa = self._previsao_e_resultado(base)
        geracao.gravar_previsao(base, longa)
        curta = geracao.gerar(painel, resultado, date(2026, 1, 31))
        geracao.gravar_previsao(base, curta)
        assert _contar(base) == 31 + 1
        outro_corte = geracao.gerar(painel.ate(date(2025, 12, 15)), resultado, date(2025, 12, 31))
        geracao.gravar_previsao(base, outro_corte)
        assert _contar(base) == 32 + 16
        assert _contar(base, where="treino_ate = '2025-12-15'") == 16

    def test_linha_gravada_traz_modelo_corte_faixa_e_erro_do_backtest(self, base):
        _, resultado, previsao = self._previsao_e_resultado(base)
        geracao.gravar_previsao(base, previsao)
        linha = base.execute(
            "SELECT versao_modelo, treino_ate, valor_baixo <= valor_previsto, wape_backtest,"
            " gerado_em IS NOT NULL FROM dw.previsao_vendas WHERE granularidade = 'mes' LIMIT 1"
        ).fetchone()
        assert linha[0] == previsao.versao and linha[1] == date(2025, 12, 31)
        assert linha[2] and linha[4]
        assert float(linha[3]) == pytest.approx(
            resultado.wape_da_serie(1, "Alimentos", "mes"), abs=1e-4
        )

    def test_grava_o_backtest_e_regravar_nao_duplica(self, base):
        _, resultado, _ = self._previsao_e_resultado(base)
        n = geracao.gravar_backtest(base, resultado)
        assert n == len(resultado.metricas) and _contar(base, "dw.previsao_backtest") == n
        geracao.gravar_backtest(base, resultado)
        assert _contar(base, "dw.previsao_backtest") == n
        escolhidas = base.execute(
            "SELECT DISTINCT versao_modelo FROM dw.previsao_backtest WHERE escolhido"
        ).fetchall()
        assert escolhidas == [(f"{resultado.escolhido}@{config.PREVISAO_VERSAO_MODELO}",)]
        com_cobertura = base.execute(
            "SELECT nivel, count(*) FROM dw.previsao_backtest WHERE cobertura_faixa IS NOT NULL"
            " GROUP BY nivel ORDER BY nivel"
        ).fetchall()
        assert com_cobertura == [("loja", 2), ("rede", 2)]  # (dia, mês) x (1 loja | rede)

    def test_falha_na_gravacao_desfaz_tudo(self, base):
        _, _, previsao = self._previsao_e_resultado(base)
        ruim = previsao.linhas.copy()
        ruim.loc[0, "sk_loja"] = 999  # loja inexistente: viola a chave estrangeira
        previsao.linhas = ruim
        with pytest.raises(Exception, match="previsao_vendas"):
            geracao.gravar_previsao(base, previsao)
        assert _contar(base) == 0


@pytestmark_banco
class TestCliGerar:
    def test_gerar_sem_gravar_nao_escreve_no_dw(self, base, capsys):
        _vender_o_ano(base)
        assert principal(["gerar"], conexao=base, verificar_memoria=None) == 0
        saida = capsys.readouterr().out
        assert "de 01/01/2026 a 31/03/2026" in saida
        assert "01/2026" in saida and "03/2026" in saida
        assert _contar(base) == 0

    def test_gerar_gravar_e_idempotente(self, base, capsys):
        _vender_o_ano(base)
        assert principal(["gerar", "--gravar"], conexao=base, verificar_memoria=None) == 0
        assert "gravado no dw" in capsys.readouterr().out
        total = _contar(base)
        assert total == 90 + 3
        assert principal(["gerar", "--gravar"], conexao=base, verificar_memoria=None) == 0
        assert _contar(base) == total

    def test_corte_no_meio_do_mes_compara_com_o_real(self, base, capsys):
        _vender_o_ano(base)
        argumentos = ["gerar", "--corte", "2025-12-15", "--ate", "2025-12-31"]
        assert principal(argumentos, conexao=base, verificar_memoria=None) == 0
        saida = capsys.readouterr().out
        assert "treino até 15/12/2025" in saida and "12/2025" in saida
        linha = next(x for x in saida.splitlines() if x.startswith("12/2025"))
        assert "%" in linha  # há real nesse mês: o desvio aparece

    @pytest.mark.parametrize(
        "argumentos",
        [
            ["gerar", "--corte", "2026-02-01"],
            ["gerar", "--corte", "2025-12-15", "--ate", "2025-12-10"],
            ["gerar", "--corte", "ontem"],
        ],
    )
    def test_argumentos_invalidos_saem_com_2(self, base, argumentos):
        _vender_o_ano(base)
        assert principal(argumentos, conexao=base, verificar_memoria=None) == 2
