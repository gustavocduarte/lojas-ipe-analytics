"""Previsão de vendas (Fase 4).

    python -m src.previsao backtest      # treina até 30/06/2025, prevê 07-12/2025 e compara
    python -m src.previsao gerar         # prevê os 3 meses seguintes ao último dia com venda
    python -m src.previsao gerar --corte 2025-12-15 --ate 2025-12-31   # cenário de corte simulado
    python -m src.previsao gerar --gravar    # grava a previsão e o backtest no dw (idempotente)

Códigos de saída: 0 = ok; 2 = erro de uso; 3 = erro de execução (banco, memória insuficiente...).
"""

import argparse
import logging
import sys
from collections.abc import Callable, Sequence
from datetime import date

import psycopg

from src import banco, config
from src.calendario import ultimo_dia_do_mes
from src.logs import configurar_logging
from src.memoria import MemoriaInsuficiente, verificar_memoria_livre
from src.previsao import backtest, dados, geracao, relatorio

log = logging.getLogger("src.previsao")


def _data(texto: str) -> date:
    try:
        return date.fromisoformat(texto)
    except ValueError as erro:
        raise argparse.ArgumentTypeError(f"data inválida (use AAAA-MM-DD): {texto}") from erro


def _criar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.previsao", description=__doc__.split("\n")[0]
    )
    sub = parser.add_subparsers(dest="comando", required=True)
    teste = sub.add_parser("backtest", help="compara as abordagens num período já conhecido")
    teste.add_argument("-v", "--detalhado", action="store_true")
    gerar = sub.add_parser("gerar", help="prevê dia e mês, por loja e setor, com faixa")
    gerar.add_argument("--corte", type=_data, help="último dia de venda usado (padrão: o último)")
    gerar.add_argument("--ate", type=_data, help="último dia a prever (padrão: --meses à frente)")
    gerar.add_argument("--meses", type=int, default=config.PREVISAO_HORIZONTE_MESES)
    gerar.add_argument("--gravar", action="store_true", help="grava previsão e backtest no dw")
    gerar.add_argument("-v", "--detalhado", action="store_true")
    return parser


def _ler_painel_completo(conexao: psycopg.Connection):
    ultimo = dados.ultimo_dia_com_venda(conexao)
    if ultimo < config.PREVISAO_TESTE_FIM_BACKTEST:
        raise RuntimeError(
            f"o dw só tem vendas até {ultimo:%d/%m/%Y}; o backtest precisa de "
            f"{config.PREVISAO_TESTE_FIM_BACKTEST:%d/%m/%Y}"
        )
    return dados.ler_painel(conexao, dados.primeiro_dia_com_venda(conexao), ultimo), ultimo


def _backtest(conexao: psycopg.Connection) -> int:
    painel, _ = _ler_painel_completo(conexao)
    print(relatorio.montar(backtest.executar(painel)))
    return config.CODIGO_SAIDA_OK


def _fim_do_horizonte(corte: date, meses: int) -> date:
    """Último dia do mês que fica `meses` meses à frente do mês do dia seguinte ao corte."""
    seguinte = date.fromordinal(corte.toordinal() + 1)
    indice = seguinte.year * 12 + seguinte.month - 1 + meses - 1
    return ultimo_dia_do_mes(indice // 12, indice % 12 + 1)


def _gerar(conexao: psycopg.Connection, args) -> int:
    painel, ultimo = _ler_painel_completo(conexao)
    corte = args.corte or ultimo
    if not painel.datas[0].date() <= corte <= ultimo:
        raise ValueError(f"corte fora do período com venda no dw: {corte:%d/%m/%Y}")
    fim = args.ate or _fim_do_horizonte(corte, args.meses)
    if fim <= corte:
        raise ValueError("--ate precisa ser depois do corte")
    resultado = backtest.executar(painel)
    previsao = geracao.gerar(painel.ate(corte), resultado, fim)
    print(
        relatorio.montar_previsao(previsao, resultado, geracao.comparar_com_real(conexao, previsao))
    )
    print(
        f"backtest: {resultado.duracao_s:.1f} s, pico de memória do processo "
        f"{resultado.pico_memoria_gb:.2f} GB"
    )
    if args.gravar:
        n_backtest = geracao.gravar_backtest(conexao, resultado)
        n_previsao = geracao.gravar_previsao(conexao, previsao)
        print(f"gravado no dw: {n_previsao} linhas de previsão, {n_backtest} de backtest")
    return config.CODIGO_SAIDA_OK


def principal(
    argv: Sequence[str] | None = None,
    *,
    conexao: psycopg.Connection | None = None,
    verificar_memoria: Callable[[], float] | None = verificar_memoria_livre,
) -> int:
    try:
        args = _criar_parser().parse_args(argv)
    except SystemExit as saida:  # argparse sai com 2 em erro de uso (ou 0 em --help)
        return int(saida.code or 0)
    configurar_logging(args.detalhado)
    proprio = conexao is None
    try:
        if verificar_memoria is not None:
            verificar_memoria()
        conexao = conexao or banco.conectar()
        if args.comando == "backtest":
            return _backtest(conexao)
        return _gerar(conexao, args)
    except ValueError as erro:
        log.error("erro de uso: %s", erro)
        return config.CODIGO_SAIDA_ERRO_DE_USO
    except (MemoriaInsuficiente, psycopg.Error, RuntimeError) as erro:
        log.error("erro de execução: %s", erro)
        return config.CODIGO_SAIDA_ERRO_DE_EXECUCAO
    finally:
        if proprio and conexao is not None:
            conexao.close()


if __name__ == "__main__":
    sys.exit(principal())
