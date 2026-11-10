"""Relatório da probabilidade de bater a meta (contagens, calibração e validação por dia)."""

import pandas as pd

from src import config
from src.previsao.probabilidade import REDE
from src.previsao.probabilidade_cortes import resumo_sem_base
from src.previsao.probabilidade_execucao import ResultadoProbabilidade

ROTULO_FAIXA_DIAS = {0: "todas"} | {
    i + 1: f"{a}-{b} dias" for i, (a, b) in enumerate(config.PROB_FAIXAS_DIAS)
}


def _pct(x) -> str:
    return "   -  " if pd.isna(x) else f"{100 * x:5.1f}%"


def sem_base(r: ResultadoProbabilidade) -> list[str]:
    s = resumo_sem_base(r.cortes)
    linhas = [
        "Sem base (loja nova: série com menos de "
        f"{config.PREVISAO_DIAS_MINIMOS_SERIE} dias de venda no corte):",
        f"  cortes de loja: {s['cortes_loja']}; sem base: {s['cortes_loja_sem_base']}; "
        f"lojas afetadas: {len(s['lojas_afetadas'])}",
    ]
    for sk in s["lojas_afetadas"]:
        primeiro, ultimo = s["primeiro_ultimo_por_loja"][sk]
        linhas.append(
            f"    {r.nomes_lojas.get(sk, sk)}: {s['cortes_por_loja'][sk]} cortes "
            f"({primeiro:%d/%m/%Y} a {ultimo:%d/%m/%Y})"
        )
    linhas.append(
        f"  rede: {s['cortes_rede_com_loja_de_fora']} de {s['cortes_rede']} cortes com loja "
        "de fora da conta"
    )
    for esquema in config.PROB_ESQUEMAS:
        d = r.so_passado if esquema == "so_passado" else r.leave_one_month_out
        lojas = d[d["nivel"] == "loja"]
        motivos = lojas[lojas["probabilidade"].isna()].groupby("motivo_sem_base").size().to_dict()
        rede = d[d["nivel"] == "rede"]
        motivos_rede = (
            rede[rede["probabilidade"].isna()].groupby("motivo_sem_base").size().to_dict()
        )
        linhas.append(
            f"  [{esquema}] cortes sem probabilidade: lojas {motivos or 0}; "
            f"rede {motivos_rede or 0}"
        )
    return linhas


def curva(r: ResultadoProbabilidade, esquema: str, nivel: str, faixa_dias: int = 0) -> list[str]:
    c = r.calibracao
    c = c[(c["esquema"] == esquema) & (c["nivel"] == nivel) & (c["faixa_dias"] == faixa_dias)]
    resumo = c[c["tipo"] == "resumo"]
    if resumo.empty:
        return [f"{esquema} / {nivel} / {ROTULO_FAIXA_DIAS[faixa_dias]}: sem pontos"]
    s = resumo.iloc[0]
    linhas = [
        f"{esquema} / {nivel} / {ROTULO_FAIXA_DIAS[faixa_dias]}: n={int(s.n)} cortes, "
        f"{int(s.n_unidades)} (loja, mês) | Brier {s.brier:.4f} | 50% constante {s.brier_50:.4f} | "
        f"frequência histórica {s.brier_frequencia:.4f} | ECE {s.ece:.4f} | "
        f"previsto médio {_pct(s.previsto_medio)}, observado {_pct(s.observado)}",
        "  faixa       previsto  observado   n(cortes)  n(loja,mês)   IC90% do observado",
    ]
    for f in c[c["tipo"] == "faixa"].itertuples():
        linhas.append(
            f"  {100 * f.prob_inicio:3.0f}-{100 * f.prob_fim:3.0f}%   {_pct(f.previsto_medio)}   "
            f"{_pct(f.observado)}   {int(f.n):9d}  {int(f.n_unidades):10d}   "
            f"[{_pct(f.ic_baixo)} ; {_pct(f.ic_alto)}]"
        )
    return linhas


def validacao(
    r: ResultadoProbabilidade, de: pd.Timestamp, ate: pd.Timestamp, nomes: list[str]
) -> list[str]:
    """Dia a dia para a rede e as lojas pedidas: cobertura, projeção e P (esquema so_passado)."""
    d = r.so_passado
    sk_por_nome = {n: sk for sk, n in r.nomes_lojas.items()}
    linhas = []
    alvos = [("Rede", "rede", REDE)] + [
        (n, "loja", sk_por_nome[n]) for n in nomes if n in sk_por_nome
    ]
    for rotulo, nivel, sk in alvos:
        sub = d[(d["nivel"] == nivel) & (d["sk_loja"] == sk) & (d["corte"].between(de, ate))]
        if sub.empty:
            linhas.append(f"{rotulo}: sem cortes no período")
            continue
        meta = sub["meta"].iloc[0]
        real_mes = (sub["realizado_ate"] + sub["real_resto"]).iloc[0]
        linhas.append(
            f"{rotulo}  (meta do mês {meta:,.0f}; desfecho real do mês {real_mes:,.0f} = "
            f"{100 * real_mes / meta:.1f}% da meta, {'BATEU' if real_mes >= meta else 'NÃO bateu'})"
        )
        linhas.append("  dia    realizado/meta   projeção/meta   probabilidade")
        for x in sub.itertuples():
            cob = 100 * x.realizado_ate / x.meta if x.meta else float("nan")
            proj = 100 * x.projecao / x.meta if x.meta and pd.notna(x.projecao) else float("nan")
            p = (
                "  sem base (" + str(x.motivo_sem_base) + ")"
                if pd.isna(x.probabilidade)
                else _pct(x.probabilidade)
            )
            linhas.append(f"  {x.corte:%d/%m}   {cob:12.1f}%   {proj:12.1f}%   {p}")
    return linhas


def montar(
    r: ResultadoProbabilidade, *, detalhe: tuple | None = None, lojas: list[str] | None = None
) -> str:
    saida = [
        f"Probabilidade de bater a meta do mês: cortes de {r.inicio:%d/%m/%Y} a {r.fim:%d/%m/%Y} "
        f"({len(r.cortes)} linhas, {r.duracao_s:.0f} s)",
        "",
        *sem_base(r),
        "",
        "Confiabilidade (cortes avaliáveis: com probabilidade, mês fechado, meta não batida):",
    ]
    for esquema in config.PROB_ESQUEMAS:
        for nivel in ("loja", "rede"):
            saida += ["", *curva(r, esquema, nivel)]
    saida += ["", "Brier por faixa de dias que faltam (so_passado, loja):"]
    for fd in range(1, len(config.PROB_FAIXAS_DIAS) + 1):
        c = r.calibracao
        s = c[
            (c.esquema == "so_passado")
            & (c.nivel == "loja")
            & (c.faixa_dias == fd)
            & (c.tipo == "resumo")
        ]
        if len(s):
            x = s.iloc[0]
            saida.append(
                f"  {ROTULO_FAIXA_DIAS[fd]:>9}: n={int(x.n):5d}  Brier {x.brier:.4f}  "
                f"(50%: {x.brier_50:.4f}, frequência: {x.brier_frequencia:.4f})  ECE {x.ece:.4f}"
            )
    if detalhe:
        saida += [
            "",
            f"Validação {detalhe[0]:%d/%m/%Y} a {detalhe[1]:%d/%m/%Y} (esquema so_passado):",
        ]
        saida += validacao(r, pd.Timestamp(detalhe[0]), pd.Timestamp(detalhe[1]), lojas or [])
    return "\n".join(saida)
