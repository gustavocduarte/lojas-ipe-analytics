"""Lotação dos vendedores por setor (com o histórico de trocas) e reatribuição dos cupons.

A lotação diz em que setor o vendedor trabalha em cada período. Ela não altera nenhum cupom: o
gerador de vendas sorteia o vendedor como sempre e, só depois, `reatribuir_vendedores` troca o
vendedor de parte dos cupons por um da mesma loja, ativo na data e lotado no setor do item de
maior receita do cupom. Tudo aqui usa fluxos aleatórios próprios (`FLUXO_LOTACAO`,
`FLUXO_REATRIBUICAO`), então o resto dos dados gerados não muda.

Cada vendedor também tem uma habilidade por setor (`config.HABILIDADE_FAIXA`): o quanto ele rende
mais ou menos do que a média quando está lotado lá. É o que o simulador de troca de setor tenta
recuperar a partir das vendas; ela só vai para o gabarito de testes.
"""

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from src import config
from src.gerador.catalogo import SETORES, Catalogo
from src.gerador.parametros import ParametrosGeracao, rng_para


@dataclass(frozen=True)
class PeriodoLotacao:
    cod_vendedor: str
    setor: str
    data_inicio: date
    data_fim: date | None  # None = vigente
    motivo: str


@dataclass(frozen=True)
class Troca:
    cod_vendedor: str
    data_troca: date
    setor_origem: str
    setor_destino: str


@dataclass
class Lotacao:
    periodos: list[PeriodoLotacao]
    trocas: list[Troca]
    habilidade: dict[tuple[str, str], float]  # (cod_vendedor, setor) -> fator de desempenho

    def setor_em(self, cod_vendedor: str, dia: date) -> str | None:
        for p in self.periodos:
            if p.cod_vendedor == cod_vendedor and p.data_inicio <= dia:
                if p.data_fim is None or dia <= p.data_fim:
                    return p.setor
        return None


def _extremos_ativos(v, params: ParametrosGeracao) -> tuple[date, date]:
    """Primeiro e último dia do vendedor dentro do período gerado."""
    inicio = max(v.data_admissao, params.data_inicio)
    fim = min(v.data_desligamento or params.data_fim, params.data_fim)
    return inicio, fim


def _lotacao_inicial(cat: Catalogo, params: ParametrosGeracao, rng) -> dict[str, str]:
    """Setor de cada vendedor na entrada: a cada admissão, o setor da loja com mais falta de gente
    (pelo peso de cada setor, `LOTACAO_PESO_DO_SETOR`), de modo que todo setor tenha alguém sempre
    que possível."""
    pesos = np.array([config.LOTACAO_PESO_DO_SETOR[s] for s in SETORES])
    escolhido: dict[str, str] = {}
    entrada: dict[str, date] = {}
    saida: dict[str, date] = {}
    for v in cat.vendedores:
        entrada[v.cod_vendedor], saida[v.cod_vendedor] = _extremos_ativos(v, params)
    por_loja: dict[str, list] = {}
    for v in cat.vendedores:
        por_loja.setdefault(v.cod_loja, []).append(v)
    for lista in por_loja.values():
        for v in sorted(lista, key=lambda x: (entrada[x.cod_vendedor], x.cod_vendedor)):
            dia = entrada[v.cod_vendedor]
            ativos = [
                o.cod_vendedor
                for o in lista
                if o.cod_vendedor in escolhido
                and entrada[o.cod_vendedor] <= dia <= saida[o.cod_vendedor]
            ]
            quantos = np.array([sum(escolhido[a] == s for a in ativos) for s in SETORES])
            falta = pesos * (len(ativos) + 1) - quantos + rng.uniform(0, 1e-3, len(SETORES))
            if len(lista) >= len(SETORES):  # loja que comporta: todo setor ganha alguém primeiro
                falta = falta + 10.0 * (quantos == 0)
            escolhido[v.cod_vendedor] = SETORES[int(np.argmax(falta))]
    return escolhido


def _cobertos(
    periodos: list[PeriodoLotacao],
    cat: Catalogo,
    dia: date,
    cod_loja: str,
    setor: str,
    ignorar: str,
) -> bool:
    """Há outro vendedor da loja lotado no setor nesse dia?"""
    da_loja = {v.cod_vendedor for v in cat.vendedores if v.cod_loja == cod_loja}
    return any(
        p.cod_vendedor in da_loja and p.cod_vendedor != ignorar and p.setor == setor
        and p.data_inicio <= dia and (p.data_fim is None or dia <= p.data_fim)
        for p in periodos
    )  # fmt: skip


def montar_lotacao(params: ParametrosGeracao, cat: Catalogo) -> Lotacao:
    """Lotação inicial de todos, trocas de setor de cerca de `LOTACAO_FRACAO_QUE_TROCA` dos
    vendedores (alguns trocam duas vezes) e habilidade por setor de cada um."""
    rng = rng_para(params.semente, config.FLUXO_LOTACAO)
    habilidade = {
        (v.cod_vendedor, setor): float(round(rng.uniform(*config.HABILIDADE_FAIXA), 3))
        for v in cat.vendedores
        for setor in SETORES
    }
    inicial = _lotacao_inicial(cat, params, rng)
    extremos = {v.cod_vendedor: _extremos_ativos(v, params) for v in cat.vendedores}

    # cada vendedor vira uma lista de (início, setor, motivo) em ordem de data
    segmentos: dict[str, list[tuple[date, str, str]]] = {}
    for v in cat.vendedores:
        entrada = extremos[v.cod_vendedor][0]
        motivo = (
            config.MOTIVO_LOTACAO_INICIAL
            if v.data_admissao < params.data_inicio
            else config.MOTIVO_ADMISSAO
        )
        segmentos[v.cod_vendedor] = [(entrada, inicial[v.cod_vendedor], motivo)]

    def periodos_atuais() -> list[PeriodoLotacao]:
        return _montar_periodos(segmentos, extremos, cat)

    minimo = timedelta(days=config.LOTACAO_DIAS_MINIMOS_ANTES_E_DEPOIS)
    janela_ini, janela_fim = config.LOTACAO_JANELA_TROCAS

    ordem = [cat.vendedores[i] for i in rng.permutation(len(cat.vendedores))]
    quero = round(config.LOTACAO_FRACAO_QUE_TROCA * len(cat.vendedores))
    quero_duas = round(config.LOTACAO_FRACAO_TROCA_DUPLA * quero)
    trocas: list[Troca] = []
    trocaram = 0
    for v in ordem:
        if trocaram >= quero:
            break
        entrada, saida = extremos[v.cod_vendedor]
        vezes = 2 if trocaram < quero_duas else 1
        feitas: list[Troca] = []
        segmentos_antes = list(segmentos[v.cod_vendedor])
        for _ in range(vezes):
            ultimo_inicio = segmentos[v.cod_vendedor][-1][0]
            cedo = max(janela_ini, ultimo_inicio + minimo)
            tarde = min(janela_fim, saida - minimo)
            if cedo > tarde:
                break
            dia = cedo + timedelta(days=int(rng.integers(0, (tarde - cedo).days + 1)))
            origem = segmentos[v.cod_vendedor][-1][1]
            if not _cobertos(periodos_atuais(), cat, dia, v.cod_loja, origem, v.cod_vendedor):
                break  # o setor de origem ficaria sem ninguém na loja
            destinos = [s for s in SETORES if s != origem]
            pesos = np.array([config.LOTACAO_PESO_DO_SETOR[s] for s in destinos])
            destino = destinos[int(rng.choice(len(destinos), p=pesos / pesos.sum()))]
            segmentos[v.cod_vendedor].append((dia, destino, config.MOTIVO_TROCA_DE_SETOR))
            feitas.append(Troca(v.cod_vendedor, dia, origem, destino))
        if (
            len(feitas) < vezes
        ):  # só conta quem trocou o tanto sorteado; senão, desfaz e tenta outro
            segmentos[v.cod_vendedor] = segmentos_antes
            continue
        trocas.extend(feitas)
        trocaram += 1
    return Lotacao(
        periodos_atuais(), sorted(trocas, key=lambda t: (t.data_troca, t.cod_vendedor)), habilidade
    )


def _montar_periodos(segmentos, extremos, cat: Catalogo) -> list[PeriodoLotacao]:
    periodos = []
    for v in cat.vendedores:
        lista = segmentos[v.cod_vendedor]
        saida = extremos[v.cod_vendedor][1]
        for k, (inicio, setor, motivo) in enumerate(lista):
            if k + 1 < len(lista):
                fim: date | None = lista[k + 1][0] - timedelta(days=1)
            else:
                fim = v.data_desligamento  # desligado: encerra no desligamento; ativo: vigente
            if fim is not None and fim > saida:
                fim = saida
            periodos.append(PeriodoLotacao(v.cod_vendedor, setor, inicio, fim, motivo))
    return periodos


# ---------------------------------------------------------------------------------------------
class Reatribuidor:
    """Troca o vendedor de parte dos cupons (mesma loja, ativo na data, no turno do cupom),
    preferindo quem está lotado no setor do item de maior receita."""

    def __init__(self, cat: Catalogo, lotacao: Lotacao, indices_vendedor: dict[str, int]) -> None:
        self.cat, self.lotacao = cat, lotacao
        self.indice = indices_vendedor
        self.n_setores = len(SETORES)
        n = len(cat.vendedores)
        self.habilidade = np.ones((n, self.n_setores))
        for (cod, setor), valor in lotacao.habilidade.items():
            self.habilidade[self.indice[cod], SETORES.index(setor)] = valor
        self.periodos_do_vendedor: dict[int, list[tuple[date, date, int]]] = {}
        for p in lotacao.periodos:
            fim = p.data_fim or date(9999, 12, 31)
            self.periodos_do_vendedor.setdefault(self.indice[p.cod_vendedor], []).append(
                (p.data_inicio, fim, SETORES.index(p.setor))
            )

    def setores_no_mes(self, dias: list[date]) -> np.ndarray:
        """Matriz (vendedores x dias) com o índice do setor de lotação (-1 = sem lotação)."""
        matriz = np.full((len(self.cat.vendedores), len(dias)), -1)
        for v, lista in self.periodos_do_vendedor.items():
            for inicio, fim, setor in lista:
                for k, dia in enumerate(dias):
                    if inicio <= dia <= fim:
                        matriz[v, k] = setor
        return matriz

    def reatribuir(
        self, *, vendedor, dia_do_cupom, loja_do_cupom, classe_do_cupom, setor_do_cupom, elegivel,
        setor_lotado, ativo_no_dia, turno_ok, desempenho, proibido, vendedores_da_loja, rng,
    ):  # fmt: skip
        """Devolve o vetor de vendedores por cupom, com a parte reatribuída trocada.

        Para cada cupom elegível, sorteia entre os vendedores da loja lotados no setor do cupom
        (ativos, de preferência do turno do cupom, ponderados por desempenho x habilidade); o
        escolhido fica com o cupom com chance `LOTACAO_PROB_REATRIBUIR` mais a habilidade (acima
        de 1 aumenta, abaixo diminui): quem rende mais fica com mais."""
        novo = vendedor.copy()
        posicoes = np.flatnonzero(elegivel)
        chave = (dia_do_cupom * 64 + loja_do_cupom) * 8 + classe_do_cupom
        for grupo in _grupos(chave[posicoes], posicoes):
            dia, loja, classe = (
                dia_do_cupom[grupo[0]],
                loja_do_cupom[grupo[0]],
                classe_do_cupom[grupo[0]],
            )
            candidatos = vendedores_da_loja[loja]
            candidatos = candidatos[ativo_no_dia[candidatos, dia] & ~proibido[candidatos]]
            for setor in np.unique(setor_do_cupom[grupo]):
                lotados = candidatos[setor_lotado[candidatos, dia] == setor]
                no_turno = lotados[turno_ok[lotados, classe]]
                lotados = (
                    no_turno if len(no_turno) else lotados
                )  # sem ninguém no turno, qualquer um
                if len(lotados) == 0:
                    continue
                cupons = grupo[setor_do_cupom[grupo] == setor]
                habilidade = self.habilidade[lotados, setor]
                pesos = desempenho[lotados] * habilidade**config.LOTACAO_EXPOENTE_HABILIDADE
                escolhidos = lotados[
                    rng.choice(len(lotados), size=len(cupons), p=pesos / pesos.sum())
                ]
                desvio = self.habilidade[escolhidos, setor] - 1.0
                chance = np.clip(
                    config.LOTACAO_PROB_REATRIBUIR
                    + config.LOTACAO_SENSIBILIDADE_HABILIDADE * desvio,
                    0.0,
                    1.0,
                )
                aceitos = rng.random(len(cupons)) < chance
                novo[cupons[aceitos]] = escolhidos[aceitos]
        return novo


def _grupos(chaves: np.ndarray, posicoes: np.ndarray):
    """Agrupa `posicoes` pelas `chaves` iguais."""
    if len(posicoes) == 0:
        return []
    ordem = np.argsort(chaves, kind="stable")
    cortes = np.flatnonzero(np.diff(chaves[ordem])) + 1
    return [posicoes[g] for g in np.split(ordem, cortes)]
