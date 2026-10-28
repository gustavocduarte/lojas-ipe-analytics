"""Escrita incremental de CSVs (um pedaço por vez, sem acumular tudo na memória)."""

import csv
from collections.abc import Iterable
from pathlib import Path
from typing import Self

import pandas as pd

from src import config


class EscritorCsv:
    """Grava DataFrames de texto em um CSV, acompanhando quantas linhas de dados já saíram."""

    def __init__(self, caminho: Path, colunas: list[str]) -> None:
        self.caminho = caminho
        self.colunas = colunas
        self.linhas = 0
        self._arquivo = caminho.open("w", encoding=config.CODIFICACAO_CSV, newline="")
        self._arquivo.write(config.SEPARADOR_CSV.join(colunas) + "\n")

    def escrever(self, df: pd.DataFrame) -> int:
        """Grava o pedaço e devolve o número (base 1) da primeira linha de dados gravada."""
        primeira = self.linhas + 1
        df[self.colunas].to_csv(
            self._arquivo,
            sep=config.SEPARADOR_CSV,
            header=False,
            index=False,
            lineterminator="\n",
        )
        self.linhas += len(df)
        return primeira

    def fechar(self) -> None:
        self._arquivo.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.fechar()


class RegistroCsv:
    """Arquivo de registro (gabarito de anomalias, problemas de qualidade) gravado por linhas."""

    def __init__(self, caminho: Path, colunas: list[str]) -> None:
        self.caminho = caminho
        self.linhas = 0
        self._arquivo = caminho.open("w", encoding=config.CODIFICACAO_CSV, newline="")
        self._escritor = csv.writer(
            self._arquivo, delimiter=config.SEPARADOR_CSV, lineterminator="\n"
        )
        self._escritor.writerow(colunas)

    def adicionar(self, linhas: Iterable[Iterable[object]]) -> None:
        for linha in linhas:
            self._escritor.writerow(linha)
            self.linhas += 1

    def fechar(self) -> None:
        self._arquivo.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.fechar()


def formatar_dinheiro(valor: float) -> str:
    """Formato do ERP: ponto decimal, duas casas (ex.: 1234.56)."""
    return f"{valor:.{config.CASAS_DECIMAIS_DINHEIRO}f}"


def formatar_dinheiro_br(valor: float) -> str:
    """Valor em texto no formato brasileiro (ex.: 1.234,56)."""
    texto = f"{valor:,.{config.CASAS_DECIMAIS_DINHEIRO}f}"
    return texto.replace(",", "#").replace(".", ",").replace("#", ".")
