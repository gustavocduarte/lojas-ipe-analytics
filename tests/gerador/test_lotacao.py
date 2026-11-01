"""Lotação dos vendedores por setor e reatribuição dos cupons (sem banco)."""

from datetime import timedelta

import pandas as pd
import pytest

from src import config
from src.gerador.catalogo import SETORES, montar_catalogo
from src.gerador.lotacao import montar_lotacao
from src.gerador.parametros import ParametrosGeracao
from src.gerador.principal import gerar_dados
from tests.gerador.utilitarios import data, ler_csv, ler_vendas

LINHAS = 40_000


@pytest.fixture(scope="module")
def catalogo():
    p = ParametrosGeracao()
    return montar_catalogo(p.semente, p.data_inicio, p.data_fim)


@pytest.fixture(scope="module")
def lotacao(catalogo):
    return montar_lotacao(ParametrosGeracao(), catalogo)


@pytest.fixture(scope="module")
def pastas(tmp_path_factory):
    """Os mesmos dados com e sem a lotação por setor."""
    saida = {}
    for nome, ligada in (("sem", False), ("com", True)):
        params = ParametrosGeracao(
            diretorio_saida=tmp_path_factory.mktemp(nome), total_linhas_venda=LINHAS,
            verificar_memoria=False, gerar_exemplo_outra_empresa=False, lotacao_por_setor=ligada,
        )  # fmt: skip
        gerar_dados(params)
        saida[nome] = params.diretorio_saida
    return saida


# --- a lotação ------------------------------------------------------------------------------
def test_lotacao_e_reprodutivel(catalogo, lotacao):
    outra = montar_lotacao(ParametrosGeracao(), catalogo)
    assert outra.periodos == lotacao.periodos and outra.habilidade == lotacao.habilidade


def test_todo_vendedor_tem_periodos_contiguos_dentro_da_vida_dele(catalogo, lotacao):
    p = ParametrosGeracao()
    por_vendedor = {}
    for per in lotacao.periodos:
        por_vendedor.setdefault(per.cod_vendedor, []).append(per)
    assert set(por_vendedor) == {v.cod_vendedor for v in catalogo.vendedores}
    for v in catalogo.vendedores:
        periodos = sorted(por_vendedor[v.cod_vendedor], key=lambda x: x.data_inicio)
        assert periodos[0].data_inicio == max(v.data_admissao, p.data_inicio)
        for anterior, seguinte in zip(periodos, periodos[1:], strict=False):
            assert anterior.data_fim == seguinte.data_inicio - timedelta(
                days=1
            )  # sem vão nem sobra
            assert anterior.setor != seguinte.setor
        assert periodos[-1].data_fim == v.data_desligamento  # desligado encerra; ativo fica vigente
        assert all(per.setor in SETORES for per in periodos)


def test_cerca_de_20_por_cento_troca_e_toda_lotacao_dura_ao_menos_3_meses(catalogo, lotacao):
    quem_troca = {t.cod_vendedor for t in lotacao.trocas}
    assert len(quem_troca) == round(config.LOTACAO_FRACAO_QUE_TROCA * len(catalogo.vendedores))
    duas = sum(1 for c in quem_troca if sum(t.cod_vendedor == c for t in lotacao.trocas) == 2)
    assert 0 < duas < len(quem_troca) / 2  # alguns trocam duas vezes
    inicio, fim = config.LOTACAO_JANELA_TROCAS
    assert all(inicio <= t.data_troca <= fim for t in lotacao.trocas)
    minimo = config.LOTACAO_DIAS_MINIMOS_ANTES_E_DEPOIS
    por_vendedor = {}
    for per in lotacao.periodos:
        por_vendedor.setdefault(per.cod_vendedor, []).append(per)
    for cod in quem_troca:
        periodos = sorted(por_vendedor[cod], key=lambda x: x.data_inicio)
        fim_de_tudo = ParametrosGeracao().data_fim
        for per in periodos:
            ate = per.data_fim or fim_de_tudo
            assert (ate - per.data_inicio).days + 1 >= minimo, (cod, per)


def test_habilidade_de_todo_vendedor_em_todo_setor_dentro_da_faixa(catalogo, lotacao):
    baixo, alto = config.HABILIDADE_FAIXA
    assert len(lotacao.habilidade) == len(catalogo.vendedores) * len(SETORES)
    assert all(baixo <= h <= alto for h in lotacao.habilidade.values())


def test_trocas_batem_com_os_periodos(lotacao):
    for t in lotacao.trocas:
        assert lotacao.setor_em(t.cod_vendedor, t.data_troca - timedelta(days=1)) == t.setor_origem
        assert lotacao.setor_em(t.cod_vendedor, t.data_troca) == t.setor_destino


# --- a reatribuição dos cupons -----------------------------------------------------------------
def test_so_o_vendedor_muda_e_o_resto_dos_dados_e_identico(pastas):
    sem, com = ler_vendas(pastas["sem"]), ler_vendas(pastas["com"])
    assert sem.drop(columns="cod_vendedor").equals(com.drop(columns="cod_vendedor"))
    assert (sem.cod_vendedor != com.cod_vendedor).sum() > 0.3 * len(sem)  # muita coisa foi movida
    for nome in (config.ARQ_METAS, config.ARQ_DESPESAS, config.ARQ_ORCAMENTO,
                 config.ARQ_ANOMALIAS, config.ARQ_PROBLEMAS, config.ARQ_VENDEDORES):  # fmt: skip
        assert (pastas["sem"] / nome).read_bytes() == (pastas["com"] / nome).read_bytes(), nome


def test_vendedor_novo_e_da_mesma_loja_e_estava_ativo_na_data(pastas):
    sem, com = ler_vendas(pastas["sem"]), ler_vendas(pastas["com"])
    cadastro = ler_csv(pastas["com"] / config.ARQ_VENDEDORES).set_index("cod_vendedor")
    mudou = com[sem.cod_vendedor != com.cod_vendedor]
    assert (cadastro.loc[mudou.cod_vendedor, "cod_loja"].values == mudou.cod_loja.values).all()
    admissao = pd.to_datetime(cadastro.loc[mudou.cod_vendedor, "data_admissao"].map(data)).values
    deslig = cadastro.loc[mudou.cod_vendedor, "data_desligamento"]
    dia = pd.to_datetime(mudou.data_venda.map(data)).values
    assert (admissao <= dia).all()
    fim = pd.to_datetime(deslig.map(lambda t: data(t) if t else pd.Timestamp.max.date())).values
    assert (dia < fim).all()


def test_cancelamento_alto_e_anomalias_ficam_como_estavam(pastas):
    sem, com = ler_vendas(pastas["sem"]), ler_vendas(pastas["com"])
    gabarito = ler_csv(pastas["com"] / config.ARQ_ANOMALIAS)
    alto = set(
        gabarito[gabarito.tipo_anomalia == config.ANOMALIA_VENDEDOR_CANCELAMENTO].identificador
    )
    assert len(alto) == config.QUANTIDADE_ANOMALIAS[config.ANOMALIA_VENDEDOR_CANCELAMENTO]
    de_ou_para = sem.cod_vendedor.isin(alto) | com.cod_vendedor.isin(alto)
    assert (sem.cod_vendedor[de_ou_para] == com.cod_vendedor[de_ou_para]).all()
    por_cupom = sem.assign(novo=com.cod_vendedor).groupby("numero_cupom")
    assert (por_cupom.novo.nunique() == 1).all()  # um cupom, um vendedor (inclusive duplicatas)
    com_gabarito = com.assign(
        id=com.id_venda_erp, cupom=com.numero_cupom
    )  # itens/cupons marcados no gabarito
    marcados = set(gabarito.identificador)
    pega = com_gabarito.id.isin(marcados) | com_gabarito.cupom.isin(marcados)
    assert pega.sum() > 0
    cupons_marcados = set(com_gabarito.cupom[pega])
    antes = sem[sem.numero_cupom.isin(cupons_marcados)].cod_vendedor.values
    depois = com[com.numero_cupom.isin(cupons_marcados)].cod_vendedor.values
    assert (antes == depois).all()


def test_totais_por_loja_setor_e_dia_nao_mudam(pastas):
    produtos = ler_csv(pastas["com"] / config.ARQ_PRODUTOS)[["sku", "setor"]]

    def totais(pasta):
        v = ler_vendas(pasta)
        v["sku"] = v.sku.str.strip().str.upper()
        v = v.merge(produtos, on="sku")
        v["r"] = v.receita_liquida.map(
            lambda t: float(t.replace(".", "").replace(",", ".")) if "," in t else float(t)
        )
        return v.groupby(["cod_loja", "setor", "data_venda", "status"]).r.sum().round(2)

    assert totais(pastas["sem"]).equals(totais(pastas["com"]))


def test_mediana_da_participacao_no_setor_de_lotacao_fica_na_faixa_alvo(pastas):
    v = ler_vendas(pastas["com"])
    v = v[v.status == config.STATUS_CONCLUIDA].copy()
    v["sku"] = v.sku.str.strip().str.upper()
    v = v.merge(ler_csv(pastas["com"] / config.ARQ_PRODUTOS)[["sku", "setor"]], on="sku")
    v["r"] = v.receita_liquida.map(
        lambda t: float(t.replace(".", "").replace(",", ".")) if "," in t else float(t)
    )
    v["dia"] = pd.to_datetime(v.data_venda.map(data))
    lot = ler_csv(pastas["com"] / config.ARQ_LOTACAO_SETOR)
    lot["ini"] = pd.to_datetime(lot.data_inicio.map(data))
    lot["fim"] = pd.to_datetime(
        lot.data_fim.map(lambda t: data(t) if t else pd.Timestamp.max.date())
    )
    m = v.merge(
        lot[["cod_vendedor", "setor", "ini", "fim"]].rename(columns={"setor": "lot"}),
        on="cod_vendedor",
    )
    m = m[(m.dia >= m.ini) & (m.dia <= m.fim)]
    participacao = (
        m[m.setor == m.lot].groupby("cod_vendedor").r.sum() / v.groupby("cod_vendedor").r.sum()
    )
    baixo, alto = config.LOTACAO_ALVO_PARTICIPACAO
    assert baixo <= participacao.median() <= alto
    assert (participacao < 1.0).all()  # ninguém vende só no setor dele


def test_gabaritos_de_lotacao_so_existem_para_teste(pastas):
    pasta = pastas["com"]
    habilidade = ler_csv(pasta / config.ARQ_HABILIDADE_VERDADEIRA)
    assert list(habilidade.columns) == ["cod_vendedor", "setor", "habilidade"]
    assert len(habilidade) == 185 * len(SETORES)
    trocas = ler_csv(pasta / config.ARQ_TROCAS_SETOR)
    assert list(trocas.columns) == ["cod_vendedor", "data_troca", "setor_origem", "setor_destino"]
    assert len(trocas) > 0 and (trocas.setor_origem != trocas.setor_destino).all()
    assert not (pastas["sem"] / config.ARQ_LOTACAO_SETOR).exists()  # desligada: nada de lotação
