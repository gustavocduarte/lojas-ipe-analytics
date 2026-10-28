"""Leitura tolerante dos CSVs gerados (formatos mistos), usada só pelos testes."""

import hashlib
from datetime import date, datetime, time
from pathlib import Path

import pandas as pd

from src import config


def ler_csv(caminho: Path) -> pd.DataFrame:
    return pd.read_csv(caminho, sep=config.SEPARADOR_CSV, dtype=str, keep_default_na=False)


def ler_vendas(pasta: Path) -> pd.DataFrame:
    partes = []
    for arquivo in sorted(pasta.glob("vendas_*.csv")):
        parte = ler_csv(arquivo)
        parte["arquivo"] = arquivo.name
        parte["linha"] = range(1, len(parte) + 1)
        partes.append(parte)
    return pd.concat(partes, ignore_index=True)


def numero(texto: str) -> float:
    """Aceita '1234.56' e '1.234,56'."""
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    return float(texto)


def data(texto: str) -> date:
    """Aceita dd/mm/aaaa e aaaa-mm-dd."""
    formato = config.FORMATO_DATA_ISO if texto[4:5] == "-" else config.FORMATO_DATA_BR
    return datetime.strptime(texto, formato).date()


def hash_da_pasta(pasta: Path) -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(pasta.glob("*.csv"))}


def hora(texto: str) -> time:
    """Aceita HH:MM:SS, HH:MM, HHhMM e HH:MM AM/PM."""
    for formato in (config.FORMATO_HORA, *config.FORMATOS_HORA_ALTERNATIVOS):
        try:
            return datetime.strptime(texto, formato).time()
        except ValueError:
            continue
    raise ValueError(f"hora em formato desconhecido: {texto!r}")
