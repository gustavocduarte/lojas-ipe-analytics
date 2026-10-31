"""Relatório de fechamento em Excel: consulta o dw, monta as abas e grava o arquivo."""

import logging
import time
from datetime import date
from pathlib import Path

import psycopg
from openpyxl import load_workbook

from src import config
from src.memoria import pico_memoria_processo_gb
from src.relatorios import consultas
from src.relatorios.planilha import DadosFechamento, montar_pasta

log = logging.getLogger(__name__)


def coletar(conexao: psycopg.Connection, mes: date, dia: date) -> DadosFechamento:
    """Consulta o dw (uma consulta por aba) para o mês e o dia de posição."""
    return DadosFechamento(
        mes=mes,
        dia=dia,
        lojas=consultas.lojas(conexao, mes, dia),
        indicadores=consultas.indicadores_da_rede(conexao, mes, dia),
        vendas_por_dia=consultas.vendas_por_dia(conexao, mes, dia),
        vendedores=consultas.vendedores(conexao, mes, dia),
        alertas=consultas.alertas_abertos(conexao),
        previsao_mensal=consultas.previsao_mensal(conexao),
        previsao_diaria=consultas.previsao_diaria_da_rede(conexao),
    )


def caminho_padrao(mes: date, modelo_xlsm: bool, pasta: Path = config.DIR_RELATORIOS_EXCEL) -> Path:
    nome = config.MODELO_ARQ_FECHAMENTO.format(ano=mes.year, mes=mes.month)
    return pasta / (nome + (".xlsm" if modelo_xlsm else ".xlsx"))


def gerar(
    conexao: psycopg.Connection,
    mes: date,
    dia: date,
    saida: Path | None = None,
    modelo: Path | None = config.ARQ_MODELO_XLSM,
) -> tuple[Path, dict]:
    """Gera o fechamento. Com `modelo` existente (.xlsm), preenche-o mantendo as macros e salva
    .xlsm; sem ele, salva .xlsx puro. Devolve (caminho, desempenho)."""
    inicio = time.perf_counter()
    com_macros = modelo is not None and modelo.exists()
    destino = saida or caminho_padrao(mes, com_macros)
    if com_macros and destino.suffix.lower() != ".xlsm":
        raise ValueError("com o modelo de macros o arquivo de saída precisa ser .xlsm")
    if not com_macros and destino.suffix.lower() == ".xlsm":
        raise ValueError("sem o modelo de macros (vba/modelo_fechamento.xlsm) a saída é .xlsx")
    dados = coletar(conexao, mes, dia)
    pasta = load_workbook(modelo, keep_vba=True) if com_macros else None
    planilha = montar_pasta(dados, pasta)
    destino.parent.mkdir(parents=True, exist_ok=True)
    planilha.save(destino)
    desempenho = {
        "duracao_s": round(time.perf_counter() - inicio, 2),
        "pico_memoria_gb": round(pico_memoria_processo_gb(), 2),
        "com_macros": com_macros,
    }
    log.info("fechamento gravado em %s (%s)", destino, desempenho)
    return destino, desempenho
