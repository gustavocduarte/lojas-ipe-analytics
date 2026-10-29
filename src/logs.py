"""Padrão de logging do projeto: data/hora, nível, módulo e mensagem, na saída padrão."""

import logging
import sys

from src import config


def configurar_logging(detalhado: bool = False) -> None:
    """Configura o logging raiz (idempotente: chamar de novo troca o nível, não duplica saída)."""
    manipulador = logging.StreamHandler(sys.stdout)
    manipulador.setFormatter(logging.Formatter(config.FORMATO_LOG, config.FORMATO_DATA_LOG))
    raiz = logging.getLogger()
    raiz.handlers = [manipulador]
    raiz.setLevel(logging.DEBUG if detalhado else logging.INFO)
