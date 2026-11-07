"""Simula e confere a calibração das metas de venda (SOMENTE LEITURA no dw: só SELECT).

Objetivo: mostrar, por nível (loja x setor x mês, loja x mês, vendedor x mês, dia da rede e rede x
mês), quanto das metas é batido pelas vendas realizadas, para verificar que as metas são o
"esperado" do período (meio a meio) e não um alvo otimista ou pessimista. A regra das metas está em
`src/gerador/metas.py` e é explicada em `docs/metodologia_metas.md`.

Dois modos:
  python scripts/simular_metas.py validar
      Confere as metas carregadas no dw (fato_meta_vendas e fato_meta_vendedor) e a meta diária da
      view `dw.vw_meta_vendas_diaria`. Também mostra dezembro/2025 até o dia 15.
  python scripts/simular_metas.py simular --esforco 0.00 0.01 0.02
      Recalcula as metas em memória com cada esforço (mesma função do gerador, vendas do dw como
      histórico e calendário comercial) e mostra os percentuais. Nada é gravado.

Os percentuais saem por ano: % de lojas-mês, setores-mês e vendedores-mês com cobertura >= 100%,
% de dias em que a rede bateu a meta do dia, meses com a rede acima da meta e cobertura média.
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from src import banco, calendario, config  # noqa: E402
from src.calendario_comercial import pesos_do_periodo  # noqa: E402
from src.gerador import metas as mod_metas  # noqa: E402
from src.gerador import vendas  # noqa: E402
from src.gerador.catalogo import montar_catalogo  # noqa: E402
from src.gerador.parametros import ParametrosGeracao, rng_para  # noqa: E402
from src.gerador.sazonalidade import Sazonalidade  # noqa: E402


def consulta(con, sql: str) -> pd.DataFrame:
    return pd.read_sql(sql, con)


def ler_realizado(con) -> dict[str, pd.DataFrame]:
    """Receita concluída do dw por loja x setor x mês, por vendedor x mês e por dia (rede)."""
    base = """FROM dw.fato_vendas f JOIN dw.dim_tempo t USING (sk_tempo)
              WHERE f.status = 'Concluída'"""
    return {
        "loja_setor": consulta(
            con,
            """SELECT make_date(t.ano, t.mes, 1) AS m, l.cod_loja, p.setor,
                       SUM(f.receita_liquida)::float AS r
                FROM dw.fato_vendas f JOIN dw.dim_tempo t USING (sk_tempo)
                JOIN dw.dim_produto p USING (sk_produto) JOIN dw.dim_loja l USING (sk_loja)
                WHERE f.status = 'Concluída' GROUP BY 1, 2, 3""",
        ),
        "vendedor": consulta(
            con,
            """SELECT make_date(t.ano, t.mes, 1) AS m, v.cod_vendedor,
                       SUM(f.receita_liquida)::float AS r
                FROM dw.fato_vendas f JOIN dw.dim_tempo t USING (sk_tempo)
                JOIN dw.dim_vendedor v USING (sk_vendedor)
                WHERE f.status = 'Concluída' GROUP BY 1, 2""",
        ),
        "dia": consulta(
            con, f"SELECT t.data, SUM(f.receita_liquida)::float AS r {base} GROUP BY 1"
        ),
    }


def percentual(serie: pd.Series) -> float:
    return 100 * float(serie.mean())


def avaliar(
    metas_ls: pd.DataFrame, metas_v: pd.DataFrame, meta_dia: pd.DataFrame, real: dict
) -> pd.DataFrame:
    """Uma linha por mês com o percentual de batimento em cada nível e a cobertura da rede."""
    for df in (metas_ls, metas_v, real["loja_setor"], real["vendedor"]):
        df["m"] = pd.to_datetime(df.pop("competencia") if "competencia" in df else df["m"])
    ls = metas_ls.merge(real["loja_setor"], on=["m", "cod_loja", "setor"], how="left")
    ls = ls.fillna({"r": 0})
    lj = ls.groupby(["m", "cod_loja"])[["valor_meta", "r"]].sum().reset_index()
    vd = metas_v.merge(real["vendedor"], on=["m", "cod_vendedor"], how="left").fillna({"r": 0})
    dd = meta_dia.merge(real["dia"], on="data", how="left").fillna({"r": 0})
    dd["m"] = pd.to_datetime(dd["data"]).dt.to_period("M").dt.to_timestamp()
    rede = ls.groupby("m")[["valor_meta", "r"]].sum()
    return pd.DataFrame(
        {
            "setores": ls.groupby("m").apply(lambda g: percentual(g["r"] >= g["valor_meta"])),
            "lojas": lj.groupby("m").apply(lambda g: percentual(g["r"] >= g["valor_meta"])),
            "vendedores": vd.groupby("m").apply(lambda g: percentual(g["r"] >= g["valor_meta"])),
            "dias": dd.groupby("m").apply(lambda g: percentual(g["r"] >= g["valor_meta_dia"])),
            "cobertura_rede": 100 * rede["r"] / rede["valor_meta"],
        }
    )


def resumo_por_ano(mensal: pd.DataFrame) -> pd.DataFrame:
    linhas = []
    for ano, g in mensal.groupby(mensal.index.year):
        linhas.append(
            {
                "ano": ano,
                "lojas_%": round(g["lojas"].mean()),
                "setores_%": round(g["setores"].mean()),
                "vendedores_%": round(g["vendedores"].mean()),
                "dias_%": round(g["dias"].mean()),
                "meses_rede_acima": f"{int((g['cobertura_rede'] >= 100).sum())}/{len(g)}",
                "cobertura_media_rede_%": round(g["cobertura_rede"].mean(), 1),
            }
        )
    return pd.DataFrame(linhas)


def validar(con) -> None:
    real = ler_realizado(con)
    metas_ls = consulta(
        con,
        """SELECT make_date(t.ano, t.mes, 1) AS m, l.cod_loja, f.setor,
                  f.valor_meta::float AS valor_meta
           FROM dw.fato_meta_vendas f JOIN dw.dim_tempo t USING (sk_tempo)
           JOIN dw.dim_loja l USING (sk_loja)""",
    )
    metas_v = consulta(
        con,
        """SELECT make_date(t.ano, t.mes, 1) AS m, v.cod_vendedor, f.valor_meta::float AS valor_meta
           FROM dw.fato_meta_vendedor f JOIN dw.dim_tempo t USING (sk_tempo)
           JOIN dw.dim_vendedor v USING (sk_vendedor)""",
    )
    meta_dia = consulta(
        con,
        """SELECT data, SUM(valor_meta_dia)::float AS valor_meta_dia
           FROM dw.vw_meta_vendas_diaria GROUP BY 1""",
    )
    mensal = avaliar(metas_ls.copy(), metas_v.copy(), meta_dia, real)
    print("\n== Metas carregadas no dw: batimento mensal (%) ==")
    print(mensal.round(1).to_string())
    print("\n== Resumo por ano ==")
    print(resumo_por_ano(mensal).to_string(index=False))
    quinzena(con, real)


def quinzena(con, real: dict) -> None:
    """Dezembro/2025 até o dia 15: lojas acima da meta e cobertura da rede."""
    meta = consulta(
        con,
        """SELECT l.cod_loja, l.nome_loja, SUM(m.valor_meta_dia)::float AS meta
           FROM dw.vw_meta_vendas_diaria m JOIN dw.dim_loja l USING (sk_loja)
           WHERE m.data BETWEEN '2025-12-01' AND '2025-12-15' GROUP BY 1, 2""",
    )
    venda = consulta(
        con,
        """SELECT l.cod_loja, SUM(f.receita_liquida)::float AS r
           FROM dw.fato_vendas f JOIN dw.dim_tempo t USING (sk_tempo)
           JOIN dw.dim_loja l USING (sk_loja)
           WHERE f.status = 'Concluída'
             AND t.data BETWEEN '2025-12-01' AND '2025-12-15' GROUP BY 1""",
    )
    q = meta.merge(venda, on="cod_loja")
    q["cobertura_%"] = (100 * q["r"] / q["meta"]).round(1)
    print("\n== Dez/2025 até o dia 15 ==")
    print(q[["nome_loja", "cobertura_%"]].sort_values("cobertura_%").to_string(index=False))
    print(
        f"lojas acima da meta: {(q['cobertura_%'] >= 100).sum()} de {len(q)} | "
        f"rede: {100 * q['r'].sum() / q['meta'].sum():.1f}%"
    )
    dia = consulta(
        con,
        """SELECT data, SUM(valor_meta_dia)::float AS meta FROM dw.vw_meta_vendas_diaria
           WHERE data BETWEEN '2025-12-01' AND '2025-12-15' GROUP BY 1""",
    ).merge(real["dia"], on="data")
    acima = (dia["r"] >= dia["meta"]).sum()
    print(f"dias da rede acima da meta (1 a 15/12): {acima} de {len(dia)}")


def simular(con, esforcos: list[float]) -> None:
    params = ParametrosGeracao()
    cat = montar_catalogo(params.semente, params.data_inicio, params.data_fim)
    sazon = Sazonalidade(params.data_inicio, params.data_fim)
    meses = calendario.meses_do_periodo(params.data_inicio, params.data_fim)
    pesos = {m: vendas.pesos_do_mes(sazon, cat, *m, params) for m in meses}
    soma_pesos = [float(pesos[m][1].sum()) for m in meses]
    itens = vendas.distribuir_linhas(params.total_linhas_venda, soma_pesos)
    esperado = mod_metas.esperado_estrutural(cat, sazon, meses, pesos, itens)
    real = ler_realizado(con)
    receita_ls = {
        (r.cod_loja, r.setor, r.m.year, r.m.month): r.r for r in real["loja_setor"].itertuples()
    }
    receita_v = {(r.cod_vendedor, r.m.year, r.m.month): r.r for r in real["vendedor"].itertuples()}
    pc = pesos_do_periodo(params.data_inicio, params.data_fim)
    pc["m"] = pd.to_datetime(pc["data"]).dt.to_period("M").dt.to_timestamp()
    pc["fracao"] = pc["peso"] / pc.groupby(["m", "setor"])["peso"].transform("sum")
    original = config.ESFORCO_META
    try:
        for esforco in esforcos:
            config.ESFORCO_META = esforco
            ls = mod_metas.gerar_metas(
                cat, sazon, meses, esperado, receita_ls,
                rng_para(params.semente, config.FLUXO_METAS),
                (params.data_inicio, params.data_fim),
            )  # fmt: skip
            mv = mod_metas.gerar_metas_vendedor(cat, ls, receita_v, meses)
            ls["m"] = pd.to_datetime(ls["competencia"])
            dia = ls.merge(pc, on=["m", "setor"])
            dia["valor_meta_dia"] = dia["valor_meta"] * dia["fracao"]
            meta_dia = dia.groupby("data")["valor_meta_dia"].sum().reset_index()
            meta_dia["data"] = pd.to_datetime(meta_dia["data"])
            real_dia = real["dia"].assign(data=lambda d: pd.to_datetime(d["data"]))
            mensal = avaliar(ls.copy(), mv.copy(), meta_dia, {**real, "dia": real_dia})
            print(f"\n== Esforço {esforco:+.1%} ==")
            print(resumo_por_ano(mensal).to_string(index=False))
    finally:
        config.ESFORCO_META = original


def principal() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="modo", required=True)
    sub.add_parser("validar", help="confere as metas carregadas no dw")
    s = sub.add_parser("simular", help="recalcula as metas em memória para cada esforço")
    s.add_argument("--esforco", type=float, nargs="+", default=[config.ESFORCO_META])
    args = parser.parse_args()
    with banco.conectar() as con:
        con.read_only = True
        if args.modo == "validar":
            validar(con)
        else:
            simular(con, args.esforco)


if __name__ == "__main__":
    principal()
