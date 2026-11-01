"""Simulador v2: base em fatia semanal do setor na loja, com encolhimento.

fatia semanal = venda do vendedor no setor / venda total do setor na loja, nas semanas (segunda a
domingo) em que ele esteve lotado no setor a semana inteira. A fatia estimada é encolhida para a
fatia média dos lotados no setor na loja: (n x fatia do vendedor + k x fatia média) / (n + k), com
n = semanas de histórico. Projeção semanal = fatia x venda prevista do setor na loja na semana.
O conservador é um percentil da distribuição das fatias semanais (já encolhidas).
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import psycopg

from src import config
from src.simulador import backtest as v1
from src.simulador.backtest import Historico

DIAS = pd.Timedelta(days=config.SIMULADOR_DIAS_POR_SEMANA - 1)


class Semanal:
    """Vendas semanais (segunda a domingo) por loja e setor e por vendedor e setor."""

    def __init__(self, h: Historico):
        self.h = h
        painel = h.painel
        semana = painel.datas.to_period("W-SUN").start_time
        tabela = pd.DataFrame(np.nan_to_num(painel.valores).T, index=painel.datas)
        tabela = tabela.groupby(semana).sum()
        tabela.columns = pd.MultiIndex.from_tuples(painel.chaves)
        self.loja_setor = tabela
        self._vendedor: dict[tuple[int, str], pd.Series] = {}
        self._pool: dict[tuple, np.ndarray] = {}

    def _semanal_vendedor(self, sk_vendedor: int, setor: str) -> pd.Series:
        chave = (sk_vendedor, setor)
        if chave not in self._vendedor:
            vendas = self.h.vendas.get(chave)
            if vendas is None:
                self._vendedor[chave] = pd.Series(dtype=float)
            else:
                self._vendedor[chave] = vendas.groupby(
                    vendas.index.to_period("W-SUN").start_time
                ).sum()
        return self._vendedor[chave]

    def observacoes(self, sk_vendedor: int, setor: str, origem: date) -> np.ndarray:
        """Fatias semanais do vendedor no setor, nas semanas inteiras lotado até `origem`."""
        h = self.h
        loja = int(h.cadastro.loc[sk_vendedor, "sk_loja"])
        periodos = h.periodos.get((sk_vendedor, setor), [])
        if not periodos or (loja, setor) not in self.loja_setor.columns:
            return np.empty(0)
        total = self.loja_setor[(loja, setor)]
        fim = pd.Timestamp(origem)
        segundas = total.index[
            (total.index > fim - pd.Timedelta(days=h.parametros.janela_dias))
            & (total.index + DIAS <= fim)
        ]
        inteira = np.zeros(len(segundas), dtype=bool)
        for ini, fim_p in periodos:
            inteira |= (segundas >= ini) & (segundas + DIAS <= fim_p)
        segundas = segundas[inteira]
        base = total.loc[segundas]
        vendido = self._semanal_vendedor(sk_vendedor, setor).reindex(segundas, fill_value=0.0)
        return (vendido / base)[base > 0].to_numpy()

    def conjunto(self, sk_loja: int, setor: str, origem: date, excluir: int) -> np.ndarray:
        """Fatias semanais de todos os outros lotados no setor na loja; se não houver, na rede."""

        def juntar(lojas):
            partes = [
                self.observacoes(v, setor, origem)
                for loja in lojas
                for v in self.h.vendedores_da_loja.get(loja, [])
                if v != excluir
            ]
            partes = [p for p in partes if len(p)]
            return np.concatenate(partes) if partes else np.empty(0)

        da_loja = juntar([sk_loja])
        if len(da_loja):
            return da_loja
        chave = ("rede", setor, origem, excluir)
        if chave not in self._pool:
            self._pool[chave] = juntar(self.h.vendedores_da_loja)
        return self._pool[chave]


def estimar(proprias: np.ndarray, conjunto: np.ndarray, k: float, percentil: float):
    """(fatia central, fatia conservadora) ou None se não há base alguma."""
    if len(conjunto) == 0 and len(proprias) == 0:
        return None
    media = float(conjunto.mean()) if len(conjunto) else float(proprias.mean())
    n = len(proprias)
    if n == 0:
        return media, float(np.percentile(conjunto, percentil * 100))
    encolhidas = (n * proprias + k * media) / (n + k)
    central = float((n * proprias.mean() + k * media) / (n + k))
    return central, float(np.percentile(encolhidas, percentil * 100))


def _semanas(valores: np.ndarray) -> np.ndarray:
    return valores.reshape(-1, config.SIMULADOR_DIAS_POR_SEMANA).sum(axis=1)


def preparar(h: Historico, sem: Semanal) -> list[dict]:
    """Para cada evento avaliável: o que o v2 e a referência precisam (uma vez só)."""
    maior = max(config.SIMULADOR_HORIZONTES_DIAS)
    from src.previsao import modelos

    trocas = v1.eventos_de_troca(h)
    eventos = trocas + v1.eventos_placebo(h, len(trocas), trocas)
    previsoes: dict[date, np.ndarray] = {}
    saida = []
    for e in eventos:
        if e.inicio + timedelta(days=maior - 1) > h.fim:
            continue
        desligamento = h.cadastro.loc[e.sk_vendedor, "data_desligamento"]
        if desligamento is not None and desligamento < e.inicio + timedelta(days=maior):
            continue
        chaves = h.painel.chaves
        if (e.sk_loja, e.setor_destino) not in chaves:
            continue
        if e.origem not in previsoes:
            alvo = pd.date_range(e.inicio, periods=maior, freq="D")
            previsoes[e.origem] = modelos.prever_decomposicao(h.painel.ate(e.origem), alvo)
        previsto = previsoes[e.origem][chaves.index((e.sk_loja, e.setor_destino))]
        if not np.isfinite(previsto).all():
            continue
        saida.append({
            "evento": e,
            "previsto_semana": _semanas(previsto),
            "real_semana": _semanas(h.real(e.sk_vendedor, e.setor_destino, e.inicio, maior)),
            "proprias": sem.observacoes(e.sk_vendedor, e.setor_destino, e.origem),
            "conjunto": sem.conjunto(e.sk_loja, e.setor_destino, e.origem, e.sk_vendedor),
            "referencia": v1.projetar(h, e, previsto, maior),
        })  # fmt: skip
    return saida


def metricas(real: np.ndarray, proj: np.ndarray) -> dict:
    return {
        "cobertura_conservadora": float(np.mean(real >= proj)),
        "wape": float(np.abs(real - proj).sum() / real.sum()),
        "vies": float(proj.sum() / real.sum() - 1),
    }


def projetar_v2(item: dict, k: float, percentil: float, horizonte: int):
    """Projeção semanal (central, conservadora) do v2 para o horizonte, ou None sem base."""
    fatias = estimar(item["proprias"], item["conjunto"], k, percentil)
    if fatias is None:
        return None
    semanas = horizonte // config.SIMULADOR_DIAS_POR_SEMANA
    previsto = item["previsto_semana"][:semanas]
    return fatias[0] * previsto, fatias[1] * previsto


def _agregar(itens: list[dict], funcao, horizonte: int) -> dict | None:
    reais, projs, eventos = [], [], 0
    semanas = horizonte // config.SIMULADOR_DIAS_POR_SEMANA
    for item in itens:
        proj = funcao(item, horizonte)
        if proj is None:
            continue
        reais.append(item["real_semana"][:semanas])
        projs.append(proj)
        eventos += 1
    if not eventos:
        return None
    real, proj = np.concatenate(reais), np.concatenate(projs)
    return {"eventos": eventos, "semanas": len(real), **metricas(real, proj)}


def escolher_k(itens: list[dict], percentil: float = 0.5) -> pd.DataFrame:
    """WAPE do v2 central por k, por grupo e juntos (maior horizonte). Sem gabarito."""
    horizonte = max(config.SIMULADOR_HORIZONTES_DIAS)
    linhas = []
    for k in config.SIMULADOR_K_GRADE:

        def central(item, hz, k=k):
            proj = projetar_v2(item, k, percentil, hz)
            return None if proj is None else proj[0]

        linha = {"k": k}
        for grupo in (*v1.GRUPOS, "todos"):
            sel = [i for i in itens if grupo == "todos" or i["evento"].grupo == grupo]
            r = _agregar(sel, central, horizonte)
            linha[f"wape_{grupo}"] = r["wape"] if r else np.nan
        linhas.append(linha)
    return pd.DataFrame(linhas)


def curva_percentil(itens: list[dict], k: float) -> pd.DataFrame:
    """Cobertura, WAPE e viés da fatia conservadora para cada percentil, por grupo e horizonte."""
    linhas = []
    for q in config.SIMULADOR_PERCENTIS_CURVA:
        for grupo in v1.GRUPOS:
            for horizonte in config.SIMULADOR_HORIZONTES_DIAS:
                sel = [i for i in itens if i["evento"].grupo == grupo]
                r = _agregar(
                    sel,
                    lambda i, hz, q=q: (lambda p: p[1] if p else None)(projetar_v2(i, k, q, hz)),
                    horizonte,
                )
                if r:
                    linhas.append(
                        {"percentil": q, "grupo": grupo, "horizonte_dias": horizonte, **r}
                    )
    return pd.DataFrame(linhas)


def escolher_percentil(curva: pd.DataFrame) -> float:
    """Percentil cuja cobertura nas trocas (maior horizonte) fica mais perto do alvo."""
    t = curva[
        (curva.grupo == "trocas") & (curva.horizonte_dias == max(config.SIMULADOR_HORIZONTES_DIAS))
    ]
    return float(
        t.loc[
            (t.cobertura_conservadora - config.SIMULADOR_COBERTURA_ALVO).abs().idxmin(), "percentil"
        ]
    )


def tabela_final(itens: list[dict], k: float, percentil: float) -> pd.DataFrame:
    """v2 central e conservador, o p25 diário atual e o ingênuo, por grupo e horizonte."""
    metodos = {
        "v2_central": lambda i, hz: (lambda p: p[0] if p else None)(
            projetar_v2(i, k, percentil, hz)
        ),
        "v2_conservador": lambda i, hz: (lambda p: p[1] if p else None)(
            projetar_v2(i, k, percentil, hz)
        ),
        "completo_p25_diario": lambda i, hz: _referencia(i, "completo", hz),
        "ingenuo": lambda i, hz: _referencia(i, "ingenuo", hz),
    }
    linhas = []
    for grupo in v1.GRUPOS:
        for nome, funcao in metodos.items():
            for horizonte in config.SIMULADOR_HORIZONTES_DIAS:
                sel = [i for i in itens if i["evento"].grupo == grupo]
                r = _agregar(sel, funcao, horizonte)
                if r:
                    linhas.append(
                        {"grupo": grupo, "metodo": nome, "horizonte_dias": horizonte, **r}
                    )
    return pd.DataFrame(linhas)


def _referencia(item: dict, metodo: str, horizonte: int):
    proj = item["referencia"].get(metodo)
    return None if proj is None else _semanas(proj[:horizonte])


def correlacao_fatia(
    sem: Semanal, conexao: psycopg.Connection, gabarito: pd.DataFrame, k: float
) -> dict:
    """Fatia encolhida (relativa à dos colegas lotados) x habilidade verdadeira. Só análise."""
    h = sem.h
    ref = h.fim
    linhas = []
    for (sk, setor), periodos in h.periodos.items():
        if not any(ini <= pd.Timestamp(ref) <= fim for ini, fim in periodos):
            continue  # só quem está lotado no setor na referência
        proprias = sem.observacoes(sk, setor, ref)
        if len(proprias) < config.SIMULADOR_SEMANAS_CORRELACAO:
            continue
        conjunto = sem.conjunto(int(h.cadastro.loc[sk, "sk_loja"]), setor, ref, sk)
        if not len(conjunto):
            continue
        media = float(conjunto.mean())
        n = len(proprias)
        encolhida = (n * proprias.mean() + k * media) / (n + k)
        cod = h.cadastro.loc[sk, "cod_vendedor"]
        linhas.append(
            {"cod_vendedor": cod, "setor": setor, "relativa": encolhida / media,
             "bruta": proprias.mean() / media}
        )  # fmt: skip
    d = pd.DataFrame(linhas).merge(gabarito, on=["cod_vendedor", "setor"])
    return {
        "pares": len(d),
        "pearson": float(d.relativa.corr(d.habilidade)),
        "spearman": float(d.relativa.rank().corr(d.habilidade.rank())),
        "pearson_sem_encolher": float(d.bruta.corr(d.habilidade)),
    }


def k_escolhido(tabela_k: pd.DataFrame) -> float:
    """O maior k cujo WAPE (trocas e placebo juntos) fica até a tolerância do menor WAPE."""
    menor = tabela_k.wape_todos.min()
    return float(tabela_k[tabela_k.wape_todos <= menor + config.SIMULADOR_TOLERANCIA_K].k.max())


def gravar(
    conexao: psycopg.Connection,
    tabela: pd.DataFrame,
    curva: pd.DataFrame,
    k: float,
    percentil: float,
) -> int:
    """Substitui as linhas v2 de dw.simulador_backtest e a curva (idempotente)."""
    conexao.execute("DELETE FROM dw.simulador_backtest WHERE versao = 'v2'")
    conexao.execute("DELETE FROM dw.simulador_backtest_curva")
    with conexao.cursor() as cur:
        cur.executemany(
            "INSERT INTO dw.simulador_backtest (versao, grupo, metodo, horizonte_dias, eventos,"
            " semanas, cobertura_conservadora, wape, vies, k, percentil)"
            " VALUES ('v2', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [
                (r.grupo, r.metodo, int(r.horizonte_dias), int(r.eventos), int(r.semanas),
                 round(r.cobertura_conservadora, 4), round(r.wape, 4), round(r.vies, 4),
                 k if r.metodo.startswith("v2") else None,
                 percentil if r.metodo == "v2_conservador" else None)
                for r in tabela.itertuples()
            ],
        )  # fmt: skip
        cur.executemany(
            "INSERT INTO dw.simulador_backtest_curva (grupo, horizonte_dias, percentil, k, eventos,"
            " semanas, cobertura_conservadora, wape, vies)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [
                (r.grupo, int(r.horizonte_dias), round(r.percentil, 2), k, int(r.eventos),
                 int(r.semanas), round(r.cobertura_conservadora, 4), round(r.wape, 4),
                 round(r.vies, 4))
                for r in curva.itertuples()
            ],
        )  # fmt: skip
    conexao.commit()
    return len(tabela)
