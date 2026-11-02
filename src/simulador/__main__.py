"""Simulador de troca de setor.

    python -m src.simulador backtest [--gravar]     # trocas reais e placebo, 4 e 8 semanas
    python -m src.simulador backtest-v2 [--gravar]  # fatia semanal encolhida (v2)
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
from src.simulador import backtest, fatias

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
    v2 = sub.add_parser(
        "backtest-v2", help="fatia semanal encolhida contra o p25 diário e o ingênuo"
    )
    v2.add_argument("--gravar", action="store_true", help="grava em dw.simulador_backtest(_curva)")
    v2.add_argument("--habilidade-verdadeira", type=Path, help="CSV do gabarito (só análise)")
    v2.add_argument("-v", "--detalhado", action="store_true")
    return parser


def _formatar(resultado: pd.DataFrame) -> str:
    exibicao = resultado.assign(
        cobertura=(resultado.cobertura_conservadora * 100).round(1).astype(str) + "%",
        wape=(resultado.wape * 100).round(1).astype(str) + "%",
        vies=(resultado.vies * 100).round(1).astype(str) + "%",
    )
    colunas = [
        *(["escala"] if "escala" in resultado else []),
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


def _backtest_v2(conexao: psycopg.Connection, args) -> int:
    historico = backtest.Historico(conexao)
    semanal = fatias.Semanal(historico)
    itens = fatias.preparar(historico, semanal)
    tabela_k = fatias.escolher_k(itens, diluir=False)
    k = fatias.k_escolhido(tabela_k)
    curva = fatias.curva_percentil(itens, k, diluir=False)
    percentil = fatias.escolher_percentil(curva)
    antes = fatias.tabela_final(itens, k, percentil, diluir=False)
    depois = fatias.tabela_final(itens, k, percentil, diluir=True)
    print("WAPE do v2 central por k (56 dias, sem diluição):")
    print(tabela_k.round(4).to_string(index=False))
    print(f"k escolhido: {k:g}; percentil do conservador: {percentil:g}")
    print("ANTES do ajuste de diluição:")
    print(_formatar(antes))
    print("DEPOIS (fatia x n/(n+1) para quem não está lotado no destino):")
    print(_formatar(depois))
    adotar = fatias.diluicao_ajuda(antes, depois)
    print(
        "ajuste de diluição:",
        "adotado" if adotar else "NÃO adotado (piora o placebo ou não reduz o viés)",
    )
    curva = fatias.curva_percentil(itens, k, diluir=adotar)
    print("curva do percentil (com a decisão acima):")
    print(curva.round(4).to_string(index=False))
    if args.gravar:
        gravadas = fatias.gravar(conexao, depois if adotar else antes, curva, k, percentil, adotar)
        print(f"gravado: {gravadas} linhas")
    if args.habilidade_verdadeira:
        gabarito = pd.read_csv(args.habilidade_verdadeira, sep=";", dtype={"habilidade": float})
        print(
            "fatia encolhida x habilidade:", fatias.correlacao_fatia(semanal, conexao, gabarito, k)
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
        conexao = conexao or banco.conectar()
        if args.comando == "backtest-v2":
            return _backtest_v2(conexao, args)
        return _backtest(conexao, args)
    except ValueError as erro:
        log.error("erro de uso: %s", erro)
        return config.CODIGO_SAIDA_ERRO_DE_USO
    except (MemoriaInsuficiente, psycopg.Error, RuntimeError) as erro:
        log.error("erro de execução: %s", erro)
        return config.CODIGO_SAIDA_ERRO_DE_EXECUCAO


if __name__ == "__main__":
    sys.exit(principal())
