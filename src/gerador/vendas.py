"""Geração de cupons e itens de venda, mês a mês, e das metas mensais."""

from datetime import date

import numpy as np
import pandas as pd

from src import calendario, config
from src.gerador.catalogo import SETORES, Catalogo, horario_funcionamento
from src.gerador.parametros import ParametrosGeracao, rng_para
from src.gerador.sazonalidade import Sazonalidade

COLUNAS_VENDAS = [
    "id_venda_erp",
    "numero_cupom",
    "numero_item",
    "data_venda",
    "hora_venda",
    "cod_loja",
    "caixa",
    "cod_vendedor",
    "cod_cliente",
    "cod_forma_pagamento",
    "numero_parcelas",
    "cod_campanha",
    "sku",
    "quantidade",
    "preco_unitario",
    "desconto",
    "receita_liquida",
    "custo_total",
    "total_cupom",
    "status",
    "motivo_cancelamento_devolucao",
]
COLUNAS_VALOR_VENDAS = [
    "preco_unitario",
    "desconto",
    "receita_liquida",
    "custo_total",
    "total_cupom",
]
COLUNAS_TEXTO_VENDAS = [
    "id_venda_erp",
    "numero_cupom",
    "numero_item",
    "cod_loja",
    "caixa",
    "cod_vendedor",
    "cod_cliente",
    "cod_forma_pagamento",
    "numero_parcelas",
    "cod_campanha",
    "sku",
    "quantidade",
    "status",
    "motivo_cancelamento_devolucao",
]
CODIGOS_FORMAS = [codigo for codigo, _ in config.FORMAS_PAGAMENTO]
INDICE_ELETRO = SETORES.index("Eletro")
SEM_DESLIGAMENTO = date(9999, 12, 31)
CODIGO_TURNO = {config.TURNO_MANHA: 0, config.TURNO_TARDE: 1, config.TURNO_INTEGRAL: 2}
TURNO_INTEGRAL = CODIGO_TURNO[config.TURNO_INTEGRAL]


def pesos_do_mes(
    sazon: Sazonalidade, cat: Catalogo, ano: int, mes: int, params: ParametrosGeracao
) -> tuple[list[date], np.ndarray]:
    """Dias do mês e matriz de pesos (dias x lojas); lojas ainda não abertas pesam zero."""
    dias = calendario.dias_do_mes(ano, mes, params.data_inicio, params.data_fim)
    pesos = np.zeros((len(dias), len(cat.lojas)))
    for i, dia in enumerate(dias):
        base = sazon.fator_dia(dia)
        for j, loja in enumerate(cat.lojas):
            if loja.data_abertura <= dia:
                pesos[i, j] = base * loja.porte
    return dias, pesos


def distribuir_linhas(total: int, pesos_por_mes: list[float]) -> list[int]:
    """Reparte `total` entre os meses proporcionalmente (maior resto), somando exato."""
    soma = sum(pesos_por_mes)
    cotas = [total * p / soma for p in pesos_por_mes]
    base = [int(c) for c in cotas]
    faltam = total - sum(base)
    ordem = sorted(range(len(cotas)), key=lambda k: cotas[k] - base[k], reverse=True)
    for k in ordem[:faltam]:
        base[k] += 1
    return base


class GeradorVendas:
    """Gera os cupons do mês. Guarda os cadastros já convertidos em arrays (calculados uma vez)."""

    def __init__(self, params: ParametrosGeracao, cat: Catalogo, sazon: Sazonalidade) -> None:
        self.params, self.cat, self.sazon = params, cat, sazon
        lojas = cat.lojas
        self.codigos_loja = np.array([lj.cod_loja for lj in lojas])
        self.mix_setor = cat.mix_setor_por_loja()
        self.fator_preco_loja = np.array([lj.fator_preco for lj in lojas])
        self.horarios = [[horario_funcionamento(lj.formato, w) for w in range(7)] for lj in lojas]
        self.n_caixas = np.array(
            [max(config.CAIXAS_MINIMO, round(config.CAIXAS_POR_PORTE * lj.porte)) for lj in lojas]
        )

        produtos = cat.produtos
        self.skus = np.array([p.sku for p in produtos])
        self.preco_lista = np.array([p.preco_lista for p in produtos])
        self.custo_unitario = np.array([p.custo_unitario for p in produtos])
        self.produtos_do_setor = []
        for setor in SETORES:
            indices = np.array([i for i, p in enumerate(produtos) if p.setor == setor])
            pesos = np.array([produtos[i].popularidade for i in indices])
            self.produtos_do_setor.append((indices, pesos / pesos.sum()))
        self.lambda_quantidade = np.array(
            [config.QUANTIDADE_MEDIA_EXTRA_POR_SETOR[s] for s in SETORES]
        )

        vend = cat.vendedores
        self.cod_vendedor = np.array([v.cod_vendedor for v in vend])
        self.admissao = np.array([v.data_admissao for v in vend], dtype="datetime64[D]")
        self.desligamento = np.array(
            [v.data_desligamento or SEM_DESLIGAMENTO for v in vend], dtype="datetime64[D]"
        )
        self.turno = np.array([CODIGO_TURNO[v.turno] for v in vend])
        self.desempenho = np.array([v.desempenho for v in vend])
        self.vendedores_da_loja = [
            np.flatnonzero([v.cod_loja == lj.cod_loja for v in vend]) for lj in lojas
        ]
        self.vendedor_cancela_muito = self._escolher_vendedores_cancelamento_alto()

        self.clientes_da_loja = []
        for loja in lojas:
            clientes = sorted(
                (c for c in cat.clientes if c.cod_loja == loja.cod_loja),
                key=lambda c: c.data_cadastro,
            )
            self.clientes_da_loja.append(
                (
                    np.array([c.cod_cliente for c in clientes]),
                    np.array([c.data_cadastro for c in clientes], dtype="datetime64[D]"),
                    np.cumsum([c.peso_recorrencia for c in clientes]),
                )
            )

        self.codigos_campanha = np.array([c.cod_campanha for c in cat.campanhas] + [""])
        self.desconto_campanha = np.array([c.desconto_medio for c in cat.campanhas] + [0.0])
        self.total_meses = max(
            1,
            (params.data_fim.year - params.data_inicio.year) * 12
            + params.data_fim.month
            - params.data_inicio.month,
        )

    def _escolher_vendedores_cancelamento_alto(self) -> np.ndarray:
        """Poucos vendedores veteranos de lojas grandes terão taxa de cancelamento anormal."""
        quantidade = self.params.quantidade_anomalias[config.ANOMALIA_VENDEDOR_CANCELAMENTO]
        porte = {lj.cod_loja: lj.porte for lj in self.cat.lojas}
        candidatos = [
            i
            for i, v in enumerate(self.cat.vendedores)
            if v.turno == config.TURNO_INTEGRAL
            and v.data_desligamento is None
            and porte[v.cod_loja] >= 1.0
        ]
        rng = rng_para(self.params.semente, config.FLUXO_PLANO_ANOMALIAS, 99)
        escolhidos = rng.choice(candidatos, size=min(quantidade, len(candidatos)), replace=False)
        marcados = np.zeros(len(self.cat.vendedores), dtype=bool)
        marcados[escolhidos] = True
        return marcados

    # -------------------------------------------------------------------------------------
    def _sortear_hora(self, loja: int, dia_semana: int, n: int, rng: np.random.Generator):
        abre, fecha = self.horarios[loja][dia_semana]
        pesos = np.array(config.PESO_POR_HORA, dtype=float)
        horas = np.arange(len(pesos))
        pesos[(horas < abre) | (horas >= fecha)] = 0.0
        return rng.choice(len(pesos), size=n, p=pesos / pesos.sum())

    def _escolher_vendedores(self, idx_dia, idx_loja, hora, dias_np, n_lojas, rng) -> np.ndarray:
        """Um vendedor ativo e do turno certo para cada cupom, ponderado pelo desempenho."""
        classe = (hora >= config.HORA_CORTE_TURNO).astype(int)
        chave = (idx_dia * n_lojas + idx_loja) * 2 + classe
        ordem = np.argsort(chave, kind="stable")
        cortes = np.flatnonzero(np.diff(chave[ordem])) + 1
        escolhido = np.empty(len(chave), dtype=int)
        for grupo in np.split(ordem, cortes):
            primeiro = grupo[0]
            dia = dias_np[idx_dia[primeiro]]
            candidatos = self.vendedores_da_loja[idx_loja[primeiro]]
            ativo = (self.admissao[candidatos] <= dia) & (self.desligamento[candidatos] > dia)
            turno_ok = (self.turno[candidatos] == TURNO_INTEGRAL) | (
                self.turno[candidatos] == classe[primeiro]
            )
            candidatos = candidatos[ativo & turno_ok]
            pesos = self.desempenho[candidatos]
            escolhido[grupo] = rng.choice(candidatos, size=len(grupo), p=pesos / pesos.sum())
        return escolhido

    def _escolher_clientes(self, idx_dia, idx_loja, dias_np, n_lojas, rng) -> np.ndarray:
        """Cliente identificado (ou vazio): só quem já estava cadastrado, fiéis compram mais."""
        n = len(idx_dia)
        cliente = np.full(n, "", dtype=object)
        identificado = rng.random(n) < config.PROB_CLIENTE_IDENTIFICADO
        for j in range(n_lojas):
            codigos, cadastros, acumulado = self.clientes_da_loja[j]
            pos = np.flatnonzero(identificado & (idx_loja == j))
            if len(pos) == 0 or len(codigos) == 0:
                continue
            elegiveis = np.searchsorted(cadastros, dias_np[idx_dia[pos]], side="right")
            valido = elegiveis > 0
            pos, elegiveis = pos[valido], elegiveis[valido]
            sorteio = rng.random(len(pos)) * acumulado[elegiveis - 1]
            posicao = np.minimum(np.searchsorted(acumulado, sorteio, side="right"), elegiveis - 1)
            cliente[pos] = codigos[posicao]
        return cliente

    def _formas_pagamento(self, ano, mes, tem_eletro, rng) -> tuple[np.ndarray, np.ndarray]:
        meses_passados = (
            (ano - self.params.data_inicio.year) * 12 + mes - self.params.data_inicio.month
        )
        t = min(1.0, meses_passados / self.total_meses)
        base = np.array(
            [
                config.PARTICIPACAO_PAGAMENTO[c][0]
                + t * (config.PARTICIPACAO_PAGAMENTO[c][1] - config.PARTICIPACAO_PAGAMENTO[c][0])
                for c in CODIGOS_FORMAS
            ]
        )
        probs = np.tile(base, (len(tem_eletro), 1))
        parcelado, dinheiro = CODIGOS_FORMAS.index("CRP"), CODIGOS_FORMAS.index("DIN")
        probs[:, parcelado] *= np.where(tem_eletro, config.MULT_PARCELADO_ELETRO, 1.0)
        probs[:, dinheiro] *= np.where(tem_eletro, config.MULT_DINHEIRO_ELETRO, 1.0)
        probs /= probs.sum(axis=1, keepdims=True)
        forma = np.minimum(
            (np.cumsum(probs, axis=1) < rng.random(len(tem_eletro))[:, None]).sum(axis=1),
            len(CODIGOS_FORMAS) - 1,
        )
        parcelas = np.ones(len(tem_eletro), dtype=int)
        e_parcelado = forma == parcelado
        comum = rng.integers(config.PARCELAS_COMUM[0], config.PARCELAS_COMUM[1] + 1, len(forma))
        eletro = rng.integers(config.PARCELAS_ELETRO[0], config.PARCELAS_ELETRO[1] + 1, len(forma))
        parcelas[e_parcelado] = np.where(tem_eletro, eletro, comum)[e_parcelado]
        return np.array(CODIGOS_FORMAS)[forma], parcelas

    # -------------------------------------------------------------------------------------
    def gerar_mes(
        self,
        *,
        ano: int,
        mes: int,
        dias: list[date],
        pesos: np.ndarray,
        n_itens: int,
        plano: dict[str, int],
        rng: np.random.Generator,
    ) -> pd.DataFrame:
        """Itens de cupom do mês (tipados). Colunas `_...` guardam anomalias e dados auxiliares."""
        cat = self.cat
        n_dias, n_lojas = pesos.shape
        dias_np = np.array(dias, dtype="datetime64[D]")
        dia_semana = np.array([d.weekday() for d in dias])

        # --- cupons: dia, loja, hora -------------------------------------------------------
        media_itens = 1 + config.LAMBDA_ITENS_EXTRA_POR_CUPOM
        n_dup_pedido = plano[config.ANOMALIA_CUPOM_DUPLICADO]
        n_cupons = max(1, round(n_itens / media_itens) - n_dup_pedido)
        contagens = rng.multinomial(n_cupons, (pesos / pesos.sum()).ravel())
        celulas = np.repeat(np.arange(n_dias * n_lojas), contagens)
        idx_dia, idx_loja = celulas // n_lojas, celulas % n_lojas
        n_c = len(celulas)
        semana_cupom = dia_semana[idx_dia]

        hora = np.zeros(n_c, dtype=int)
        for j in range(n_lojas):
            for w in range(7):
                mascara = (idx_loja == j) & (semana_cupom == w)
                if mascara.any():
                    hora[mascara] = self._sortear_hora(j, w, int(mascara.sum()), rng)
        minuto = rng.integers(0, 60, n_c)
        segundo = rng.integers(0, 60, n_c)
        ordem = np.lexsort((segundo, minuto, hora, celulas))  # dentro de cada loja/dia, por hora
        hora, minuto, segundo = hora[ordem], minuto[ordem], segundo[ordem]

        # --- itens por cupom (soma exata = n_itens, contando as cópias dos duplicados) -----
        limite_dup = int(n_c * config.LIMITE_ITENS_REPARTIDOS)
        n_dup = min(n_dup_pedido, limite_dup)
        dup = (
            np.sort(rng.choice(limite_dup, size=n_dup, replace=False))
            if n_dup
            else np.array([], int)
        )
        k = 1 + rng.poisson(config.LAMBDA_ITENS_EXTRA_POR_CUPOM, n_c)
        livres_ajuste = np.setdiff1d(np.arange(n_c), dup)
        diferenca = (n_itens - int(k[dup].sum())) - int(k.sum())
        if diferenca > 0:
            k += np.bincount(rng.choice(livres_ajuste, size=diferenca), minlength=n_c)
        while diferenca < 0:
            elegiveis = livres_ajuste[k[livres_ajuste] > 1]
            retirar = rng.choice(elegiveis, size=min(-diferenca, len(elegiveis)), replace=False)
            k[retirar] -= 1
            diferenca += len(retirar)

        ic = np.repeat(np.arange(n_c), k)  # cupom de cada item
        n = len(ic)
        inicio_cupom = np.cumsum(k) - k
        numero_item = np.arange(n) - inicio_cupom[ic] + 1
        i_dia, i_loja = idx_dia[ic], idx_loja[ic]

        # --- atributos do cupom --------------------------------------------------------------
        caixa = rng.integers(1, self.n_caixas[idx_loja] + 1)
        vendedor = self._escolher_vendedores(idx_dia, idx_loja, hora, dias_np, n_lojas, rng)
        cliente = self._escolher_clientes(idx_dia, idx_loja, dias_np, n_lojas, rng)

        campanha_do_dia = np.full(n_dias, -1)
        for i, dia in enumerate(dias):
            for c, campanha in enumerate(cat.campanhas):
                if campanha.data_inicio <= dia <= campanha.data_fim:
                    campanha_do_dia[i] = c
                    break
        na_campanha = (campanha_do_dia[idx_dia] >= 0) & (
            rng.random(n_c) < config.PROB_CUPOM_EM_CAMPANHA
        )
        campanha_cupom = np.where(na_campanha, campanha_do_dia[idx_dia], -1)

        # --- itens: setor, produto, preço, desconto, custo ---------------------------------
        mult_setor = np.array(
            [[self.sazon.multiplicador_setor(d, s) for s in SETORES] for d in dias]
        )
        probs = self.mix_setor[i_loja] * mult_setor[i_dia]
        probs /= probs.sum(axis=1, keepdims=True)
        idx_setor = np.minimum(
            (np.cumsum(probs, axis=1) < rng.random(n)[:, None]).sum(axis=1), len(SETORES) - 1
        )
        idx_produto = np.zeros(n, dtype=int)
        for s, (indices, pesos_sku) in enumerate(self.produtos_do_setor):
            mascara = idx_setor == s
            idx_produto[mascara] = rng.choice(indices, size=int(mascara.sum()), p=pesos_sku)

        quantidade = 1 + rng.poisson(self.lambda_quantidade[idx_setor])
        preco = np.round(
            self.preco_lista[idx_produto] * self.fator_preco_loja[i_loja],
            config.CASAS_DECIMAIS_DINHEIRO,
        )
        em_campanha = campanha_cupom[ic] >= 0
        media_campanha = self.desconto_campanha[campanha_cupom[ic]]
        fracao_campanha = rng.normal(media_campanha, config.DESVIO_DESCONTO_CAMPANHA)
        fracao_normal = rng.uniform(*config.FAIXA_DESCONTO_NORMAL, n)
        tem_desconto = rng.random(n) < np.where(
            em_campanha, config.PROB_DESCONTO_CAMPANHA, config.PROB_DESCONTO_NORMAL
        )
        fracao = np.where(tem_desconto, np.where(em_campanha, fracao_campanha, fracao_normal), 0.0)
        fracao = fracao.clip(0.0, config.DESCONTO_MAXIMO)
        bruto = quantidade * preco
        desconto = np.round(bruto * fracao, config.CASAS_DECIMAIS_DINHEIRO)
        receita = np.round(bruto - desconto, config.CASAS_DECIMAIS_DINHEIRO)
        custo = np.round(
            quantidade * self.custo_unitario[idx_produto], config.CASAS_DECIMAIS_DINHEIRO
        )

        # --- pagamento e status do cupom -----------------------------------------------------
        tem_eletro = np.bincount(ic, weights=(idx_setor == INDICE_ELETRO), minlength=n_c) > 0
        forma, parcelas = self._formas_pagamento(ano, mes, tem_eletro, rng)
        prob_cancelar = np.where(
            self.vendedor_cancela_muito[vendedor],
            config.PROB_CANCELAMENTO_VENDEDOR_ALTO,
            config.PROB_CANCELAMENTO,
        )
        cancelada = rng.random(n_c) < prob_cancelar
        devolvida = ~cancelada & (rng.random(n_c) < config.PROB_DEVOLUCAO)
        status = np.where(
            cancelada,
            config.STATUS_CANCELADA,
            np.where(devolvida, config.STATUS_DEVOLVIDA, config.STATUS_CONCLUIDA),
        )
        motivo = np.full(n_c, "", dtype=object)
        motivos_canc = np.array(config.MOTIVOS_CANCELAMENTO)
        motivos_dev = np.array(config.MOTIVOS_DEVOLUCAO)
        motivo[cancelada] = rng.choice(motivos_canc, size=int(cancelada.sum()))
        motivo[devolvida] = rng.choice(motivos_dev, size=int(devolvida.sum()))

        # --- anomalias de venda (nunca em cupons que serão duplicados) -----------------------
        tipo = np.full(n, "", dtype=object)
        detalhe = np.full(n, "", dtype=object)
        itens_livres = np.flatnonzero(~np.isin(ic, dup))
        negativas = rng.choice(
            itens_livres,
            size=min(plano[config.ANOMALIA_MARGEM_NEGATIVA], len(itens_livres)),
            replace=False,
        )
        custo[negativas] = np.round(
            receita[negativas]
            * rng.uniform(*config.FAIXA_CUSTO_SOBRE_RECEITA_NEGATIVA, len(negativas)),
            config.CASAS_DECIMAIS_DINHEIRO,
        )
        tipo[negativas] = config.ANOMALIA_MARGEM_NEGATIVA

        restantes = np.setdiff1d(itens_livres, negativas)
        com_desconto_alto = rng.choice(
            restantes,
            size=min(plano[config.ANOMALIA_DESCONTO_ACIMA_LIMITE], len(restantes)),
            replace=False,
        )
        frac_alta = rng.uniform(*config.FAIXA_DESCONTO_ACIMA_LIMITE, len(com_desconto_alto))
        desconto[com_desconto_alto] = np.round(
            bruto[com_desconto_alto] * frac_alta, config.CASAS_DECIMAIS_DINHEIRO
        )
        receita[com_desconto_alto] = np.round(
            bruto[com_desconto_alto] - desconto[com_desconto_alto], config.CASAS_DECIMAIS_DINHEIRO
        )
        tipo[com_desconto_alto] = config.ANOMALIA_DESCONTO_ACIMA_LIMITE
        for item, frac in zip(com_desconto_alto, frac_alta, strict=True):
            detalhe[item] = f"desconto={frac:.1%} | limite={config.DESCONTO_MAXIMO:.0%}"

        segundos_do_dia = hora * 3600 + minuto * 60 + segundo
        cupons_livres = np.setdiff1d(np.arange(n_c), dup)
        cupons_livres = cupons_livres[tipo[inicio_cupom[cupons_livres]] == ""]  # não sobrescrever
        fora = rng.choice(
            cupons_livres,
            size=min(plano[config.ANOMALIA_FORA_HORARIO], len(cupons_livres)),
            replace=False,
        )
        for c in fora:
            abre, fecha = self.horarios[idx_loja[c]][semana_cupom[c]]
            horas_fora = [h for h in range(24) if h < abre or h >= fecha]
            nova_hora = int(rng.choice(horas_fora))
            segundos_do_dia[c] = nova_hora * 3600 + minuto[c] * 60 + segundo[c]
            primeiro_item = inicio_cupom[c]
            tipo[primeiro_item] = config.ANOMALIA_FORA_HORARIO
            detalhe[primeiro_item] = (
                f"hora={nova_hora:02d}:{minuto[c]:02d} | horario_loja={abre:02d}-{fecha:02d}"
            )

        total_cupom = np.round(
            np.bincount(ic, weights=receita, minlength=n_c), config.CASAS_DECIMAIS_DINHEIRO
        )
        momento = dias_np[idx_dia].astype("datetime64[s]") + segundos_do_dia.astype(
            "timedelta64[s]"
        )

        df = pd.DataFrame(
            {
                "numero_cupom": np.array(
                    [
                        f"{config.PREFIXO_CUPOM}{ano}{mes:02d}{c:0{config.DIGITOS_CUPOM}d}"
                        for c in range(1, n_c + 1)
                    ]
                )[ic],
                "numero_item": numero_item,
                "data_venda": pd.to_datetime(dias_np[idx_dia][ic]),
                "hora_venda": pd.to_datetime(momento[ic]),
                "cod_loja": self.codigos_loja[i_loja],
                "caixa": caixa[ic],
                "cod_vendedor": self.cod_vendedor[vendedor][ic],
                "cod_cliente": cliente[ic],
                "cod_forma_pagamento": forma[ic],
                "numero_parcelas": parcelas[ic],
                "cod_campanha": self.codigos_campanha[campanha_cupom][ic],
                "sku": self.skus[idx_produto],
                "quantidade": quantidade,
                "preco_unitario": preco,
                "desconto": desconto,
                "receita_liquida": receita,
                "custo_total": custo,
                "total_cupom": total_cupom[ic],
                "status": status[ic],
                "motivo_cancelamento_devolucao": motivo[ic],
                "_setor": np.array(SETORES)[idx_setor],
                "_tipo": tipo,
                "_detalhe": detalhe,
                "_duplicata": np.zeros(n, dtype=bool),
            }
        )

        # --- cupons duplicados: cópias integrais (mesmo número de cupom) ao final do mês --------
        if len(dup):
            copias = df.loc[np.isin(ic, dup)].copy()
            copias["_tipo"] = ""
            copias["_detalhe"] = ""
            copias["_duplicata"] = True
            primeiros = copias.index[copias["numero_item"] == 1]
            copias.loc[primeiros, "_tipo"] = config.ANOMALIA_CUPOM_DUPLICADO
            copias.loc[primeiros, "_detalhe"] = [
                f"duplicata do cupom {c}" for c in copias.loc[primeiros, "numero_cupom"]
            ]
            df = pd.concat([df, copias], ignore_index=True)

        df.insert(
            0,
            "id_venda_erp",
            [
                f"{config.PREFIXO_ID_VENDA}{ano}{mes:02d}{k:0{config.DIGITOS_ID_VENDA}d}"
                for k in range(1, len(df) + 1)
            ],
        )
        return df


def gerar_metas(
    receita_realizada: dict[tuple[str, str, int, int], float],
    cat: Catalogo,
    meses: list[tuple[int, int]],
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Meta mensal por loja e setor, derivada do realizado: lojas diferem no atingimento típico."""
    linhas = []
    for ano, mes in meses:
        fim_do_mes = calendario.ultimo_dia_do_mes(ano, mes)
        for loja in cat.lojas:
            if loja.data_abertura > fim_do_mes:
                continue
            for setor in SETORES:
                realizado = receita_realizada.get((loja.cod_loja, setor, ano, mes), 0.0)
                atingimento = max(
                    config.ATINGIMENTO_MINIMO,
                    loja.atingimento_meta * rng.normal(1.0, config.DESVIO_ATINGIMENTO_MENSAL),
                )
                if realizado > 0:
                    linhas.append(
                        (
                            date(ano, mes, 1),
                            loja.cod_loja,
                            setor,
                            round(realizado / atingimento, config.CASAS_DECIMAIS_DINHEIRO),
                        )
                    )
    df = pd.DataFrame(linhas, columns=["competencia", "cod_loja", "setor", "valor_meta"])
    df["competencia"] = pd.to_datetime(df["competencia"])
    return df


def gerar_metas_vendedor(
    receita_vendedor: dict[tuple[str, int, int], float],
    cat: Catalogo,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Meta mensal por vendedor: quem tem desempenho maior tende a bater a meta, os demais não."""
    desempenho = {v.cod_vendedor: v.desempenho for v in cat.vendedores}
    linhas = []
    for (cod, ano, mes), realizado in sorted(receita_vendedor.items()):
        if realizado <= 0:
            continue
        atingimento = np.clip(
            np.sqrt(desempenho[cod]) * rng.normal(1.0, config.DESVIO_ATINGIMENTO_MENSAL),
            *config.ATINGIMENTO_META_VENDEDOR,
        )
        linhas.append(
            (
                date(ano, mes, 1),
                cod,
                round(realizado / float(atingimento), config.CASAS_DECIMAIS_DINHEIRO),
            )
        )
    df = pd.DataFrame(linhas, columns=["competencia", "cod_vendedor", "valor_meta"])
    df["competencia"] = pd.to_datetime(df["competencia"])
    return df
