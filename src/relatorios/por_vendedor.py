"""Dados de todos os vendedores em formato longo, para a aba oculta "Dados por vendedor".

A macro GerarAbaDoVendedor (vba/ModuloVendedor.bas) filtra a aba pelo código do vendedor e escreve
cada bloco na ordem de `BLOCOS`. Cada bloco tem uma linha de ordem 0 (o título da seção e, nas
tabelas, os títulos das colunas separados por "|") e as linhas de dados (ordem 1, 2, ...).
`formatos` diz, para cada uma das seis colunas de valor, como a macro formata a célula; "-" é coluna
sem uso (a macro não a copia).
"""

from datetime import date

import pandas as pd

from src import config

BLOCO_TITULO = "titulo"  # título da aba
BLOCO_CABECALHO = "cabecalho"
BLOCO_DIA = "dia"
BLOCO_MES = "mes"
BLOCO_ANO = "ano"
BLOCO_DIA_A_DIA = "dia_a_dia"
BLOCO_EVOLUCAO = "evolucao"
BLOCO_PRODUTOS = "produtos"
BLOCO_MIX = "mix"
BLOCO_COMPORTAMENTO = "comportamento"
BLOCO_ALERTAS = "alertas"
# a ordem em que a macro escreve os blocos na aba
BLOCOS = (
    BLOCO_TITULO, BLOCO_CABECALHO, BLOCO_DIA, BLOCO_MES, BLOCO_ANO, BLOCO_DIA_A_DIA,
    BLOCO_EVOLUCAO, BLOCO_PRODUTOS, BLOCO_MIX, BLOCO_COMPORTAMENTO, BLOCO_ALERTAS,
)  # fmt: skip

# letras de `formatos` (a macro tem a mesma tabela): "-" coluna sem uso
FORMATOS = {
    "T": "General", "R": '"R$" #,##0.00', "P": "0.0%", "I": "#,##0", "D": "dd/mm/yyyy",
    "M": "mm/yyyy", "N": "0.00", "-": None,
}  # fmt: skip
COLUNAS_DE_VALOR = 6
COLUNAS_FIXAS = ("cod_vendedor", "bloco", "ordem", "titulo", "cabecalhos", "formatos")
COLUNAS = COLUNAS_FIXAS + tuple(f"col_{k}" for k in range(1, COLUNAS_DE_VALOR + 1))

TITULO_COBERTURA_DIA = "Cobertura do dia"
TITULO_COBERTURA_ATE_O_DIA = "Cobertura da meta até o dia"
TITULO_META_DO_MES_ATINGIDO = "% da meta do mês atingido"
TITULO_RITMO = "Ritmo necessário por dia"
INDICADORES_COMPORTAMENTO = (
    "Ticket médio", "Itens por cupom", "Desconto médio", "Taxa de cancelamento",
)  # fmt: skip


def _nativo(valor):
    """Valor do pandas/numpy como tipo do Python; vazio (NaN/None/NaT) vira None."""
    if valor is None or (not isinstance(valor, str | date) and pd.isna(valor)):
        return None
    if isinstance(valor, pd.Timestamp):
        return valor.date()
    return valor.item() if hasattr(valor, "item") else valor


def _razao(numerador, denominador):
    if numerador is None or not denominador:
        return None
    return float(numerador) / float(denominador)


def _pct(valor: float) -> str:
    return f"{valor * 100:.1f}".replace(".", ",") + "%"


def dias_que_bateu_a_meta(dias: pd.DataFrame) -> tuple[int, int]:
    """(X, Y): Y = dias do mês em que o vendedor vendeu; X = quantos deles venderam pelo menos a
    meta do dia (sem meta no dia, não conta como meta batida)."""
    com_venda = dias[dias["venda"] > 0]
    meta = pd.to_numeric(com_venda["meta_dia"], errors="coerce")  # sem meta no mês: tudo None
    bateu = meta.notna() & (pd.to_numeric(com_venda["venda"]) >= meta)
    return int(bateu.sum()), len(com_venda)


def comportamento_da_loja(comportamento: pd.DataFrame) -> pd.DataFrame:
    """Indicadores de comportamento por loja, somando os totais dos vendedores dela."""
    soma = comportamento.drop(columns="cod_vendedor").groupby("cod_loja").sum()
    return indicadores_de_comportamento(soma)


def indicadores_de_comportamento(totais: pd.DataFrame) -> pd.DataFrame:
    """De `cupons`, `itens`, `bruto`, `desconto`, `receita` e `cancelados` para os quatro
    indicadores. Taxa de cancelamento = cupons cancelados ÷ (concluídos + cancelados)."""
    return pd.DataFrame(
        {
            "Ticket médio": totais["receita"] / totais["cupons"].where(totais["cupons"] > 0),
            "Itens por cupom": totais["itens"] / totais["cupons"].where(totais["cupons"] > 0),
            "Desconto médio": totais["desconto"] / totais["bruto"].where(totais["bruto"] > 0),
            "Taxa de cancelamento": totais["cancelados"]
            / (totais["cupons"] + totais["cancelados"]).where(
                (totais["cupons"] + totais["cancelados"]) > 0
            ),
        }
    )


def montar_dados_por_vendedor(
    vendedores: pd.DataFrame,
    dias: pd.DataFrame,
    evolucao: pd.DataFrame,
    produtos: pd.DataFrame,
    mix: pd.DataFrame,
    comportamento: pd.DataFrame,
    alertas: pd.DataFrame,
    mes: date,
    dia: date,
) -> pd.DataFrame:
    """Uma linha por item de cada bloco de cada vendedor do ranking (formato longo)."""
    linhas: list[dict] = []
    ate = f"até {dia:%d/%m/%Y}"
    meses = config.RELATORIO_MESES_EVOLUCAO_VENDEDOR

    def linha(cod, bloco, ordem, valores=(), formatos="", titulo="", cabecalhos=""):
        formatos = formatos.ljust(COLUNAS_DE_VALOR, "-")
        valores = [_nativo(v) for v in valores]
        valores += [None] * (COLUNAS_DE_VALOR - len(valores))
        linhas.append(
            {"cod_vendedor": cod, "bloco": bloco, "ordem": ordem, "titulo": titulo,
             "cabecalhos": cabecalhos, "formatos": formatos}
            | {f"col_{k}": valores[k - 1] for k in range(1, COLUNAS_DE_VALOR + 1)}
        )  # fmt: skip

    def pares(cod, bloco, titulo, itens):
        """Bloco de rótulo e valor: título na ordem 0 e uma linha por indicador."""
        linha(cod, bloco, 0, titulo=titulo)
        for ordem, (rotulo, valor, formato) in enumerate(itens, start=1):
            linha(cod, bloco, ordem, (rotulo, valor), "T" + formato)

    def tabela(cod, bloco, titulo, cabecalhos):
        """Início de um bloco em tabela: título da seção e títulos das colunas (ordem 0)."""
        linha(cod, bloco, 0, titulo=titulo, cabecalhos=cabecalhos)

    ranking = vendedores.assign(
        posicao_loja=vendedores.groupby("cod_loja")["acumulado_mes"].rank(
            method="min", ascending=False
        ),
        vendedores_na_loja=vendedores.groupby("cod_loja")["cod_vendedor"].transform("size"),
    )
    por_vendedor = {
        nome: {cod: g for cod, g in quadro.groupby("cod_vendedor")}  # noqa: C416
        for nome, quadro in (
            ("dias", dias), ("evolucao", evolucao), ("produtos", produtos), ("mix", mix),
        )
    }  # fmt: skip
    alertas_do = {cod: g for cod, g in alertas.groupby("cod_vendedor")}  # noqa: C416
    totais = comportamento.set_index("cod_vendedor")
    do_vendedor = indicadores_de_comportamento(totais)
    da_loja = comportamento_da_loja(comportamento)
    vazio = pd.DataFrame()

    for v in ranking.itertuples():
        cod = v.cod_vendedor
        meus_dias = por_vendedor["dias"].get(cod, vazio)
        meus_meses = por_vendedor["evolucao"].get(cod, vazio)

        linha(cod, BLOCO_TITULO, 0, titulo=f"Vendedor {cod} - {v.nome_vendedor} ({v.cod_loja})")
        setor = "-" if _nativo(v.setor_principal) is None else v.setor_principal
        if setor != "-" and _nativo(v.percentual_setor_principal) is not None:
            setor += f" ({_pct(v.percentual_setor_principal)} da receita)"
        pares(cod, BLOCO_CABECALHO, "Identificação", [
            ("Nome", v.nome_vendedor, "T"), ("Loja", f"{v.cod_loja} - {v.nome_loja}", "T"),
            ("Setor principal", setor, "T"),
            ("Posição na loja", f"{int(v.posicao_loja)} de {int(v.vendedores_na_loja)}", "T"),
            ("Posição na rede", f"{int(v.posicao)} de {len(ranking)}", "T"),
        ])  # fmt: skip

        do_dia = meus_dias[meus_dias["dia"] == dia] if not meus_dias.empty else vazio
        venda_dia = float(do_dia["venda"].iloc[0]) if len(do_dia) else 0.0
        meta_dia = _nativo(do_dia["meta_dia"].iloc[0]) if len(do_dia) else None
        pares(cod, BLOCO_DIA, f"Metas do dia ({dia:%d/%m/%Y})", [
            ("Venda do dia", venda_dia, "R"), ("Meta do dia", meta_dia, "R"),
            (TITULO_COBERTURA_DIA, _razao(venda_dia, meta_dia), "P"),
        ])  # fmt: skip

        pares(cod, BLOCO_MES, f"Metas do mês ({ate})", [
            ("Acumulado do mês", v.acumulado_mes, "R"),
            ("Meta acumulada até o dia", v.meta_acumulada, "R"),
            (TITULO_COBERTURA_ATE_O_DIA, v.cobertura_ate_o_dia, "P"),
            (TITULO_META_DO_MES_ATINGIDO, v.cobertura_mes, "P"),
            (TITULO_RITMO, v.ritmo_necessario_dia, "R"),
        ])  # fmt: skip

        no_ano = (
            meus_meses[meus_meses["mes_ref"] >= date(dia.year, 1, 1)] if len(meus_meses) else vazio
        )
        acumulado_ano = float(no_ano["venda"].sum()) if len(no_ano) else 0.0
        meta_ano = _nativo(no_ano["meta"].sum(min_count=1)) if len(no_ano) else None
        pares(cod, BLOCO_ANO, f"Metas do ano ({ate})", [
            ("Acumulado no ano", acumulado_ano, "R"), ("Meta do ano até a posição", meta_ano, "R"),
            ("Cobertura do ano", _razao(acumulado_ano, meta_ano), "P"),
        ])  # fmt: skip

        x, y = dias_que_bateu_a_meta(meus_dias) if len(meus_dias) else (0, 0)
        titulo_dias = f"Dias que bateu a meta no mês: {x} de {y} dias com venda"
        tabela(cod, BLOCO_DIA_A_DIA, titulo_dias, "Dia|Venda|Meta|Cobertura")
        com_venda = meus_dias[meus_dias["venda"] > 0] if len(meus_dias) else vazio
        for ordem, d in enumerate(com_venda.itertuples(), start=1):
            cobertura = _razao(d.venda, _nativo(d.meta_dia))
            linha(cod, BLOCO_DIA_A_DIA, ordem, (d.dia, d.venda, d.meta_dia, cobertura), "DRRP")

        titulo_evolucao = f"Evolução: {meses} meses fechados e o mês corrente ({ate})"
        tabela(cod, BLOCO_EVOLUCAO, titulo_evolucao, "Mês|Venda|Meta|Cobertura")
        for ordem, m in enumerate(meus_meses.itertuples(), start=1):
            cobertura = _razao(m.venda, _nativo(m.meta))
            linha(cod, BLOCO_EVOLUCAO, ordem, (m.mes_ref, m.venda, m.meta, cobertura), "MRRP")

        n = config.RELATORIO_TOP_PRODUTOS_VENDEDOR
        tabela(cod, BLOCO_PRODUTOS, f"Top {n} produtos do mês ({ate})",
               "Produto|Setor|Quantidade|Receita")  # fmt: skip
        for p in por_vendedor["produtos"].get(cod, vazio).itertuples():
            valores = (p.descricao, p.setor, p.quantidade, p.receita)
            linha(cod, BLOCO_PRODUTOS, int(p.posicao), valores, "TTIR")

        tabela(cod, BLOCO_MIX, "Mix por setor no mês", "Setor|Receita|% da receita")
        for ordem, s in enumerate(por_vendedor["mix"].get(cod, vazio).itertuples(), start=1):
            linha(cod, BLOCO_MIX, ordem, (s.setor, s.receita, s.participacao), "TRP")

        tabela(cod, BLOCO_COMPORTAMENTO, "Comportamento no mês", "Indicador|Vendedor|Média da loja")
        for ordem, (indicador, formato) in enumerate(
            zip(INDICADORES_COMPORTAMENTO, "RNPP", strict=True), start=1
        ):
            meu = do_vendedor.at[cod, indicador] if cod in do_vendedor.index else None
            da_minha_loja = (
                da_loja.at[v.cod_loja, indicador] if v.cod_loja in da_loja.index else None
            )
            linha(
                cod, BLOCO_COMPORTAMENTO, ordem, (indicador, meu, da_minha_loja), "T" + formato * 2
            )

        tabela(cod, BLOCO_ALERTAS, "Alertas abertos do vendedor",
               "Severidade|Tipo|Data|Valor envolvido|Status|Explicação")  # fmt: skip
        for ordem, a in enumerate(alertas_do.get(cod, vazio).itertuples(), start=1):
            valores = (a.severidade, a.tipo, a.data, a.valor_envolvido, a.status, a.explicacao)
            linha(cod, BLOCO_ALERTAS, ordem, valores, "TTDRTT")

    return pd.DataFrame(linhas, columns=list(COLUNAS))
