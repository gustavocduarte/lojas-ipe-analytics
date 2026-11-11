"""Consistência entre a previsão gravada em `dw.previsao_vendas` e o modelo atual.

Para cada corte (`treino_ate`) com previsão vigente (`dw.vw_previsao_vigente`), refaz em memória a
previsão do mesmo horizonte com o modelo atual, só com o painel até o corte (o mesmo caminho do
`montar_cortes` da probabilidade: `prever(painel.ate(corte), alvo)` e `np.maximum(..., 0)`), e
compara o previsto por loja e mês (e o total da rede) com o gravado. Um corte gravado com outra
versão do modelo, ou com outro painel, aparece como divergência.

A tolerância é de R$ 0,01 por loja (a da rede é a soma das tolerâncias das lojas): ela NÃO deve ser
aumentada para fazer o teste passar. O recalculado arredonda cada série-dia com as mesmas casas da
gravação (`CASAS_PREVISAO`) antes de somar, para comparar igual com igual; qualquer diferença que
sobrar é reportada com o caso, para decisão humana.
"""

from collections.abc import Callable

import numpy as np
import pandas as pd
import psycopg

from src import config
from src.previsao.modelos import MODELOS, versao_do_modelo
from src.previsao.painel import Painel

TOLERANCIA_POR_LOJA = 0.01
COLUNAS = [
    "corte", "versao_gravada", "versao_atual", "nivel", "sk_loja", "mes", "resto_do_mes",
    "gravado", "recalculado", "dif", "tolerancia", "ok",
]  # fmt: skip

CONSULTA_GRAVADO = """
    SELECT treino_ate, versao_modelo, data, sk_loja, setor, valor_previsto::float8
    FROM dw.vw_previsao_vigente
    WHERE nivel = 'loja_setor' AND granularidade = 'dia'
"""


def ler_gravado(conexao: psycopg.Connection) -> pd.DataFrame:
    linhas = conexao.execute(CONSULTA_GRAVADO).fetchall()
    return pd.DataFrame(
        linhas,
        columns=["treino_ate", "versao_modelo", "data", "sk_loja", "setor", "valor_previsto"],
    )


def _recalcular(
    painel: Painel, corte: pd.Timestamp, datas: pd.DatetimeIndex, modelo
) -> pd.DataFrame:
    """Previsto atual (série x dia) do corte: séries sem previsão completa ficam de fora, como em
    `geracao.gerar`."""
    bruto = modelo(painel.ate(corte.date()), datas)
    previsiveis = np.isfinite(bruto).all(axis=1)
    # igual com igual: cada série-dia é arredondada como na gravação, ANTES de somar
    previsto = np.round(np.maximum(bruto[previsiveis], 0.0), config.CASAS_PREVISAO)
    chaves = [c for c, ok in zip(painel.chaves, previsiveis, strict=True) if ok]
    return pd.DataFrame(
        {
            "sk_loja": np.repeat([loja for loja, _ in chaves], len(datas)),
            "data": np.tile(datas.to_numpy(), len(chaves)),
            "valor": previsto.ravel(),
        }
    )


def _por_loja_e_mes(df: pd.DataFrame, coluna: str) -> pd.Series:
    mes = pd.to_datetime(df["data"]).dt.to_period("M").dt.to_timestamp()
    return df.groupby([df["sk_loja"], mes])[coluna].sum()


def comparar(
    gravado: pd.DataFrame,
    painel: Painel,
    *,
    modelo: Callable | None = None,
    versao_atual: str | None = None,
    tolerancia: float = TOLERANCIA_POR_LOJA,
) -> pd.DataFrame:
    """Uma linha por corte, loja (e rede) e mês do horizonte gravado: gravado, recalculado, dif."""
    modelo = modelo or MODELOS[config.PROB_MODELO]
    versao_atual = versao_atual or versao_do_modelo(config.PROB_MODELO)
    linhas = []
    for (corte, versao), g in gravado.groupby(["treino_ate", "versao_modelo"]):
        corte = pd.Timestamp(corte)
        datas = pd.DatetimeIndex(sorted(pd.to_datetime(g["data"]).unique()))
        novo = _recalcular(painel, corte, datas, modelo)
        mes_do_corte = (corte + pd.Timedelta(days=1)).to_period("M").to_timestamp()
        grav = _por_loja_e_mes(g, "valor_previsto")
        reca = _por_loja_e_mes(novo, "valor")
        chaves = grav.index.union(reca.index)
        grav, reca = grav.reindex(chaves, fill_value=0.0), reca.reindex(chaves, fill_value=0.0)
        for (sk, mes), valor in grav.items():
            linhas.append((corte, versao, versao_atual, "loja", sk, mes, mes == mes_do_corte,
                           valor, reca[(sk, mes)], tolerancia))  # fmt: skip
        for mes in sorted({m for _, m in chaves}):
            lojas = [sk for sk, m in chaves if m == mes]
            linhas.append((corte, versao, versao_atual, "rede", None, mes, mes == mes_do_corte,
                           grav.xs(mes, level=1).sum(), reca.xs(mes, level=1).sum(),
                           tolerancia * len(lojas)))  # fmt: skip
    df = pd.DataFrame(
        linhas,
        columns=[c for c in COLUNAS if c not in ("dif", "ok")],
    )
    df["dif"] = df["gravado"] - df["recalculado"]
    df["ok"] = (df["dif"].abs() <= df["tolerancia"]) & (df["versao_gravada"] == df["versao_atual"])
    return df[COLUNAS]


def verificar(
    conexao: psycopg.Connection, painel: Painel, *, modelo: Callable | None = None,
    versao_atual: str | None = None, tolerancia: float = TOLERANCIA_POR_LOJA,
) -> pd.DataFrame:  # fmt: skip
    return comparar(
        ler_gravado(conexao), painel, modelo=modelo, versao_atual=versao_atual,
        tolerancia=tolerancia,
    )  # fmt: skip


def relatorio(resultado: pd.DataFrame, maximo: int = 25) -> str:
    """Resumo por corte e, se houver divergência, os piores casos."""
    if resultado.empty:
        return "nenhuma previsão gravada para verificar"
    saida = []
    for (corte, versao), g in resultado.groupby(["corte", "versao_gravada"]):
        ruins = g[~g["ok"]]
        saida.append(
            f"corte {corte:%d/%m/%Y} ({versao}; atual {g['versao_atual'].iloc[0]}): "
            f"{len(g)} comparações, {len(ruins)} fora da tolerância; "
            f"maior |dif| = R$ {g['dif'].abs().max():,.2f}"
        )
    ruins = resultado[~resultado["ok"]].copy()
    if len(ruins):
        ruins["abs"] = ruins["dif"].abs()
        topo = ruins.sort_values("abs", ascending=False).head(maximo)
        saida.append("")
        saida.append("piores casos (gravado - recalculado):")
        for r in topo.itertuples():
            alvo = "rede" if r.nivel == "rede" else f"loja {int(r.sk_loja)}"
            saida.append(
                f"  {r.corte:%d/%m/%Y} {r.mes:%m/%Y} {alvo}: gravado {r.gravado:,.2f}, "
                f"recalculado {r.recalculado:,.2f}, dif {r.dif:+,.4f} "
                f"(tolerância {r.tolerancia:.2f})"
            )
    return "\n".join(saida)
