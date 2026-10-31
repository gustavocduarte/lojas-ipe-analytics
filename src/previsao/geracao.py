"""Geração da previsão (dia e mês, com faixa) e gravação dela e do backtest no dw."""

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd
import psycopg

from src import config
from src.calendario import ultimo_dia_do_mes
from src.previsao import faixa as faixa_mod
from src.previsao import faixa_agregada as agregada_mod
from src.previsao.backtest import ResultadoBacktest
from src.previsao.modelos import MODELOS, versao_do_modelo
from src.previsao.painel import Painel

COLUNAS_PREVISAO = [
    "granularidade", "data", "sk_loja", "setor", "valor_previsto", "valor_baixo", "valor_alto",
    "wape_backtest",
]  # fmt: skip


@dataclass
class PrevisaoGerada:
    modelo: str
    versao: str
    treino_ate: date
    inicio: date
    fim: date
    linhas: pd.DataFrame  # COLUNAS_PREVISAO das séries (loja e setor), dia e mês juntos
    sem_previsao: list[tuple[int, str]] = field(
        default_factory=list
    )  # séries que o modelo não previu
    agregadas: pd.DataFrame = field(  # loja (soma dos setores) e rede, com faixa própria
        default_factory=lambda: pd.DataFrame(columns=["nivel", *COLUNAS_PREVISAO])
    )

    def mensal_da_rede(self) -> pd.DataFrame:
        """Previsto e faixa por mês previsto, no total da rede. A faixa é a calibrada no total da
        rede; sem ela (backtest sem faixa agregada) cai na soma das faixas de cada série."""
        colunas = ["valor_previsto", "valor_baixo", "valor_alto"]
        rede = self.agregadas[
            (self.agregadas["nivel"] == "rede") & (self.agregadas["granularidade"] == "mes")
        ]
        if len(rede):
            return rede.set_index("data")[colunas]
        meses = self.linhas[self.linhas["granularidade"] == "mes"]
        return meses.groupby("data")[colunas].sum()


def meses_completos(inicio: date, fim: date) -> list[date]:
    """Primeiro dia dos meses que estão inteiros dentro de [inicio, fim]."""
    meses = []
    ano, mes = inicio.year, inicio.month
    while date(ano, mes, 1) <= fim:
        primeiro = date(ano, mes, 1)
        if primeiro >= inicio and ultimo_dia_do_mes(ano, mes) <= fim:
            meses.append(primeiro)
        ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    return meses


def gerar(
    painel_treino: Painel, resultado: ResultadoBacktest, fim: date, *, modelos: dict | None = None
) -> PrevisaoGerada:
    """Prevê do dia seguinte ao fim do painel até `fim`, com o modelo e as faixas do backtest."""
    nome = resultado.escolhido
    treino_ate = painel_treino.datas[-1].date()
    alvo = pd.date_range(treino_ate + pd.Timedelta(days=1), fim, freq="D")
    inicio = alvo[0].date()
    bruto = (modelos or MODELOS)[nome](painel_treino, alvo)
    previsiveis = np.isfinite(bruto).all(axis=1)
    chaves = [c for c, ok in zip(painel_treino.chaves, previsiveis, strict=True) if ok]
    sem_previsao = [c for c, ok in zip(painel_treino.chaves, previsiveis, strict=True) if not ok]
    previsto = np.maximum(bruto[previsiveis], 0.0)
    setores = [setor for _, setor in chaves]

    partes = []
    baixo, alto = faixa_mod.aplicar_faixa(previsto, setores, resultado.faixas, "dia")
    partes.append(
        _linhas("dia", [d.date() for d in alvo], chaves, previsto, baixo, alto, resultado)
    )
    primeiros = meses_completos(inicio, fim)
    if primeiros:
        por_mes = {m: (alvo.year == m.year) & (alvo.month == m.month) for m in primeiros}
        mensal = np.stack([previsto[:, mask].sum(axis=1) for mask in por_mes.values()], axis=1)
        baixo_m, alto_m = faixa_mod.aplicar_faixa(mensal, setores, resultado.faixas, "mes")
        partes.append(_linhas("mes", primeiros, chaves, mensal, baixo_m, alto_m, resultado))
    agregadas = _linhas_agregadas(
        chaves, previsto, alvo, [(m, por_mes[m]) for m in primeiros] if primeiros else [], resultado
    )
    return PrevisaoGerada(
        nome, versao_do_modelo(nome), treino_ate, inicio, fim,
        pd.concat(partes, ignore_index=True), sem_previsao, agregadas,
    )  # fmt: skip


def _linhas_agregadas(chaves, previsto, alvo, meses, resultado) -> pd.DataFrame:
    """Linhas de nível "loja" (soma dos setores) e "rede" (soma de tudo), com a faixa calibrada no
    próprio total. `meses` = [(primeiro dia, máscara dos dias do mês)] dos meses completos."""
    lojas = np.array([loja for loja, _ in chaves])
    casas = config.CASAS_PREVISAO
    por_granularidade = [("dia", [d.date() for d in alvo], previsto)]
    if meses:
        mensal = np.stack([previsto[:, mask].sum(axis=1) for _, mask in meses], axis=1)
        por_granularidade.append(("mes", [m for m, _ in meses], mensal))
    partes = [pd.DataFrame(columns=COLUNAS_PREVISAO)]
    for granularidade, datas, matriz in por_granularidade:
        for nivel in ("rede", "loja"):
            faixa = resultado.faixas_agregadas.get((nivel, granularidade))
            if faixa is None:
                continue
            rotulos, somado = agregada_mod.agregar(matriz, lojas, nivel)
            baixo, alto = agregada_mod.aplicar(somado, faixa)
            n_datas = len(datas)
            wape = [resultado.wape_do_nivel(nivel, rotulo, granularidade) for rotulo in rotulos]
            partes.append(
                pd.DataFrame(
                    {
                        "nivel": nivel,
                        "granularidade": granularidade,
                        "data": np.tile(np.array(datas, dtype=object), len(rotulos)),
                        "sk_loja": np.repeat(np.array(rotulos, dtype=object), n_datas),
                        "setor": None,
                        "valor_previsto": np.round(somado.ravel(), casas),
                        "valor_baixo": np.round(baixo.ravel(), casas),
                        "valor_alto": np.round(alto.ravel(), casas),
                        "wape_backtest": np.round(
                            np.repeat(np.array(wape, dtype=float), n_datas), 4
                        ),
                    }
                )
            )
    return pd.concat(partes, ignore_index=True)[["nivel", *COLUNAS_PREVISAO]]


def _linhas(granularidade, datas, chaves, previsto, baixo, alto, resultado) -> pd.DataFrame:
    n_series, n_datas = previsto.shape
    lojas = np.repeat([loja for loja, _ in chaves], n_datas)
    setores = np.repeat([setor for _, setor in chaves], n_datas)
    wape_por_serie = [resultado.wape_da_serie(loja, setor, granularidade) for loja, setor in chaves]
    wape = np.repeat(np.array(wape_por_serie, dtype=float), n_datas)
    casas = config.CASAS_PREVISAO
    return pd.DataFrame(
        {
            "granularidade": granularidade,
            "data": np.tile(np.array(datas, dtype=object), n_series),
            "sk_loja": lojas,
            "setor": setores,
            "valor_previsto": np.round(previsto.ravel(), casas),
            "valor_baixo": np.round(baixo.ravel(), casas),
            "valor_alto": np.round(alto.ravel(), casas),
            "wape_backtest": np.round(wape, 4),
        }
    )[COLUNAS_PREVISAO]


def _copiar(conexao: psycopg.Connection, tabela: str, colunas: list[str], linhas) -> None:
    with conexao.cursor() as cursor:
        with cursor.copy(f"COPY {tabela} ({', '.join(colunas)}) FROM STDIN") as copia:
            for linha in linhas:
                copia.write_row(linha)


def _python(valor):
    """Converte numpy/NaN em tipos que o COPY entende (NaN vira NULL)."""
    if isinstance(valor, float | np.floating):
        return None if np.isnan(valor) else float(valor)
    if isinstance(valor, np.integer):
        return int(valor)
    return valor


def gravar_previsao(conexao: psycopg.Connection, previsao: PrevisaoGerada) -> int:
    """Substitui no dw a previsão deste modelo e deste corte. Devolve as linhas gravadas."""
    try:
        conexao.execute(
            "CREATE TEMP TABLE tmp_previsao_vendas (nivel VARCHAR(10), granularidade VARCHAR(3),"
            " data DATE,"
            " sk_loja INTEGER, setor VARCHAR(30), valor_previsto NUMERIC(14, 2),"
            " valor_baixo NUMERIC(14, 2), valor_alto NUMERIC(14, 2), wape_backtest NUMERIC(8, 4))"
            " ON COMMIT DROP"
        )
        todas = pd.concat(
            [previsao.linhas.assign(nivel="loja_setor"), previsao.agregadas], ignore_index=True
        )[["nivel", *COLUNAS_PREVISAO]]
        linhas = (_linha_previsao(linha) for linha in todas.itertuples(index=False, name=None))
        _copiar(conexao, "tmp_previsao_vendas", ["nivel", *COLUNAS_PREVISAO], linhas)
        conexao.execute("CALL dw.gravar_previsao(%s, %s)", (previsao.versao, previsao.treino_ate))
        conexao.commit()
    except Exception:
        conexao.rollback()
        raise
    return len(previsao.linhas)


def _linha_previsao(linha: tuple) -> list:
    """Uma linha da previsão para o COPY: vazios viram NULL e a loja volta a ser inteira."""
    valores = [None if pd.isna(v) else _python(v) for v in linha]
    if valores[3] is not None:  # sk_loja
        valores[3] = int(valores[3])
    return valores


def linhas_do_backtest(resultado: ResultadoBacktest) -> pd.DataFrame:
    """Métricas do backtest no formato de dw.previsao_backtest (cobertura: modelo escolhido)."""
    m = resultado.metricas.copy()
    c = resultado.cobertura_agregada
    cobertura = {}
    if not c.empty:
        origem = (
            "fora_da_amostra" if (c["origem_faixa"] == "fora_da_amostra").any() else "na_amostra"
        )
        # a cobertura gravada em rede/loja é a do total, na faixa calibrada naquele nível
        for linha in c[c["origem_faixa"] == origem].itertuples():
            loja = None if pd.isna(linha.sk_loja) else int(linha.sk_loja)
            cobertura[(linha.granularidade, loja)] = linha.cobertura
    m["versao_modelo"] = m["modelo"].map(versao_do_modelo)
    m["escolhido"] = m["modelo"] == resultado.escolhido
    m["teste_inicio"] = resultado.teste_inicio
    m["teste_fim"] = resultado.teste_fim

    def da_cobertura(linha):
        if not linha.escolhido or linha.nivel not in ("rede", "loja"):
            return None
        if linha.nivel == "loja" and linha.agregado:
            return None
        loja = None if linha.nivel == "rede" else int(linha.sk_loja)
        return cobertura.get((linha.granularidade, loja))

    m["cobertura_faixa"] = [da_cobertura(linha) for linha in m.itertuples()]
    m["wape"] = m["wape"].round(4)
    m["vies"] = m["vies"].round(4)
    return m


def _linha_backtest(linha: tuple) -> list:
    """Uma linha do backtest para o COPY: vazios viram NULL e a loja volta a ser inteira."""
    valores = [None if pd.isna(v) else _python(v) for v in linha]
    if valores[3] is not None:  # sk_loja
        valores[3] = int(valores[3])
    return valores


def gravar_backtest(conexao: psycopg.Connection, resultado: ResultadoBacktest) -> int:
    colunas = [
        "versao_modelo", "nivel", "granularidade", "sk_loja", "setor", "teste_inicio",
        "teste_fim", "wape", "vies", "cobertura_faixa", "escolhido",
    ]  # fmt: skip
    linhas = linhas_do_backtest(resultado)[colunas]
    try:
        conexao.execute(
            "CREATE TEMP TABLE tmp_previsao_backtest (versao_modelo VARCHAR(40),"
            " nivel VARCHAR(10), granularidade VARCHAR(3), sk_loja INTEGER, setor VARCHAR(30),"
            " teste_inicio DATE, teste_fim DATE, wape NUMERIC(8, 4), vies NUMERIC(8, 4),"
            " cobertura_faixa NUMERIC(6, 4), escolhido BOOLEAN) ON COMMIT DROP"
        )
        _copiar(
            conexao,
            "tmp_previsao_backtest",
            colunas,
            map(_linha_backtest, linhas.itertuples(index=False, name=None)),
        )
        conexao.execute("CALL dw.gravar_backtest(%s)", (resultado.treino_ate,))
        conexao.commit()
    except Exception:
        conexao.rollback()
        raise
    return len(linhas)


def comparar_com_real(conexao: psycopg.Connection, previsao: PrevisaoGerada) -> pd.DataFrame:
    """Rede, mês a mês: previsto x real nos dias que já têm venda no dw (se houver).

    Colunas: mes, dias, dias_com_real, previsto, baixo, alto, real, desvio. `previsto` soma os dias
    previstos do mês; `baixo`/`alto` só existem para mês inteiro (soma das faixas das séries);
    `real` e `desvio` só olham os dias com venda, e o `previsto` do desvio é o desses mesmos dias.
    """
    from src.previsao import dados  # evita ciclo: dados não conhece a geração

    dias = previsao.linhas[previsao.linhas["granularidade"] == "dia"].copy()
    dias["mes"] = [d.replace(day=1) for d in dias["data"]]
    ultimo = dados.ultimo_dia_com_venda(conexao)
    real_por_dia: dict[date, float] = {}
    if previsao.inicio <= ultimo:
        painel = dados.ler_painel(conexao, previsao.inicio, min(previsao.fim, ultimo))
        series = set(zip(dias["sk_loja"], dias["setor"], strict=True))
        linhas = [i for i, c in enumerate(painel.chaves) if c in series]
        somas = np.nansum(painel.valores[linhas], axis=0)
        real_por_dia = {d.date(): float(v) for d, v in zip(painel.datas, somas, strict=True)}
    meses = previsao.mensal_da_rede()[["valor_baixo", "valor_alto"]]
    saida = []
    for mes, parte in dias.groupby("mes"):
        por_dia = parte.groupby("data")["valor_previsto"].sum()
        com_real = [d for d in por_dia.index if d in real_por_dia]
        real = sum(real_por_dia[d] for d in com_real) if com_real else np.nan
        previsto_comparavel = float(por_dia[com_real].sum()) if com_real else np.nan
        saida.append(
            {
                "mes": mes,
                "dias": len(por_dia),
                "dias_com_real": len(com_real),
                "previsto": float(por_dia.sum()),
                "baixo": float(meses.loc[mes, "valor_baixo"]) if mes in meses.index else np.nan,
                "alto": float(meses.loc[mes, "valor_alto"]) if mes in meses.index else np.nan,
                "real": real,
                "desvio": previsto_comparavel / real - 1 if com_real and real else np.nan,
            }
        )
    return pd.DataFrame(saida)
