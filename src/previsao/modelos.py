"""Modelos de previsão diária de receita por (loja, setor). Só numpy/pandas, sem estatística pesada.

Todo modelo tem a mesma assinatura: recebe o painel de treino e os dias a prever e devolve uma
matriz (n_series, n_dias_alvo); séries sem histórico suficiente voltam NaN.

- ingenua: o mesmo dia da semana um ano antes (364 dias). Linha de base.
- decomposicao: nível recente x fator do dia da semana x fator de feriado x fator do mês x
  tendência amortecida. Os fatores são aprendidos por setor, juntando as lojas com histórico longo.
- holt_winters: nível + tendência amortecida + sazonalidade semanal (aditiva), uma série por vez.
- holt_winters_mensal: o Holt-Winters corrigido pelo fator do mês da decomposição.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src import config
from src.calendario import feriados_do_periodo
from src.previsao.painel import Painel

DIAS_POR_MES = 30.4375
MIN_DIAS_JANELA_NIVEL = 14


def _nomes_feriado(datas: pd.DatetimeIndex) -> np.ndarray:
    """Nome do feriado nacional de cada dia (None nos dias comuns)."""
    feriados = feriados_do_periodo(datas[0].date(), datas[-1].date())
    return np.array([feriados.get(d.date()) for d in datas], dtype=object)


def _series_previsiveis(painel: Painel) -> np.ndarray:
    return painel.dias_com_historico() >= config.PREVISAO_DIAS_MINIMOS_SERIE


# --- ingênua -------------------------------------------------------------------------------------
def prever_ingenua(painel: Painel, alvo: pd.DatetimeIndex) -> np.ndarray:
    """Cada dia vale o mesmo dia da semana de 364 dias antes (recua mais um ano se cair fora do
    treino). Série sem esse dia no passado usa a média dos últimos 28 dias."""
    saida = np.full((len(painel.chaves), len(alvo)), np.nan)
    ultimo = len(painel.datas) - 1
    for j, dia in enumerate(alvo):
        posicao = painel.posicao(dia)
        anos = max(1, math.ceil((posicao - ultimo) / config.PREVISAO_DIAS_ANO_ANTERIOR))
        origem = posicao - anos * config.PREVISAO_DIAS_ANO_ANTERIOR
        if origem >= 0:
            saida[:, j] = painel.valores[:, origem]
    recente = np.nanmean(painel.valores[:, -config.PREVISAO_DIAS_MINIMOS_SERIE :], axis=1)
    saida = np.where(np.isnan(saida), recente[:, None], saida)
    saida[~_series_previsiveis(painel)] = np.nan
    return saida


# --- decomposição --------------------------------------------------------------------------------
@dataclass
class Fatores:
    dia_semana: np.ndarray  # 7, segunda = 0, média 1
    feriado_geral: float
    feriado_por_nome: dict[str, float]
    mes: np.ndarray  # 12, janeiro = 0, média 1
    crescimento_mensal: float  # variação em log por mês

    def feriado(self, nome: str | None) -> float:
        if nome is None:
            return 1.0
        return self.feriado_por_nome.get(nome, self.feriado_geral)


def estimar_fatores(datas: pd.DatetimeIndex, soma: np.ndarray) -> Fatores:
    """Aprende os fatores de uma série diária (a soma de um setor nas lojas com histórico longo).

    Dia da semana e feriado: razão do dia pela média móvel centrada de 7 dias. Mês e crescimento:
    média mensal da série já sem dia da semana e feriado; o crescimento é a variação ano contra
    ano dos meses que têm dois anos de dados, e o fator do mês é o que sobra depois de tirá-lo.
    """
    serie = pd.Series(soma, index=datas)
    razao = (serie / serie.rolling(7, center=True).mean()).to_numpy()
    dia_semana = datas.day_of_week.to_numpy()
    nomes = _nomes_feriado(datas)
    eh_feriado = np.array([n is not None for n in nomes])
    valido = np.isfinite(razao)

    f_dia = np.ones(7)
    for d in range(7):
        usados = valido & ~eh_feriado & (dia_semana == d)
        if usados.any():
            f_dia[d] = razao[usados].mean()
    f_dia /= f_dia.mean()

    sem_dia = razao / f_dia[dia_semana]
    usados = valido & eh_feriado
    geral = float(sem_dia[usados].mean()) if usados.any() else 1.0
    por_nome = {}
    for nome in {n for n in nomes if n is not None}:
        valores = sem_dia[valido & (nomes == nome)]
        if len(valores):
            k = config.PREVISAO_SUAVIZACAO_FERIADO_K
            por_nome[nome] = (len(valores) * float(valores.mean()) + k * geral) / (len(valores) + k)

    f_feriado = np.array([por_nome.get(n, geral) if n is not None else 1.0 for n in nomes])
    sem_calendario = serie.to_numpy() / (f_dia[dia_semana] * f_feriado)
    agrupado = pd.DataFrame({"d": sem_calendario}).groupby([datas.year, datas.month])["d"]
    mensal = agrupado.agg(["mean", "count"])
    mensal = mensal[mensal["count"] >= config.PREVISAO_DIAS_MES_COMPLETO]
    log_mensal = {ano * 12 + mes: math.log(m) for (ano, mes), m in mensal["mean"].items() if m > 0}
    pares = [v - log_mensal[k - 12] for k, v in log_mensal.items() if k - 12 in log_mensal]
    crescimento = float(np.mean(pares)) / 12 if pares else 0.0

    sobras: dict[int, list[float]] = {}
    for k, v in log_mensal.items():
        sobras.setdefault((k - 1) % 12, []).append(v - crescimento * k)
    medias = {mes: float(np.mean(v)) for mes, v in sobras.items()}
    centro = float(np.mean(list(medias.values()))) if medias else 0.0
    log_mes = np.zeros(12)
    for mes, media in medias.items():
        n = len(sobras[mes])
        log_mes[mes] = n / (n + config.PREVISAO_SUAVIZACAO_MENSAL_K) * (media - centro)
    f_mes = np.exp(log_mes)
    return Fatores(f_dia, geral, por_nome, f_mes / f_mes.mean(), crescimento)


def _fatores_por_setor(painel: Painel) -> dict[str, Fatores]:
    """Fatores de cada setor, aprendidos nas lojas com histórico longo (ou em todas, se nenhuma)."""
    historico = painel.dias_com_historico()
    minimo = config.PREVISAO_DIAS_MINIMOS_HISTORICO_FATORES
    fatores = {}
    for setor in sorted({s for _, s in painel.chaves}):
        do_setor = [i for i, (_, s) in enumerate(painel.chaves) if s == setor]
        base = [i for i in do_setor if historico[i] >= minimo] or do_setor
        fatores[setor] = estimar_fatores(painel.datas, np.nansum(painel.valores[base], axis=0))
    return fatores


def _soma_amortecida(meses: np.ndarray) -> np.ndarray:
    """Quanto da tendência mensal vale daqui a `meses` meses, com o ritmo se amortecendo."""
    phi = config.PREVISAO_AMORTECIMENTO_MENSAL
    return phi * (1 - phi**meses) / (1 - phi)


def prever_decomposicao(painel: Painel, alvo: pd.DatetimeIndex) -> np.ndarray:
    ultimo = painel.datas[-1]
    n = len(painel.datas)
    janela = config.PREVISAO_JANELA_NIVEL_DIAS
    datas_janela = painel.datas[-janela:]
    nomes = _nomes_feriado(painel.datas.append(alvo))
    nomes_janela, nomes_alvo = nomes[n - janela : n], nomes[n:]
    meses_janela = (datas_janela - ultimo).days.to_numpy() / DIAS_POR_MES  # <= 0
    meses_alvo = (alvo - ultimo).days.to_numpy() / DIAS_POR_MES
    previsiveis = _series_previsiveis(painel)
    saida = np.full((len(painel.chaves), len(alvo)), np.nan)

    for setor, f in _fatores_por_setor(painel).items():
        sazonal_janela = (
            f.dia_semana[datas_janela.day_of_week]
            * np.array([f.feriado(x) for x in nomes_janela])
            * f.mes[datas_janela.month - 1]
            * np.exp(f.crescimento_mensal * meses_janela)
        )
        sazonal_alvo = (
            f.dia_semana[alvo.day_of_week]
            * np.array([f.feriado(x) for x in nomes_alvo])
            * f.mes[alvo.month - 1]
            * np.exp(f.crescimento_mensal * _soma_amortecida(meses_alvo))
        )
        for i, (_, s) in enumerate(painel.chaves):
            if s != setor or not previsiveis[i]:
                continue
            reais = painel.valores[i, -janela:]
            validos = np.isfinite(reais)
            if validos.sum() < MIN_DIAS_JANELA_NIVEL:
                continue
            saida[i] = float(np.mean(reais[validos] / sazonal_janela[validos])) * sazonal_alvo
    return saida


# --- Holt-Winters --------------------------------------------------------------------------------
def _hw_passar(y: np.ndarray, alfa: float, beta: float, gama: float, phi: float, m: int):
    """Uma passada do Holt-Winters aditivo com tendência amortecida.

    Devolve (erro quadrático dos passos de 1 dia, nível, tendência, sazonalidade final).
    A primeira semana serve de partida: a tendência é a diferença entre as duas primeiras semanas
    por dia (zero se houver menos de duas), o nível é o da última posição da semana e a
    sazonalidade, o que sobra de cada dia depois de tirar nível e tendência.
    """
    n = len(y)
    media = float(y[:m].mean())
    tendencia = float((y[m : 2 * m].mean() - media) / m) if n >= 2 * m else 0.0
    nivel = media + tendencia * (m - 1) / 2
    sazonal = list(y[:m] - (nivel - tendencia * (m - 1 - np.arange(m))))
    erro2 = 0.0
    for t in range(m, n):
        base = nivel + phi * tendencia
        erro2 += (y[t] - (base + sazonal[t - m])) ** 2
        novo_nivel = alfa * (y[t] - sazonal[t - m]) + (1 - alfa) * base
        tendencia = beta * (novo_nivel - nivel) + (1 - beta) * phi * tendencia
        sazonal.append(gama * (y[t] - base) + (1 - gama) * sazonal[t - m])
        nivel = novo_nivel
    return erro2, nivel, tendencia, np.array(sazonal[-m:])


def ajustar_holt_winters(
    y: np.ndarray, passos: int, *, phi: float = config.PREVISAO_HW_AMORTECIMENTO
) -> np.ndarray:
    """Escolhe alfa, beta e gama pela menor soma de erros quadráticos de 1 passo e prevê `passos`
    dias seguidos ao fim de `y` (nunca abaixo de zero). Exige pelo menos duas semanas."""
    m = config.PREVISAO_HW_PERIODO
    melhor = None
    for alfa in config.PREVISAO_HW_ALFAS:
        for beta in config.PREVISAO_HW_BETAS:
            for gama in config.PREVISAO_HW_GAMAS:
                resultado = _hw_passar(y, alfa, beta, gama, phi, m)
                if melhor is None or resultado[0] < melhor[0]:
                    melhor = resultado
    _, nivel, tendencia, sazonal = melhor
    h = np.arange(1, passos + 1)
    acumulado = np.cumsum(phi**h) if phi != 1 else h.astype(float)
    return np.maximum(nivel + tendencia * acumulado + sazonal[(h - 1) % m], 0.0)


def prever_holt_winters(painel: Painel, alvo: pd.DatetimeIndex) -> np.ndarray:
    passos = (alvo[-1] - painel.datas[-1]).days
    posicoes = (alvo - painel.datas[-1]).days.to_numpy() - 1
    previsiveis = _series_previsiveis(painel)
    saida = np.full((len(painel.chaves), len(alvo)), np.nan)
    for i in range(len(painel.chaves)):
        y = painel.valores[i][np.isfinite(painel.valores[i])]
        if previsiveis[i] and len(y) >= 2 * config.PREVISAO_HW_PERIODO:
            saida[i] = ajustar_holt_winters(y, passos)[posicoes]
    return saida


def prever_holt_winters_mensal(painel: Painel, alvo: pd.DatetimeIndex) -> np.ndarray:
    """Holt-Winters x (fator do mês previsto / fator médio dos meses da janela final do treino)."""
    saida = prever_holt_winters(painel, alvo)
    janela = painel.datas[-config.PREVISAO_JANELA_NIVEL_DIAS :]
    for setor, f in _fatores_por_setor(painel).items():
        ajuste = f.mes[alvo.month - 1] / float(np.mean(f.mes[janela.month - 1]))
        for i, (_, s) in enumerate(painel.chaves):
            if s == setor:
                saida[i] = saida[i] * ajuste
    return saida


MODELOS: dict[str, Callable[[Painel, pd.DatetimeIndex], np.ndarray]] = {
    "ingenua": prever_ingenua,
    "decomposicao": prever_decomposicao,
    "holt_winters": prever_holt_winters,
    "holt_winters_mensal": prever_holt_winters_mensal,
}


def versao_do_modelo(nome: str) -> str:
    return f"{nome}@{config.PREVISAO_VERSAO_MODELO}"
