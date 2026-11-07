"""Calendário comercial: o peso de cada dia (e setor) conhecido com antecedência.

Uma rede real sabe de antemão quais dias são feriado, Natal, Black Friday, Dia das Mães, Carnaval e
volta às aulas, e como cada setor reage a eles. Este módulo reúne esse conhecimento (vem de
`Sazonalidade`) num peso por data e setor, SEM a tendência de crescimento do período e SEM nenhuma
venda realizada. É a base das metas: repartição da meta do mês pelos dias (view
`dw.vw_meta_vendas_diaria`, tabela `etl.pesos_calendario`) e taxa-base de cada mês.
"""

from datetime import date, timedelta

import pandas as pd

from src import config
from src.gerador.catalogo import SETORES
from src.gerador.sazonalidade import Sazonalidade


def peso_do_dia(sazon: Sazonalidade, dia: date, setor: str) -> float:
    """Dia da semana x mês x eventos x feriado x multiplicador do setor, sem a tendência anual."""
    tendencia = (1 + config.CRESCIMENTO_ANUAL_VENDAS) ** (
        (dia - sazon.data_inicio).days / config.DIAS_POR_ANO
    )
    return sazon.fator_dia(dia) / tendencia * sazon.multiplicador_setor(dia, setor)


def pesos_do_periodo(inicio: date, fim: date) -> pd.DataFrame:
    """Uma linha por data e setor: colunas data, setor, peso."""
    sazon = Sazonalidade(inicio, fim)
    linhas = []
    dia = inicio
    while dia <= fim:
        for setor in SETORES:
            linhas.append((dia, setor, round(peso_do_dia(sazon, dia, setor), 6)))
        dia += timedelta(days=1)
    return pd.DataFrame(linhas, columns=["data", "setor", "peso"])
