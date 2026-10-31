"""Texto do relatório do backtest (formatos brasileiros: vírgula decimal e %)."""

import pandas as pd

from src.previsao.backtest import ResultadoBacktest


def pct(valor: float, casas: int = 1, sinal: bool = False) -> str:
    texto = f"{valor * 100:{'+' if sinal else ''}.{casas}f}".replace(".", ",")
    return f"{texto}%"


def _agregado(m: pd.DataFrame, modelo: str, nivel: str, granularidade: str, coluna: str) -> float:
    linha = m[
        (m["modelo"] == modelo) & (m["nivel"] == nivel)
        & (m["granularidade"] == granularidade) & m["agregado"]
    ]  # fmt: skip
    return float(linha[coluna].iloc[0])


def tabela_abordagens(resultado: ResultadoBacktest) -> list[str]:
    m = resultado.metricas
    linhas = [
        f"{'abordagem':<22}{'WAPE mês L×S':>14}{'WAPE dia L×S':>14}{'WAPE mês rede':>15}"
        f"{'WAPE dia rede':>15}{'viés mês rede':>15}",
    ]
    for modelo in sorted(
        m["modelo"].unique(), key=lambda x: _agregado(m, x, "loja_setor", "mes", "wape")
    ):
        marca = " *" if modelo == resultado.escolhido else ""
        linhas.append(
            f"{modelo + marca:<22}"
            f"{pct(_agregado(m, modelo, 'loja_setor', 'mes', 'wape')):>14}"
            f"{pct(_agregado(m, modelo, 'loja_setor', 'dia', 'wape')):>14}"
            f"{pct(_agregado(m, modelo, 'rede', 'mes', 'wape')):>15}"
            f"{pct(_agregado(m, modelo, 'rede', 'dia', 'wape')):>15}"
            f"{pct(_agregado(m, modelo, 'rede', 'mes', 'vies'), sinal=True):>15}"
        )
    linhas.append("(* = escolhida; L×S = por loja e setor, erros somados de todas as séries)")
    return linhas


def resumo_por_loja(resultado: ResultadoBacktest) -> list[str]:
    m = resultado.metricas
    linhas = [f"{'abordagem':<22}{'WAPE mês por loja':>40}{'WAPE dia por loja':>40}"]
    linhas.append(f"{'':<22}{'mín / mediana / máx':>40}{'mín / mediana / máx':>40}")
    for modelo in sorted(m["modelo"].unique()):
        partes = []
        for granularidade in ("mes", "dia"):
            lojas = m[
                (m["modelo"] == modelo) & (m["nivel"] == "loja")
                & (m["granularidade"] == granularidade) & ~m["agregado"]
            ]["wape"]  # fmt: skip
            partes.append(f"{pct(lojas.min())} / {pct(lojas.median())} / {pct(lojas.max())}")
        linhas.append(f"{modelo:<22}{partes[0]:>40}{partes[1]:>40}")
    return linhas


def resumo_por_setor(resultado: ResultadoBacktest) -> list[str]:
    m = resultado.metricas
    setores = sorted(m[m["nivel"] == "setor"]["setor"].dropna().unique())
    linhas = [f"{'WAPE mês por setor':<22}" + "".join(f"{s:>18}" for s in setores)]
    for modelo in sorted(m["modelo"].unique()):
        valores = [
            float(m[(m["modelo"] == modelo) & (m["nivel"] == "setor") & (m["setor"] == s)
                    & (m["granularidade"] == "mes")]["wape"].iloc[0])
            for s in setores
        ]  # fmt: skip
        linhas.append(f"{modelo:<22}" + "".join(f"{pct(v):>18}" for v in valores))
    return linhas


def resumo_cobertura(resultado: ResultadoBacktest) -> list[str]:
    linhas = []
    for origem, rotulo in (("fora_da_amostra", "fora da amostra"), ("na_amostra", "na amostra")):
        for granularidade in ("dia", "mes"):
            sel = resultado.cobertura[
                (resultado.cobertura["origem_faixa"] == origem)
                & (resultado.cobertura["granularidade"] == granularidade)
            ]
            if sel.empty:
                continue
            rede = float(sel[sel["sk_loja"].isna()]["cobertura"].iloc[0])
            lojas = sel[sel["sk_loja"].notna()]["cobertura"]
            linhas.append(
                f"cobertura {rotulo}, {granularidade}, por loja e setor: média {pct(rede)}; "
                f"lojas {pct(lojas.min())} a {pct(lojas.max())} (mediana {pct(lojas.median())})"
            )
            total = resultado.cobertura_agregada
            total = total[
                (total["origem_faixa"] == origem) & (total["granularidade"] == granularidade)
            ]
            if total.empty:
                continue
            total_lojas = total[total["sk_loja"].notna()]["cobertura"]
            linhas.append(
                f"cobertura {rotulo}, {granularidade}, faixa calibrada no total: "
                f"rede {pct(float(total[total['sk_loja'].isna()]['cobertura'].iloc[0]))}; "
                f"lojas {pct(total_lojas.min())} a {pct(total_lojas.max())} "
                f"(mediana {pct(total_lojas.median())})"
            )
    return linhas


def montar(resultado: ResultadoBacktest) -> str:
    cabecalho = (
        f"Backtest: treino até {resultado.treino_ate:%d/%m/%Y}, teste de "
        f"{resultado.teste_inicio:%d/%m/%Y} a {resultado.teste_fim:%d/%m/%Y}; "
        f"{len(resultado.chaves)} séries avaliadas, {len(resultado.ignoradas)} ignoradas."
    )
    corpo = [
        cabecalho, "", *tabela_abordagens(resultado), "", *resumo_por_loja(resultado), "",
        *resumo_por_setor(resultado), "",
        f"Faixa baixa/alta (percentis 10 e 90), modelo {resultado.escolhido}:",
        *resumo_cobertura(resultado), "",
        f"{resultado.duracao_s:.1f} s, pico de memória do processo "
        f"{resultado.pico_memoria_gb:.2f} GB",
    ]  # fmt: skip
    return "\n".join(corpo)


def montar_previsao(previsao, resultado: ResultadoBacktest, comparacao: pd.DataFrame) -> str:
    """Resumo da previsão gerada: rede, mês a mês, com faixa e (se já houver venda) o real."""
    linhas = [
        f"Previsão {previsao.versao}: treino até {previsao.treino_ate:%d/%m/%Y}, "
        f"de {previsao.inicio:%d/%m/%Y} a {previsao.fim:%d/%m/%Y}; "
        f"WAPE mensal por loja e setor no backtest: "
        f"{pct(_agregado(resultado.metricas, previsao.modelo, 'loja_setor', 'mes', 'wape'))}.",
        f"{'mês':<10}{'dias':>5}{'previsto (R$)':>18}{'faixa baixa':>16}{'faixa alta':>16}"
        f"{'real (R$)':>16}{'desvio':>9}",
    ]
    for linha in comparacao.itertuples():
        real = f"{brl(linha.real)}" if pd.notna(linha.real) else "-"
        desvio = pct(linha.desvio, sinal=True) if pd.notna(linha.desvio) else "-"
        baixo = brl(linha.baixo) if pd.notna(linha.baixo) else "-"
        alto = brl(linha.alto) if pd.notna(linha.alto) else "-"
        linhas.append(
            f"{linha.mes:%m/%Y}".ljust(10) + f"{linha.dias:>5}{brl(linha.previsto):>18}{baixo:>16}"
            f"{alto:>16}{real:>16}{desvio:>9}"
        )
    linhas.append(
        "(faixa da rede calibrada no total do backtest, não a soma das faixas das séries)"
    )
    if previsao.sem_previsao:
        linhas.append(
            f"{len(previsao.sem_previsao)} séries sem histórico suficiente não foram previstas."
        )
    return "\n".join(linhas)


def brl(valor: float) -> str:
    """R$ no padrão brasileiro: milhar com ponto e vírgula decimal."""
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
