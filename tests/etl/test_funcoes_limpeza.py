"""Funções de limpeza em SQL (sql/ddl/07), chamadas num banco de teste. Cada tipo de problema
tem casos válidos (corrigidos) e inválidos (devolvem NULL, o que leva à rejeição na carga)."""

from datetime import date, time
from decimal import Decimal

import pytest

pytestmark = pytest.mark.banco


def _chamar(con, funcao, entrada):
    return con.execute(f"SELECT etl.{funcao}(%s)", (entrada,)).fetchone()[0]


def _verificar(con, funcao, casos):
    erros = [
        (entrada, esperado, obtido)
        for entrada, esperado in casos
        if (obtido := _chamar(con, funcao, entrada)) != esperado
    ]
    assert not erros, f"{funcao}: (entrada, esperado, obtido) = {erros}"


def test_limpar_texto(banco_compartilhado):
    _verificar(
        banco_compartilhado,
        "limpar_texto",
        [(None, None), ("", None), ("   ", None), ("  Pix ", "Pix"), ("a  b", "a  b")],
    )


def test_limpar_data_aceita_os_dois_formatos(banco_compartilhado):
    _verificar(
        banco_compartilhado,
        "limpar_data",
        [
            ("05/03/2024", date(2024, 3, 5)),
            ("2024-03-05", date(2024, 3, 5)),
            (" 29/02/2024 ", date(2024, 2, 29)),  # ano bissexto
            ("2024-12-31", date(2024, 12, 31)),
        ],
    )


@pytest.mark.parametrize(
    "invalida",
    ["31/02/2024", "29/02/2023", "2024-02-30", "00/01/2024", "10/13/2024", "2024-00-10",
     "32/01/2024", "5/3/2024", "05-03-2024", "2024/03/05", "ontem", "", None, "1850-01-01",
     "05/03/24"],
)  # fmt: skip
def test_limpar_data_rejeita_o_que_nao_e_data(banco_compartilhado, invalida):
    assert _chamar(banco_compartilhado, "limpar_data", invalida) is None


def test_limpar_hora_aceita_todos_os_formatos(banco_compartilhado):
    _verificar(
        banco_compartilhado,
        "limpar_hora",
        [
            ("09:53:22", time(9, 53, 22)),
            ("9:05:07", time(9, 5, 7)),
            ("21:45", time(21, 45)),
            ("21h45", time(21, 45)),
            ("09:30 AM", time(9, 30)),
            ("09:30 PM", time(21, 30)),
            ("12:15 AM", time(0, 15)),
            ("12:15 PM", time(12, 15)),
            ("12:15pm", time(12, 15)),
            ("01:00 pm", time(13, 0)),
            (" 07:00 ", time(7, 0)),
            ("00:00:00", time(0, 0)),
        ],
    )


@pytest.mark.parametrize(
    "invalida",
    ["24:00:00", "25:10", "12:60", "10:10:60", "13:00 PM", "00:30 AM", "7h5", "abc", "", None,
     "10.30", "10:30:"],
)  # fmt: skip
def test_limpar_hora_rejeita_o_que_nao_e_hora(banco_compartilhado, invalida):
    assert _chamar(banco_compartilhado, "limpar_hora", invalida) is None


def test_limpar_numero_aceita_ponto_virgula_e_milhar_brasileiro(banco_compartilhado):
    _verificar(
        banco_compartilhado,
        "limpar_numero",
        [
            ("1234.56", Decimal("1234.56")),
            ("0.5", Decimal("0.5")),
            ("17", Decimal("17")),
            ("1234,56", Decimal("1234.56")),
            ("1.234,56", Decimal("1234.56")),
            ("1.234.567,89", Decimal("1234567.89")),
            ("-10.5", Decimal("-10.5")),
            (" 3.20 ", Decimal("3.20")),
        ],
    )


@pytest.mark.parametrize(
    "invalido",
    ["abc", "12,3,4", "1.2.3", "R$ 10,00", "10,00,", "", None, "1e5", "--1", "12 34",
     "9999999999999"],
)  # fmt: skip
def test_limpar_numero_rejeita_o_que_nao_e_numero(banco_compartilhado, invalido):
    assert _chamar(banco_compartilhado, "limpar_numero", invalido) is None


def test_limpar_inteiro(banco_compartilhado):
    _verificar(
        banco_compartilhado,
        "limpar_inteiro",
        [("7", 7), (" 12 ", 12), ("3.0", 3), ("-4", -4), ("2147483647", 2147483647)],
    )
    for invalido in ("3.5", "abc", "", None, "1,5", "2147483648", "99999999999"):
        assert _chamar(banco_compartilhado, "limpar_inteiro", invalido) is None, invalido


def test_limpar_sku(banco_compartilhado):
    _verificar(
        banco_compartilhado,
        "limpar_sku",
        [
            ("ALI-0001", "ALI-0001"),
            (" ALI-0001 ", "ALI-0001"),
            ("ali-0001", "ALI-0001"),
            ("ali-0001 ", "ALI-0001"),
            ("ALI - 0001", "ALI-0001"),
            ("", None),
            ("   ", None),
            (None, None),
        ],
    )


def test_limpar_nome(banco_compartilhado):
    _verificar(
        banco_compartilhado,
        "limpar_nome",
        [
            ("Ian Duarte", "Ian Duarte"),
            ("  Ian   Duarte ", "Ian Duarte"),
            ("IAN DUARTE", "Ian Duarte"),
            ("ian duarte", "Ian Duarte"),
            ("sarah da mata", "Sarah da Mata"),
            ("  SARAH   DA   MATA ", "Sarah da Mata"),
            ("Maria Eduarda dos Santos", "Maria Eduarda dos Santos"),
            ("DA SILVA", "Da Silva"),  # partícula na primeira posição leva maiúscula
            ("josé d'ávila", "José D'Ávila"),
            ("ÂNGELA SOUZA", "Ângela Souza"),
            ("", None),
            ("   ", None),
            (None, None),
        ],
    )


def test_funcoes_sao_imutaveis(banco_compartilhado):
    """Imutáveis e puras: podem rodar em paralelo e ser usadas em índices."""
    linhas = banco_compartilhado.execute(
        "SELECT p.proname, p.provolatile FROM pg_proc p"
        " JOIN pg_namespace n ON n.oid = p.pronamespace"
        " WHERE n.nspname = 'etl' AND p.proname LIKE 'limpar_%'"
    ).fetchall()
    assert {nome for nome, _ in linhas} >= {
        "limpar_texto",
        "limpar_data",
        "limpar_hora",
        "limpar_numero",
        "limpar_inteiro",
        "limpar_sku",
        "limpar_nome",
    }
    assert {volatilidade for _, volatilidade in linhas} == {"i"}
