"""Converte um pedaço tipado em texto de ERP e injeta problemas de qualidade (para o ETL da Fase 2).

Cada problema injetado é registrado em _problemas_qualidade.csv, com a regra esperada de correção.
"""

import numpy as np
import pandas as pd

from src import config
from src.gerador.escrita import RegistroCsv, formatar_dinheiro, formatar_dinheiro_br

COLUNAS_PROBLEMAS = [
    "arquivo",
    "linha_arquivo",
    "coluna",
    "tipo_problema",
    "valor_original",
    "valor_gravado",
    "regra_correcao",
]
REGRA_DATA = "converter para DATE aceitando dd/mm/aaaa e aaaa-mm-dd"
REGRA_SKU = "remover espacos e converter para maiusculas"
REGRA_HORA = "converter para TIME aceitando HH:MM:SS, HH:MM, HHhMM e HH:MM AM/PM"
REGRA_NOME = "remover espacos extras e padronizar caixa (nome proprio)"
REGRA_VALOR_BR = "converter texto brasileiro (1.234,56) para NUMERIC"
REGRA_NULO_RECALCULAVEL = "recalcular: quantidade * preco_unitario - receita_liquida"
REGRA_NULO_PADRAO = "tratar nulo: usar 'NAO INFORMADO'"


def converter_para_texto(
    df: pd.DataFrame,
    colunas_data: list[str],
    colunas_valor: list[str],
    colunas_texto: list[str],
    colunas_hora: list[str] | None = None,
) -> pd.DataFrame:
    """Formato 'limpo' do ERP: datas dd/mm/aaaa e dinheiro com ponto decimal."""
    saida = pd.DataFrame(index=df.index)
    for coluna in colunas_data:
        saida[coluna] = df[coluna].dt.strftime(config.FORMATO_DATA_BR).fillna("")
    for coluna in colunas_hora or []:
        saida[coluna] = df[coluna].dt.strftime(config.FORMATO_HORA)
    for coluna in colunas_valor:
        saida[coluna] = [formatar_dinheiro(v) for v in df[coluna]]
    for coluna in colunas_texto:
        saida[coluna] = df[coluna].fillna("").astype(str)
    return saida


def injetar_problemas(
    texto: pd.DataFrame,
    tipado: pd.DataFrame,
    *,
    arquivo: str,
    linha_inicial: int,
    colunas_data: list[str],
    colunas_valor: list[str],
    coluna_sku: str | None,
    nulos: dict[str, str],
    rng: np.random.Generator,
    registro: RegistroCsv,
    linhas_protegidas: np.ndarray | None = None,
    colunas_hora: list[str] | None = None,
    colunas_nome: list[str] | None = None,
) -> pd.DataFrame:
    """Degrada `texto` (colunas em str) e registra cada alteração. Devolve o novo DataFrame.

    Os problemas são exceção: exatamente `TAXA_LINHAS_COM_PROBLEMA` das linhas recebem um único
    problema, sorteado entre os tipos aplicáveis ao arquivo (pesos em `PESO_PROBLEMA`).
    `nulos` mapeia coluna -> regra de correção. `linhas_protegidas` (opcional) são linhas que não
    podem virar nulo, para não apagar a evidência de uma anomalia injetada.
    """
    n = len(texto)
    protegidas = np.zeros(n, dtype=bool) if linhas_protegidas is None else linhas_protegidas
    texto = texto.copy()
    linhas = np.arange(n) + linha_inicial

    def registrar(posicoes, coluna, tipo, originais, gravados, regra):
        registro.adicionar(
            (arquivo, int(linhas[i]), coluna, tipo, o, g, regra)
            for i, o, g in zip(posicoes, originais, gravados, strict=True)
        )

    def gravar(pos, coluna, novos):
        texto.loc[texto.index[pos], coluna] = novos

    def aplicar_nulo(coluna, regra):
        def aplicar(pos):
            originais = texto[coluna].to_numpy()[pos]
            gravar(pos, coluna, "")
            registrar(pos, coluna, config.PROBLEMA_VALOR_NULO, originais, [""] * len(pos), regra)

        return aplicar

    def aplicar_data(coluna):
        def aplicar(pos):
            originais = texto[coluna].to_numpy()[pos]
            novos = tipado[coluna].dt.strftime(config.FORMATO_DATA_ISO).to_numpy()[pos]
            gravar(pos, coluna, novos)
            registrar(pos, coluna, config.PROBLEMA_DATA_FORMATO_MISTO, originais, novos, REGRA_DATA)

        return aplicar

    def aplicar_hora(coluna):
        def aplicar(pos):
            variantes = rng.integers(0, len(config.FORMATOS_HORA_ALTERNATIVOS), len(pos))
            originais = texto[coluna].to_numpy()[pos]
            novos = [
                tipado[coluna].iat[i].strftime(config.FORMATOS_HORA_ALTERNATIVOS[v])
                for i, v in zip(pos, variantes, strict=True)
            ]
            gravar(pos, coluna, novos)
            registrar(pos, coluna, config.PROBLEMA_HORA_FORMATO_MISTO, originais, novos, REGRA_HORA)

        return aplicar

    def aplicar_nome(coluna):
        def aplicar(pos):
            variantes = rng.integers(0, 3, len(pos))
            originais = texto[coluna].to_numpy()[pos]
            novos = [_sujar_nome(nome, v) for nome, v in zip(originais, variantes, strict=True)]
            gravar(pos, coluna, novos)
            registrar(pos, coluna, config.PROBLEMA_NOME_SUJO, originais, novos, REGRA_NOME)

        return aplicar

    def aplicar_sku(pos):
        variantes = rng.integers(0, config.VARIANTES_SKU_SUJO, len(pos))
        originais = texto[coluna_sku].to_numpy()[pos]
        novos = [_sujar_sku(sku, v) for sku, v in zip(originais, variantes, strict=True)]
        gravar(pos, coluna_sku, novos)
        registrar(pos, coluna_sku, config.PROBLEMA_SKU_SUJO, originais, novos, REGRA_SKU)

    def aplicar_valor(pos):  # todas as colunas de valor da linha viram texto brasileiro
        for coluna in colunas_valor:
            alvo = np.array([i for i in pos if texto[coluna].iat[i] != ""], dtype=int)
            originais = texto[coluna].to_numpy()[alvo]
            novos = [formatar_dinheiro_br(float(v)) for v in originais]
            gravar(alvo, coluna, novos)
            registrar(
                alvo, coluna, config.PROBLEMA_VALOR_TEXTO_BR, originais, novos, REGRA_VALOR_BR
            )

    # (peso, aplicador, é nulo?) — o peso de cada tipo se divide entre as suas colunas
    pesos = config.PESO_PROBLEMA
    tipos: list[tuple[float, object, bool]] = []
    tipos += [(pesos["nulo"] / len(nulos), aplicar_nulo(c, r), True) for c, r in nulos.items()]
    tipos += [(pesos["data"] / len(colunas_data), aplicar_data(c), False) for c in colunas_data]
    horas = colunas_hora or []
    tipos += [(pesos["hora"] / len(horas), aplicar_hora(c), False) for c in horas]
    nomes = colunas_nome or []
    tipos += [(pesos["nome"] / len(nomes), aplicar_nome(c), False) for c in nomes]
    if coluna_sku:
        tipos.append((pesos["sku"], aplicar_sku, False))
    if colunas_valor:
        tipos.append((pesos["valor"], aplicar_valor, False))

    n_problemas = round(config.TAXA_LINHAS_COM_PROBLEMA * n)
    if n_problemas == 0 or not tipos:
        return texto
    escolhidas = np.sort(rng.choice(n, size=n_problemas, replace=False))
    p = np.array([peso for peso, _, _ in tipos])
    sorteio = rng.choice(len(tipos), size=n_problemas, p=p / p.sum())
    e_nulo = np.array([nulo for _, _, nulo in tipos])
    primeiro_comum = int(np.flatnonzero(~e_nulo)[0]) if (~e_nulo).any() else None
    for k in np.flatnonzero(e_nulo[sorteio] & protegidas[escolhidas]):
        sorteio[k] = -1 if primeiro_comum is None else primeiro_comum
    for indice, (_, aplicar, _) in enumerate(tipos):
        pos = escolhidas[sorteio == indice]
        if len(pos):
            aplicar(pos)
    return texto


def _sujar_sku(sku: str, variante: int) -> str:
    if variante == 0:
        return f" {sku} "
    if variante == 1:
        return sku.lower()
    if variante == 2:
        return f"{sku.lower()} "
    return sku.replace("-", " - ")


def _sujar_nome(nome: str, variante: int) -> str:
    if variante == 0:
        return f"  {nome.replace(' ', '   ')} "
    if variante == 1:
        return nome.upper()
    return nome.lower()
