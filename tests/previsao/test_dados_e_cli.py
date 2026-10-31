"""Leitura das séries no dw e o comando `python -m src.previsao backtest` (usam PostgreSQL)."""

from datetime import date, timedelta

import numpy as np
import pytest

from src.memoria import MemoriaInsuficiente
from src.previsao import dados
from src.previsao.__main__ import principal
from tests.etl import base_alertas as b

pytestmark = pytest.mark.banco


@pytest.fixture
def base(banco_com_ddl):
    b.montar_base(banco_com_ddl, ano=2025)
    return banco_com_ddl


def _vender_o_ano(con, loja="L01", receita_base=100.0):
    dia = date(2025, 1, 1)
    n = 0
    while dia.year == 2025:
        n += 1
        valor = receita_base * (1 + 0.1 * dia.weekday())
        b.item(
            con, f"{loja}-{n}", cupom=f"{loja}-C{n}", data=dia.isoformat(), loja=loja, receita=valor
        )
        dia += timedelta(days=1)
    con.commit()


class TestDados:
    def test_painel_soma_por_dia_ignora_cancelada_e_marca_antes_da_primeira_venda(self, base):
        b.item(base, "A1", cupom="C1", data="2025-01-03", receita=100)
        b.item(base, "A2", cupom="C1", numero_item=2, data="2025-01-03", receita=50)
        b.item(base, "A3", cupom="C2", data="2025-01-05", receita=70)
        b.item(base, "A4", cupom="C3", data="2025-01-04", receita=999, status="Cancelada")
        b.item(base, "A5", cupom="C4", data="2025-01-02", loja="L02", receita=30)
        painel = dados.ler_painel(base, date(2025, 1, 1), date(2025, 1, 6))
        assert [setor for _, setor in painel.chaves] == ["Alimentos", "Alimentos"]
        l01, l02 = painel.valores
        assert np.isnan(l01[:2]).all()
        assert l01[2:].tolist() == [150.0, 0.0, 70.0, 0.0]
        assert l02[1] == 30.0 and np.isnan(l02[0])  # NaN antes da primeira venda

    def test_ultimo_e_primeiro_dia_com_venda_ignoram_canceladas(self, base):
        b.item(base, "A1", cupom="C1", data="2025-01-03")
        b.item(base, "A2", cupom="C2", data="2025-02-10")
        b.item(base, "A3", cupom="C3", data="2025-03-01", status="Cancelada")
        assert dados.primeiro_dia_com_venda(base) == date(2025, 1, 3)
        assert dados.ultimo_dia_com_venda(base) == date(2025, 2, 10)

    def test_dw_sem_venda_levanta_erro(self, base):
        with pytest.raises(RuntimeError, match="nenhuma venda"):
            dados.ultimo_dia_com_venda(base)


class TestCli:
    def test_backtest_imprime_o_relatorio_e_sai_com_zero(self, base, capsys):
        _vender_o_ano(base)
        assert principal(["backtest"], conexao=base, verificar_memoria=None) == 0
        saida = capsys.readouterr().out
        assert "treino até 30/06/2025" in saida and "01/07/2025 a 31/12/2025" in saida
        for modelo in ("ingenua", "decomposicao", "holt_winters", "holt_winters_mensal"):
            assert modelo in saida
        assert "cobertura fora da amostra" in saida and "%" in saida

    def test_memoria_insuficiente_sai_com_3(self, base):
        def sem_memoria():
            raise MemoriaInsuficiente("pouca memória")

        assert principal(["backtest"], conexao=base, verificar_memoria=sem_memoria) == 3

    def test_dw_vazio_sai_com_3(self, base):
        assert principal(["backtest"], conexao=base, verificar_memoria=None) == 3

    def test_comando_invalido_sai_com_2(self):
        assert principal(["inexistente"]) == 2
