"""Validações da carga: estruturais (bloqueiam) e sinais de negócio (só contam).

As regras ficam em SQL (sql/procedures/60_validacoes.sql). Aqui só chamamos e guardamos os
resultados. Nada consulta arquivos de gabarito.
"""

from dataclasses import dataclass

import psycopg


class CargaReprovada(RuntimeError):
    """Alguma validação estrutural falhou: o dw não foi alterado."""

    def __init__(self, reprovadas: list["ResultadoValidacao"]):
        self.reprovadas = reprovadas
        nomes = ", ".join(r.validacao for r in reprovadas)
        super().__init__(f"validações estruturais reprovadas: {nomes}")


@dataclass(frozen=True)
class ResultadoValidacao:
    validacao: str
    ok: bool
    quantidade: int  # ocorrências com problema (0 quando ok)
    detalhe: str


@dataclass(frozen=True)
class SinalNegocio:
    sinal: str
    unidade: str
    quantidade: int
    descricao: str


def validar_estrutura(conexao: psycopg.Connection, id_carga: int) -> list[ResultadoValidacao]:
    """Roda as validações estruturais na transação aberta da carga (não grava nada)."""
    linhas = conexao.execute(
        "SELECT validacao, ok, quantidade, detalhe FROM etl.validar_estrutura(%s)", (id_carga,)
    ).fetchall()
    return [ResultadoValidacao(*linha) for linha in linhas]


def reprovadas(resultados: list[ResultadoValidacao]) -> list[ResultadoValidacao]:
    return [r for r in resultados if not r.ok]


def calcular_sinais(conexao: psycopg.Connection) -> list[SinalNegocio]:
    """Conta os sinais de negócio sobre o estado atual do dw."""
    linhas = conexao.execute(
        "SELECT sinal, unidade, quantidade, descricao FROM etl.sinais_negocio()"
    ).fetchall()
    return [SinalNegocio(*linha) for linha in linhas]


def gravar_validacoes(
    conexao: psycopg.Connection, id_carga: int, resultados: list[ResultadoValidacao]
) -> None:
    with conexao.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO etl.carga_validacoes (id_carga, validacao, ok, quantidade, detalhe)"
            " VALUES (%s, %s, %s, %s, %s)",
            [(id_carga, r.validacao, r.ok, r.quantidade, r.detalhe) for r in resultados],
        )


def gravar_sinais(conexao: psycopg.Connection, id_carga: int, sinais: list[SinalNegocio]) -> None:
    with conexao.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO etl.carga_sinais (id_carga, sinal, unidade, quantidade, descricao)"
            " VALUES (%s, %s, %s, %s, %s)",
            [(id_carga, s.sinal, s.unidade, s.quantidade, s.descricao) for s in sinais],
        )
