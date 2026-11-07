"""Metas de venda: o "esperado" do período, nunca o realizado do mês.

Meta de loja x setor x mês:
  * primeiro ano do período (orçamento inicial): esperado estrutural do gerador x peso do calendário
    x (1 + esforço) x ruído pequeno, como se o orçamento tivesse sido feito no fim do ano anterior;
  * depois, regra A: taxa do mesmo mês do ano anterior x tendência dos meses anteriores (limitada)
    x peso do calendário x (1 + esforço); regra B (só se faltar o ano anterior ou a tendência):
    média das taxas dos meses anteriores; regra C (loja nova, sem histórico): taxa por m² das lojas
    do mesmo formato no mês anterior x área.
Taxa = realizado do mês / peso do calendário do mês (só meses ANTERIORES ao da meta entram).

Meta de vendedor = meta da loja x participação histórica do vendedor, com a soma exata da loja.
"""

from calendar import monthrange
from datetime import date

import numpy as np
import pandas as pd

from src import calendario, config
from src.calendario_comercial import peso_do_dia
from src.gerador.catalogo import SETORES, Catalogo, Loja
from src.gerador.sazonalidade import Sazonalidade

Mes = tuple[int, int]
ChaveLojaSetor = tuple[str, str, int, int]


def _mes_anterior(mes: Mes, deslocamento: int) -> Mes:
    """Mês deslocado (negativo = para trás)."""
    total = mes[0] * 12 + (mes[1] - 1) + deslocamento
    return total // 12, total % 12 + 1


def esperado_estrutural(
    cat: Catalogo,
    sazon: Sazonalidade,
    meses: list[Mes],
    pesos_por_mes: dict[Mes, tuple[list[date], np.ndarray]],
    itens_por_mes: list[int],
) -> dict[ChaveLojaSetor, float]:
    """Receita esperada (concluída) de cada loja x setor x mês, em esperança matemática.

    Usa os mesmos ingredientes com que o gerador sorteia as vendas (itens do mês repartidos por
    dia e loja, mix de setor, preço de lista, quantidade, desconto, cancelamento), mas troca cada
    sorteio pela sua média. Não usa nenhuma venda realizada.
    """
    mix = cat.mix_setor_por_loja()
    fator_preco = np.array([lj.fator_preco for lj in cat.lojas])
    preco_medio = np.zeros(len(SETORES))
    for s, setor in enumerate(SETORES):
        produtos = [p for p in cat.produtos if p.setor == setor]
        popularidade = np.array([p.popularidade for p in produtos])
        preco_medio[s] = float(
            (popularidade / popularidade.sum()) @ [p.preco_lista for p in produtos]
        )
    unidades = np.array([1 + config.QUANTIDADE_MEDIA_EXTRA_POR_SETOR[s] for s in SETORES])
    desconto_normal = config.PROB_DESCONTO_NORMAL * float(np.mean(config.FAIXA_DESCONTO_NORMAL))
    concluida = (1 - config.PROB_CANCELAMENTO) * (1 - config.PROB_DEVOLUCAO)

    esperado: dict[ChaveLojaSetor, float] = {}
    for (ano, mes), n_itens in zip(meses, itens_por_mes, strict=True):
        dias, pesos = pesos_por_mes[(ano, mes)]
        itens = n_itens * pesos / pesos.sum()  # dias x lojas
        mult = np.array([[sazon.multiplicador_setor(d, s) for s in SETORES] for d in dias])
        desconto_dia = np.array([_desconto_esperado(cat, d, desconto_normal) for d in dias])
        probs = mix[None, :, :] * mult[:, None, :]  # dias x lojas x setores
        probs /= probs.sum(axis=2, keepdims=True)
        receita_item = unidades * preco_medio  # por setor
        valor = (
            np.einsum("dj,djs,s,d->js", itens, probs, receita_item, 1 - desconto_dia)
            * fator_preco[:, None]
            * concluida
        )
        for j, loja in enumerate(cat.lojas):
            for s, setor in enumerate(SETORES):
                if valor[j, s] > 0:
                    esperado[(loja.cod_loja, setor, ano, mes)] = float(valor[j, s])
    return esperado


def _desconto_esperado(cat: Catalogo, dia: date, desconto_normal: float) -> float:
    campanha = next((c for c in cat.campanhas if c.data_inicio <= dia <= c.data_fim), None)
    if campanha is None:
        return desconto_normal
    em_campanha = config.PROB_DESCONTO_CAMPANHA * campanha.desconto_medio
    return config.PROB_CUPOM_EM_CAMPANHA * em_campanha + (1 - config.PROB_CUPOM_EM_CAMPANHA) * (
        desconto_normal
    )


class _Pesos:
    """Peso do calendário por mês, loja (dias após a abertura) e setor."""

    def __init__(
        self, cat: Catalogo, sazon: Sazonalidade, meses: list[Mes], params_periodo
    ) -> None:
        inicio, fim = params_periodo
        self._dados: dict[tuple[str, str, int, int], float] = {}
        for ano, mes in meses:
            dias = calendario.dias_do_mes(ano, mes, inicio, fim)
            for setor in SETORES:
                por_dia = [(d, peso_do_dia(sazon, d, setor)) for d in dias]
                for loja in cat.lojas:
                    self._dados[(loja.cod_loja, setor, ano, mes)] = sum(
                        p for d, p in por_dia if d >= loja.data_abertura
                    )

    def da_loja(self, cod_loja: str, setor: str, ano: int, mes: int) -> float:
        return self._dados.get((cod_loja, setor, ano, mes), 0.0)


def gerar_metas(
    cat: Catalogo,
    sazon: Sazonalidade,
    meses: list[Mes],
    esperado: dict[ChaveLojaSetor, float],
    receita_realizada: dict[ChaveLojaSetor, float],
    rng: np.random.Generator,
    periodo: tuple[date, date],
) -> pd.DataFrame:
    """Meta mensal por loja e setor (ver o docstring do módulo)."""
    pesos = _Pesos(cat, sazon, meses, periodo)
    taxa: dict[ChaveLojaSetor, float] = {}
    for (cod, setor, ano, mes), valor in receita_realizada.items():
        peso = pesos.da_loja(cod, setor, ano, mes)
        if peso > 0 and valor > 0:
            taxa[(cod, setor, ano, mes)] = valor / peso
    esforco = 1 + config.ESFORCO_META
    lim_baixo, lim_alto = config.LIMITE_TENDENCIA_META

    def tendencia(loja: Loja, mes: Mes) -> float | None:
        recente = antigo = 0.0
        for k in range(1, config.MESES_TENDENCIA_META + 1):
            a, b = _mes_anterior(mes, -k), _mes_anterior(mes, -k - 12)
            for setor in SETORES:
                x, y = taxa.get((loja.cod_loja, setor, *a)), taxa.get((loja.cod_loja, setor, *b))
                if x is not None and y is not None:
                    recente += x
                    antigo += y
        return min(lim_alto, max(lim_baixo, recente / antigo)) if antigo > 0 else None

    def taxa_por_m2(loja: Loja, setor: str, mes: Mes) -> float | None:
        anterior = _mes_anterior(mes, -1)
        valores = [
            taxa[(o.cod_loja, setor, *anterior)] / o.area_m2
            for o in cat.lojas
            if o.cod_loja != loja.cod_loja
            and o.formato == loja.formato
            and (o.cod_loja, setor, *anterior) in taxa
        ]
        return float(np.mean(valores)) if valores else None

    linhas = []
    for posicao, (ano, mes) in enumerate(meses):
        fim_do_mes = calendario.ultimo_dia_do_mes(ano, mes)
        for loja in cat.lojas:
            if loja.data_abertura > fim_do_mes:
                continue
            fator_tendencia = (
                tendencia(loja, (ano, mes)) if posicao >= config.MESES_ORCAMENTO_INICIAL else None
            )
            for setor in SETORES:
                peso = pesos.da_loja(loja.cod_loja, setor, ano, mes)
                if peso <= 0:
                    continue
                if posicao < config.MESES_ORCAMENTO_INICIAL:  # orçamento inicial
                    base = esperado.get((loja.cod_loja, setor, ano, mes))
                    if base is None:
                        continue
                    valor = base * esforco * rng.normal(1.0, config.DESVIO_RUIDO_META_ORCAMENTO)
                else:
                    valor = _regra_historica(
                        loja, setor, (ano, mes), peso, taxa, fator_tendencia, taxa_por_m2
                    )
                    if valor is None:
                        continue
                    valor *= esforco
                linhas.append(
                    (
                        date(ano, mes, 1),
                        loja.cod_loja,
                        setor,
                        round(valor, config.CASAS_DECIMAIS_DINHEIRO),
                    )
                )
    df = pd.DataFrame(linhas, columns=["competencia", "cod_loja", "setor", "valor_meta"])
    df["competencia"] = pd.to_datetime(df["competencia"])
    return df


def _regra_historica(loja, setor, mes, peso, taxa, fator_tendencia, taxa_por_m2) -> float | None:
    """Regras A, B e C (nesta ordem); None se não houver nenhuma base."""
    anterior_ano = taxa.get((loja.cod_loja, setor, *_mes_anterior(mes, -12)))
    if anterior_ano is not None and fator_tendencia is not None:  # A
        return anterior_ano * fator_tendencia * peso
    recentes = [
        taxa[(loja.cod_loja, setor, *_mes_anterior(mes, -k))]
        for k in range(1, config.MESES_TENDENCIA_META + 1)
        if (loja.cod_loja, setor, *_mes_anterior(mes, -k)) in taxa
    ]
    if recentes:  # B
        return float(np.mean(recentes)) * peso
    por_m2 = taxa_por_m2(loja, setor, mes)  # C
    return None if por_m2 is None else por_m2 * loja.area_m2 * peso


def gerar_metas_vendedor(
    cat: Catalogo,
    metas_loja: pd.DataFrame,
    receita_vendedor: dict[tuple[str, int, int], float],
    meses: list[Mes],
) -> pd.DataFrame:
    """Meta do vendedor = meta da loja x participação histórica (soma exata da loja)."""
    por_loja = metas_loja.groupby(["competencia", "cod_loja"])["valor_meta"].sum()
    linhas = []
    for ano, mes in meses:
        competencia = pd.Timestamp(ano, mes, 1)
        primeiro, ultimo = date(ano, mes, 1), date(ano, mes, monthrange(ano, mes)[1])
        for loja in cat.lojas:
            if (competencia, loja.cod_loja) not in por_loja.index:
                continue
            total_loja = round(
                float(por_loja[(competencia, loja.cod_loja)]), config.CASAS_DECIMAIS_DINHEIRO
            )
            equipe = [
                v
                for v in cat.vendedores
                if v.cod_loja == loja.cod_loja
                and v.data_admissao <= ultimo
                and (v.data_desligamento is None or v.data_desligamento > primeiro)
            ]
            if not equipe:
                continue
            participacao = _participacao(equipe, loja.cod_loja, (ano, mes), receita_vendedor, cat)
            valores = [round(total_loja * p, config.CASAS_DECIMAIS_DINHEIRO) for p in participacao]
            maior = int(np.argmax(participacao))
            valores[maior] = round(
                valores[maior] + total_loja - sum(valores), config.CASAS_DECIMAIS_DINHEIRO
            )
            linhas.extend(
                (date(ano, mes, 1), v.cod_vendedor, valor)
                for v, valor in zip(equipe, valores, strict=True)
            )
    df = pd.DataFrame(linhas, columns=["competencia", "cod_vendedor", "valor_meta"])
    df["competencia"] = pd.to_datetime(df["competencia"])
    return df


def _participacao(equipe, cod_loja, mes, receita_vendedor, cat) -> np.ndarray:
    """Participação de cada vendedor da equipe (soma 1): histórica, ou estrutural sem histórico."""
    anteriores = [_mes_anterior(mes, -k) for k in range(1, config.MESES_HISTORICO_PARTICIPACAO + 1)]
    do_vendedor = {
        v.cod_vendedor: sum(receita_vendedor.get((v.cod_vendedor, *m), 0.0) for m in anteriores)
        for v in cat.vendedores
        if v.cod_loja == cod_loja
    }
    total = sum(do_vendedor.values())
    historico = np.array(
        [do_vendedor[v.cod_vendedor] / total if total > 0 else 0.0 for v in equipe]
    )
    tem = historico > 0
    if tem.any():
        pesos = np.where(tem, historico, historico[tem].mean())  # sem histórico: média da loja
    else:  # nenhum histórico (primeiro mês): desempenho x dias ativos x turno
        primeiro, ultimo = date(*mes, 1), date(*mes, monthrange(*mes)[1])
        pesos = np.array(
            [
                v.desempenho
                * (
                    (
                        min(ultimo, v.data_desligamento or ultimo) - max(primeiro, v.data_admissao)
                    ).days
                    + 1
                )
                * (1.0 if v.turno == config.TURNO_INTEGRAL else config.PESO_TURNO_PARCIAL_META)
                for v in equipe
            ]
        )
    return pesos / pesos.sum()
