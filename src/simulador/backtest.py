"""Backtest do simulador de troca de setor.

Para cada troca real (e para um grupo placebo, sem troca) volta ao dia anterior, calcula o que o
simulador teria projetado para o vendedor no setor de destino e compara, semana a semana, com o
que ele de fato vendeu. Só usa o que se sabia na origem: histórico até o dia anterior e a
previsão da decomposição treinada até ali.
"""

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd
import psycopg

from src import config
from src.previsao import dados, modelos

METODOS = ("completo", "completo_central", "so_fallback", "so_proprio", "ingenuo")
GRUPOS = ("trocas", "placebo")


@dataclass(frozen=True)
class Evento:
    grupo: str
    sk_vendedor: int
    sk_loja: int
    setor_origem: str
    setor_destino: str
    inicio: date  # primeiro dia projetado (o dia da troca)

    @property
    def origem(self) -> date:
        return self.inicio - timedelta(days=1)


@dataclass(frozen=True)
class Parametros:
    janela_dias: int
    minimo_dias: int
    percentil: float


class Historico:
    """Tudo o que o backtest lê do dw, em memória (vendas diárias por vendedor e setor)."""

    def __init__(self, conexao: psycopg.Connection):
        def lido(sql):
            cur = conexao.execute(sql)
            return pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])

        self.parametros = Parametros(
            int(conexao.execute("SELECT etl.parametro('simulador_janela_dias')").fetchone()[0]),
            int(conexao.execute("SELECT etl.parametro('simulador_min_dias_historico')")
                .fetchone()[0]),
            float(conexao.execute("SELECT etl.parametro('simulador_percentil')").fetchone()[0]),
        )  # fmt: skip
        status = config.STATUS_VENDA_VALIDA
        vendas = lido(
            "SELECT v.sk_vendedor, p.setor, t.data, sum(v.receita_liquida) AS valor"
            " FROM dw.fato_vendas v JOIN dw.dim_tempo t USING (sk_tempo)"
            f" JOIN dw.dim_produto p USING (sk_produto) WHERE v.status = '{status}'"
            " GROUP BY v.sk_vendedor, p.setor, t.data"
        )
        vendas["data"] = pd.to_datetime(vendas["data"])
        vendas["valor"] = vendas["valor"].astype(float)
        self.vendas = {
            chave: g.set_index("data")["valor"].sort_index()
            for chave, g in vendas.groupby(["sk_vendedor", "setor"])
        }
        dias = lido(
            "SELECT DISTINCT v.sk_loja, t.data FROM dw.fato_vendas v"
            f" JOIN dw.dim_tempo t USING (sk_tempo) WHERE v.status = '{status}'"
        )
        self.dias_da_loja = {
            int(loja): pd.DatetimeIndex(pd.to_datetime(g["data"])).sort_values()
            for loja, g in dias.groupby("sk_loja")
        }
        cadastro = lido(
            "SELECT sk_vendedor, cod_vendedor, sk_loja, data_admissao, data_desligamento"
            " FROM dw.dim_vendedor"
        )
        self.cadastro = cadastro.set_index("sk_vendedor")
        self.vendedores_da_loja = {
            int(loja): list(g["sk_vendedor"]) for loja, g in cadastro.groupby("sk_loja")
        }
        lotacao = lido(
            "SELECT sk_vendedor, setor, data_inicio, data_fim, motivo"
            " FROM dw.vendedor_setor_historico ORDER BY sk_vendedor, data_inicio"
        )
        self.lotacao = lotacao
        self.periodos = {
            (int(v), s): [
                (pd.Timestamp(r.data_inicio),
                 pd.Timestamp(r.data_fim) if r.data_fim is not None else pd.Timestamp.max)
                for r in g.itertuples()
            ]
            for (v, s), g in lotacao.groupby(["sk_vendedor", "setor"])
        }  # fmt: skip
        inicio, fim = dados.primeiro_dia_com_venda(conexao), dados.ultimo_dia_com_venda(conexao)
        self.fim = fim
        self.painel = dados.ler_painel(conexao, inicio, fim)

    # --- séries como o dw as mede (dias lotado, loja aberta, vendedor ativo) -------------------
    def ativo_em(self, sk_vendedor: int, dia: date) -> bool:
        c = self.cadastro.loc[sk_vendedor]
        desligamento = c["data_desligamento"]
        return c["data_admissao"] <= dia and (desligamento is None or desligamento > dia)

    def serie(self, sk_vendedor: int, setor: str, origem: date, janela: int | None = None):
        """Venda diária do vendedor no setor, nos dias lotado até `origem` (zeros incluídos)."""
        janela = janela or self.parametros.janela_dias
        c = self.cadastro.loc[sk_vendedor]
        abertos = self.dias_da_loja[int(c["sk_loja"])]
        fim = pd.Timestamp(origem)
        dias = abertos[(abertos > fim - pd.Timedelta(days=janela)) & (abertos <= fim)]
        dias = dias[dias >= pd.Timestamp(c["data_admissao"])]
        if c["data_desligamento"] is not None:
            dias = dias[dias < pd.Timestamp(c["data_desligamento"])]
        lotado = np.zeros(len(dias), dtype=bool)
        for ini, fim_p in self.periodos.get((sk_vendedor, setor), []):
            lotado |= (dias >= ini) & (dias <= fim_p)
        dias = dias[lotado]
        vendas = self.vendas.get((sk_vendedor, setor))
        if vendas is None:
            return np.zeros(len(dias))
        return vendas.reindex(dias, fill_value=0.0).to_numpy()

    def estatistica(self, sk_vendedor: int, setor: str, origem: date):
        s = self.serie(sk_vendedor, setor, origem)
        if len(s) == 0:
            return 0, None, None
        return len(s), float(np.percentile(s, self.parametros.percentil * 100)), float(s.mean())

    def fallback(self, sk_loja: int, setor: str, origem: date, excluir: int):
        """(p25 médio, média média) de quem tem histórico suficiente na loja; senão, na rede."""

        def medio(lojas):
            p25, media = [], []
            for loja in lojas:
                do_p25, da_media = [], []
                for v in self.vendedores_da_loja.get(loja, []):
                    if v == excluir or not self.ativo_em(v, origem + timedelta(days=1)):
                        continue
                    n, q, m = self.estatistica(v, setor, origem)
                    if n >= self.parametros.minimo_dias:
                        do_p25.append(q)
                        da_media.append(m)
                if do_p25:
                    p25.append(np.mean(do_p25))
                    media.append(np.mean(da_media))
            return (np.mean(p25), np.mean(media)) if p25 else None

        da_loja = medio([sk_loja])
        return da_loja or medio(self.vendedores_da_loja)

    def media_dos_outros(self, sk_loja: int, setor: str, origem: date, excluir: int) -> float:
        total = 0.0
        for v in self.vendedores_da_loja.get(sk_loja, []):
            if v == excluir or not self.ativo_em(v, origem + timedelta(days=1)):
                continue
            n, _, m = self.estatistica(v, setor, origem)
            total += m if n else 0.0
        return total

    def media_loja_setor(self, sk_loja: int, setor: str, origem: date) -> float | None:
        painel = self.painel.ate(origem)
        if (sk_loja, setor) not in painel.chaves:
            return None
        valores = painel.valores[painel.chaves.index((sk_loja, setor))]
        janela = self.parametros.janela_dias
        abertos = self.dias_da_loja[sk_loja]
        n_abertos = ((abertos > pd.Timestamp(origem) - pd.Timedelta(days=janela))
                     & (abertos <= pd.Timestamp(origem))).sum()  # fmt: skip
        return float(np.nansum(valores[-janela:]) / n_abertos) if n_abertos else None

    def real(self, sk_vendedor: int, setor: str, inicio: date, dias: int) -> np.ndarray:
        indice = pd.date_range(inicio, periods=dias, freq="D")
        vendas = self.vendas.get((sk_vendedor, setor))
        if vendas is None:
            return np.zeros(dias)
        return vendas.reindex(indice, fill_value=0.0).to_numpy()


# --- eventos ----------------------------------------------------------------------------------
def eventos_de_troca(h: Historico) -> list[Evento]:
    saida = []
    for sk, g in h.lotacao.groupby("sk_vendedor"):
        g = g.sort_values("data_inicio").reset_index(drop=True)
        for k in range(1, len(g)):
            if g.loc[k, "motivo"] == config.SIMULADOR_MOTIVO_TROCA:
                saida.append(
                    Evento("trocas", int(sk), int(h.cadastro.loc[sk, "sk_loja"]),
                           g.loc[k - 1, "setor"], g.loc[k, "setor"], g.loc[k, "data_inicio"])
                )  # fmt: skip
    return saida


def eventos_placebo(h: Historico, quantos: int, trocas: list[Evento]) -> list[Evento]:
    """Vendedores que nunca trocaram, numa data sorteada da janela das trocas: o 'destino' é o
    setor onde já trabalham."""
    rng = np.random.default_rng(config.SIMULADOR_SEMENTE_PLACEBO)
    quem_trocou = {e.sk_vendedor for e in trocas}
    inicio, fim = config.LOTACAO_JANELA_TROCAS
    candidatos = [v for v in sorted(h.cadastro.index) if v not in quem_trocou]
    rng.shuffle(candidatos)
    saida = []
    for v in candidatos:
        if len(saida) == quantos:
            break
        dia = inicio + timedelta(days=int(rng.integers(0, (fim - inicio).days + 1)))
        periodos = h.lotacao[h.lotacao.sk_vendedor == v]
        atual = periodos[
            (periodos.data_inicio <= dia)
            & (periodos.data_fim.isna() | (periodos.data_fim >= dia))
        ]  # fmt: skip
        if atual.empty:
            continue
        setor = atual.iloc[0]["setor"]
        loja = int(h.cadastro.loc[v, "sk_loja"])
        n, _, _ = h.estatistica(v, setor, dia - timedelta(days=1))
        if n >= config.SIMULADOR_MIN_DIAS_PLACEBO:
            saida.append(Evento("placebo", v, loja, setor, setor, dia))
    return saida


# --- projeção ---------------------------------------------------------------------------------
def projetar(h: Historico, e: Evento, previsto: np.ndarray, dias: int) -> dict[str, np.ndarray]:
    """Projeção diária de cada método para os `dias` seguintes à origem do evento."""
    p = h.parametros
    n_proprio, p25, media = h.estatistica(e.sk_vendedor, e.setor_destino, e.origem)
    fb = h.fallback(e.sk_loja, e.setor_destino, e.origem, e.sk_vendedor)
    ml = h.media_loja_setor(e.sk_loja, e.setor_destino, e.origem)
    outros = h.media_dos_outros(e.sk_loja, e.setor_destino, e.origem, e.sk_vendedor)
    saida: dict[str, np.ndarray] = {}
    if ml and ml > 0 and np.isfinite(previsto[:dias]).all():
        fator = previsto[:dias] / ml
        teto = np.maximum(previsto[:dias] - outros * fator, 0.0)

        def com_teto(base):
            return np.minimum(base * fator, teto)

        tem_proprio = n_proprio >= p.minimo_dias
        if tem_proprio or fb:
            saida["completo"] = com_teto(p25 if tem_proprio else fb[0])
            saida["completo_central"] = com_teto(media if tem_proprio else fb[1])
        if fb:
            saida["so_fallback"] = com_teto(fb[0])
        if tem_proprio:
            saida["so_proprio"] = com_teto(p25)
    n_origem = h.serie(e.sk_vendedor, e.setor_origem, e.origem, config.SIMULADOR_DIAS_NAIVE)
    if len(n_origem):
        saida["ingenuo"] = np.full(dias, float(n_origem.mean()))
    return saida


def executar(h: Historico) -> pd.DataFrame:
    trocas = eventos_de_troca(h)
    eventos = trocas + eventos_placebo(h, len(trocas), trocas)
    maior = max(config.SIMULADOR_HORIZONTES_DIAS)
    semana = config.SIMULADOR_DIAS_POR_SEMANA
    previsoes: dict[date, np.ndarray] = {}
    acumulo: dict[tuple, list] = {}
    for e in eventos:
        if e.inicio + timedelta(days=maior - 1) > h.fim:
            continue
        desligamento = h.cadastro.loc[e.sk_vendedor, "data_desligamento"]
        if desligamento is not None and desligamento < e.inicio + timedelta(days=maior):
            continue
        if e.origem not in previsoes:
            alvo = pd.date_range(e.inicio, periods=maior, freq="D")
            previsoes[e.origem] = modelos.prever_decomposicao(h.painel.ate(e.origem), alvo)
        chaves = h.painel.chaves
        if (e.sk_loja, e.setor_destino) not in chaves:
            continue
        previsto = previsoes[e.origem][chaves.index((e.sk_loja, e.setor_destino))]
        projecoes = projetar(h, e, previsto, maior)
        real = h.real(e.sk_vendedor, e.setor_destino, e.inicio, maior)
        for metodo, proj in projecoes.items():
            for horizonte in config.SIMULADOR_HORIZONTES_DIAS:
                r = real[:horizonte].reshape(-1, semana).sum(axis=1)
                q = proj[:horizonte].reshape(-1, semana).sum(axis=1)
                acumulo.setdefault((e.grupo, metodo, horizonte), []).append((r, q))
    linhas = []
    for (grupo, metodo, horizonte), pares in sorted(acumulo.items()):
        r = np.concatenate([a for a, _ in pares])
        q = np.concatenate([b for _, b in pares])
        linhas.append(
            {"grupo": grupo, "metodo": metodo, "horizonte_dias": horizonte,
             "eventos": len(pares), "semanas": len(r),
             "cobertura_conservadora": float(np.mean(r >= q)),
             "wape": float(np.abs(r - q).sum() / r.sum()),
             "vies": float(q.sum() / r.sum() - 1)}
        )  # fmt: skip
    return pd.DataFrame(linhas)


# --- habilidade verdadeira (só análise: o gabarito nunca entra na produção) -----------------
def correlacao_com_habilidade(conexao: psycopg.Connection, gabarito: pd.DataFrame) -> dict:
    """Compara a habilidade que o dw consegue estimar (venda média do vendedor no setor, relativa
    à dos colegas lotados no mesmo setor e loja) com a habilidade verdadeira do gerador."""
    cur = conexao.execute(
        "SELECT v.cod_vendedor, d.sk_loja, d.setor, d.media_diaria, d.p25_diaria"
        " FROM dw.desempenho_vendedor_setor d JOIN dw.dim_vendedor v USING (sk_vendedor)"
        " WHERE d.data_referencia = (SELECT max(data_referencia) FROM dw.desempenho_vendedor_setor)"
        " AND d.dias_lotado >= %s",
        (config.SIMULADOR_DIAS_CONFIANCA_CORRELACAO,),
    )
    d = pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])
    d["media_diaria"] = d["media_diaria"].astype(float)
    d["p25_diaria"] = d["p25_diaria"].astype(float)
    colegas = d.groupby(["sk_loja", "setor"])["media_diaria"].transform("mean")
    d["relativa"] = d["media_diaria"] / colegas
    d = d.merge(gabarito, on=["cod_vendedor", "setor"])
    d["habilidade"] = d["habilidade"].astype(float)
    return {
        "pares": len(d),
        "pearson": float(d["relativa"].corr(d["habilidade"])),
        "spearman": float(d["relativa"].rank().corr(d["habilidade"].rank())),
        "pearson_p25": float(d["p25_diaria"].corr(d["habilidade"])),
    }


def gravar(conexao: psycopg.Connection, resultado: pd.DataFrame) -> int:
    """Substitui o conteúdo de dw.simulador_backtest pelo resultado (idempotente)."""
    conexao.execute("DELETE FROM dw.simulador_backtest")
    with conexao.cursor() as cur:
        cur.executemany(
            "INSERT INTO dw.simulador_backtest (grupo, metodo, horizonte_dias, eventos, semanas,"
            " cobertura_conservadora, wape, vies) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            [
                (r.grupo, r.metodo, int(r.horizonte_dias), int(r.eventos), int(r.semanas),
                 round(r.cobertura_conservadora, 4), round(r.wape, 4), round(r.vies, 4))
                for r in resultado.itertuples()
            ],
        )  # fmt: skip
    conexao.commit()
    return len(resultado)
