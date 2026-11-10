"""Probabilidade de a receita do mês fechar >= meta do mês (lógica pura: numpy e pandas, sem banco).

Em cada corte diário d (a receita até d já é conhecida), o que falta do mês é a parte incerta:

    receita do mês = realizado até d + (previsto do resto) x R
    R = real do resto / previsto do resto

Modelo de erro: ln R por faixa de "dias que faltam" (config.PROB_FAIXAS_DIAS), com viés (mu) e
dispersão (sigma) por loja encolhidos para o conjunto das lojas com peso n / (n + K), n = meses
distintos observados da loja naquela faixa (os cortes de um mesmo mês não são independentes). A rede
tem a dispersão própria (o total diversifica: não é a soma das lojas). A forma da distribuição é a
dos resíduos padronizados z = (ln R - mu) / sigma, juntos de todas as lojas e faixas.

    P = P(R >= (meta - realizado até d) / previsto do resto) = 1 - F_z((ln necessário - mu) / sigma)

No último dia do mês não há o que prever: P é exatamente 0 ou 1. Meta já batida: P = 1.

Sem vazamento do futuro (duas formas, escolhidas por `esquema`):
  - "so_passado": a distribuição do erro de um mês usa SÓ meses já fechados e anteriores a ele. É
    a probabilidade que vai para o painel (em qualquer data de referência d, só entram meses que
    terminaram antes de d, porque o desfecho de um corte só é conhecido no fim do seu mês).
  - "leave_one_month_out": a do mês avaliado sai do ajuste, mas entram meses POSTERIORES a ele.
    Serve só para medir a calibração com mais meses (é otimista); nunca vai para o painel.

Quem não tem base fica SEM probabilidade (None), nunca com 50%: loja nova (série com menos de
config.PREVISAO_DIAS_MINIMOS_SERIE dias), mês sem meta, ou meses fechados de menos para estimar
o erro.
"""

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src import config

REDE = 0  # valor de sk_loja da linha de rede nos DataFrames (vira NULL no banco)
MOTIVOS = ("loja_nova", "sem_meta", "sem_amostra_erro", "sem_previsao")
FORMA_MINIMA = 30  # menos resíduos que isto: a forma não é confiável e não há probabilidade


def faixa_de_dias(dias_restantes: int) -> int:
    """Índice da faixa de dias que faltam (0 a 4), ou -1 se não houver (último dia do mês)."""
    for i, (inicio, fim) in enumerate(config.PROB_FAIXAS_DIAS):
        if inicio <= dias_restantes <= fim:
            return i
    return -1


@dataclass
class ParametrosErro:
    mu: float  # viés de ln R (já encolhido)
    sigma: float  # dispersão de ln R (já encolhida e com piso)
    n_meses: int
    n_amostras: int
    mu_bruto: float
    sigma_bruto: float
    peso: float  # peso da loja no encolhimento (1 no conjunto e na rede)


@dataclass
class ModeloErro:
    """Erro do que falta do mês, ajustado com os meses fechados escolhidos para o treino."""

    meses_ate: pd.Timestamp | None  # último mês do treino
    n_meses: int
    k: float
    loja: dict[tuple[int, int], ParametrosErro] = field(default_factory=dict)
    conjunto: dict[int, ParametrosErro] = field(default_factory=dict)
    rede: dict[int, ParametrosErro] = field(default_factory=dict)
    forma: np.ndarray = field(default_factory=lambda: np.array([]))  # z ordenados

    def parametros(self, nivel: str, sk_loja: int, faixa: int) -> ParametrosErro | None:
        if nivel == "rede":
            return self.rede.get(faixa)
        return self.loja.get((sk_loja, faixa), self.conjunto.get(faixa))

    def cdf(self, z: float) -> float:
        """Distribuição acumulada empírica da forma (interpolada; nas pontas, o último passo)."""
        n = len(self.forma)
        return float(np.interp(z, self.forma, (np.arange(n) + 0.5) / n))


def amostras_de_erro(cortes: pd.DataFrame) -> pd.DataFrame:
    """Linhas com desfecho conhecido do resto do mês: nivel, sk_loja, mes, faixa, ln_r."""
    c = cortes
    usadas = (
        c["base"]
        & (c["dias_restantes"] >= 1)
        & c["real_resto"].notna()
        & (c["prev_resto"] > 0)
        & (c["real_resto"] > 0)
    )
    a = c[usadas]
    return pd.DataFrame(
        {
            "nivel": a["nivel"].to_numpy(),
            "sk_loja": a["sk_loja"].to_numpy(),
            "mes": a["mes"].to_numpy(),
            "faixa": a["faixa"].to_numpy(),
            "ln_r": np.log(a["real_resto"].to_numpy() / a["prev_resto"].to_numpy()),
        }
    )


def _momentos(valores: np.ndarray) -> tuple[float, float]:
    mu = float(np.mean(valores))
    sigma = float(np.std(valores, ddof=1)) if len(valores) > 1 else float("nan")
    return mu, sigma


def peso_do_encolhimento(n_meses: int, k: float = config.PROB_SHRINKAGE_K) -> float:
    """Peso da loja = n / (n + K)."""
    return n_meses / (n_meses + k)


def _pisar(sigma: float) -> float:
    return max(sigma, config.PROB_SIGMA_MINIMO)


def ajustar_erro(
    amostras: pd.DataFrame,
    k: float = config.PROB_SHRINKAGE_K,
    meses_minimos: int = config.PROB_MESES_MINIMOS,
) -> ModeloErro:
    """Ajusta o modelo de erro. Faixa com menos de `meses_minimos` meses fica sem parâmetros."""
    meses = pd.DatetimeIndex(amostras["mes"].unique()) if len(amostras) else pd.DatetimeIndex([])
    modelo = ModeloErro(meses_ate=meses.max() if len(meses) else None, n_meses=len(meses), k=k)
    if not len(amostras):
        return modelo
    lojas = amostras[amostras["nivel"] == "loja"]
    for faixa, sub in lojas.groupby("faixa"):
        n_meses = sub["mes"].nunique()
        if n_meses < meses_minimos or len(sub) < 2:
            continue
        mu, sigma = _momentos(sub["ln_r"].to_numpy())
        modelo.conjunto[int(faixa)] = ParametrosErro(
            mu, _pisar(sigma), n_meses, len(sub), mu, sigma, 1.0
        )
    for (sk, faixa), sub in lojas.groupby(["sk_loja", "faixa"]):
        faixa = int(faixa)
        base = modelo.conjunto.get(faixa)
        if base is None:
            continue
        n_meses = sub["mes"].nunique()
        mu_b, sigma_b = _momentos(sub["ln_r"].to_numpy())
        peso = peso_do_encolhimento(n_meses, k) if len(sub) > 1 else 0.0
        variancia = (peso * sigma_b**2 if peso else 0.0) + (1 - peso) * base.sigma**2
        modelo.loja[(int(sk), faixa)] = ParametrosErro(
            peso * mu_b + (1 - peso) * base.mu if peso else base.mu,
            _pisar(math.sqrt(variancia)),
            n_meses, len(sub), mu_b, sigma_b, peso,
        )  # fmt: skip
    for faixa, sub in amostras[amostras["nivel"] == "rede"].groupby("faixa"):
        if sub["mes"].nunique() < meses_minimos or len(sub) < 2:
            continue
        mu, sigma = _momentos(sub["ln_r"].to_numpy())
        modelo.rede[int(faixa)] = ParametrosErro(
            mu, _pisar(sigma), sub["mes"].nunique(), len(sub), mu, sigma, 1.0
        )
    z = []
    for linha in lojas.itertuples(index=False):
        par = modelo.loja.get((int(linha.sk_loja), int(linha.faixa)))
        if par is not None:
            z.append((linha.ln_r - par.mu) / par.sigma)
    if len(z) >= FORMA_MINIMA:
        modelo.forma = np.sort(np.array(z))
    return modelo


def probabilidade_do_corte(
    modelo: ModeloErro,
    nivel: str,
    sk_loja: int,
    dias_restantes: int,
    realizado_ate: float,
    prev_resto: float,
    meta: float,
) -> tuple[float | None, str | None]:
    """(probabilidade, motivo de não ter). Um dos dois é None."""
    if not meta > 0:
        return None, "sem_meta"
    if realizado_ate >= meta:
        return 1.0, None
    if dias_restantes <= 0:
        return 0.0, None  # mês fechado abaixo da meta: sem nada a prever
    if not prev_resto > 0:
        return None, "sem_previsao"
    par = modelo.parametros(nivel, sk_loja, faixa_de_dias(dias_restantes))
    if par is None or len(modelo.forma) < FORMA_MINIMA:
        return None, "sem_amostra_erro"
    necessario = (meta - realizado_ate) / prev_resto
    z = (math.log(necessario) - par.mu) / par.sigma
    return float(1.0 - modelo.cdf(z)), None


def calcular_probabilidades(
    cortes: pd.DataFrame, esquema: str, k: float = config.PROB_SHRINKAGE_K
) -> tuple[pd.DataFrame, dict[pd.Timestamp, ModeloErro]]:
    """Probabilidade de cada linha de `cortes`. Devolve também o modelo de cada mês (só passado)."""
    if esquema not in config.PROB_ESQUEMAS:
        raise ValueError(f"esquema desconhecido: {esquema}")
    amostras = amostras_de_erro(cortes)
    modelos: dict[pd.Timestamp, ModeloErro] = {}
    partes = []
    for mes, grupo in cortes.groupby("mes", sort=True):
        if esquema == "so_passado":
            treino = amostras[amostras["mes"] < mes]  # só meses que terminaram antes deste
        else:
            treino = amostras[amostras["mes"] != mes]
        modelo = ajustar_erro(treino, k)
        if esquema == "so_passado":
            modelos[mes] = modelo
        probs, motivos = [], []
        for r in grupo.itertuples(index=False):
            if not r.base:
                p, m = None, r.motivo
            else:
                p, m = probabilidade_do_corte(
                    modelo,
                    r.nivel,
                    r.sk_loja,
                    r.dias_restantes,
                    r.realizado_ate,
                    r.prev_resto,
                    r.meta,
                )
            probs.append(np.nan if p is None else p)
            motivos.append(m)
        partes.append(grupo.assign(probabilidade=probs, motivo_sem_base=motivos))
    if not partes:
        return cortes.assign(probabilidade=np.nan, motivo_sem_base=None, esquema=esquema), modelos
    saida = pd.concat(partes).sort_index()
    saida["projecao"] = saida["realizado_ate"] + saida["prev_resto"]
    saida["esquema"] = esquema
    return saida, modelos


# --- calibração ----------------------------------------------------------------------------------
def intervalo_wilson(p: float, n: int, z: float = config.PROB_Z_IC) -> tuple[float, float]:
    """Intervalo de Wilson para uma proporção p observada em n unidades independentes."""
    if n <= 0:
        return float("nan"), float("nan")
    den = 1 + z * z / n
    centro = (p + z * z / (2 * n)) / den
    margem = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, centro - margem), min(1.0, centro + margem)


def pontos_avaliaveis(com_p: pd.DataFrame) -> pd.DataFrame:
    """Cortes que medem calibração: tem P, desfecho do mês conhecido, falta algo para vender e a
    meta ainda não foi batida (aí P = 1 por construção, sem informação)."""
    c = com_p
    ok = (
        c["probabilidade"].notna()
        & c["real_resto"].notna()
        & (c["dias_restantes"] >= 1)
        & (c["meta"] > 0)
        & (c["realizado_ate"] < c["meta"])
    )
    a = c[ok].copy()
    a["atingiu"] = ((a["realizado_ate"] + a["real_resto"]) >= a["meta"]).astype(float)
    n_faixas = config.PROB_FAIXAS_CALIBRACAO
    a["faixa_prob"] = np.minimum((a["probabilidade"] * n_faixas).astype(int), n_faixas - 1)
    return a


def avaliar(com_p: pd.DataFrame, esquema: str) -> pd.DataFrame:
    """Curva de confiabilidade (linhas tipo 'faixa') e Brier/ECE (linhas tipo 'resumo'), por nível
    (loja, rede) e por faixa de dias que faltam (0 = todas). Formato de
    dw.previsao_probabilidade_calibracao."""
    a = pontos_avaliaveis(com_p)
    n_faixas = config.PROB_FAIXAS_CALIBRACAO
    linhas = []
    for nivel in ("loja", "rede"):
        de_nivel = a[a["nivel"] == nivel]
        for faixa_dias in range(len(config.PROB_FAIXAS_DIAS) + 1):
            sub = de_nivel if faixa_dias == 0 else de_nivel[de_nivel["faixa"] == faixa_dias - 1]
            if sub.empty:
                continue
            y, p = sub["atingiu"].to_numpy(), sub["probabilidade"].to_numpy()
            freq = float(y.mean())
            ece = 0.0
            for faixa_prob, g in sub.groupby("faixa_prob"):
                unidades = g[["sk_loja", "mes"]].drop_duplicates().shape[0]
                obs, prev = float(g["atingiu"].mean()), float(g["probabilidade"].mean())
                baixo, alto = intervalo_wilson(obs, unidades)
                ece += len(g) / len(sub) * abs(obs - prev)
                linhas.append(
                    {
                        "esquema": esquema, "nivel": nivel, "faixa_dias": faixa_dias,
                        "tipo": "faixa", "prob_inicio": faixa_prob / n_faixas,
                        "prob_fim": (faixa_prob + 1) / n_faixas, "previsto_medio": prev,
                        "observado": obs, "n": len(g), "n_unidades": unidades,
                        "ic_baixo": baixo, "ic_alto": alto,
                    }
                )  # fmt: skip
            linhas.append(
                {
                    "esquema": esquema, "nivel": nivel, "faixa_dias": faixa_dias, "tipo": "resumo",
                    "previsto_medio": float(p.mean()), "observado": freq, "n": len(sub),
                    "n_unidades": sub[["sk_loja", "mes"]].drop_duplicates().shape[0],
                    "brier": float(np.mean((p - y) ** 2)),
                    "brier_50": float(np.mean((0.5 - y) ** 2)),
                    "brier_frequencia": float(np.mean((freq - y) ** 2)),
                    "ece": ece,
                }
            )  # fmt: skip
    colunas = [
        "esquema", "nivel", "faixa_dias", "tipo", "prob_inicio", "prob_fim", "previsto_medio",
        "observado", "n", "n_unidades", "ic_baixo", "ic_alto", "brier", "brier_50",
        "brier_frequencia", "ece",
    ]  # fmt: skip
    return pd.DataFrame(linhas, columns=colunas)


# --- linhas para gravar o ajuste no banco ---------------------------------------------------------
def linhas_do_ajuste(modelos: dict[pd.Timestamp, ModeloErro]) -> pd.DataFrame:
    """Parâmetros (loja, conjunto, rede) e forma (quantis dos resíduos) de cada ajuste mensal, no
    formato de dw.previsao_erro_resto. `meses_ate` = último mês fechado que entrou no ajuste."""
    colunas = [
        "nivel", "sk_loja", "faixa_dias", "posicao", "meses_ate", "n_meses", "n_amostras",
        "mu_bruto", "sigma_bruto", "peso", "mu", "sigma", "z",
    ]  # fmt: skip
    linhas = []
    for modelo in modelos.values():
        if modelo.meses_ate is None:
            continue
        ate = modelo.meses_ate.date()

        def par_linha(nivel, sk, faixa, p, ate=ate):
            return {
                "nivel": nivel, "sk_loja": sk, "faixa_dias": faixa + 1, "posicao": None,
                "meses_ate": ate, "n_meses": p.n_meses, "n_amostras": p.n_amostras,
                "mu_bruto": p.mu_bruto, "sigma_bruto": p.sigma_bruto, "peso": p.peso,
                "mu": p.mu, "sigma": p.sigma, "z": None,
            }  # fmt: skip

        for (sk, faixa), p in modelo.loja.items():
            linhas.append(par_linha("loja", sk, faixa, p))
        for faixa, p in modelo.conjunto.items():
            linhas.append(par_linha("conjunto", None, faixa, p))
        for faixa, p in modelo.rede.items():
            linhas.append(par_linha("rede", None, faixa, p))
        if len(modelo.forma) >= FORMA_MINIMA:
            quantis = np.quantile(modelo.forma, np.linspace(0, 1, config.PROB_QUANTIS_FORMA))
            for posicao, z in enumerate(quantis):
                linhas.append(
                    {
                        "nivel": "forma", "sk_loja": None, "faixa_dias": None, "posicao": posicao,
                        "meses_ate": ate, "n_meses": modelo.n_meses,
                        "n_amostras": len(modelo.forma),
                        "mu_bruto": None, "sigma_bruto": None, "peso": None, "mu": None,
                        "sigma": None, "z": float(z),
                    }
                )  # fmt: skip
    return pd.DataFrame(linhas, columns=colunas)
