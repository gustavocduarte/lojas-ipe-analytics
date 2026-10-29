"""Cargas stg -> dw (procedures PL/pgSQL): dimensões, fatos, rejeitados e correções."""

import dataclasses
import shutil

import pytest

from src import config
from src.etl.leitura import carregar_para_staging
from src.etl.mapeamento import carregar_fontes
from tests.gerador.utilitarios import ler_csv, ler_vendas

pytestmark = pytest.mark.banco

TABELAS_DW_POR_ENTIDADE = {
    "lojas": "dim_loja",
    "horarios_loja": "dim_loja_horario",
    "produtos": "dim_produto",
    "centros_custo": "dim_centro_custo",
    "formas_pagamento": "dim_forma_pagamento",
    "campanhas": "dim_campanha",
    "vendedores": "dim_vendedor",
    "clientes": "dim_cliente",
    "vendas": "fato_vendas",
    "metas_vendas": "fato_meta_vendas",
    "metas_vendedor": "fato_meta_vendedor",
    "despesas": "fato_despesas",
    "orcamento_despesas": "fato_orcamento_despesas",
}


@pytest.fixture
def erp(dados_pequenos, tmp_path):
    params, _ = dados_pequenos
    pasta = tmp_path / "raw"
    shutil.copytree(params.diretorio_saida, pasta)
    return dataclasses.replace(carregar_fontes()["lojas_ipe_erp"], pasta=pasta)


def _carregar(con, fonte, **opcoes):
    """Staging + dw numa transação, como fará o pipeline. Devolve o id da carga."""
    id_carga = carregar_para_staging(con, fonte, **opcoes).id_carga
    con.execute("CALL etl.carregar_dw(%s)", (id_carga,))
    con.commit()
    return id_carga


def _contar(con, tabela, esquema="dw"):
    return con.execute(f"SELECT count(*) FROM {esquema}.{tabela}").fetchone()[0]


def _editar(pasta, arquivo, linha, coluna, valor):
    """Troca o valor de uma célula (linha = posição de dados, 1 = primeira após o cabeçalho)."""
    caminho = pasta / arquivo
    linhas = caminho.read_text(encoding="utf-8").splitlines()
    cabecalho = linhas[0].split(";")
    partes = linhas[linha].split(";")
    partes[cabecalho.index(coluna)] = valor
    linhas[linha] = ";".join(partes)
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")


def _rejeitados(con):
    return {
        (arq, lin, col): m
        for arq, lin, col, m in con.execute(
            "SELECT arquivo_origem, linha_origem, coluna, motivo FROM stg.rejeitados"
        )
    }


class TestCargaDoErp:
    def test_todas_as_tabelas_do_dw_recebem_dados(self, banco_com_ddl, erp):
        _carregar(banco_com_ddl, erp)
        for tabela in TABELAS_DW_POR_ENTIDADE.values():
            assert _contar(banco_com_ddl, tabela) > 0, tabela
        assert _contar(banco_com_ddl, "dim_hora") == 24
        assert _contar(banco_com_ddl, "dim_tempo") == 731  # 2024 (bissexto) + 2025

    def test_nada_do_erp_e_rejeitado_pois_todo_problema_tem_correcao(self, banco_com_ddl, erp):
        _carregar(banco_com_ddl, erp)
        assert _contar(banco_com_ddl, "rejeitados", "stg") == 0

    def test_contagens_por_entidade_fecham(self, banco_com_ddl, erp):
        id_carga = _carregar(banco_com_ddl, erp)
        linhas = banco_com_ddl.execute(
            "SELECT entidade, lidas, rejeitadas, carregadas, inseridas FROM etl.carga_tabelas"
            " WHERE id_carga = %s",
            (id_carga,),
        ).fetchall()
        assert {e for e, *_ in linhas} == set(TABELAS_DW_POR_ENTIDADE) | {"feriados"}
        for entidade, lidas, rejeitadas, carregadas, inseridas in linhas:
            assert lidas == rejeitadas + carregadas, entidade
            assert inseridas == carregadas, entidade  # banco vazio: tudo é inserção

    def test_vendas_no_dw_tem_um_item_por_linha_do_staging(self, banco_com_ddl, erp):
        _carregar(banco_com_ddl, erp)
        total_csv = len(ler_vendas(erp.pasta))
        assert _contar(banco_com_ddl, "fato_vendas") == total_csv  # duplicatas incluídas

    def test_valores_corrigidos_chegam_tipados(self, banco_com_ddl, erp):
        _carregar(banco_com_ddl, erp)
        con = banco_com_ddl
        assert con.execute("SELECT count(*) FROM dw.fato_vendas WHERE receita_liquida IS NULL")
        # nenhum nome de vendedor ficou com espaços repetidos ou caixa estranha
        nomes = [n for (n,) in con.execute("SELECT nome_vendedor FROM dw.dim_vendedor")]
        assert all(n == " ".join(n.split()) for n in nomes)
        assert all(n[0].isupper() for n in nomes)
        skus = [s for (s,) in con.execute("SELECT sku FROM dw.dim_produto")]
        assert all(s == s.upper() and " " not in s for s in skus)
        faixas = dict(con.execute("SELECT hora, faixa_do_dia FROM dw.dim_hora"))
        for faixa, inicio, fim in config.FAIXAS_DO_DIA:
            assert all(faixas[h] == faixa for h in range(inicio, fim + 1)), faixa

    def test_feriados_marcados_na_dim_tempo(self, banco_com_ddl, erp):
        _carregar(banco_com_ddl, erp)
        n = banco_com_ddl.execute(
            "SELECT count(*) FROM dw.dim_tempo WHERE feriado_nacional"
        ).fetchone()[0]
        assert n == len(ler_csv(erp.pasta / "feriados.csv"))

    def test_desconto_nulo_e_recalculado(self, banco_com_ddl, erp):
        _carregar(banco_com_ddl, erp)
        inconsistentes = banco_com_ddl.execute(
            "SELECT count(*) FROM dw.fato_vendas WHERE round(quantidade * preco_unitario - desconto"
            " - receita_liquida, 2) <> 0"
        ).fetchone()[0]
        assert inconsistentes == 0

    def test_correcoes_sao_contadas_por_tipo(self, banco_com_ddl, erp):
        id_carga = _carregar(banco_com_ddl, erp)
        tipos = {
            t
            for (t,) in banco_com_ddl.execute(
                "SELECT DISTINCT tipo_problema FROM etl.carga_correcoes WHERE id_carga = %s",
                (id_carga,),
            )
        }
        assert tipos == {
            config.PROBLEMA_DATA_FORMATO_MISTO,
            config.PROBLEMA_HORA_FORMATO_MISTO,
            config.PROBLEMA_SKU_SUJO,
            config.PROBLEMA_VALOR_TEXTO_BR,
            config.PROBLEMA_VALOR_NULO,
            config.PROBLEMA_NOME_SUJO,
        }


class TestRejeicao:
    """Linhas que não têm correção vão para stg.rejeitados, com o motivo, e o resto carrega."""

    def test_vendas_invalidas_sao_rejeitadas_com_motivo(self, banco_com_ddl, erp):
        arquivo = "vendas_2024-03.csv"
        _editar(erp.pasta, arquivo, 1, "data_venda", "31/02/2024")
        _editar(erp.pasta, arquivo, 2, "sku", "XXX-9999")
        _editar(erp.pasta, arquivo, 3, "receita_liquida", "doze reais")
        _editar(erp.pasta, arquivo, 4, "cod_vendedor", "V9999")
        _editar(erp.pasta, arquivo, 5, "hora_venda", "25:99")
        _editar(erp.pasta, arquivo, 6, "quantidade", "0")
        _editar(erp.pasta, arquivo, 7, "status", "Perdida")
        _editar(erp.pasta, arquivo, 8, "cod_loja", "")
        _editar(erp.pasta, arquivo, 9, "preco_unitario", "-5")
        _carregar(banco_com_ddl, erp)
        assert _rejeitados(banco_com_ddl) == {
            (arquivo, 1, "data_venda"): "data_invalida",
            (arquivo, 2, "sku"): "sku_inexistente",
            (arquivo, 3, "receita_liquida"): "valor_nao_numerico",
            (arquivo, 4, "cod_vendedor"): "vendedor_inexistente",
            (arquivo, 5, "hora_venda"): "hora_invalida",
            (arquivo, 6, "quantidade"): "inteiro_invalido",
            (arquivo, 7, "status"): "status_invalido",
            (arquivo, 8, "cod_loja"): "obrigatorio_vazio",
            (arquivo, 9, "preco_unitario"): "valor_negativo",
        }
        total = len(ler_vendas(erp.pasta))
        assert _contar(banco_com_ddl, "fato_vendas") == total - 9
        rejeitado = banco_com_ddl.execute(
            "SELECT valor_original, entidade FROM stg.rejeitados WHERE coluna = 'receita_liquida'"
        ).fetchone()
        assert rejeitado == ("doze reais", "vendas")

    def test_id_de_venda_repetido_rejeita_a_segunda_ocorrencia(self, banco_com_ddl, erp):
        arquivo = "vendas_2024-03.csv"
        linhas = (erp.pasta / arquivo).read_text(encoding="utf-8").splitlines()
        id_primeira = linhas[1].split(";")[0]
        _editar(erp.pasta, arquivo, 2, "id_venda_erp", id_primeira)
        _carregar(banco_com_ddl, erp)
        assert _rejeitados(banco_com_ddl) == {
            (arquivo, 2, "id_venda_erp"): "chave_duplicada_na_carga"
        }

    def test_cadastros_invalidos(self, banco_com_ddl, erp):
        _editar(erp.pasta, "lojas.csv", 3, "uf", "SPX")
        _editar(erp.pasta, "lojas.csv", 4, "data_abertura", "99/99/2020")
        _editar(erp.pasta, "produtos.csv", 5, "custo_unitario", "-1")
        _editar(erp.pasta, "vendedores.csv", 6, "turno", "Madrugada")
        _editar(erp.pasta, "vendedores.csv", 7, "cod_loja", "L99")
        _editar(erp.pasta, "campanhas.csv", 1, "data_fim", "01/01/2000")
        _editar(erp.pasta, "horarios_loja.csv", 2, "hora_fechamento", "05:00")
        _editar(erp.pasta, "centros_custo.csv", 2, "tipo_despesa", "Outros")
        _carregar(banco_com_ddl, erp)
        rejeitados = _rejeitados(banco_com_ddl)
        esperados = {
            ("lojas.csv", 3, "uf"): "uf_invalida",
            ("lojas.csv", 4, "data_abertura"): "data_invalida",
            ("produtos.csv", 5, "custo_unitario"): "valor_negativo",
            ("vendedores.csv", 6, "turno"): "turno_invalido",
            ("vendedores.csv", 7, "cod_loja"): "loja_inexistente",
            ("campanhas.csv", 1, "data_fim"): "fim_antes_do_inicio",
            ("horarios_loja.csv", 2, "hora_fechamento"): "fechamento_nao_posterior_a_abertura",
            ("centros_custo.csv", 2, "tipo_despesa"): "tipo_despesa_invalido",
        }
        assert esperados.items() <= rejeitados.items()
        # uma loja rejeitada leva consigo o que depende dela (centros, vendedores, horários, vendas)
        em_cascata = {k: m for k, m in rejeitados.items() if k not in esperados}
        assert em_cascata
        assert all(m.endswith("_inexistente") for m in em_cascata.values())

    def test_despesas_e_metas_invalidas(self, banco_com_ddl, erp):
        _editar(erp.pasta, "despesas.csv", 1, "cod_centro_custo", "CC-NAO-EXISTE")
        _editar(erp.pasta, "despesas.csv", 2, "valor", "muito")
        _editar(erp.pasta, "despesas.csv", 3, "data_lancamento", "")
        _editar(erp.pasta, "metas_vendas.csv", 1, "cod_loja", "L99")
        _editar(erp.pasta, "metas_vendedor.csv", 1, "valor_meta", "-3")
        _editar(erp.pasta, "orcamento_despesas.csv", 1, "competencia", "13/2024")
        _carregar(banco_com_ddl, erp)
        assert _rejeitados(banco_com_ddl) == {
            ("despesas.csv", 1, "cod_centro_custo"): "centro_custo_inexistente",
            ("despesas.csv", 2, "valor"): "valor_nao_numerico",
            ("despesas.csv", 3, "data_lancamento"): "obrigatorio_vazio",
            ("metas_vendas.csv", 1, "cod_loja"): "loja_inexistente",
            ("metas_vendedor.csv", 1, "valor_meta"): "valor_negativo",
            ("orcamento_despesas.csv", 1, "competencia"): "data_invalida",
        }

    def test_contagem_stg_igual_dw_mais_rejeitados(self, banco_com_ddl, erp):
        _editar(erp.pasta, "vendas_2024-03.csv", 1, "sku", "XXX-9999")
        _editar(erp.pasta, "despesas.csv", 2, "valor", "muito")
        id_carga = _carregar(banco_com_ddl, erp)
        for entidade, rejeitadas in (("vendas", 1), ("despesas", 1), ("lojas", 0)):
            lidas, rej, carregadas = banco_com_ddl.execute(
                "SELECT lidas, rejeitadas, carregadas FROM etl.carga_tabelas"
                " WHERE id_carga = %s AND entidade = %s",
                (id_carga, entidade),
            ).fetchone()
            assert rej == rejeitadas
            assert lidas == carregadas + rej
            stg = _contar(banco_com_ddl, entidade, "stg")
            assert stg == lidas
            assert _contar(banco_com_ddl, TABELAS_DW_POR_ENTIDADE[entidade]) == carregadas


class TestReprocessamento:
    def test_segunda_carga_completa_nao_muda_o_dw(self, banco_com_ddl, erp):
        _carregar(banco_com_ddl, erp)
        antes = {t: _contar(banco_com_ddl, t) for t in TABELAS_DW_POR_ENTIDADE.values()}
        id_segunda = _carregar(banco_com_ddl, erp, modo="completo")
        assert {t: _contar(banco_com_ddl, t) for t in TABELAS_DW_POR_ENTIDADE.values()} == antes
        for entidade, inseridas, atualizadas in banco_com_ddl.execute(
            "SELECT entidade, inseridas, atualizadas FROM etl.carga_tabelas WHERE id_carga = %s",
            (id_segunda,),
        ):
            assert (inseridas, atualizadas) == (0, 0), entidade

    def test_corrigir_o_arquivo_atualiza_e_remove_o_que_saiu(self, banco_com_ddl, erp):
        _carregar(banco_com_ddl, erp)
        total = _contar(banco_com_ddl, "fato_vendas")
        arquivo = erp.pasta / "vendas_2024-01.csv"
        linhas = arquivo.read_text(encoding="utf-8").splitlines()
        arquivo.write_text("\n".join(linhas[:-2]) + "\n", encoding="utf-8")  # duas vendas a menos
        id_carga = _carregar(banco_com_ddl, erp)
        assert _contar(banco_com_ddl, "fato_vendas") == total - 2
        removidas = banco_com_ddl.execute(
            "SELECT removidas FROM etl.carga_tabelas WHERE id_carga = %s AND entidade = 'vendas'",
            (id_carga,),
        ).fetchone()[0]
        assert removidas == 2

    def test_carga_de_uma_entidade_so_toca_nela(self, banco_com_ddl, erp):
        _carregar(banco_com_ddl, erp)
        _editar(erp.pasta, "lojas.csv", 1, "nome_loja", "Ipê Renomeada")
        id_carga = _carregar(banco_com_ddl, erp, entidades=["lojas"])
        nome = banco_com_ddl.execute("SELECT nome_loja FROM dw.dim_loja ORDER BY sk_loja LIMIT 1")
        assert nome.fetchone()[0] == "Ipê Renomeada"
        entidades = {
            e
            for (e,) in banco_com_ddl.execute(
                "SELECT entidade FROM etl.carga_tabelas WHERE id_carga = %s", (id_carga,)
            )
        }
        assert entidades == {"lojas"}
