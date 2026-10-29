"""Parâmetros de uma execução do gerador (padrões vêm de src/config.py)."""

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np

from src import config


@dataclass(frozen=True)
class ParametrosGeracao:
    diretorio_saida: Path = config.DIR_DADOS_BRUTOS
    semente: int = config.SEMENTE_ALEATORIA
    data_inicio: date = config.DATA_INICIO
    data_fim: date = config.DATA_FIM
    total_linhas_venda: int = config.TOTAL_LINHAS_VENDA
    quantidade_anomalias: dict[str, int] = field(
        default_factory=lambda: dict(config.QUANTIDADE_ANOMALIAS)
    )
    verificar_memoria: bool = True
    gerar_exemplo_outra_empresa: bool = True  # planilha Excel de outra empresa (um mês)


def rng_para(semente: int, *chaves: int) -> np.random.Generator:
    """Gerador aleatório independente e reprodutível para cada (fluxo, mês, ...)."""
    return np.random.default_rng(np.random.SeedSequence([semente, *chaves]))
