"""Cores do relatório Power BI: etl.parametros_cores, dw.vw_parametros_cores e o modelo."""

import re

import psycopg
import pytest

from src import config

DIR_TABELAS = config.RAIZ_PROJETO / "powerbi" / "lojas_ipe.SemanticModel" / "definition" / "tables"
MEDIDAS = DIR_TABELAS / "Medidas.tmdl"
# Cores que ficam fora da tabela de parâmetros de propósito (tema da lista: texto e fundo).
LITERAIS_PERMITIDOS = {"#242424", "#FFFFFF"}


def _medidas() -> str:
    return MEDIDAS.read_text(encoding="utf-8")


def _chaves_lidas_pelo_modelo() -> set[str]:
    """Chaves usadas nos LOOKUPVALUE da tabela 'Parâmetros de cores' em Medidas.tmdl."""
    return set(re.findall(r"'Parâmetros de cores'\[chave\], \"([a-z_]+)\"", _medidas()))


@pytest.mark.banco
def test_view_traz_todas_as_chaves_que_o_modelo_usa(banco_com_ddl):
    no_banco = {c for (c,) in banco_com_ddl.execute("SELECT chave FROM dw.vw_parametros_cores")}
    usadas = _chaves_lidas_pelo_modelo()
    assert usadas, "o modelo não lê nenhuma chave de cor"
    assert usadas <= no_banco, f"chaves do modelo ausentes no banco: {sorted(usadas - no_banco)}"


@pytest.mark.banco
def test_cores_validas_com_descricao_e_ambar_unico(banco_com_ddl):
    linhas = banco_com_ddl.execute(
        "SELECT chave, cor, descricao FROM dw.vw_parametros_cores"
    ).fetchall()
    assert all(re.fullmatch(r"#[0-9A-Fa-f]{6}", cor) for _, cor, _ in linhas)
    assert all(descricao for _, _, descricao in linhas)
    ambares = [chave for chave, _, _ in linhas if chave.startswith("ambar")]
    assert ambares == ["ambar"]  # uma só chave de âmbar para o relatório inteiro
    assert dict((c, v) for c, v, _ in linhas)["ambar"] == "#B26A00"


@pytest.mark.banco
def test_cor_fora_do_formato_e_recusada(banco_com_ddl):
    with pytest.raises(psycopg.errors.CheckViolation):
        banco_com_ddl.execute(
            "INSERT INTO etl.parametros_cores (chave, cor, descricao) VALUES ('x', 'verde', 'x')"
        )


@pytest.mark.banco
def test_reaplicar_o_ddl_nao_sobrescreve_uma_cor_alterada(banco_com_ddl):
    banco_com_ddl.execute("UPDATE etl.parametros_cores SET cor = '#112233' WHERE chave = 'verde'")
    script = config.DIR_DDL / "27_parametros_cores.sql"
    banco_com_ddl.execute(script.read_text(encoding="utf-8"))
    cor = banco_com_ddl.execute("SELECT cor FROM dw.vw_parametros_cores WHERE chave = 'verde'")
    assert cor.fetchone()[0] == "#112233"


def test_medidas_nao_tem_cor_fixa_fora_da_tabela_de_parametros():
    literais = set(re.findall(r"\"(#[0-9A-Fa-f]{6})\"", _medidas()))
    assert literais <= LITERAIS_PERMITIDOS, (
        f"cores fixas no DAX: {sorted(literais - LITERAIS_PERMITIDOS)}"
    )


def test_toda_medida_cor_usada_esta_definida():
    texto = _medidas()
    definidas = set(re.findall(r"measure '(Cor: [^']+)'", texto))
    usadas = set(re.findall(r"\[(Cor: [^\]]+)\]", texto))
    assert usadas <= definidas, f"medidas de cor sem definição: {sorted(usadas - definidas)}"
