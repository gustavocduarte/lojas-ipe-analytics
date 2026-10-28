"""Testes do gerador de dados sintéticos (volume pequeno, tudo em pasta temporária)."""

import pytest

from src import calendario, config
from src.gerador.catalogo import DESCRICOES_POR_TIPO, montar_catalogo
from src.gerador.principal import gerar_dados
from tests.conftest import LINHAS_VENDA_TESTE, com_saida
from tests.gerador.utilitarios import data, hash_da_pasta, ler_csv, ler_vendas, numero


def test_volume_de_vendas_exato_e_dividido_em_arquivos_mensais(dados_pequenos):
    params, resumo = dados_pequenos
    vendas = ler_vendas(params.diretorio_saida)
    assert len(vendas) == LINHAS_VENDA_TESTE
    arquivos = sorted(vendas["arquivo"].unique())
    assert len(arquivos) == 24
    assert arquivos[0] == "vendas_2024-01.csv"
    assert arquivos[-1] == "vendas_2025-12.csv"
    assert vendas["id_venda_erp"].is_unique
    assert sum(v for k, v in resumo.linhas_por_arquivo.items() if k.startswith("vendas_")) == len(
        vendas
    )


def test_volume_proporcional_ao_parametro(dados_pequenos, tmp_path):
    params, _ = dados_pequenos
    dobro = com_saida(params, tmp_path, total_linhas_venda=2 * LINHAS_VENDA_TESTE)
    resumo = gerar_dados(dobro)
    total = sum(v for k, v in resumo.linhas_por_arquivo.items() if k.startswith("vendas_"))
    assert total == 2 * LINHAS_VENDA_TESTE


def test_periodo_das_vendas_e_despesas(dados_pequenos):
    params, _ = dados_pequenos
    vendas = ler_vendas(params.diretorio_saida)
    datas_venda = [data(t) for t in vendas["data_venda"]]
    assert min(datas_venda) >= params.data_inicio
    assert max(datas_venda) <= params.data_fim
    despesas = ler_csv(params.diretorio_saida / config.ARQ_DESPESAS)
    datas_desp = [data(t) for t in despesas["data_lancamento"]]
    assert min(datas_desp) >= params.data_inicio
    assert max(datas_desp) <= params.data_fim


def test_lojas_so_vendem_depois_de_abrir(dados_pequenos):
    params, _ = dados_pequenos
    abertura = {lj.cod_loja: lj.data_abertura for lj in montar_catalogo(params.semente).lojas}
    vendas = ler_vendas(params.diretorio_saida)
    for cod_loja, data_venda in zip(vendas["cod_loja"], vendas["data_venda"], strict=True):
        assert data(data_venda) >= abertura[cod_loja]


def test_metas_e_orcamento_cobrem_o_periodo(dados_pequenos):
    params, _ = dados_pequenos
    metas = ler_csv(params.diretorio_saida / config.ARQ_METAS)
    assert metas["competencia"].nunique() == 24
    assert {"Alimentos", "Eletro"} <= set(metas["setor"])
    orcamento = ler_csv(params.diretorio_saida / config.ARQ_ORCAMENTO)
    assert orcamento["competencia"].nunique() == 24
    assert set(orcamento["cod_centro_custo"]) == {
        c.cod_centro_custo for c in montar_catalogo().centros_custo
    }


def test_gabarito_tem_todos_os_tipos_na_quantidade_configurada(dados_pequenos):
    params, resumo = dados_pequenos
    for tipo, quantidade in params.quantidade_anomalias.items():
        assert resumo.anomalias_por_tipo[tipo] == quantidade, tipo


class TestAnomaliasDoGabaritoExistemNosDados:
    @pytest.fixture
    def gabarito(self, dados_pequenos):
        params, _ = dados_pequenos
        return ler_csv(params.diretorio_saida / config.ARQ_ANOMALIAS)

    @pytest.fixture
    def despesas(self, dados_pequenos):
        params, _ = dados_pequenos
        df = ler_csv(params.diretorio_saida / config.ARQ_DESPESAS)
        df["valor_num"] = [numero(v) for v in df["valor"]]
        return df

    def _linhas(self, gabarito, tipo):
        return gabarito[gabarito["tipo_anomalia"] == tipo]

    def test_despesa_duplicada(self, gabarito, despesas):
        linhas = self._linhas(gabarito, config.ANOMALIA_DESPESA_DUPLICADA)
        assert len(linhas) > 0
        contagem = despesas["numero_documento"].value_counts()
        for _, a in linhas.iterrows():
            registro = despesas.iloc[int(a["linha_arquivo"]) - 1]
            assert registro["numero_documento"] == a["identificador"]
            assert contagem[a["identificador"]] == 2

    def test_valor_atipico(self, gabarito, despesas):
        linhas = self._linhas(gabarito, config.ANOMALIA_VALOR_ATIPICO)
        assert len(linhas) > 0
        mediana = despesas.groupby("cod_centro_custo")["valor_num"].median()
        for _, a in linhas.iterrows():
            registro = despesas.iloc[int(a["linha_arquivo"]) - 1]
            assert registro["numero_documento"] == a["identificador"]
            assert registro["valor_num"] > 4 * mediana[registro["cod_centro_custo"]]

    def test_centro_custo_errado(self, gabarito, despesas, dados_pequenos):
        params, _ = dados_pequenos
        tipo_do_cc = {
            c.cod_centro_custo: c.tipo_despesa
            for c in montar_catalogo(params.semente).centros_custo
        }
        tipo_da_descricao = {d: t for t, ds in DESCRICOES_POR_TIPO.items() for d in ds}
        linhas = self._linhas(gabarito, config.ANOMALIA_CENTRO_CUSTO_ERRADO)
        assert len(linhas) > 0
        for _, a in linhas.iterrows():
            registro = despesas.iloc[int(a["linha_arquivo"]) - 1]
            assert registro["numero_documento"] == a["identificador"]
            assert registro["cod_centro_custo"] == a["cod_centro_custo"]
            assert (
                tipo_do_cc[registro["cod_centro_custo"]] != tipo_da_descricao[registro["descricao"]]
            )

    def test_lancamento_em_fim_de_semana_ou_feriado(self, gabarito, despesas, dados_pequenos):
        params, _ = dados_pequenos
        feriados = calendario.feriados_do_periodo(params.data_inicio, params.data_fim)
        linhas = self._linhas(gabarito, config.ANOMALIA_FIM_SEMANA_FERIADO)
        assert len(linhas) > 0
        for _, a in linhas.iterrows():
            registro = despesas.iloc[int(a["linha_arquivo"]) - 1]
            assert registro["numero_documento"] == a["identificador"]
            dia = data(registro["data_lancamento"])
            assert calendario.eh_fim_de_semana(dia) or dia in feriados

    def test_despesas_normais_ficam_em_dias_uteis(self, gabarito, despesas, dados_pequenos):
        params, _ = dados_pequenos
        feriados = calendario.feriados_do_periodo(params.data_inicio, params.data_fim)
        marcados = set(self._linhas(gabarito, config.ANOMALIA_FIM_SEMANA_FERIADO)["linha_arquivo"])
        for linha, texto in enumerate(despesas["data_lancamento"], start=1):
            if str(linha) in marcados:
                continue
            dia = data(texto)
            assert not calendario.eh_fim_de_semana(dia) and dia not in feriados

    def test_venda_com_margem_negativa(self, gabarito, dados_pequenos):
        params, _ = dados_pequenos
        vendas = ler_vendas(params.diretorio_saida).set_index(["arquivo", "linha"])
        linhas = self._linhas(gabarito, config.ANOMALIA_MARGEM_NEGATIVA)
        assert len(linhas) > 0
        for _, a in linhas.iterrows():
            venda = vendas.loc[(a["arquivo"], int(a["linha_arquivo"]))]
            assert venda["id_venda_erp"] == a["identificador"]
            assert numero(venda["custo_total"]) > numero(venda["receita_liquida"])

    def test_vendas_normais_nao_tem_margem_negativa(self, gabarito, dados_pequenos):
        params, _ = dados_pequenos
        vendas = ler_vendas(params.diretorio_saida)
        negativas = vendas[
            [
                numero(c) > numero(r)
                for c, r in zip(vendas["custo_total"], vendas["receita_liquida"], strict=True)
            ]
        ]
        esperadas = set(self._linhas(gabarito, config.ANOMALIA_MARGEM_NEGATIVA)["identificador"])
        assert set(negativas["id_venda_erp"]) == esperadas

    def test_despesa_acima_do_orcado(self, gabarito, despesas, dados_pequenos):
        params, _ = dados_pequenos
        orcamento = ler_csv(params.diretorio_saida / config.ARQ_ORCAMENTO)
        orcamento["chave"] = [
            f"{c}|{data(d):%Y-%m}"
            for c, d in zip(orcamento["cod_centro_custo"], orcamento["competencia"], strict=True)
        ]
        orcado = {
            k: numero(v) for k, v in zip(orcamento["chave"], orcamento["valor_orcado"], strict=True)
        }
        despesas["chave"] = [
            f"{c}|{data(d):%Y-%m}"
            for c, d in zip(despesas["cod_centro_custo"], despesas["data_lancamento"], strict=True)
        ]
        realizado = despesas.groupby("chave")["valor_num"].sum()
        linhas = self._linhas(gabarito, config.ANOMALIA_ACIMA_ORCADO)
        assert len(linhas) > 0
        for chave in linhas["identificador"]:
            assert realizado[chave] > 1.3 * orcado[chave]


def test_problemas_de_qualidade_registrados_e_presentes_nos_arquivos(dados_pequenos):
    params, resumo = dados_pequenos
    for tipo in (
        config.PROBLEMA_DATA_FORMATO_MISTO,
        config.PROBLEMA_SKU_SUJO,
        config.PROBLEMA_VALOR_TEXTO_BR,
        config.PROBLEMA_VALOR_NULO,
    ):
        assert resumo.problemas_por_tipo.get(tipo, 0) > 0, tipo

    problemas = ler_csv(params.diretorio_saida / config.ARQ_PROBLEMAS)
    vendas = ler_vendas(params.diretorio_saida).set_index(["arquivo", "linha"])
    amostra = problemas[problemas["arquivo"].str.startswith("vendas_")].head(300)
    for _, p in amostra.iterrows():
        gravado = vendas.loc[(p["arquivo"], int(p["linha_arquivo"]))][p["coluna"]]
        assert gravado == p["valor_gravado"]


def test_datas_aparecem_nos_dois_formatos(dados_pequenos):
    params, _ = dados_pequenos
    textos = ler_vendas(params.diretorio_saida)["data_venda"]
    assert textos.str.match(r"^\d{2}/\d{2}/\d{4}$").any()
    assert textos.str.match(r"^\d{4}-\d{2}-\d{2}$").any()


def test_mesma_semente_gera_arquivos_identicos(parametros_pequenos, tmp_path_factory):
    outra_pasta = tmp_path_factory.mktemp("raw_repetido")
    gerar_dados(parametros_pequenos)
    gerar_dados(com_saida(parametros_pequenos, outra_pasta))
    assert hash_da_pasta(parametros_pequenos.diretorio_saida) == hash_da_pasta(outra_pasta)


def test_semente_diferente_gera_arquivos_diferentes(parametros_pequenos, tmp_path_factory):
    outra_pasta = tmp_path_factory.mktemp("raw_outra_semente")
    gerar_dados(parametros_pequenos)
    gerar_dados(
        com_saida(parametros_pequenos, outra_pasta, semente=parametros_pequenos.semente + 1)
    )
    antes = hash_da_pasta(parametros_pequenos.diretorio_saida)
    depois = hash_da_pasta(outra_pasta)
    assert antes["despesas.csv"] != depois["despesas.csv"]
    assert antes["vendas_2024-01.csv"] != depois["vendas_2024-01.csv"]
