"""Backtest de várias origens (rolling origin) para calibrar as faixas baixa/alta.

Um único backtest de seis meses dá só 6 pontos mensais, pouco para estimar percentis. Aqui o modelo
é treinado só até cada origem (fim de mês) e prevê de 1 a N meses à frente, o mesmo horizonte da
previsão real; cada ponto previsto é fora da amostra do modelo. Os resíduos (razão real / previsto)
de todas as origens são juntados para calibrar as faixas da rede, da loja e de cada setor.

Cobertura "fora da amostra" = leave-origin-out: a faixa que cobre as origens `i` é calibrada só com
origens cujo período previsto não se sobrepõe ao da origem `i` (diferença de pelo menos N meses),
então a faixa nunca vê o que vai ser medido. Cobertura "na amostra" = faixa calibrada com todas as
origens (otimista).
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from src import config
from src.calendario import ultimo_dia_do_mes
from src.previsao import faixa as faixa_mod
from src.previsao import faixa_agregada as agregada_mod

# obter(origem, inicio, fim) -> (real, previsto, datas) de todas as séries do painel
Obter = Callable[[date, date, date], tuple[np.ndarray, np.ndarray, pd.DatetimeIndex]]
COLUNAS_COBERTURA = ["origem_faixa", "granularidade", "sk_loja", "cobertura", "pontos"]


@dataclass
class Origem:
    origem: date
    real: np.ndarray  # séries x dias
    previsto: np.ndarray
    datas: pd.DatetimeIndex
    lojas: np.ndarray
    setores: np.ndarray

    @property
    def indice_mes(self) -> int:
        return self.origem.year * 12 + self.origem.month


def somar_meses(dia: date, meses: int) -> date:
    indice = dia.year * 12 + dia.month - 1 + meses
    return date(indice // 12, indice % 12 + 1, 1)


def origens_mensais(primeira: date, ultima: date) -> list[date]:
    """Fins de mês de `primeira` a `ultima` (inclusive)."""
    saida, mes = [], date(primeira.year, primeira.month, 1)
    while mes <= ultima:
        saida.append(ultimo_dia_do_mes(mes.year, mes.month))
        mes = somar_meses(mes, 1)
    return [o for o in saida if primeira <= o <= ultima]


def coletar(
    obter: Obter,
    chaves_series: list[tuple[int, str]],
    todas_as_chaves: list[tuple[int, str]],
    origens: list[date],
    ultimo_dia: date,
    meses_a_frente: int = config.PREVISAO_ROLLING_MESES_A_FRENTE,
) -> list[Origem]:
    """Previsto e real de cada origem. Origens cujo horizonte passa do último dia são puladas;
    séries sem real ou sem previsão numa origem (loja ainda não aberta) ficam fora dela."""
    posicao = {c: i for i, c in enumerate(todas_as_chaves)}
    linhas = [posicao[c] for c in chaves_series]
    saida = []
    for origem in origens:
        primeiro_mes_depois = somar_meses(origem, 1)
        fim = ultimo_dia_do_mes(*divmod_ano_mes(somar_meses(origem, meses_a_frente)))
        if fim > ultimo_dia:
            continue
        real, previsto, datas = obter(origem, primeiro_mes_depois, fim)
        real, previsto = real[linhas], previsto[linhas]
        boas = np.isfinite(real).all(axis=1) & np.isfinite(previsto).all(axis=1)
        if not boas.any():
            continue
        lojas = np.array([c[0] for c in chaves_series])[boas]
        setores = np.array([c[1] for c in chaves_series])[boas]
        saida.append(Origem(origem, real[boas], previsto[boas], datas, lojas, setores))
    return saida


def divmod_ano_mes(primeiro_dia: date) -> tuple[int, int]:
    return primeiro_dia.year, primeiro_dia.month


def _por_granularidade(o: Origem) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    return faixa_mod._por_granularidade(o.real, o.previsto, o.datas)


def _quantis(razoes: list[np.ndarray]) -> tuple[float, float] | None:
    juntas = np.concatenate(razoes) if razoes else np.array([])
    if not len(juntas):
        return None
    baixo, alto = np.quantile(juntas, [config.PREVISAO_QUANTIL_BAIXO, config.PREVISAO_QUANTIL_ALTO])
    return float(baixo), float(alto)


def _razao(r: np.ndarray, p: np.ndarray) -> np.ndarray:
    usados = p > 0
    return r[usados] / p[usados]


def calibrar(
    origens: list[Origem],
) -> tuple[agregada_mod.FaixasAgregadas, faixa_mod.Faixas]:
    """Faixas da rede e da loja (nível agregado) e de cada setor (nível loja x setor), com os
    resíduos juntos de todas as `origens`."""
    agregadas: agregada_mod.FaixasAgregadas = {}
    series: faixa_mod.Faixas = {}
    for granularidade in ("dia", "mes"):
        por_nivel: dict[tuple, list[np.ndarray]] = {}
        for o in origens:
            r, p = _por_granularidade(o)[granularidade]
            for nivel in ("loja", "rede"):
                r_n = agregada_mod.agregar(r, o.lojas, nivel)[1]
                p_n = agregada_mod.agregar(p, o.lojas, nivel)[1]
                por_nivel.setdefault((nivel, None), []).append(_razao(r_n.ravel(), p_n.ravel()))
            for setor in sorted(set(o.setores.tolist())):
                linhas = o.setores == setor
                por_nivel.setdefault(("loja_setor", setor), []).append(
                    _razao(r[linhas].ravel(), p[linhas].ravel())
                )
        for (nivel, setor), razoes in por_nivel.items():
            quantis = _quantis(razoes)
            if quantis is None:
                continue
            if nivel == "loja_setor":
                series[(granularidade, setor)] = quantis
            else:
                agregadas[(nivel, granularidade)] = quantis
    return agregadas, series


def _dentro(r: np.ndarray, baixo: np.ndarray, alto: np.ndarray) -> np.ndarray:
    return (r >= baixo - 1e-9) & (r <= alto + 1e-9)


def _cobertura_origem(o: Origem, agregadas, series, granularidade: str):
    """Para uma origem: indicadores 0/1 (séries/totais x pontos) dentro da faixa, por nível."""
    r, p = _por_granularidade(o)[granularidade]
    saida = {}
    for nivel in ("rede", "loja"):
        faixa = agregadas.get((nivel, granularidade))
        if faixa is None:
            continue
        rotulos, r_n = agregada_mod.agregar(r, o.lojas, nivel)
        p_n = agregada_mod.agregar(p, o.lojas, nivel)[1]
        baixo, alto = agregada_mod.aplicar(p_n, faixa)
        saida[nivel] = (rotulos, _dentro(r_n, baixo, alto))
    if all((granularidade, s) in series for s in set(o.setores.tolist())):
        baixo, alto = faixa_mod.aplicar_faixa(p, o.setores.tolist(), series, granularidade)
        saida["loja_setor"] = (o.lojas.tolist(), _dentro(r, baixo, alto))
    return saida


def _sem_sobreposicao(origens: list[Origem], i: Origem, meses_a_frente: int) -> list[Origem]:
    return [o for o in origens if abs(o.indice_mes - i.indice_mes) >= meses_a_frente]


def medir_cobertura(
    origens: list[Origem], meses_a_frente: int = config.PREVISAO_ROLLING_MESES_A_FRENTE
) -> dict[str, pd.DataFrame]:
    """Cobertura da faixa por nível ("agregado" = rede e loja; "loja_setor"), fora e na amostra.

    Cada DataFrame tem COLUNAS_COBERTURA; `sk_loja` vazio = rede (agregado) ou a média de todas as
    lojas (loja_setor); `pontos` = quantos valores reais entraram na média."""
    linhas = {"agregado": [], "loja_setor": []}
    for rotulo, fora in (("fora_da_amostra", True), ("na_amostra", False)):
        faixas_de = {}
        for o in origens:
            usadas = _sem_sobreposicao(origens, o, meses_a_frente) if fora else origens
            faixas_de[o.origem] = calibrar(usadas) if usadas else ({}, {})
        for granularidade in ("dia", "mes"):
            acumulado: dict[tuple[str, int | None], list[np.ndarray]] = {}
            for o in origens:
                agregadas, series = faixas_de[o.origem]
                for nivel, (rotulos, dentro) in _cobertura_origem(
                    o, agregadas, series, granularidade
                ).items():
                    chave_nivel = "loja_setor" if nivel == "loja_setor" else "agregado"
                    if nivel == "rede":
                        acumulado.setdefault((chave_nivel, None), []).append(dentro.ravel())
                        continue
                    lojas = np.array(rotulos)
                    for loja in sorted(set(lojas.tolist())):
                        acumulado.setdefault((chave_nivel, int(loja)), []).append(
                            dentro[lojas == loja].ravel()
                        )
                    if nivel == "loja_setor":
                        acumulado.setdefault((chave_nivel, None), []).append(dentro.ravel())
            for (chave_nivel, loja), partes in acumulado.items():
                valores = np.concatenate(partes)
                linhas[chave_nivel].append(
                    (rotulo, granularidade, loja, float(valores.mean()), int(len(valores)))
                )
    return {k: pd.DataFrame(v, columns=COLUNAS_COBERTURA) for k, v in linhas.items()}
