"""Ponta a ponta: gera dados, carrega no banco de teste e confere contra os GABARITOS.

Os gabaritos (_problemas_qualidade.csv e _anomalias_injetadas.csv) só existem para estes testes:
o código de produção nunca os lê. Aqui conferimos que
  * todo problema de qualidade injetado foi corrigido (ou rejeitado com motivo);
  * toda anomalia injetada chegou ao dw intacta e é vista pelos sinais de negócio;
  * contagens e somas batem com os arquivos;
  * rodar de novo não muda nada.
"""

import dataclasses
from collections import Counter
from datetime import time
from decimal import Decimal

import pytest

from src import config
from src.etl import pipeline, relatorio
from src.etl.mapeamento import carregar_fontes
from src.gerador.parametros import ParametrosGeracao
from src.gerador.principal import gerar_dados
from tests.gerador.utilitarios import data, hora, ler_csv, ler_vendas, numero

pytestmark = pytest.mark.banco

LINHAS_VENDA = 12_000
ENTIDADE_DO_ARQUIVO = {
    config.ARQ_DESPESAS: "despesas",
    config.ARQ_VENDEDORES: "vendedores",
}
NAO_INFORMADO = "NAO INFORMADO"
CENTAVO = Decimal("0.01")


def _entidade(arquivo: str) -> str:
    return "vendas" if arquivo.startswith("vendas_") else ENTIDADE_DO_ARQUIVO[arquivo]


@pytest.fixture(scope="module")
def dados(tmp_path_factory):
    params = ParametrosGeracao(
        diretorio_saida=tmp_path_factory.mktemp("raw_ponta_a_ponta"),
        total_linhas_venda=LINHAS_VENDA,
        verificar_memoria=False,
    )
    gerar_dados(params)
    return params


@pytest.fixture(scope="module")
def pasta(dados):
    return dados.diretorio_saida


@pytest.fixture(scope="module")
def erp(pasta):
    return dataclasses.replace(carregar_fontes()["lojas_ipe_erp"], pasta=pasta)


@pytest.fixture(scope="module")
def carga(banco_compartilhado, erp, tmp_path_factory):
    resultado = pipeline.carregar(
        banco_compartilhado,
        erp,
        verificar_memoria=False,
        pasta_relatorios=tmp_path_factory.mktemp("relatorios"),
    )
    return banco_compartilhado, resultado


@pytest.fixture(scope="module")
def problemas(pasta):
    return ler_csv(pasta / config.ARQ_PROBLEMAS).to_dict("records")


@pytest.fixture(scope="module")
def anomalias(pasta):
    return ler_csv(pasta / config.ARQ_ANOMALIAS).to_dict("records")


@pytest.fixture(scope="module")
def vendas_dw(carga):
    con, _ = carga
    linhas = con.execute(
        "SELECT f.arquivo_origem, f.linha_origem, f.data_hora_venda::DATE, f.data_hora_venda::TIME,"
        " p.sku, f.preco_unitario, f.desconto, f.receita_liquida, f.custo, f.id_venda_erp"
        " FROM dw.fato_vendas f JOIN dw.dim_produto p USING (sk_produto)"
    ).fetchall()
    chaves = ("data_venda", "hora_venda", "sku", "preco_unitario", "desconto", "receita_liquida")
    return {
        (arq, lin): dict(zip((*chaves, "custo_total", "id"), resto, strict=True))
        for arq, lin, *resto in linhas
    }


@pytest.fixture(scope="module")
def despesas_dw(carga):
    con, _ = carga
    linhas = con.execute(
        "SELECT f.arquivo_origem, f.linha_origem, t.data, f.valor, f.descricao, c.cod_centro_custo,"
        " f.numero_documento FROM dw.fato_despesas f JOIN dw.dim_tempo t USING (sk_tempo)"
        " JOIN dw.dim_centro_custo c USING (sk_centro_custo)"
    ).fetchall()
    chaves = ("data_lancamento", "valor", "descricao", "cod_centro_custo", "numero_documento")
    return {(arq, lin): dict(zip(chaves, resto, strict=True)) for arq, lin, *resto in linhas}


@pytest.fixture(scope="module")
def vendedores_dw(carga, pasta):
    con, _ = carga
    nomes = dict(con.execute("SELECT cod_vendedor, nome_vendedor FROM dw.dim_vendedor"))
    codigos = ler_csv(pasta / config.ARQ_VENDEDORES)["cod_vendedor"].tolist()
    return {
        (config.ARQ_VENDEDORES, i + 1): {"nome_vendedor": nomes[c]} for i, c in enumerate(codigos)
    }


def _dinheiro(texto: str) -> Decimal:
    return Decimal(f"{numero(texto):.2f}")


def _rejeitados(con) -> set[tuple[str, int]]:
    return {
        (a, int(lin))
        for a, lin in con.execute("SELECT arquivo_origem, linha_origem FROM stg.rejeitados")
    }


# ---- 1. problemas de qualidade --------------------------------------------------------------
class TestProblemasDeQualidade:
    def test_a_carga_foi_aprovada_e_nada_do_erp_foi_rejeitado(self, carga):
        con, resultado = carga
        assert resultado.aprovada
        assert con.execute("SELECT count(*) FROM stg.rejeitados").fetchone()[0] == 0

    def _esperado(self, problema, destino) -> object:
        coluna, tipo = problema["coluna"], problema["tipo_problema"]
        original = problema["valor_original"]
        if tipo == config.PROBLEMA_VALOR_NULO:
            # desconto vazio é recalculável (volta ao original); descrição vira 'NAO INFORMADO'
            return NAO_INFORMADO if coluna == "descricao" else _dinheiro(original)
        if coluna == "hora_venda":
            esperado = hora(original)
            sem_segundos = (
                problema["valor_gravado"].count(":") < 2 or "h" in problema["valor_gravado"]
            )
            return time(esperado.hour, esperado.minute) if sem_segundos else esperado
        if coluna in ("data_venda", "data_lancamento"):
            return data(original)
        if coluna in ("sku", "nome_vendedor"):
            return original
        return _dinheiro(original)

    def test_todo_problema_injetado_foi_corrigido_ou_rejeitado_com_motivo(
        self, carga, problemas, vendas_dw, despesas_dw, vendedores_dw
    ):
        con, _ = carga
        rejeitados = _rejeitados(con)
        destinos = {"vendas": vendas_dw, "despesas": despesas_dw, "vendedores": vendedores_dw}
        coluna_no_dw = {"custo_total": "custo_total"}
        sem_valor_no_dw = {"total_cupom"}  # só existe no staging: conferido nas contagens
        falhas, conferidos = [], 0
        for p in problemas:
            if p["coluna"] in sem_valor_no_dw:
                continue
            chave = (p["arquivo"], int(p["linha_arquivo"]))
            if chave in rejeitados:
                continue  # rejeitado com motivo (nenhum esperado no ERP, mas é um desfecho válido)
            linha = destinos[_entidade(p["arquivo"])].get(chave)
            if linha is None:
                falhas.append((chave, p["coluna"], "linha ausente no dw"))
                continue
            obtido = linha[coluna_no_dw.get(p["coluna"], p["coluna"])]
            esperado = self._esperado(p, destinos)
            conferidos += 1
            if obtido != esperado:
                falhas.append((chave, p["coluna"], p["tipo_problema"], esperado, obtido))
        assert conferidos > 500
        assert not falhas, falhas[:5]

    def test_correcoes_contadas_pelo_etl_batem_com_o_gabarito_por_tipo(self, carga, problemas):
        _, resultado = carga
        esperado = Counter(p["tipo_problema"] for p in problemas)
        assert resultado.relatorio["corrigidas_por_tipo"] == dict(sorted(esperado.items()))

    def test_correcoes_batem_por_entidade_e_coluna(self, carga, problemas):
        _, resultado = carga
        esperado = Counter(
            (_entidade(p["arquivo"]), p["coluna"], p["tipo_problema"]) for p in problemas
        )
        obtido = Counter(
            {
                (c["entidade"], c["coluna"], c["tipo_problema"]): c["quantidade"]
                for c in resultado.relatorio["correcoes"]
            }
        )
        assert obtido == esperado

    def test_todos_os_tipos_de_problema_estao_representados(self, problemas):
        assert {p["tipo_problema"] for p in problemas} == {
            config.PROBLEMA_DATA_FORMATO_MISTO,
            config.PROBLEMA_HORA_FORMATO_MISTO,
            config.PROBLEMA_SKU_SUJO,
            config.PROBLEMA_VALOR_TEXTO_BR,
            config.PROBLEMA_VALOR_NULO,
            config.PROBLEMA_NOME_SUJO,
        }


# ---- 2. anomalias --------------------------------------------------------------------------
class TestAnomaliasChegamIntactas:
    def _do_tipo(self, anomalias, tipo):
        achadas = [a for a in anomalias if a["tipo_anomalia"] == tipo]
        assert achadas, tipo
        return achadas

    def test_quantidades_do_gabarito(self, anomalias):
        contagem = Counter(a["tipo_anomalia"] for a in anomalias)
        assert dict(contagem) == config.QUANTIDADE_ANOMALIAS

    def test_margem_negativa(self, carga, anomalias):
        con, _ = carga
        ids = {
            a["identificador"] for a in self._do_tipo(anomalias, config.ANOMALIA_MARGEM_NEGATIVA)
        }
        no_dw = {
            i for (i,) in con.execute("SELECT id_venda_erp FROM dw.fato_vendas WHERE margem < 0")
        }
        assert no_dw == ids  # as anomalias existem e nenhuma venda normal tem margem negativa

    def test_desconto_acima_do_limite(self, carga, anomalias):
        con, _ = carga
        ids = {
            a["identificador"]
            for a in self._do_tipo(anomalias, config.ANOMALIA_DESCONTO_ACIMA_LIMITE)
        }
        no_dw = {
            i
            for (i,) in con.execute(
                "SELECT id_venda_erp FROM dw.fato_vendas"
                " WHERE desconto > quantidade * preco_unitario * 0.18 + 0.01"
            )
        }
        assert no_dw == ids

    def test_venda_fora_do_horario(self, carga, anomalias):
        con, _ = carga
        cupons = {
            a["identificador"] for a in self._do_tipo(anomalias, config.ANOMALIA_FORA_HORARIO)
        }
        fora = {
            c
            for (c,) in con.execute(
                "SELECT DISTINCT f.numero_cupom FROM dw.fato_vendas f JOIN dw.dim_loja_horario h"
                " ON h.sk_loja = f.sk_loja"
                " AND h.dia_semana = extract(isodow FROM f.data_hora_venda)"
                " WHERE f.data_hora_venda::TIME < h.hora_abertura"
                " OR f.data_hora_venda::TIME >= h.hora_fechamento"
            )
        }
        assert fora == cupons

    def test_cupom_duplicado(self, carga, anomalias):
        con, _ = carga
        cupons = {
            a["identificador"] for a in self._do_tipo(anomalias, config.ANOMALIA_CUPOM_DUPLICADO)
        }
        repetidos = {
            c
            for (c,) in con.execute(
                "SELECT DISTINCT numero_cupom FROM (SELECT numero_cupom FROM dw.fato_vendas"
                " GROUP BY numero_cupom, numero_item HAVING count(*) > 1) x"
            )
        }
        assert repetidos == cupons

    def test_vendedores_com_cancelamento_alto_lideram_a_taxa(self, carga, anomalias):
        con, _ = carga
        marcados = {
            a["identificador"]
            for a in self._do_tipo(anomalias, config.ANOMALIA_VENDEDOR_CANCELAMENTO)
        }
        taxas = con.execute(
            "SELECT v.cod_vendedor FROM (SELECT DISTINCT numero_cupom, sk_vendedor, status"
            " FROM dw.fato_vendas) c JOIN dw.dim_vendedor v USING (sk_vendedor)"
            " GROUP BY v.cod_vendedor HAVING count(*) >= 15"
            " ORDER BY avg((status = 'Cancelada')::INT) DESC LIMIT %s",
            (len(marcados),),
        ).fetchall()
        assert {c for (c,) in taxas} == marcados

    def test_despesas_duplicadas_atipicas_e_no_centro_errado(self, carga, anomalias, despesas_dw):
        con, _ = carga
        for a in self._do_tipo(anomalias, config.ANOMALIA_DESPESA_DUPLICADA):
            linha = despesas_dw[(a["arquivo"], int(a["linha_arquivo"]))]
            repeticoes = con.execute(
                "SELECT count(*) FROM dw.fato_despesas WHERE numero_documento = %s",
                (linha["numero_documento"],),
            ).fetchone()[0]
            assert linha["numero_documento"] == a["identificador"] and repeticoes == 2
        for a in self._do_tipo(anomalias, config.ANOMALIA_VALOR_ATIPICO):
            linha = despesas_dw[(a["arquivo"], int(a["linha_arquivo"]))]
            assert linha["valor"] == _dinheiro(a["valor"])
        for a in self._do_tipo(anomalias, config.ANOMALIA_CENTRO_CUSTO_ERRADO):
            linha = despesas_dw[(a["arquivo"], int(a["linha_arquivo"]))]
            assert linha["cod_centro_custo"] == a["cod_centro_custo"]

    def test_lancamentos_em_fim_de_semana_ou_feriado(self, carga, anomalias, despesas_dw):
        con, _ = carga
        nao_uteis = {
            d
            for (d,) in con.execute(
                "SELECT data FROM dw.dim_tempo WHERE feriado_nacional"
                " OR nome_dia_semana IN ('Sábado', 'Domingo')"
            )
        }
        for a in self._do_tipo(anomalias, config.ANOMALIA_FIM_SEMANA_FERIADO):
            linha = despesas_dw[(a["arquivo"], int(a["linha_arquivo"]))]
            assert linha["data_lancamento"] in nao_uteis
            assert linha["data_lancamento"] == data(a["data_referencia"])

    def test_despesas_acima_do_orcado(self, carga, anomalias):
        con, _ = carga
        for a in self._do_tipo(anomalias, config.ANOMALIA_ACIMA_ORCADO):
            realizado, orcado = con.execute(
                "SELECT (SELECT sum(f.valor) FROM dw.fato_despesas f JOIN dw.dim_tempo t"
                "  USING (sk_tempo) JOIN dw.dim_centro_custo c USING (sk_centro_custo)"
                "  WHERE c.cod_centro_custo = %(cc)s AND t.ano = %(ano)s AND t.mes = %(mes)s),"
                " (SELECT o.valor_orcado FROM dw.fato_orcamento_despesas o JOIN dw.dim_tempo t"
                "  USING (sk_tempo) JOIN dw.dim_centro_custo c USING (sk_centro_custo)"
                "  WHERE c.cod_centro_custo = %(cc)s AND t.ano = %(ano)s AND t.mes = %(mes)s)",
                {
                    "cc": a["cod_centro_custo"],
                    "ano": int(a["data_referencia"][:4]),
                    "mes": int(a["data_referencia"][5:7]),
                },
            ).fetchone()
            assert abs(realizado - _dinheiro(a["valor"])) <= 2 * CENTAVO  # soma de lançamentos
            assert realizado > Decimal("1.3") * orcado

    def test_nenhuma_anomalia_foi_rejeitada_ou_alterada_pelo_etl(self, carga, anomalias):
        con, _ = carga
        assert con.execute("SELECT count(*) FROM stg.rejeitados").fetchone()[0] == 0
        assert len(anomalias) == sum(config.QUANTIDADE_ANOMALIAS.values())


@pytest.fixture(scope="module")
def sinais(carga):
    _, resultado = carga
    return {s["sinal"]: s["quantidade"] for s in resultado.relatorio["sinais_de_negocio"]}


class TestSinaisVersusGabarito:
    """Os sinais de negócio enxergam as anomalias, sem nunca consultar o gabarito."""

    def test_sinais_de_venda_batem_com_as_quantidades_injetadas(self, sinais):
        q = config.QUANTIDADE_ANOMALIAS
        assert sinais["margem_negativa"] == q[config.ANOMALIA_MARGEM_NEGATIVA]
        assert sinais["desconto_acima_do_limite"] == q[config.ANOMALIA_DESCONTO_ACIMA_LIMITE]
        assert sinais["venda_fora_do_horario"] == q[config.ANOMALIA_FORA_HORARIO]
        assert sinais["cupom_duplicado"] == q[config.ANOMALIA_CUPOM_DUPLICADO]
        assert sinais["venda_de_vendedor_inativo"] == 0  # não é anomalia injetada

    def test_sinais_de_despesa(self, sinais):
        q = config.QUANTIDADE_ANOMALIAS
        assert sinais["despesa_documento_repetido"] == q[config.ANOMALIA_DESPESA_DUPLICADA]
        assert (
            sinais["despesa_em_fim_de_semana_ou_feriado"] == q[config.ANOMALIA_FIM_SEMANA_FERIADO]
        )
        assert sinais["despesa_de_valor_atipico"] >= q[config.ANOMALIA_VALOR_ATIPICO]
        assert sinais["despesa_acima_do_orcado"] >= q[config.ANOMALIA_ACIMA_ORCADO]


# ---- 3. contagens e somas ------------------------------------------------------------------
class TestContagensESomas:
    def test_linhas_dos_arquivos_igual_staging_igual_dw_mais_rejeitados(self, carga, pasta):
        con, resultado = carga
        assert resultado.relatorio["resumo"]["linhas_rejeitadas"] == 0
        arquivos = {a["arquivo"]: a["linhas_lidas"] for a in resultado.relatorio["arquivos"]}
        for arquivo, lidas in arquivos.items():
            assert lidas == len(ler_csv(pasta / arquivo)), arquivo
        por_tabela = {t["entidade"]: t for t in resultado.relatorio["tabelas"]}
        dw = resultado.relatorio["linhas_no_dw"]
        assert por_tabela["vendas"]["carregadas"] == dw["fato_vendas"]
        assert por_tabela["despesas"]["carregadas"] == dw["fato_despesas"]
        assert por_tabela["metas_vendas"]["carregadas"] == dw["fato_meta_vendas"]
        assert por_tabela["metas_vendedor"]["carregadas"] == dw["fato_meta_vendedor"]
        assert por_tabela["orcamento_despesas"]["carregadas"] == dw["fato_orcamento_despesas"]
        assert por_tabela["vendedores"]["carregadas"] == dw["dim_vendedor"]
        assert dw["fato_vendas"] == len(ler_vendas(pasta))
        for t in por_tabela.values():
            assert t["lidas"] == t["rejeitadas"] + t["carregadas"], t["entidade"]

    def test_somas_monetarias_batem_com_os_arquivos(self, carga, pasta):
        con, _ = carga
        vendas = ler_vendas(pasta)
        for coluna_csv, coluna_dw in (
            ("receita_liquida", "receita_liquida"),
            ("custo_total", "custo"),
            ("preco_unitario", "preco_unitario"),
        ):
            esperado = sum(_dinheiro(v) for v in vendas[coluna_csv])
            obtido = con.execute(f"SELECT sum({coluna_dw}) FROM dw.fato_vendas").fetchone()[0]
            assert obtido == esperado, coluna_csv
        despesas = ler_csv(pasta / config.ARQ_DESPESAS)
        assert con.execute("SELECT sum(valor) FROM dw.fato_despesas").fetchone()[0] == sum(
            _dinheiro(v) for v in despesas["valor"]
        )
        orcamento = ler_csv(pasta / config.ARQ_ORCAMENTO)
        assert con.execute("SELECT sum(valor_orcado) FROM dw.fato_orcamento_despesas").fetchone()[
            0
        ] == sum(_dinheiro(v) for v in orcamento["valor_orcado"])
        metas = ler_csv(pasta / config.ARQ_METAS)
        assert con.execute("SELECT sum(valor_meta) FROM dw.fato_meta_vendas").fetchone()[0] == sum(
            _dinheiro(v) for v in metas["valor_meta"]
        )

    def test_soma_dos_itens_e_igual_ao_total_do_cupom_nos_arquivos(self, carga, pasta):
        """Conferência independente da validação do ETL, feita sobre o dw e os arquivos."""
        con, _ = carga
        vendas = ler_vendas(pasta).drop_duplicates(["numero_cupom", "numero_item"])
        vendas["receita"] = [_dinheiro(v) for v in vendas["receita_liquida"]]
        vendas["total"] = [_dinheiro(v) for v in vendas["total_cupom"]]
        por_cupom = vendas.groupby("numero_cupom").agg(
            soma=("receita", "sum"), total=("total", "first")
        )
        assert (por_cupom["soma"] == por_cupom["total"]).all()
        no_dw = con.execute("SELECT count(DISTINCT numero_cupom) FROM dw.fato_vendas").fetchone()[0]
        assert no_dw == len(por_cupom)

    def test_relatorio_tem_todas_as_secoes_pedidas(self, carga):
        _, resultado = carga
        doc = resultado.relatorio
        for chave in (
            "resumo",
            "arquivos",
            "tabelas",
            "corrigidas_por_tipo",
            "rejeitadas_por_motivo",
            "validacoes_estruturais",
            "sinais_de_negocio",
            "linhas_no_dw",
            "desempenho",
        ):
            assert chave in doc, chave
        assert doc["status"] == "concluida"
        assert resultado.caminho_relatorio.exists()


# ---- 4. idempotência -----------------------------------------------------------------------
class TestSegundaExecucao:
    def test_rodar_de_novo_nao_muda_nada(self, carga, erp, tmp_path):
        con, _ = carga
        antes = _fingerprint(con)
        incremental = pipeline.carregar(
            con, erp, verificar_memoria=False, pasta_relatorios=tmp_path
        )
        assert incremental.aprovada and incremental.relatorio["resumo"]["linhas_lidas"] == 0
        assert _fingerprint(con) == antes
        completa = pipeline.carregar(
            con, erp, modo="completo", verificar_memoria=False, pasta_relatorios=tmp_path
        )
        assert completa.aprovada
        assert completa.relatorio["resumo"]["linhas_lidas"] > 0
        assert all(
            t["inseridas"] == 0 and t["atualizadas"] == 0 for t in completa.relatorio["tabelas"]
        )
        assert _fingerprint(con) == antes

    def test_nada_duplicado_alem_das_duplicatas_do_gabarito(self, carga, anomalias):
        con, _ = carga
        repetidos = con.execute(
            "SELECT count(DISTINCT numero_cupom) FROM (SELECT numero_cupom FROM dw.fato_vendas"
            " GROUP BY numero_cupom, numero_item HAVING count(*) > 1) x"
        ).fetchone()[0]
        assert repetidos == config.QUANTIDADE_ANOMALIAS[config.ANOMALIA_CUPOM_DUPLICADO]
        for tabela, chave in (
            ("dim_loja", "cod_loja"),
            ("dim_produto", "sku"),
            ("dim_vendedor", "cod_vendedor"),
            ("dim_cliente", "cod_cliente"),
            ("fato_vendas", "id_venda_erp"),
            ("fato_meta_vendas", "sk_tempo, sk_loja, setor"),
        ):
            assert (
                con.execute(
                    f"SELECT count(*) - count(DISTINCT ({chave})) FROM dw.{tabela}"
                ).fetchone()[0]
                == 0
            ), tabela


def _fingerprint(con) -> dict[str, str]:
    return {
        tabela: con.execute(
            f"SELECT md5(string_agg(t::TEXT, '|' ORDER BY t::TEXT)) FROM dw.{tabela} t"
        ).fetchone()[0]
        for tabela in relatorio.TABELAS_DW
    }
