"""Backtest: treina até uma data, prevê o período seguinte e mede o erro de cada abordagem.

Métricas (iguais para todas as abordagens, sobre as mesmas séries):
- WAPE = soma dos erros absolutos / soma do real. Por loja e setor, por loja, por setor e na rede,
  no dia e no mês. Cada nível soma as séries antes de comparar (o erro da rede é o do total).
- viés = soma do previsto / soma do real - 1 (positivo: a abordagem prevê a mais).
- A abordagem escolhida é a de menor WAPE mensal por loja e setor, calculado juntando todos os
  pontos (soma dos erros de todas as séries e meses / soma do real).
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from src import config
from src.memoria import pico_memoria_processo_gb
from src.previsao import faixa as faixa_mod
from src.previsao import faixa_agregada as agregada_mod
from src.previsao.modelos import MODELOS
from src.previsao.painel import Painel

Faixas = faixa_mod.Faixas
Modelo = Callable[[Painel, pd.DatetimeIndex], np.ndarray]
COLUNAS_METRICAS = [
    "modelo",
    "nivel",
    "granularidade",
    "sk_loja",
    "setor",
    "agregado",
    "wape",
    "vies",
]


@dataclass
class ResultadoBacktest:
    treino_ate: date
    teste_inicio: date
    teste_fim: date
    metricas: pd.DataFrame  # COLUNAS_METRICAS; sk_loja/setor vazios nas linhas agregadas
    escolhido: str
    faixas: Faixas = field(default_factory=dict)  # calibradas neste backtest (uso na produção)
    faixas_agregadas: agregada_mod.FaixasAgregadas = field(default_factory=dict)  # loja e rede
    cobertura: pd.DataFrame = field(default_factory=pd.DataFrame)
    # cobertura do total da rede (sk_loja vazio) e de cada loja na faixa calibrada no total
    cobertura_agregada: pd.DataFrame = field(default_factory=pd.DataFrame)
    chaves: list[tuple[int, str]] = field(default_factory=list)  # séries avaliadas
    ignoradas: list[tuple[int, str]] = field(
        default_factory=list
    )  # séries que algum modelo não previu
    duracao_s: float = 0.0
    pico_memoria_gb: float = 0.0

    def wape_do_nivel(self, nivel: str, sk_loja: int | None, granularidade: str) -> float | None:
        """WAPE do modelo escolhido no total da loja ou da rede (None se não houver)."""
        m = self.metricas
        achou = m[
            (m["modelo"] == self.escolhido)
            & (m["nivel"] == nivel)
            & (m["granularidade"] == granularidade)
            & (m["agregado"] if sk_loja is None else (m["sk_loja"] == sk_loja))
        ]
        return float(achou["wape"].iloc[0]) if len(achou) else None

    def wape_da_serie(self, sk_loja: int, setor: str, granularidade: str) -> float | None:
        """WAPE do modelo escolhido para uma loja e setor (None se a série não foi avaliada)."""
        m = self.metricas
        achou = m[
            (m["modelo"] == self.escolhido)
            & (m["nivel"] == "loja_setor")
            & (m["granularidade"] == granularidade)
            & (m["sk_loja"] == sk_loja)
            & (m["setor"] == setor)
        ]
        return float(achou["wape"].iloc[0]) if len(achou) else None


def _dias(inicio: date, fim: date) -> pd.DatetimeIndex:
    return pd.date_range(inicio, fim, freq="D")


def _somar_grupos(matriz: np.ndarray, rotulos: list) -> tuple[list, np.ndarray]:
    unicos = sorted(set(rotulos), key=lambda x: (str(x[0]), str(x[1])))
    indice = {r: i for i, r in enumerate(unicos)}
    saida = np.zeros((len(unicos), matriz.shape[1]))
    for linha, rotulo in zip(matriz, rotulos, strict=True):
        saida[indice[rotulo]] += linha
    return unicos, saida


def avaliar(
    modelo: str,
    real: np.ndarray,
    previsto: np.ndarray,
    chaves: list[tuple[int, str]],
    datas: pd.DatetimeIndex,
) -> pd.DataFrame:
    """WAPE e viés de um modelo em todos os níveis e nas duas granularidades."""
    rotulos_por_nivel = {
        "rede": [(None, None)] * len(chaves),
        "loja": [(loja, None) for loja, _ in chaves],
        "setor": [(None, setor) for _, setor in chaves],
        "loja_setor": [(loja, setor) for loja, setor in chaves],
    }
    pares = {
        "dia": (real, previsto),
        "mes": (faixa_mod.somar_por_mes(real, datas), faixa_mod.somar_por_mes(previsto, datas)),
    }
    linhas = []
    for granularidade, (r, p) in pares.items():
        for nivel, rotulos in rotulos_por_nivel.items():
            unicos, r_g = _somar_grupos(r, rotulos)
            _, p_g = _somar_grupos(p, rotulos)
            total, erro, soma_p = r_g.sum(axis=1), np.abs(r_g - p_g).sum(axis=1), p_g.sum(axis=1)
            if nivel != "rede":
                for (loja, setor), t, e, sp in zip(unicos, total, erro, soma_p, strict=True):
                    if t > 0:
                        linhas.append(
                            (modelo, nivel, granularidade, loja, setor, False, e / t, sp / t - 1)
                        )
            if total.sum() > 0:
                linhas.append(
                    (modelo, nivel, granularidade, None, None, True,
                     erro.sum() / total.sum(), soma_p.sum() / total.sum() - 1)
                )  # fmt: skip
    return pd.DataFrame(linhas, columns=COLUNAS_METRICAS)


def _wape_de_escolha(metricas: pd.DataFrame, modelo: str) -> float:
    m = metricas
    linha = m[
        (m["modelo"] == modelo) & (m["nivel"] == "loja_setor")
        & (m["granularidade"] == "mes") & m["agregado"]
    ]  # fmt: skip
    return float(linha["wape"].iloc[0])


def _real_e_previsto(painel, modelo_fn, treino_ate, inicio, fim):
    alvo = _dias(inicio, fim)
    treino = painel.ate(treino_ate)
    previsto = modelo_fn(treino, alvo)
    posicoes = slice(painel.posicao(inicio), painel.posicao(fim) + 1)
    return painel.valores[:, posicoes], previsto, alvo


def executar(
    painel: Painel,
    treino_ate: date = config.PREVISAO_TREINO_ATE_BACKTEST,
    teste_inicio: date = config.PREVISAO_TESTE_INICIO_BACKTEST,
    teste_fim: date = config.PREVISAO_TESTE_FIM_BACKTEST,
    *,
    modelos: dict[str, Modelo] | None = None,
    origem_calibracao: date | None = config.PREVISAO_ORIGEM_CALIBRACAO,
) -> ResultadoBacktest:
    """Roda todas as abordagens, escolhe a melhor e mede a faixa (veja o módulo `faixa`).

    `painel` precisa cobrir até `teste_fim`. A cobertura "fora da amostra" aplica ao backtest
    oficial uma faixa calibrada num backtest anterior (`origem_calibracao`); a "na amostra" usa a
    faixa calibrada no próprio backtest oficial (otimista por construção).
    """
    inicio_execucao = time.perf_counter()
    modelos = modelos or MODELOS
    previsoes = {}
    for nome, funcao in modelos.items():
        real, previsto, alvo = _real_e_previsto(painel, funcao, treino_ate, teste_inicio, teste_fim)
        previsoes[nome] = previsto
    valida = np.isfinite(real).all(axis=1)
    for previsto in previsoes.values():
        valida &= np.isfinite(previsto).all(axis=1)
    chaves = [c for c, ok in zip(painel.chaves, valida, strict=True) if ok]
    ignoradas = [c for c, ok in zip(painel.chaves, valida, strict=True) if not ok]
    real = real[valida]

    metricas = pd.concat(
        [
            avaliar(nome, real, previsto[valida], chaves, alvo)
            for nome, previsto in previsoes.items()
        ],
        ignore_index=True,
    )
    escolhido = min(previsoes, key=lambda nome: _wape_de_escolha(metricas, nome))
    setores = [setor for _, setor in chaves]
    previsto = previsoes[escolhido][valida]
    faixas = faixa_mod.calibrar_faixas(real, previsto, setores, alvo)
    lojas = np.array([loja for loja, _ in chaves])
    faixas_agregadas = agregada_mod.calibrar(real, previsto, lojas, alvo)

    cobertura, cobertura_agregada = _medir_cobertura(
        painel, modelos[escolhido], chaves, real, previsto, alvo, (faixas, faixas_agregadas),
        setores, treino_ate, teste_inicio, teste_fim, origem_calibracao,
    )  # fmt: skip
    return ResultadoBacktest(
        treino_ate, teste_inicio, teste_fim, metricas, escolhido, faixas, faixas_agregadas,
        cobertura, cobertura_agregada, chaves, ignoradas,
        time.perf_counter() - inicio_execucao, pico_memoria_processo_gb(),
    )  # fmt: skip


def _medir_cobertura(
    painel, modelo_fn, chaves, real, previsto, alvo, faixas_na_amostra, setores,
    treino_ate, teste_inicio, teste_fim, origem_calibracao,
):  # fmt: skip
    """Cobertura da faixa, dentro e fora da amostra. Primeiro DataFrame: média, por loja e na rede,
    da cobertura de cada série. Segundo: o total da loja e o total da rede dentro da faixa
    calibrada no próprio total (sk_loja vazio = rede)."""
    faixas, faixas_agregadas = faixas_na_amostra
    lojas = np.array([loja for loja, _ in chaves])
    faixas_fora = None
    agregadas_fora = None
    if origem_calibracao is not None and origem_calibracao < treino_ate:
        duracao = (teste_fim - teste_inicio).days
        inicio_antigo = origem_calibracao + timedelta(days=1)
        fim_antigo = min(inicio_antigo + timedelta(days=duracao), painel.datas[-1].date())
        real_a, previsto_a, alvo_a = _real_e_previsto(
            painel, modelo_fn, origem_calibracao, inicio_antigo, fim_antigo
        )
        posicao = {c: i for i, c in enumerate(painel.chaves)}
        linhas = [posicao[c] for c in chaves]
        real_a, previsto_a = real_a[linhas], previsto_a[linhas]
        boas = np.isfinite(real_a).all(axis=1) & np.isfinite(previsto_a).all(axis=1)
        if boas.any():
            faixas_fora = faixa_mod.calibrar_faixas(
                real_a[boas],
                previsto_a[boas],
                [s for s, b in zip(setores, boas, strict=True) if b],
                alvo_a,
            )
            agregadas_fora = agregada_mod.calibrar(
                real_a[boas], previsto_a[boas], lojas[boas], alvo_a
            )
    linhas_saida, saida_agregada = [], []
    origens = (
        ("fora_da_amostra", faixas_fora, agregadas_fora),
        ("na_amostra", faixas, faixas_agregadas),
    )
    for origem, faixas_usadas, agregadas_usadas in origens:
        if faixas_usadas is None:
            continue
        for granularidade in ("dia", "mes"):
            por_serie = faixa_mod.cobertura(
                real, previsto, setores, faixas_usadas, alvo, granularidade
            )
            linhas_saida.append((origem, granularidade, None, float(por_serie.mean())))
            for loja in sorted(set(lojas)):
                media = float(por_serie[lojas == loja].mean())
                linhas_saida.append((origem, granularidade, int(loja), media))
            agregada = agregada_mod.cobertura(
                real, previsto, lojas, agregadas_usadas, alvo, granularidade
            )
            for (_, loja), valor in agregada.items():
                saida_agregada.append((origem, granularidade, loja, valor))
    colunas = ["origem_faixa", "granularidade", "sk_loja", "cobertura"]
    return pd.DataFrame(linhas_saida, columns=colunas), pd.DataFrame(
        saida_agregada, columns=colunas
    )
