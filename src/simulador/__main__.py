"""Simulador de troca de setor.

    python -m src.simulador backtest [--gravar]     # trocas reais e placebo, 4 e 8 semanas
    python -m src.simulador backtest --habilidade-verdadeira data/raw/_habilidade_verdadeira.csv

O gabarito de habilidade só serve para conferir, em análise, se o dw recupera a habilidade; a
projeção nunca o lê.

Códigos de saída: 0 = ok; 2 = erro de uso; 3 = erro de execução (banco, memória insuficiente...).
"""

import argparse
import logging
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import pandas as pd
import psycopg

from src import banco, config
from src.logs import configurar_logging
from src.memoria import MemoriaInsuficiente, verificar_memoria_livre
from src.simulador import backtest

log = logging.getLogger("src.simulador")


def _criar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.simulador", description=__doc__.split("\n")[0]
    )
    sub = parser.add_subparsers(dest="comando", required=True)
    teste = sub.add_parser("backtest", help="compara o projetado com o vendido nas trocas reais")
    teste.add_argument("--gravar", action="store_true", help="grava em dw.simulador_backtest")
    teste.add_argument("--habilidade-verdadeira", type=Path, help="CSV do gabarito (só análise)")
    teste.add_argument("-v", "--detalhado", action="store_true")
    return parser


def _formatar(resultado: pd.DataFrame) -> str:
    exibicao = resultado.assign(
        cobertura=(resultado.cobertura_conservadora * 100).round(1).astype(str) + "%",
        wape=(resultado.wape * 100).round(1).astype(str) + "%",
        vies=(resultado.vies * 100).round(1).astype(str) + "%",
    )
    colunas = [
        "grupo",
        "metodo",
        "horizonte_dias",
        "eventos",
        "semanas",
        "cobertura",
        "wape",
        "vies",
    ]
    return exibicao[colunas].to_string(index=False)


def _backtest(conexao: psycopg.Connection, args) -> int:
    resultado = backtest.executar(backtest.Historico(conexao))
    print(_formatar(resultado))
    if args.gravar:
        print(f"gravado em dw.simulador_backtest: {backtest.gravar(conexao, resultado)} linhas")
    if args.habilidade_verdadeira:
        gabarito = pd.read_csv(args.habilidade_verdadeira, sep=";", dtype={"habilidade": float})
        print(
            "habilidade estimada x verdadeira:",
            backtest.correlacao_com_habilidade(conexao, gabarito),
        )
    return config.CODIGO_SAIDA_OK


def principal(
    argv: Sequence[str] | None = None,
    *,
    conexao: psycopg.Connection | None = None,
    verificar_memoria: Callable[[], float] | None = verificar_memoria_livre,
) -> int:
    try:
        args = _criar_parser().parse_args(argv)
    except SystemExit as saida:
        return int(saida.code or 0)
    configurar_logging(args.detalhado)
    try:
        if verificar_memoria is not None:
            verificar_memoria()
        return _backtest(conexao or banco.conectar(), args)
    except ValueError as erro:
        log.error("erro de uso: %s", erro)
        return config.CODIGO_SAIDA_ERRO_DE_USO
    except (MemoriaInsuficiente, psycopg.Error, RuntimeError) as erro:
        log.error("erro de execução: %s", erro)
        return config.CODIGO_SAIDA_ERRO_DE_EXECUCAO


if __name__ == "__main__":
    sys.exit(principal())
