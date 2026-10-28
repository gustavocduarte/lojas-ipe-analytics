"""Testes do modelo ampliado: cupons, horários, vendedores, clientes e anomalias novas."""

import pandas as pd
import pytest

from src import config
from src.gerador.parametros import ParametrosGeracao
from src.gerador.principal import gerar_dados
from tests.gerador.utilitarios import data, hora, ler_csv, ler_vendas, numero

ITENS_VOLUME_MEDIO = 12_000


@pytest.fixture(scope="module")
def medios(tmp_path_factory):
    """Volume maior (12 mil itens) para os testes estatísticos."""
    pasta = tmp_path_factory.mktemp("raw_medio")
    params = ParametrosGeracao(
        diretorio_saida=pasta, total_linhas_venda=ITENS_VOLUME_MEDIO, verificar_memoria=False
    )
    resumo = gerar_dados(params)
    return params, resumo


def _preparar(pasta) -> pd.DataFrame:
    df = ler_vendas(pasta)
    df["data"] = [data(t) for t in df["data_venda"]]
    df["hora_do_dia"] = [hora(t) for t in df["hora_venda"]]
    for coluna in ("receita_liquida", "custo_total", "preco_unitario", "total_cupom"):
        df[coluna + "_num"] = [numero(t) for t in df[coluna]]
    df["quantidade_num"] = df["quantidade"].astype(int)
    return df


def _gabarito(pasta, tipo) -> pd.DataFrame:
    g = ler_csv(pasta / config.ARQ_ANOMALIAS)
    return g[g["tipo_anomalia"] == tipo]


def _sem_duplicatas(df: pd.DataFrame) -> pd.DataFrame:
    return df.drop_duplicates(["numero_cupom", "numero_item"], keep="first")


# --- estrutura dos cupons ---------------------------------------------------------------------
def test_media_de_itens_por_cupom_em_torno_de_3(medios):
    params, _ = medios
    df = _sem_duplicatas(ler_vendas(params.diretorio_saida))
    media = len(df) / df["numero_cupom"].nunique()
    assert 2.7 < media < 3.3


def test_total_do_volume_inclui_os_cupons_duplicados(medios):
    params, _ = medios
    assert len(ler_vendas(params.diretorio_saida)) == ITENS_VOLUME_MEDIO


def test_soma_dos_itens_e_igual_ao_total_do_cupom(dados_pequenos):
    params, _ = dados_pequenos
    df = _sem_duplicatas(_preparar(params.diretorio_saida))
    soma = df.groupby("numero_cupom")["receita_liquida_num"].sum()
    total = df.groupby("numero_cupom")["total_cupom_num"].first()
    assert ((soma - total).abs() < 0.011).all()


def test_numeracao_dos_itens_do_cupom_e_sequencial(dados_pequenos):
    params, _ = dados_pequenos
    df = _sem_duplicatas(ler_vendas(params.diretorio_saida))
    maior = df.groupby("numero_cupom")["numero_item"].apply(lambda s: s.astype(int).max())
    quantidade = df.groupby("numero_cupom").size()
    assert (maior == quantidade).all()


def test_ticket_do_cupom_com_eletro_e_maior(medios):
    params, _ = medios
    df = _sem_duplicatas(_preparar(params.diretorio_saida))
    df["eletro"] = df["sku"].str.upper().str.replace(" ", "").str.startswith("ELE-")
    por_cupom = df.groupby("numero_cupom").agg(
        total=("total_cupom_num", "first"), eletro=("eletro", "any")
    )
    assert (
        por_cupom.loc[por_cupom["eletro"], "total"].mean()
        > 2 * por_cupom.loc[~por_cupom["eletro"], "total"].mean()
    )


# --- horários -------------------------------------------------------------------------------
def test_vendas_normais_ficam_dentro_do_horario_da_loja(dados_pequenos):
    params, _ = dados_pequenos
    pasta = params.diretorio_saida
    horarios = ler_csv(pasta / config.ARQ_HORARIOS)
    janela = {
        (h["cod_loja"], int(h["dia_semana"])): (
            hora(h["hora_abertura"]).hour,
            hora(h["hora_fechamento"]).hour,
        )
        for _, h in horarios.iterrows()
    }
    fora_do_horario = set(_gabarito(pasta, config.ANOMALIA_FORA_HORARIO)["identificador"])
    df = _preparar(pasta)
    df = df[~df["numero_cupom"].isin(fora_do_horario)]
    assert len(df) > 0
    for loja, d, h in zip(df["cod_loja"], df["data"], df["hora_do_dia"], strict=True):
        abre, fecha = janela[(loja, d.weekday() + 1)]
        assert abre <= h.hour < fecha


def test_domingo_tem_horario_reduzido_em_todas_as_lojas(dados_pequenos):
    params, _ = dados_pequenos
    horarios = ler_csv(params.diretorio_saida / config.ARQ_HORARIOS)
    horarios["horas"] = [
        hora(f).hour - hora(a).hour
        for a, f in zip(horarios["hora_abertura"], horarios["hora_fechamento"], strict=True)
    ]
    for _, loja in horarios.groupby("cod_loja"):
        domingo = loja.loc[loja["dia_semana"] == "7", "horas"].iloc[0]
        segunda = loja.loc[loja["dia_semana"] == "1", "horas"].iloc[0]
        assert domingo < segunda


def test_picos_no_almoco_e_no_fim_da_tarde(medios):
    params, _ = medios
    df = _sem_duplicatas(_preparar(params.diretorio_saida))
    cupons = df[df["numero_item"] == "1"]
    por_hora = cupons["hora_do_dia"].map(lambda t: t.hour).value_counts()
    assert por_hora[12] > 1.5 * por_hora[9]
    assert por_hora[18] > 1.5 * por_hora[15]
    assert por_hora[12] > por_hora[21] and por_hora[18] > por_hora[21]


def test_sabado_forte_e_domingo_reduzido(medios):
    params, _ = medios
    df = _sem_duplicatas(_preparar(params.diretorio_saida))
    cupons = df[df["numero_item"] == "1"]
    media_por_dia = cupons.groupby("data").size()
    por_semana = media_por_dia.groupby([d.weekday() for d in media_por_dia.index]).mean()
    assert por_semana[5] > por_semana[:5].mean() > por_semana[6]


# --- vendedores -----------------------------------------------------------------------------
def test_vendedor_pertence_a_loja_e_estava_ativo_na_data_da_venda(dados_pequenos):
    params, _ = dados_pequenos
    vendedores = ler_csv(params.diretorio_saida / config.ARQ_VENDEDORES).set_index("cod_vendedor")
    df = _preparar(params.diretorio_saida)
    assert set(df["cod_vendedor"]) <= set(vendedores.index)
    for cod, loja, d in zip(df["cod_vendedor"], df["cod_loja"], df["data"], strict=True):
        v = vendedores.loc[cod]
        assert v["cod_loja"] == loja
        assert data(v["data_admissao"]) <= d
        assert not v["data_desligamento"] or d <= data(v["data_desligamento"])


def test_vendedores_por_loja_com_admissoes_e_desligamentos(dados_pequenos):
    params, _ = dados_pequenos
    vendedores = ler_csv(params.diretorio_saida / config.ARQ_VENDEDORES)
    inicio, fim = params.data_inicio, params.data_fim
    ativos_no_inicio = vendedores[
        [
            data(a) <= inicio and (not d or data(d) >= inicio)
            for a, d in zip(
                vendedores["data_admissao"], vendedores["data_desligamento"], strict=True
            )
        ]
    ]
    por_loja = ativos_no_inicio.groupby("cod_loja").size()
    minimo, maximo = config.VENDEDORES_POR_LOJA
    assert por_loja.min() >= minimo - 3 and por_loja.max() <= maximo
    desligados = [d for d in vendedores["data_desligamento"] if d]
    admitidos = [data(a) for a in vendedores["data_admissao"] if inicio < data(a) <= fim]
    assert len(desligados) > 5 and len(admitidos) > 5


def test_vendedores_tem_desempenhos_diferentes(medios):
    params, _ = medios
    df = _sem_duplicatas(_preparar(params.diretorio_saida))
    por_vendedor = df.groupby("cod_vendedor")["receita_liquida_num"].sum()
    assert por_vendedor.max() > 3 * por_vendedor.median()


def test_metas_por_vendedor_alguns_batem_e_outros_nao(medios):
    params, _ = medios
    pasta = params.diretorio_saida
    df = _sem_duplicatas(_preparar(pasta))
    df = df[df["status"] == config.STATUS_CONCLUIDA]
    df["competencia"] = [d.replace(day=1) for d in df["data"]]
    realizado = df.groupby(["cod_vendedor", "competencia"])["receita_liquida_num"].sum()
    metas = ler_csv(pasta / config.ARQ_METAS_VENDEDOR)
    metas["chave"] = list(
        zip(metas["cod_vendedor"], [data(t) for t in metas["competencia"]], strict=True)
    )
    ating = [
        realizado[k] / numero(v) for k, v in zip(metas["chave"], metas["valor_meta"], strict=True)
    ]
    assert sum(a > 1 for a in ating) > 0.2 * len(ating)
    assert sum(a < 1 for a in ating) > 0.2 * len(ating)


# --- clientes -------------------------------------------------------------------------------
def test_cerca_de_30_por_cento_dos_cupons_tem_cliente(medios):
    params, _ = medios
    cupons = _sem_duplicatas(ler_vendas(params.diretorio_saida))
    cupons = cupons[cupons["numero_item"] == "1"]
    assert 0.25 < (cupons["cod_cliente"] != "").mean() < 0.35


def test_cliente_so_compra_depois_de_se_cadastrar_e_ha_recorrencia(medios):
    params, _ = medios
    pasta = params.diretorio_saida
    clientes = ler_csv(pasta / config.ARQ_CLIENTES).set_index("cod_cliente")
    df = _preparar(pasta)
    identificados = df[df["cod_cliente"] != ""]
    for cod, d in zip(identificados["cod_cliente"], identificados["data"], strict=True):
        assert data(clientes.loc[cod, "data_cadastro_fidelidade"]) <= d
    compras = _sem_duplicatas(identificados).groupby("cod_cliente")["numero_cupom"].nunique()
    assert (compras >= 3).sum() >= 5


def test_clientes_nao_tem_dados_pessoais_identificaveis(dados_pequenos):
    params, _ = dados_pequenos
    colunas = set(ler_csv(params.diretorio_saida / config.ARQ_CLIENTES).columns)
    assert colunas == {"cod_cliente", "cidade", "uf", "faixa_etaria", "data_cadastro_fidelidade"}


# --- pagamentos, campanhas, cancelamentos -----------------------------------------------------
def test_pix_cresce_e_dinheiro_diminui_ao_longo_do_periodo(medios):
    params, _ = medios
    cupons = _sem_duplicatas(_preparar(params.diretorio_saida))
    cupons = cupons[cupons["numero_item"] == "1"]
    primeiro = cupons[[d.year == 2024 and d.month <= 6 for d in cupons["data"]]]
    ultimo = cupons[[d.year == 2025 and d.month >= 7 for d in cupons["data"]]]

    def participacao(grupo, forma):
        return (grupo["cod_forma_pagamento"] == forma).mean()

    assert participacao(ultimo, "PIX") > participacao(primeiro, "PIX") + 0.08
    assert participacao(ultimo, "DIN") < participacao(primeiro, "DIN") - 0.03


def test_parcelamento_e_mais_comum_em_cupons_com_eletro(medios):
    params, _ = medios
    df = _sem_duplicatas(_preparar(params.diretorio_saida))
    df["eletro"] = df["sku"].str.upper().str.replace(" ", "").str.startswith("ELE-")
    cupons = df.groupby("numero_cupom").agg(
        eletro=("eletro", "any"),
        forma=("cod_forma_pagamento", "first"),
        parcelas=("numero_parcelas", "first"),
    )
    parcelado = cupons["forma"] == "CRP"
    assert parcelado[cupons["eletro"]].mean() > 2 * parcelado[~cupons["eletro"]].mean()
    assert (cupons.loc[~parcelado, "parcelas"] == "1").all()
    assert (cupons.loc[parcelado, "parcelas"].astype(int) >= 2).all()


def test_campanha_so_aparece_dentro_do_periodo_dela(dados_pequenos):
    params, _ = dados_pequenos
    pasta = params.diretorio_saida
    campanhas = ler_csv(pasta / config.ARQ_CAMPANHAS).set_index("cod_campanha")
    df = _preparar(pasta)
    com_campanha = df[df["cod_campanha"] != ""]
    assert len(com_campanha) > 0
    for cod, d in zip(com_campanha["cod_campanha"], com_campanha["data"], strict=True):
        assert data(campanhas.loc[cod, "data_inicio"]) <= d <= data(campanhas.loc[cod, "data_fim"])
    assert {"Black Friday", "Natal", "Dia das Mães", "Volta às Aulas"} <= set(
        campanhas["nome_campanha"]
    )


def test_cancelamentos_e_devolucoes_em_taxa_baixa_com_motivo(medios):
    params, _ = medios
    pasta = params.diretorio_saida
    cupons = _sem_duplicatas(ler_vendas(pasta))
    cupons = cupons[cupons["numero_item"] == "1"]
    alto = set(_gabarito(pasta, config.ANOMALIA_VENDEDOR_CANCELAMENTO)["identificador"])
    normais = cupons[~cupons["cod_vendedor"].isin(alto)]
    taxa = (normais["status"] != config.STATUS_CONCLUIDA).mean()
    assert 0.01 < taxa < 0.07
    assert set(cupons["status"]) == {
        config.STATUS_CONCLUIDA,
        config.STATUS_CANCELADA,
        config.STATUS_DEVOLVIDA,
    }
    assert (
        cupons.loc[cupons["status"] != config.STATUS_CONCLUIDA, "motivo_cancelamento_devolucao"]
        != ""
    ).all()
    assert (
        cupons.loc[cupons["status"] == config.STATUS_CONCLUIDA, "motivo_cancelamento_devolucao"]
        == ""
    ).all()


# --- anomalias novas ------------------------------------------------------------------------
def test_vendas_fora_do_horario_existem_nos_dados(dados_pequenos):
    params, _ = dados_pequenos
    pasta = params.diretorio_saida
    horarios = ler_csv(pasta / config.ARQ_HORARIOS)
    janela = {
        (h["cod_loja"], int(h["dia_semana"])): (
            hora(h["hora_abertura"]).hour,
            hora(h["hora_fechamento"]).hour,
        )
        for _, h in horarios.iterrows()
    }
    gabarito = _gabarito(pasta, config.ANOMALIA_FORA_HORARIO)
    assert len(gabarito) == params.quantidade_anomalias[config.ANOMALIA_FORA_HORARIO]
    df = _preparar(pasta).set_index(["arquivo", "linha"])
    for _, a in gabarito.iterrows():
        venda = df.loc[(a["arquivo"], int(a["linha_arquivo"]))]
        assert venda["numero_cupom"] == a["identificador"]
        abre, fecha = janela[(venda["cod_loja"], venda["data"].weekday() + 1)]
        assert not (abre <= venda["hora_do_dia"].hour < fecha)


def test_descontos_acima_do_limite_existem_nos_dados(dados_pequenos):
    params, _ = dados_pequenos
    pasta = params.diretorio_saida
    gabarito = _gabarito(pasta, config.ANOMALIA_DESCONTO_ACIMA_LIMITE)
    assert len(gabarito) == params.quantidade_anomalias[config.ANOMALIA_DESCONTO_ACIMA_LIMITE]
    df = _preparar(pasta)
    df["bruto"] = df["preco_unitario_num"] * df["quantidade_num"]
    df["fracao"] = 1 - df["receita_liquida_num"] / df["bruto"]
    indexado = df.set_index(["arquivo", "linha"])
    for _, a in gabarito.iterrows():
        venda = indexado.loc[(a["arquivo"], int(a["linha_arquivo"]))]
        assert venda["id_venda_erp"] == a["identificador"]
        assert venda["fracao"] > config.DESCONTO_MAXIMO + 0.01
    normais = df[~df["id_venda_erp"].isin(gabarito["identificador"])]
    assert (normais["fracao"] <= config.DESCONTO_MAXIMO + 0.001).all()


def test_cupons_duplicados_existem_nos_dados(dados_pequenos):
    params, _ = dados_pequenos
    pasta = params.diretorio_saida
    gabarito = _gabarito(pasta, config.ANOMALIA_CUPOM_DUPLICADO)
    assert len(gabarito) == params.quantidade_anomalias[config.ANOMALIA_CUPOM_DUPLICADO]
    df = ler_vendas(pasta)
    itens_por_chave = df.groupby(["numero_cupom", "numero_item"]).size()
    indexado = df.set_index(["arquivo", "linha"])
    for _, a in gabarito.iterrows():
        copia = indexado.loc[(a["arquivo"], int(a["linha_arquivo"]))]
        assert copia["numero_cupom"] == a["identificador"]
        itens = itens_por_chave[a["identificador"]]
        assert (itens == 2).all()
    duplicados = itens_por_chave[itens_por_chave > 1].index.get_level_values(0).unique()
    assert set(duplicados) == set(gabarito["identificador"])


def test_vendedores_com_cancelamento_muito_acima_da_media(medios):
    params, _ = medios
    pasta = params.diretorio_saida
    gabarito = _gabarito(pasta, config.ANOMALIA_VENDEDOR_CANCELAMENTO)
    assert len(gabarito) == params.quantidade_anomalias[config.ANOMALIA_VENDEDOR_CANCELAMENTO]
    cupons = _sem_duplicatas(ler_vendas(pasta))
    cupons = cupons[cupons["numero_item"] == "1"]
    cancelada = cupons["status"] == config.STATUS_CANCELADA
    taxa_geral = cancelada.mean()
    for cod in gabarito["identificador"]:
        do_vendedor = cupons["cod_vendedor"] == cod
        assert do_vendedor.sum() >= 10
        assert cancelada[do_vendedor].mean() > 3 * taxa_geral
        assert cancelada[do_vendedor].mean() > 0.15


# --- problemas de qualidade novos -------------------------------------------------------------
def test_horas_aparecem_em_formatos_diferentes(dados_pequenos):
    params, resumo = dados_pequenos
    assert resumo.problemas_por_tipo.get(config.PROBLEMA_HORA_FORMATO_MISTO, 0) > 0
    horas = ler_vendas(params.diretorio_saida)["hora_venda"]
    assert horas.str.match(r"^\d{2}:\d{2}:\d{2}$").any()
    assert (~horas.str.match(r"^\d{2}:\d{2}:\d{2}$")).any()
    for texto in horas:
        hora(texto)  # todos os formatos devem ser reconhecíveis


def test_nomes_de_vendedor_com_espacos_extras_e_caixa_diferente(dados_pequenos):
    params, resumo = dados_pequenos
    assert resumo.problemas_por_tipo.get(config.PROBLEMA_NOME_SUJO, 0) > 0
    nomes = ler_csv(params.diretorio_saida / config.ARQ_VENDEDORES)["nome_vendedor"]
    assert any(n != n.strip() or "  " in n for n in nomes)
    assert any(n.isupper() for n in nomes) and any(n.islower() for n in nomes)
    limpos = [" ".join(n.split()).title() for n in nomes]
    assert all(limpo.replace(" ", "").isalpha() for limpo in limpos)


def test_faixas_do_dia_cobrem_as_24_horas_sem_sobreposicao():
    horas = [h for _, inicio, fim in config.FAIXAS_DO_DIA for h in range(inicio, fim + 1)]
    assert sorted(horas) == list(range(24))
