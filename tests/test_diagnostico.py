"""Diagnóstico da loja (referência em Python do painel): limites, bordas, loja nova e veredito."""

from datetime import date

import pytest

from src.diagnostico import Indicadores, diagnosticar

PARAMETROS = {
    "cupons_queda": 0.05,
    "ticket_minimo": 0.90,
    "ticket_forte": 1.10,
    "desconto_pp": 0.005,
    "setor_fraco": 0.70,
    "setor_forte": 1.30,
    "equipe_abaixo": 0.50,
    "equipe_acima": 0.75,
    "meta_folga": 0.10,
}


def _loja(**mudancas) -> Indicadores:
    """Loja neutra: tudo dentro dos limites, cobertura 100%."""
    base = dict(
        nome_loja="Ipê Teste",
        aberta_em=date(2015, 1, 1),
        ate=date(2025, 12, 15),
        receita=1000.0,
        meta=1000.0,
        cupons=100,
        cupons_ano_anterior=100,
        ticket=100.0,
        ticket_rede=100.0,
        desconto=0.05,
        desconto_rede=0.05,
        venda_ano_anterior=1000.0,
        setores={"Alimentos": (500.0, 500.0), "Casa": (500.0, 500.0)},
        vendedores=[(50.0, 100.0)] + [(150.0, 100.0)] * 2,  # 1 de 3 abaixo: nem atenção nem forte
    )
    base.update(mudancas)
    return Indicadores(**base)


def _valor(ind: Indicadores, codigo: str):
    sinal = diagnosticar(ind, PARAMETROS).sinais.get(codigo)
    return None if sinal is None else sinal.valor


def test_loja_neutra_nao_tem_atencao_nem_ponto_forte():
    res = diagnosticar(_loja(), PARAMETROS)
    assert res.atencoes == [] and res.fortes == []
    assert res.veredito == "Acima da meta (100,0%)."


@pytest.mark.parametrize(
    ("cupons", "esperado"),
    [(95, -1), (96, 0), (100, 0), (104, 0), (105, 1)],  # ano anterior = 100: bordas de 5%
)
def test_fluxo_de_cupons_nas_bordas(cupons, esperado):
    assert _valor(_loja(cupons=cupons), "fluxo") == esperado


@pytest.mark.parametrize(("ticket", "esperado"), [(89.9, -1), (90.0, 0), (109.9, 0), (110.0, 1)])
def test_ticket_vs_rede_nas_bordas(ticket, esperado):
    assert _valor(_loja(ticket=ticket), "ticket") == esperado


@pytest.mark.parametrize(
    ("desconto", "esperado"), [(0.0551, -1), (0.054, 0), (0.046, 0), (0.0449, 1)]
)
def test_desconto_vs_rede_em_pontos_percentuais(desconto, esperado):
    assert _valor(_loja(desconto=desconto), "desconto") == esperado


def test_setor_fraco_e_forte_usam_os_limites_dos_parametros():
    ind = _loja(setores={"Eletro": (69.0, 100.0), "Casa": (70.0, 100.0), "Bebidas": (130.0, 100.0)})
    res = diagnosticar(ind, PARAMETROS)
    assert res.sinais["setor_fraco"].texto == "Eletro (69%) abaixo de 70% da meta"
    assert res.sinais["setor_forte"].texto == "Bebidas (130%) acima de 130% da meta"
    outro = diagnosticar(ind, {**PARAMETROS, "setor_fraco": 0.60})
    assert outro.sinais["setor_fraco"].valor == 0  # o limite vem do parâmetro, não do código


def test_equipe_atencao_com_metade_abaixo_e_forte_com_tres_quartos_acima():
    assert _valor(_loja(vendedores=[(50.0, 100.0)] * 2 + [(150.0, 100.0)] * 2), "equipe") == -1
    assert _valor(_loja(vendedores=[(50.0, 100.0)] + [(150.0, 100.0)] * 2), "equipe") == 0
    assert _valor(_loja(vendedores=[(50.0, 100.0)] + [(150.0, 100.0)] * 3), "equipe") == 1
    assert _valor(_loja(vendedores=[]), "equipe") is None


def test_loja_nova_mostra_sem_base_e_nao_vira_atencao():
    ind = _loja(
        aberta_em=date(2025, 3, 3),
        cupons_ano_anterior=None,
        venda_ano_anterior=None,
        receita=770.0,
    )
    res = diagnosticar(ind, PARAMETROS)
    assert "fluxo" not in res.sinais and "meta" not in res.sinais  # sem base
    assert all("cupons" not in t for t in res.atencoes)
    assert res.veredito.startswith(
        "Abaixo da meta (77,0%). Loja em maturação: aberta em 03/03/2025, sem ano anterior;"
    )


def test_loja_aberta_ha_mais_de_12_meses_nao_e_maturacao():
    assert not _loja(aberta_em=date(2024, 12, 15)).em_maturacao
    assert _loja(aberta_em=date(2024, 12, 16)).em_maturacao


def test_abaixo_da_meta_sem_causa_diz_que_nao_ha_causa_clara():
    res = diagnosticar(_loja(receita=900.0), PARAMETROS)
    assert (
        res.veredito
        == "Abaixo da meta (90,0%). Sem causa clara nos indicadores (variação do período)."
    )


def test_veredito_abaixo_da_meta_com_causas_e_ponto_forte():
    ind = _loja(
        receita=800.0,
        cupons=90,
        ticket=115.0,
        setores={"Casa": (52.0, 100.0), "Eletro": (140.0, 100.0)},
    )
    res = diagnosticar(ind, PARAMETROS)
    assert res.veredito == (
        "Abaixo da meta (80,0%). Atenção: Casa (52%) abaixo de 70% da meta; "
        "o fluxo de cupons caiu 10,0%. "
        "Pontos fortes: Eletro (140%) acima de 130% da meta; "
        "o ticket médio está 15,0% acima da rede."
    )


def test_meta_folgada_ou_apertada_entra_como_contexto():
    folgada = diagnosticar(_loja(meta=800.0, receita=1200.0), PARAMETROS)
    assert folgada.veredito.endswith(
        "Contexto: meta 20,0% abaixo da venda do ano anterior (folgada)."
    )
    apertada = diagnosticar(_loja(meta=1200.0, receita=1000.0), PARAMETROS)
    assert apertada.veredito.endswith(
        "Contexto: meta 20,0% acima da venda do ano anterior (apertada)."
    )


def test_limite_de_causas_no_veredito():
    ind = _loja(
        receita=500.0,
        cupons=80,
        ticket=80.0,
        desconto=0.07,
        setores={"Casa": (10.0, 100.0)},
        vendedores=[(0.0, 100.0)] * 4,
    )
    res = diagnosticar(ind, PARAMETROS)
    assert len(res.atencoes) == 5
    assert res.veredito.count(";") == 1  # só as 2 primeiras causas, na ordem de prioridade
