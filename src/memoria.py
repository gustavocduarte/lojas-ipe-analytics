"""Controle de memória: o computador do projeto tem pouca RAM livre."""

import psutil

from src import config


class MemoriaInsuficiente(RuntimeError):
    """Memória livre abaixo do mínimo configurado para uma execução pesada."""


def memoria_livre_gb() -> float:
    return psutil.virtual_memory().available / config.BYTES_POR_GB


def verificar_memoria_livre(minimo_gb: float = config.MEMORIA_LIVRE_MINIMA_GB) -> float:
    """Retorna a memória livre em GB ou levanta MemoriaInsuficiente se estiver abaixo do mínimo."""
    livre = memoria_livre_gb()
    if livre < minimo_gb:
        raise MemoriaInsuficiente(
            f"Memória livre {livre:.2f} GB abaixo do mínimo de {minimo_gb:.2f} GB: "
            "feche programas e tente de novo."
        )
    return livre


def pico_memoria_processo_gb() -> float:
    """Pico de memória do processo atual (working set de pico no Windows; RSS atual nos demais)."""
    info = psutil.Process().memory_info()
    return getattr(info, "peak_wset", info.rss) / config.BYTES_POR_GB
