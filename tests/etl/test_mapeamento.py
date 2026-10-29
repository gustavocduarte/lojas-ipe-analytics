"""Contrato de entrada e mapeamento de fontes. Sem rede e sem banco."""

import re
import textwrap

import pytest

from src import config
from src.etl import contrato
from src.etl.mapeamento import MapeamentoInvalido, RegraIgnorar, carregar_fonte, carregar_fontes
from tests.gerador.utilitarios import ler_csv

DOC_CONTRATO = config.RAIZ_PROJETO / "docs" / "contrato_de_entrada.md"
DDL_STAGING = config.DIR_DDL / "04_staging.sql"
COLUNAS_DE_CONTROLE = {"arquivo_origem", "linha_origem", "carregado_em"}


def _escrever(tmp_path, texto):
    caminho = tmp_path / "fonte.yaml"
    caminho.write_text(textwrap.dedent(texto), encoding="utf-8")
    return caminho


ARQUIVO = "arquivo: formas.csv"
MINIMO_FORMAS = """
    fonte: teste
    pasta: dados
    entidades:
      formas_pagamento:
        arquivo: formas.csv
        colunas:
          Código: cod_forma_pagamento
          Nome: nome_forma_pagamento
"""


class TestContrato:
    def test_documento_esta_em_dia_com_o_contrato(self):
        assert DOC_CONTRATO.read_text(encoding="utf-8") == contrato.gerar_markdown()

    def test_toda_coluna_aparece_no_documento(self):
        texto = DOC_CONTRATO.read_text(encoding="utf-8")
        for entidade in contrato.CONTRATO.values():
            assert f"## {entidade.nome}" in texto
            for coluna in entidade.colunas:
                assert f"`{coluna.nome}`" in texto

    def test_colunas_batem_com_as_tabelas_de_staging(self):
        ddl = DDL_STAGING.read_text(encoding="utf-8")
        tabelas = re.findall(r"CREATE TABLE stg\.(\w+) \((.*?)\n\);", ddl, flags=re.S)
        assert {nome for nome, _ in tabelas} == set(contrato.CONTRATO)
        for nome, corpo in tabelas:
            corpo = re.sub(r"--[^\n]*", "", corpo)
            colunas = [c.split()[0] for c in re.split(r",\s*(?![^()]*\))", corpo) if c.strip()]
            esperadas = [c for c in contrato.CONTRATO[nome].nomes_das_colunas]
            assert [c for c in colunas if c not in COLUNAS_DE_CONTROLE] == esperadas, nome

    def test_tipos_validos_e_obrigatoriedade_coerente(self):
        for entidade in contrato.CONTRATO.values():
            for coluna in entidade.colunas:
                assert coluna.tipo in contrato.TIPOS
            for chave in entidade.chave_natural:
                assert entidade.coluna(chave).obrigatoria


class TestMapeamentoDoErp:
    def test_cobre_todas_as_entidades_do_contrato(self):
        fontes = carregar_fontes()
        erp = fontes["lojas_ipe_erp"]
        assert set(erp.entidades) == set(contrato.CONTRATO)

    def test_colunas_mapeadas_existem_nos_csvs_gerados(self, dados_pequenos):
        params, _ = dados_pequenos
        erp = carregar_fontes()["lojas_ipe_erp"]
        for entidade, mapa in erp.entidades.items():
            arquivos = sorted(params.diretorio_saida.glob(mapa.arquivo))
            assert arquivos, entidade
            cabecalho = list(ler_csv(arquivos[0]).columns)
            assert set(mapa.colunas) == set(cabecalho), entidade

    def test_padroes_do_csv(self):
        vendas = carregar_fontes()["lojas_ipe_erp"].entidades["vendas"]
        assert (vendas.formato, vendas.separador, vendas.codificacao) == ("csv", ";", "utf-8")
        assert vendas.linha_cabecalho == 1
        assert vendas.arquivo == "vendas_*.csv"


class TestValidacao:
    def test_mapeamento_minimo_valido(self, tmp_path):
        fonte = carregar_fonte(_escrever(tmp_path, MINIMO_FORMAS), raiz=tmp_path)
        mapa = fonte.entidades["formas_pagamento"]
        assert fonte.pasta == tmp_path / "dados"
        assert mapa.colunas == {"Código": "cod_forma_pagamento", "Nome": "nome_forma_pagamento"}
        assert mapa.separador == ";"

    @pytest.mark.parametrize(
        ("alteracao", "trecho"),
        [
            (("formas_pagamento:", "formas_inexistentes:"), "fora do contrato"),
            (("Nome: nome_forma_pagamento", "Nome: nome_errado"), "fora do contrato"),
            (("      Nome: nome_forma_pagamento\n", ""), "obrigatórias sem mapeamento"),
            ((ARQUIVO, ARQUIVO + "\n    formato: ods"), "não suportado"),
            ((ARQUIVO, ARQUIVO + "\n    formato: xlsx"), "'aba'"),
            ((ARQUIVO, ARQUIVO + "\n    linha_cabecalho: 0"), "inteiro"),
            ((ARQUIVO, ARQUIVO + "\n    invento: 1"), "desconhecidas"),
            (("Nome: nome_forma_pagamento", "Nome: cod_forma_pagamento"), "repetida"),
        ],
    )
    def test_mapeamentos_invalidos_sao_recusados(self, tmp_path, alteracao, trecho):
        texto = textwrap.dedent(MINIMO_FORMAS).replace(*alteracao)
        with pytest.raises(MapeamentoInvalido, match=trecho):
            carregar_fonte(_escrever(tmp_path, texto), raiz=tmp_path)

    def test_falta_de_chave_raiz(self, tmp_path):
        with pytest.raises(MapeamentoInvalido, match="falta a chave 'pasta'"):
            carregar_fonte(_escrever(tmp_path, "fonte: x\nentidades: {}\n"), raiz=tmp_path)

    def test_regra_de_ignorar_linhas_precisa_de_coluna_mapeada(self, tmp_path):
        texto = textwrap.dedent(MINIMO_FORMAS).replace(
            "colunas:",
            "ignorar_linhas:\n      - {coluna: Outra, igual_a: TOTAL}\n    colunas:",
        )
        with pytest.raises(MapeamentoInvalido, match="coluna não mapeada"):
            carregar_fonte(_escrever(tmp_path, texto), raiz=tmp_path)


class TestRegraIgnorar:
    def test_igual_a_ignora_caixa_e_espacos(self):
        assert RegraIgnorar("A", igual_a="total").casa("  TOTAL ")
        assert not RegraIgnorar("A", igual_a="total").casa("Total geral")

    def test_comeca_com(self):
        assert RegraIgnorar("A", comeca_com="total").casa("Total geral")
        assert not RegraIgnorar("A", comeca_com="total").casa("Subtotal")
