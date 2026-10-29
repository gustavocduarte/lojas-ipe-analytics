"""Leitor de CSV e Excel conforme o mapeamento. Sem banco e sem rede (arquivos em tmp_path)."""

from datetime import date, datetime, time

import pytest
from openpyxl import Workbook

from src.etl.leitura import ErroDeLeitura, celula_para_texto, hash_do_arquivo, ler_registros
from src.etl.mapeamento import MapeamentoEntidade, RegraIgnorar

COLUNAS_FORMAS = {"Código": "cod_forma_pagamento", "Nome": "nome_forma_pagamento"}
COLUNAS_METAS = {"Mês": "competencia", "Loja": "cod_loja", "Setor": "setor", "Meta": "valor_meta"}


def _mapa(entidade="formas_pagamento", colunas=None, **mudancas) -> MapeamentoEntidade:
    base = {
        "entidade": entidade,
        "arquivo": "x",
        "formato": "csv",
        "separador": ";",
        "codificacao": "utf-8",
        "aba": None,
        "linha_cabecalho": 1,
        "ignorar_linhas": (),
        "colunas": colunas or COLUNAS_FORMAS,
        "formato_data": None,
        "separador_decimal": ".",
        "separador_milhar": "",
    }
    return MapeamentoEntidade(**{**base, **mudancas})


def _ler(mapa, caminho):
    contagem = {}
    return list(ler_registros(mapa, caminho, contagem)), contagem


class TestCsv:
    def test_le_cabecalho_na_primeira_linha(self, tmp_path):
        arquivo = tmp_path / "f.csv"
        arquivo.write_text("Código;Nome\nPIX;Pix\nDIN;Dinheiro\n", encoding="utf-8")
        linhas, contagem = _ler(_mapa(), arquivo)
        assert linhas == [("PIX", "Pix"), ("DIN", "Dinheiro")]
        assert contagem == {"lidas": 2, "ignoradas": 0}

    def test_cabecalho_na_linha_tres_e_colunas_em_outra_ordem(self, tmp_path):
        arquivo = tmp_path / "f.csv"
        arquivo.write_text(
            "Relatório de formas\n\nNome;Código;Extra\nPix;PIX;1\nDinheiro;DIN;2\n",
            encoding="utf-8",
        )
        linhas, _ = _ler(_mapa(linha_cabecalho=3), arquivo)
        assert linhas == [
            ("PIX", "Pix"),
            ("DIN", "Dinheiro"),
        ]  # ordem do mapeamento, não do arquivo

    def test_ignora_total_e_linhas_vazias(self, tmp_path):
        arquivo = tmp_path / "f.csv"
        arquivo.write_text("Código;Nome\nPIX;Pix\n;;\nTOTAL;2\n", encoding="utf-8")
        regras = (RegraIgnorar("Código", igual_a="total"),)
        linhas, contagem = _ler(_mapa(ignorar_linhas=regras), arquivo)
        assert linhas == [("PIX", "Pix")]
        assert contagem == {"lidas": 1, "ignoradas": 2}

    def test_celulas_vazias_viram_none_e_bom_e_aceito(self, tmp_path):
        arquivo = tmp_path / "f.csv"
        arquivo.write_bytes("﻿Código;Nome\nPIX;\n".encode())
        linhas, _ = _ler(_mapa(), arquivo)
        assert linhas == [("PIX", None)]

    def test_linha_curta_vira_none_nas_colunas_que_faltam(self, tmp_path):
        arquivo = tmp_path / "f.csv"
        arquivo.write_text("Código;Nome\nPIX\n", encoding="utf-8")
        linhas, _ = _ler(_mapa(), arquivo)
        assert linhas == [("PIX", None)]

    def test_separador_e_codificacao_proprios(self, tmp_path):
        arquivo = tmp_path / "f.csv"
        arquivo.write_bytes("Código,Nome\nPIX,Débito\n".encode("latin-1"))
        linhas, _ = _ler(_mapa(separador=",", codificacao="latin-1"), arquivo)
        assert linhas == [("PIX", "Débito")]

    def test_coluna_ausente_no_cabecalho_levanta_erro(self, tmp_path):
        arquivo = tmp_path / "f.csv"
        arquivo.write_text("Código;Outro\nPIX;x\n", encoding="utf-8")
        with pytest.raises(ErroDeLeitura, match="ausentes no cabeçalho"):
            _ler(_mapa(), arquivo)

    def test_arquivo_sem_linha_de_cabecalho_levanta_erro(self, tmp_path):
        arquivo = tmp_path / "f.csv"
        arquivo.write_text("Código;Nome\n", encoding="utf-8")
        with pytest.raises(ErroDeLeitura, match="sem a linha de cabeçalho"):
            _ler(_mapa(linha_cabecalho=5), arquivo)


class TestFormatosDeclarados:
    def test_formato_de_data_da_fonte_vira_dd_mm_aaaa(self, tmp_path):
        arquivo = tmp_path / "m.csv"
        arquivo.write_text(
            "Mês;Loja;Setor;Meta\n2024-03-01;L01;Eletro;10\n03/31/2024;L01;Casa;7\n",
            encoding="utf-8",
        )
        mapa = _mapa("metas_vendas", COLUNAS_METAS, formato_data="%Y-%m-%d")
        linhas, _ = _ler(mapa, arquivo)
        assert linhas[0][0] == "01/03/2024"
        assert (
            linhas[1][0] == "03/31/2024"
        )  # não casa com o formato: fica cru para a limpeza decidir

    def test_decimal_com_virgula_e_milhar_viram_ponto(self, tmp_path):
        arquivo = tmp_path / "m.csv"
        arquivo.write_text(
            "Mês;Loja;Setor;Meta\n01/01/2024;L01;Eletro;1.234,56\n", encoding="utf-8"
        )
        mapa = _mapa("metas_vendas", COLUNAS_METAS, separador_decimal=",", separador_milhar=".")
        linhas, _ = _ler(mapa, arquivo)
        assert linhas[0][3] == "1234.56"

    def test_sem_declaracao_o_texto_vai_cru(self, tmp_path):
        arquivo = tmp_path / "m.csv"
        arquivo.write_text(
            "Mês;Loja;Setor;Meta\n2024-03-01;L01;Eletro;1.234,56\n", encoding="utf-8"
        )
        linhas, _ = _ler(_mapa("metas_vendas", COLUNAS_METAS), arquivo)
        assert linhas[0] == ("2024-03-01", "L01", "Eletro", "1.234,56")


class TestExcel:
    def _planilha(self, tmp_path, linhas, nome_aba="Dados"):
        pasta = Workbook()
        extra = pasta.active
        extra.title = "Resumo"
        extra.append(["Esta aba deve ser ignorada", 123])
        aba = pasta.create_sheet(nome_aba)
        for linha in linhas:
            aba.append(linha)
        caminho = tmp_path / "f.xlsx"
        pasta.save(caminho)
        return caminho

    def test_le_a_aba_certa_com_cabecalho_na_linha_tres_e_ignora_total(self, tmp_path):
        caminho = self._planilha(
            tmp_path,
            [
                ["Relatório mensal"],
                [],
                ["Mês", "Loja", "Setor", "Meta"],
                [datetime(2024, 1, 1), "L01", "Eletro", 1234.5],
                [date(2024, 2, 1), "L02", "Casa", 10.0],
                ["TOTAL", None, None, 1244.5],
            ],
        )
        mapa = _mapa(
            "metas_vendas",
            COLUNAS_METAS,
            formato="xlsx",
            aba="Dados",
            linha_cabecalho=3,
            ignorar_linhas=(RegraIgnorar("Mês", igual_a="TOTAL"),),
        )
        linhas, contagem = _ler(mapa, caminho)
        assert linhas == [
            ("01/01/2024", "L01", "Eletro", "1234.5"),
            ("01/02/2024", "L02", "Casa", "10"),
        ]
        assert contagem == {"lidas": 2, "ignoradas": 1}

    def test_aba_inexistente_levanta_erro(self, tmp_path):
        caminho = self._planilha(tmp_path, [["Código", "Nome"], ["PIX", "Pix"]])
        with pytest.raises(ErroDeLeitura, match="aba 'Outra' não encontrada"):
            _ler(_mapa(formato="xlsx", aba="Outra"), caminho)

    def test_horas_do_excel_viram_texto(self, tmp_path):
        caminho = self._planilha(
            tmp_path,
            [["Código", "Abre", "Fecha"], ["L01", time(7, 0), datetime(1899, 12, 30, 22, 30)]],
        )
        colunas = {"Código": "cod_loja", "Abre": "hora_abertura", "Fecha": "hora_fechamento"}
        mapa = _mapa("horarios_loja", colunas, formato="xlsx", aba="Dados")
        linhas, _ = _ler(mapa, caminho)
        assert linhas == [("L01", "07:00:00", "22:30:00")]


class TestCelulas:
    @pytest.mark.parametrize(
        ("valor", "tipo", "esperado"),
        [
            (None, "texto", None),
            ("  Pix ", "texto", "Pix"),
            ("   ", "texto", None),
            (7, "inteiro", "7"),
            (3.0, "decimal", "3"),
            (3.25, "decimal", "3.25"),
            (datetime(2024, 5, 3, 0, 0), "data", "03/05/2024"),
            (datetime(2024, 5, 3, 14, 30), "data", "03/05/2024"),
            (date(2024, 5, 3), "data", "03/05/2024"),
            (time(9, 5, 7), "hora", "09:05:07"),
            (datetime(2024, 5, 3, 9, 5), "hora", "09:05:00"),
        ],
    )
    def test_conversao(self, valor, tipo, esperado):
        assert celula_para_texto(valor, tipo) == esperado


def test_hash_muda_com_o_conteudo(tmp_path):
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    a.write_text("x", encoding="utf-8")
    b.write_text("x", encoding="utf-8")
    assert hash_do_arquivo(a) == hash_do_arquivo(b)
    b.write_text("y", encoding="utf-8")
    assert hash_do_arquivo(a) != hash_do_arquivo(b)


class TestTextoBruto:
    """O staging é cru: o leitor não pode apagar a sujeira que a limpeza precisa ver."""

    def test_modo_bruto_preserva_espacos_das_pontas(self):
        assert celula_para_texto("  ALI-0001 ", "texto", bruto=True) == "  ALI-0001 "
        assert celula_para_texto("   ", "texto", bruto=True) is None

    def test_csv_chega_ao_staging_sem_aparar(self, tmp_path):
        arquivo = tmp_path / "f.csv"
        arquivo.write_text("Código;Nome\n PIX ;  Pix  \n", encoding="utf-8")
        linhas, _ = _ler(_mapa(), arquivo)
        assert linhas == [(" PIX ", "  Pix  ")]
