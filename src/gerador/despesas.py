"""Geração de orçamento e lançamentos de despesa, mês a mês, com anomalias propositais."""

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from src import calendario, config
from src.gerador.catalogo import DESCRICOES_POR_TIPO, Catalogo, CentroCusto
from src.gerador.parametros import ParametrosGeracao

COLUNAS_DESPESAS = [
    "numero_documento",
    "data_lancamento",
    "cod_centro_custo",
    "valor",
    "descricao",
    "fornecedor",
]
TIPOS_VENDA = (
    config.ANOMALIA_MARGEM_NEGATIVA,
    config.ANOMALIA_DESCONTO_ACIMA_LIMITE,
    config.ANOMALIA_FORA_HORARIO,
    config.ANOMALIA_CUPOM_DUPLICADO,
)
COLUNAS_ORCAMENTO = ["competencia", "cod_centro_custo", "valor_orcado"]
ORDEM_INJECAO = (
    config.ANOMALIA_VALOR_ATIPICO,
    config.ANOMALIA_CENTRO_CUSTO_ERRADO,
    config.ANOMALIA_FIM_SEMANA_FERIADO,
    config.ANOMALIA_DESPESA_DUPLICADA,
)


@dataclass
class PlanoAnomalias:
    """O que será injetado e onde, decidido antes de gerar (reprodutível pela semente)."""

    acima_orcado: dict[tuple[str, int, int], float] = field(default_factory=dict)
    despesas_por_mes: dict[tuple[int, int], dict[str, int]] = field(default_factory=dict)
    vendas_por_mes: dict[tuple[int, int], dict[str, int]] = field(default_factory=dict)


def centro_ativo(cc: CentroCusto, cat: Catalogo, ano: int, mes: int) -> bool:
    """Centros de loja só existem a partir do mês de abertura da loja."""
    if cc.cod_loja is None:
        return True
    loja = next(lj for lj in cat.lojas if lj.cod_loja == cc.cod_loja)
    return loja.data_abertura <= calendario.ultimo_dia_do_mes(ano, mes)


def receita_media_mensal(
    receita_loja_setor: dict[tuple[str, str, int, int], float],
    cat: Catalogo,
    meses: list[tuple[int, int]],
) -> dict[tuple[str | None, int], float]:
    """Receita líquida média por mês ativo, por (loja, ano); a chave (None, ano) é a rede."""
    por_mes: dict[tuple[str | None, int, int], float] = {}
    for (cod_loja, _setor, ano, mes), valor in receita_loja_setor.items():
        por_mes[(cod_loja, ano, mes)] = por_mes.get((cod_loja, ano, mes), 0.0) + valor
        por_mes[(None, ano, mes)] = por_mes.get((None, ano, mes), 0.0) + valor
    media = {}
    for ano in sorted({a for a, _ in meses}):
        meses_do_ano = [m for a, m in meses if a == ano]
        for cod_loja in [None, *(lj.cod_loja for lj in cat.lojas)]:
            ativos = [m for m in meses_do_ano if cod_loja is None or (cod_loja, ano, m) in por_mes]
            total = sum(por_mes.get((cod_loja, ano, m), 0.0) for m in ativos)
            media[(cod_loja, ano)] = total / len(ativos) if ativos else 0.0
    return media


def orcamento_mensal(
    cc: CentroCusto,
    ano: int,
    mes: int,
    receita_media: dict[tuple[str | None, int], float],
) -> float:
    """Orçamento derivado da receita: percentual do centro sobre a receita média mensal do ano."""
    valor = cc.percentual_receita * receita_media.get((cc.cod_loja, ano), 0.0)
    if cc.tipo_despesa == config.TIPO_PESSOAL:
        valor *= config.FATOR_ORCAMENTO_PESSOAL_MES.get(mes, 1.0)
    return round(max(valor, config.ORCAMENTO_MINIMO_CENTRO), config.CASAS_DECIMAIS_DINHEIRO)


def montar_plano(
    params: ParametrosGeracao,
    cat: Catalogo,
    meses: list[tuple[int, int]],
    rng: np.random.Generator,
) -> PlanoAnomalias:
    plano = PlanoAnomalias()
    qtd = params.quantidade_anomalias

    candidatos = [
        (cc.cod_centro_custo, ano, mes)
        for ano, mes in meses
        for cc in cat.centros_custo
        if centro_ativo(cc, cat, ano, mes)
    ]
    n_acima = min(qtd[config.ANOMALIA_ACIMA_ORCADO], len(candidatos))
    for k in sorted(rng.choice(len(candidatos), size=n_acima, replace=False)):
        plano.acima_orcado[candidatos[k]] = round(
            float(rng.uniform(*config.FAIXA_FATOR_ACIMA_ORCADO)), config.CASAS_DECIMAIS_DINHEIRO
        )

    uniforme = np.full(len(meses), 1 / len(meses))
    por_tipo = {tipo: rng.multinomial(qtd[tipo], uniforme) for tipo in ORDEM_INJECAO}
    por_tipo_venda = {tipo: rng.multinomial(qtd[tipo], uniforme) for tipo in TIPOS_VENDA}
    for i, chave in enumerate(meses):
        plano.despesas_por_mes[chave] = {tipo: int(por_tipo[tipo][i]) for tipo in ORDEM_INJECAO}
        plano.vendas_por_mes[chave] = {tipo: int(por_tipo_venda[tipo][i]) for tipo in TIPOS_VENDA}
    return plano


@dataclass
class DespesasDoMes:
    despesas: pd.DataFrame  # tipado; colunas `_tipo`, `_detalhe`, `_ref` marcam anomalias
    orcamento: pd.DataFrame
    acima_orcado: list[dict]  # linhas de gabarito dos centros/meses acima do orçado


def gerar_despesas_mes(
    *,
    params: ParametrosGeracao,
    cat: Catalogo,
    receita_media: dict[tuple[str | None, int], float],
    feriados: dict[date, str],
    ano: int,
    mes: int,
    plano: PlanoAnomalias,
    rng: np.random.Generator,
    proximo_documento: int,
) -> tuple[DespesasDoMes, int]:
    """Gera o mês inteiro; devolve também o próximo número de documento livre."""
    dias = calendario.dias_do_mes(ano, mes, params.data_inicio, params.data_fim)
    uteis = [d for d in dias if not calendario.eh_fim_de_semana(d) and d not in feriados]
    nao_uteis = [d for d in dias if calendario.eh_fim_de_semana(d) or d in feriados]
    primeiro_dia = date(ano, mes, 1)

    lancamentos: list[dict] = []
    orcamentos: list[dict] = []
    acima: list[dict] = []
    for cc in cat.centros_custo:
        if not centro_ativo(cc, cat, ano, mes):
            continue
        orcado = orcamento_mensal(cc, ano, mes, receita_media)
        orcamentos.append(
            {
                "competencia": primeiro_dia,
                "cod_centro_custo": cc.cod_centro_custo,
                "valor_orcado": orcado,
            }
        )
        total = orcado * rng.uniform(*config.FAIXA_REALIZACAO_ORCAMENTO)
        fator_acima = plano.acima_orcado.get((cc.cod_centro_custo, ano, mes))
        if fator_acima:
            total *= fator_acima

        n = config.LANCAMENTOS_POR_TIPO[cc.tipo_despesa]
        valores = np.round(
            total * rng.dirichlet(np.full(n, config.ALFA_DIRICHLET_LANCAMENTOS)),
            config.CASAS_DECIMAIS_DINHEIRO,
        )
        valores[-1] = round(total - valores[:-1].sum(), config.CASAS_DECIMAIS_DINHEIRO)
        datas = [uteis[k] for k in rng.integers(0, len(uteis), n)]
        descricoes = rng.choice(DESCRICOES_POR_TIPO[cc.tipo_despesa], size=n, replace=False)
        pool = cat.fornecedores_por_tipo[cc.tipo_despesa]
        fornecedores = [pool[k] for k in rng.integers(0, len(pool), n)]
        for valor, data, descricao, fornecedor in zip(
            valores, datas, descricoes, fornecedores, strict=True
        ):
            lancamentos.append(
                {
                    "data_lancamento": data,
                    "cod_centro_custo": cc.cod_centro_custo,
                    "valor": float(valor),
                    "descricao": str(descricao),
                    "fornecedor": fornecedor,
                    "_acima": bool(fator_acima),
                }
            )
        if fator_acima:
            acima.append(
                {
                    "cod_centro_custo": cc.cod_centro_custo,
                    "competencia": primeiro_dia,
                    "valor": round(float(valores.sum()), config.CASAS_DECIMAIS_DINHEIRO),
                    "detalhe": f"orcado={orcado:.2f} | fator_sobre_orcado={fator_acima:.2f}",
                }
            )

    df = pd.DataFrame(lancamentos).sort_values("data_lancamento", kind="stable", ignore_index=True)
    df.insert(
        0,
        "numero_documento",
        [
            f"{config.PREFIXO_DOCUMENTO}{proximo_documento + k:0{config.DIGITOS_DOCUMENTO}d}"
            for k in range(len(df))
        ],
    )
    proximo_documento += len(df)
    df["_tipo"] = ""
    df["_detalhe"] = ""
    df["_ref"] = -1

    df = _injetar_anomalias(df, cat, nao_uteis, plano.despesas_por_mes[(ano, mes)], rng)
    df["data_lancamento"] = pd.to_datetime(df["data_lancamento"])
    return (
        DespesasDoMes(df, pd.DataFrame(orcamentos), acima),
        proximo_documento,
    )


def _injetar_anomalias(
    df: pd.DataFrame,
    cat: Catalogo,
    dias_nao_uteis: list[date],
    contagens: dict[str, int],
    rng: np.random.Generator,
) -> pd.DataFrame:
    disponiveis = df.index[~df["_acima"]].to_numpy()
    total = min(sum(contagens.values()), len(disponiveis))
    escolhidas = list(rng.choice(disponiveis, size=total, replace=False))
    tipo_do_cc = {cc.cod_centro_custo: cc for cc in cat.centros_custo}
    duplicadas = []

    for tipo in ORDEM_INJECAO:
        alvos, escolhidas = escolhidas[: contagens[tipo]], escolhidas[contagens[tipo] :]
        for i in alvos:
            if tipo == config.ANOMALIA_VALOR_ATIPICO:
                fator = rng.uniform(*config.FAIXA_FATOR_VALOR_ATIPICO)
                df.at[i, "valor"] = round(df.at[i, "valor"] * fator, config.CASAS_DECIMAIS_DINHEIRO)
                df.at[i, "_detalhe"] = f"fator_sobre_valor_normal={fator:.1f}"
            elif tipo == config.ANOMALIA_CENTRO_CUSTO_ERRADO:
                certo = tipo_do_cc[df.at[i, "cod_centro_custo"]]
                alternativas = [
                    cc
                    for cc in cat.centros_custo
                    if cc.cod_loja == certo.cod_loja and cc.tipo_despesa != certo.tipo_despesa
                ]
                errado = alternativas[int(rng.integers(0, len(alternativas)))]
                df.at[i, "cod_centro_custo"] = errado.cod_centro_custo
                df.at[i, "_detalhe"] = (
                    f"cc_correto={certo.cod_centro_custo} | tipo_da_descricao={certo.tipo_despesa}"
                )
            elif tipo == config.ANOMALIA_FIM_SEMANA_FERIADO and dias_nao_uteis:
                nova = dias_nao_uteis[int(rng.integers(0, len(dias_nao_uteis)))]
                df.at[i, "_detalhe"] = f"data_original={df.at[i, 'data_lancamento']:%Y-%m-%d}"
                df.at[i, "data_lancamento"] = nova
            elif tipo == config.ANOMALIA_DESPESA_DUPLICADA:
                duplicadas.append(i)
                continue
            else:
                continue
            df.at[i, "_tipo"] = tipo

    if duplicadas:
        copias = df.loc[duplicadas].copy()
        copias["_tipo"] = config.ANOMALIA_DESPESA_DUPLICADA
        copias["_detalhe"] = [f"duplicata de {doc}" for doc in copias["numero_documento"]]
        copias["_ref"] = duplicadas
        df = pd.concat([df, copias], ignore_index=True)
    return df
