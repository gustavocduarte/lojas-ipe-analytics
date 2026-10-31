"""Relatório de fechamento em Excel (Fase 4).

    python -m src.relatorios fechamento             # mês e dia da referência (último dia com venda)
    python -m src.relatorios fechamento --mes 2025-12 --dia 2025-12-15
    python -m src.relatorios fechamento --saida data/processed/meu_fechamento.xlsx
    python -m src.relatorios fechamento --sem-macros    # ignora vba/modelo_fechamento.xlsm

Códigos de saída: 0 = ok; 2 = erro de uso; 3 = erro de execução (banco, memória, arquivo).
"""

import argparse
import logging
import sys
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path

import psycopg

from src import banco, config
from src.calendario import ultimo_dia_do_mes
from src.logs import configurar_logging
from src.memoria import MemoriaInsuficiente, verificar_memoria_livre
from src.previsao import dados
from src.relatorios import fechamento

log = logging.getLogger("src.relatorios")


def _data(texto: str) -> date:
    try:
        return date.fromisoformat(texto if len(texto) > 7 else texto + "-01")
    except ValueError as erro:
        raise argparse.ArgumentTypeError(
            f"data inválida (use AAAA-MM ou AAAA-MM-DD): {texto}"
        ) from erro


def _criar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.relatorios", description=__doc__.split("\n")[0]
    )
    sub = parser.add_subparsers(dest="comando", required=True)
    f = sub.add_parser("fechamento", help="gera o .xlsx (ou .xlsm) de fechamento do mês")
    f.add_argument("--mes", type=_data, help="mês AAAA-MM (padrão: o da referência)")
    f.add_argument(
        "--dia", type=_data, help="dia de posição AAAA-MM-DD (padrão: o último com venda)"
    )
    f.add_argument("--saida", type=Path, help="arquivo de saída (padrão: data/processed/)")
    f.add_argument("--sem-macros", action="store_true", help="não usa o modelo .xlsm")
    f.add_argument("-v", "--detalhado", action="store_true")
    return parser


def _escolher_periodo(conexao, mes: date | None, dia: date | None) -> tuple[date, date]:
    ultimo = dados.ultimo_dia_com_venda(conexao)
    if dia is None:
        dia = min(ultimo, ultimo_dia_do_mes(mes.year, mes.month)) if mes else ultimo
    mes = (mes or dia).replace(day=1)
    if dia.replace(day=1) != mes:
        raise ValueError(f"o dia {dia:%d/%m/%Y} não está em {mes:%m/%Y}")
    return mes, dia


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
        mes, dia = _escolher_periodo(conexao, args.mes, args.dia)
        modelo = None if args.sem_macros else config.ARQ_MODELO_XLSM
        caminho, desempenho = fechamento.gerar(conexao, mes, dia, args.saida, modelo)
        print(f"fechamento de {mes:%m/%Y} (posição {dia:%d/%m/%Y}): {caminho}")
        print(
            f"{desempenho['duracao_s']} s, pico de memória {desempenho['pico_memoria_gb']} GB, "
            + ("com macros" if desempenho["com_macros"] else "sem macros (.xlsx)")
        )
        return config.CODIGO_SAIDA_OK
    except ValueError as erro:
        log.error("erro de uso: %s", erro)
        return config.CODIGO_SAIDA_ERRO_DE_USO
    except (MemoriaInsuficiente, psycopg.Error, RuntimeError, OSError) as erro:
        log.error("erro de execução: %s", erro)
        return config.CODIGO_SAIDA_ERRO_DE_EXECUCAO
    finally:
        if proprio and conexao is not None:
            conexao.close()


if __name__ == "__main__":
    sys.exit(principal())
