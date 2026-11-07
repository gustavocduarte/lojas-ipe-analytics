"""Metas de venda: esperado do período (histórico + calendário), nunca o realizado do mês."""

from datetime import date

import pandas as pd

from src import calendario, config
from src.calendario_comercial import pesos_do_periodo
from src.gerador import metas as mod_metas
from src.gerador import vendas
from src.gerador.catalogo import SETORES, montar_catalogo
from src.gerador.principal import gerar_somente_metas
from src.gerador.sazonalidade import Sazonalidade
from tests.conftest import com_saida
from tests.gerador.utilitarios import ler_csv, numero


def _base(params):
    cat = montar_catalogo(params.semente, params.data_inicio, params.data_fim)
    sazon = Sazonalidade(params.data_inicio, params.data_fim)
    meses = calendario.meses_do_periodo(params.data_inicio, params.data_fim)
    pesos = {m: vendas.pesos_do_mes(sazon, cat, *m, params) for m in meses}
    itens = vendas.distribuir_linhas(
        params.total_linhas_venda, [float(pesos[m][1].sum()) for m in meses]
    )
    esperado = mod_metas.esperado_estrutural(cat, sazon, meses, pesos, itens)
    return cat, sazon, meses, esperado


def _metas(params, realizado):
    cat, sazon, meses, esperado = _base(params)
    from src.gerador.parametros import rng_para

    return mod_metas.gerar_metas(
        cat,
        sazon,
        meses,
        esperado,
        realizado,
        rng_para(params.semente, config.FLUXO_METAS),
        (params.data_inicio, params.data_fim),
    )


def _realizado_ficticio(params, fator_junho_2025=1.0):
    cat = montar_catalogo(params.semente, params.data_inicio, params.data_fim)
    meses = calendario.meses_do_periodo(params.data_inicio, params.data_fim)
    return {
        (lj.cod_loja, setor, ano, mes): 1000.0
        * (fator_junho_2025 if (ano, mes) == (2025, 6) else 1.0)
        for ano, mes in meses
        for lj in cat.lojas
        if lj.data_abertura <= date(ano, mes, 28)
        for setor in SETORES
    }


def test_primeiro_ano_nao_depende_do_realizado(dados_pequenos):
    params, _ = dados_pequenos
    sem_historico = _metas(params, {})
    com_historico = _metas(params, _realizado_ficticio(params))
    primeiro_ano = sem_historico["competencia"].dt.year == params.data_inicio.year
    pd.testing.assert_frame_equal(
        sem_historico[primeiro_ano].reset_index(drop=True),
        com_historico[com_historico["competencia"].dt.year == params.data_inicio.year].reset_index(
            drop=True
        ),
    )


def test_meta_do_mes_nao_usa_o_realizado_do_proprio_mes(dados_pequenos):
    params, _ = dados_pequenos
    normal = _metas(params, _realizado_ficticio(params))
    alterado = _metas(params, _realizado_ficticio(params, fator_junho_2025=3.0))
    junho = pd.Timestamp(2025, 6, 1)
    julho = pd.Timestamp(2025, 7, 1)
    chave = ["competencia", "cod_loja", "setor"]
    a = normal.set_index(chave)["valor_meta"]
    b = alterado.set_index(chave)["valor_meta"]
    assert (a.xs(junho, level=0) == b.xs(junho, level=0)).all()  # mesmo mês: igual
    assert not (a.xs(julho, level=0) == b.xs(julho, level=0)).all()  # mês seguinte: usa o histórico


def test_soma_das_metas_dos_vendedores_bate_com_a_meta_da_loja(dados_pequenos):
    params, _ = dados_pequenos
    saida = params.diretorio_saida
    cat = montar_catalogo(params.semente, params.data_inicio, params.data_fim)
    loja_do_vendedor = {v.cod_vendedor: v.cod_loja for v in cat.vendedores}
    por_loja = ler_csv(saida / config.ARQ_METAS)
    por_loja["valor"] = [numero(v) for v in por_loja["valor_meta"]]
    esperado = por_loja.groupby(["competencia", "cod_loja"])["valor"].sum().round(2)
    por_vendedor = ler_csv(saida / config.ARQ_METAS_VENDEDOR)
    por_vendedor["cod_loja"] = por_vendedor["cod_vendedor"].map(loja_do_vendedor)
    por_vendedor["valor"] = [numero(v) for v in por_vendedor["valor_meta"]]
    soma = por_vendedor.groupby(["competencia", "cod_loja"])["valor"].sum().round(2)
    assert (soma - esperado).abs().max() < 0.005


def test_regenerar_so_metas_reproduz_as_metas_e_nao_escreve_mais_nada(dados_pequenos, tmp_path):
    params, _ = dados_pequenos
    destino = com_saida(params, tmp_path / "so_metas")
    gerar_somente_metas(destino)
    escritos = sorted(p.name for p in destino.diretorio_saida.iterdir())
    assert escritos == sorted([config.ARQ_METAS, config.ARQ_METAS_VENDEDOR])
    for nome in escritos:
        original = (params.diretorio_saida / nome).read_bytes()
        assert (destino.diretorio_saida / nome).read_bytes() == original


def test_pesos_do_calendario_destacam_natal_e_nao_trazem_tendencia():
    pesos = pesos_do_periodo(date(2024, 12, 1), date(2025, 12, 31))
    dec = pesos[pesos["setor"] == "Alimentos"].set_index("data")["peso"]
    normal = dec[date(2024, 12, 10)]
    assert dec[date(2024, 12, 20)] > 1.3 * normal  # janela de Natal
    assert dec[date(2024, 12, 25)] < 0.5 * normal  # dia de Natal
    # mesma data e mesmo dia da semana um ano depois: sem tendência de crescimento no peso
    assert abs(dec[date(2025, 12, 22)] / dec[date(2024, 12, 23)] - 1) < 0.02
