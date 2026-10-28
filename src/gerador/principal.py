"""Orquestra a geração dos CSVs de ERP em data/raw/, mês a mês, com memória sob controle."""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from src import calendario, config
from src.gerador import despesas as mod_despesas
from src.gerador import qualidade, vendas
from src.gerador.catalogo import Catalogo, horario_funcionamento, montar_catalogo
from src.gerador.escrita import EscritorCsv, RegistroCsv, formatar_dinheiro
from src.gerador.parametros import ParametrosGeracao, rng_para
from src.gerador.sazonalidade import Sazonalidade
from src.memoria import memoria_livre_gb, pico_memoria_processo_gb, verificar_memoria_livre

COLUNAS_ANOMALIAS = [
    "id_anomalia",
    "tipo_anomalia",
    "arquivo",
    "linha_arquivo",
    "identificador",
    "data_referencia",
    "cod_centro_custo",
    "cod_loja",
    "valor",
    "detalhe",
]
ANOMALIAS_POR_ITEM = (config.ANOMALIA_MARGEM_NEGATIVA, config.ANOMALIA_DESCONTO_ACIMA_LIMITE)
PADRAO_ARQUIVO_VENDAS = "vendas_*.csv"


@dataclass
class ResumoGeracao:
    linhas_por_arquivo: dict[str, int] = field(default_factory=dict)
    anomalias_por_tipo: dict[str, int] = field(default_factory=dict)
    problemas_por_tipo: dict[str, int] = field(default_factory=dict)
    cupons: int = 0
    memoria_livre_inicio_gb: float = 0.0
    memoria_livre_fim_gb: float = 0.0
    pico_memoria_processo_gb: float = 0.0


def _gravar_df(df: pd.DataFrame, caminho: Path) -> int:
    with EscritorCsv(caminho, list(df.columns)) as escritor:
        escritor.escrever(df)
        return escritor.linhas


def _gravar_cadastros(
    params: ParametrosGeracao, cat: Catalogo, resumo: ResumoGeracao, problemas: RegistroCsv
) -> None:
    saida = params.diretorio_saida
    formato = config.FORMATO_DATA_BR
    lojas = pd.DataFrame(
        {
            "cod_loja": [lj.cod_loja for lj in cat.lojas],
            "nome_loja": [lj.nome_loja for lj in cat.lojas],
            "uf": [lj.uf for lj in cat.lojas],
            "regiao": [lj.regiao for lj in cat.lojas],
            "cidade": [lj.cidade for lj in cat.lojas],
            "formato": [lj.formato for lj in cat.lojas],
            "data_abertura": [lj.data_abertura.strftime(formato) for lj in cat.lojas],
        }
    )
    horarios = pd.DataFrame(
        [
            (
                lj.cod_loja,
                dia + 1,
                f"{horario_funcionamento(lj.formato, dia)[0]:02d}:00",
                f"{horario_funcionamento(lj.formato, dia)[1]:02d}:00",
            )
            for lj in cat.lojas
            for dia in range(7)
        ],
        columns=["cod_loja", "dia_semana", "hora_abertura", "hora_fechamento"],
    )  # dia_semana: 1 = segunda ... 7 = domingo (ISO)
    produtos = pd.DataFrame(
        {
            "sku": [p.sku for p in cat.produtos],
            "nome_produto": [p.nome_produto for p in cat.produtos],
            "marca": [p.marca for p in cat.produtos],
            "setor": [p.setor for p in cat.produtos],
            "categoria": [p.categoria for p in cat.produtos],
            "custo_unitario": [formatar_dinheiro(p.custo_unitario) for p in cat.produtos],
            "preco_lista": [formatar_dinheiro(p.preco_lista) for p in cat.produtos],
        }
    )
    centros = pd.DataFrame(
        {
            "cod_centro_custo": [c.cod_centro_custo for c in cat.centros_custo],
            "nome_centro_custo": [c.nome_centro_custo for c in cat.centros_custo],
            "tipo_despesa": [c.tipo_despesa for c in cat.centros_custo],
            "cod_loja": [c.cod_loja or "" for c in cat.centros_custo],
        }
    )
    feriados_periodo = calendario.feriados_do_periodo(params.data_inicio, params.data_fim)
    feriados = pd.DataFrame(
        {
            "data": [d.strftime(formato) for d in feriados_periodo],
            "nome_feriado": list(feriados_periodo.values()),
        }
    )
    formas = pd.DataFrame(
        config.FORMAS_PAGAMENTO, columns=["cod_forma_pagamento", "nome_forma_pagamento"]
    )
    campanhas = pd.DataFrame(
        {
            "cod_campanha": [c.cod_campanha for c in cat.campanhas],
            "nome_campanha": [c.nome_campanha for c in cat.campanhas],
            "data_inicio": [c.data_inicio.strftime(formato) for c in cat.campanhas],
            "data_fim": [c.data_fim.strftime(formato) for c in cat.campanhas],
            "desconto_medio_pct": [
                formatar_dinheiro(c.desconto_medio * 100) for c in cat.campanhas
            ],
        }
    )
    clientes = pd.DataFrame(
        {
            "cod_cliente": [c.cod_cliente for c in cat.clientes],
            "cidade": [c.cidade for c in cat.clientes],
            "uf": [c.uf for c in cat.clientes],
            "faixa_etaria": [c.faixa_etaria for c in cat.clientes],
            "data_cadastro_fidelidade": [c.data_cadastro.strftime(formato) for c in cat.clientes],
        }
    )

    tipado_vendedores = pd.DataFrame(
        {
            "cod_vendedor": [v.cod_vendedor for v in cat.vendedores],
            "nome_vendedor": [v.nome_vendedor for v in cat.vendedores],
            "cod_loja": [v.cod_loja for v in cat.vendedores],
            "cargo": [v.cargo for v in cat.vendedores],
            "turno": [v.turno for v in cat.vendedores],
            "data_admissao": pd.to_datetime([v.data_admissao for v in cat.vendedores]),
            "data_desligamento": pd.to_datetime([v.data_desligamento for v in cat.vendedores]),
            "percentual_comissao": [v.percentual_comissao for v in cat.vendedores],
        }
    )
    vendedores = qualidade.converter_para_texto(
        tipado_vendedores,
        colunas_data=["data_admissao", "data_desligamento"],
        colunas_valor=["percentual_comissao"],
        colunas_texto=["cod_vendedor", "nome_vendedor", "cod_loja", "cargo", "turno"],
    )[list(tipado_vendedores.columns)]
    vendedores = qualidade.injetar_problemas(
        vendedores,
        tipado_vendedores,
        arquivo=config.ARQ_VENDEDORES,
        linha_inicial=1,
        colunas_data=[],
        colunas_valor=[],
        coluna_sku=None,
        nulos={},
        colunas_nome=["nome_vendedor"],
        rng=rng_para(params.semente, config.FLUXO_QUALIDADE_CADASTROS),
        registro=problemas,
    )

    for nome, df in (
        (config.ARQ_LOJAS, lojas),
        (config.ARQ_HORARIOS, horarios),
        (config.ARQ_PRODUTOS, produtos),
        (config.ARQ_CENTROS_CUSTO, centros),
        (config.ARQ_FERIADOS, feriados),
        (config.ARQ_FORMAS_PAGAMENTO, formas),
        (config.ARQ_CAMPANHAS, campanhas),
        (config.ARQ_VENDEDORES, vendedores),
        (config.ARQ_CLIENTES, clientes),
    ):
        resumo.linhas_por_arquivo[nome] = _gravar_df(df, saida / nome)


def _linha_gabarito_venda(df: pd.DataFrame, i: int, arquivo: str) -> tuple:
    """Linha do gabarito para um item/cupom anômalo (i = posição no DataFrame do mês)."""
    linha = df.iloc[i]
    tipo = linha["_tipo"]
    por_item = tipo in ANOMALIAS_POR_ITEM
    return (
        tipo,
        arquivo,
        i + 1,
        linha["id_venda_erp"] if por_item else linha["numero_cupom"],
        f"{linha['data_venda']:%Y-%m-%d}",
        "",
        linha["cod_loja"],
        formatar_dinheiro(linha["receita_liquida"] if por_item else linha["total_cupom"]),
        linha["_detalhe"]
        if tipo != config.ANOMALIA_MARGEM_NEGATIVA
        else (f"custo={linha['custo_total']:.2f} | receita_liquida={linha['receita_liquida']:.2f}"),
    )


def gerar_dados(
    params: ParametrosGeracao | None = None,
    progresso: Callable[[str], None] | None = None,
) -> ResumoGeracao:
    """Gera todos os CSVs em params.diretorio_saida e devolve o resumo da execução."""
    params = params or ParametrosGeracao()
    avisar = progresso or (lambda _mensagem: None)
    resumo = ResumoGeracao()
    resumo.memoria_livre_inicio_gb = (
        verificar_memoria_livre() if params.verificar_memoria else memoria_livre_gb()
    )
    params.diretorio_saida.mkdir(parents=True, exist_ok=True)

    cat = montar_catalogo(params.semente, params.data_inicio, params.data_fim)
    sazon = Sazonalidade(params.data_inicio, params.data_fim)
    meses = calendario.meses_do_periodo(params.data_inicio, params.data_fim)
    plano = mod_despesas.montar_plano(
        params, cat, meses, rng_para(params.semente, config.FLUXO_PLANO_ANOMALIAS)
    )
    gerador_vendas = vendas.GeradorVendas(params, cat, sazon)

    anomalias: list[tuple] = []
    receita_loja_setor: dict[tuple[str, str, int, int], float] = defaultdict(float)
    receita_vendedor: dict[tuple[str, int, int], float] = defaultdict(float)
    cupons_vendedor: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # [cupons, cancelados]
    saida = params.diretorio_saida

    with RegistroCsv(saida / config.ARQ_PROBLEMAS, qualidade.COLUNAS_PROBLEMAS) as problemas:
        _gravar_cadastros(params, cat, resumo, problemas)

        # ---- vendas: um arquivo por mês --------------------------------------------------
        pesos = {m: vendas.pesos_do_mes(sazon, cat, *m, params) for m in meses}
        itens_por_mes = vendas.distribuir_linhas(
            params.total_linhas_venda, [float(pesos[m][1].sum()) for m in meses]
        )
        for (ano, mes), n_itens in zip(meses, itens_por_mes, strict=True):
            if params.verificar_memoria:
                verificar_memoria_livre()
            dias, pesos_mes = pesos[(ano, mes)]
            df = gerador_vendas.gerar_mes(
                ano=ano,
                mes=mes,
                dias=dias,
                pesos=pesos_mes,
                n_itens=n_itens,
                plano=plano.vendas_por_mes[(ano, mes)],
                rng=rng_para(params.semente, config.FLUXO_VENDAS, ano * 100 + mes),
            )
            unicos = df.loc[~df["_duplicata"]]
            concluidos = unicos.loc[unicos["status"] == config.STATUS_CONCLUIDA]
            for (cod_loja, setor), valor in (
                concluidos.groupby(["cod_loja", "_setor"])["receita_liquida"].sum().items()
            ):
                receita_loja_setor[(cod_loja, setor, ano, mes)] = float(valor)
            for cod, valor in concluidos.groupby("cod_vendedor")["receita_liquida"].sum().items():
                receita_vendedor[(cod, ano, mes)] = float(valor)
            primeiros = unicos.loc[unicos["numero_item"] == 1]
            resumo.cupons += len(primeiros)
            for cod, grupo in primeiros.groupby("cod_vendedor"):
                cupons_vendedor[cod][0] += len(grupo)
                cupons_vendedor[cod][1] += int((grupo["status"] == config.STATUS_CANCELADA).sum())

            nome = config.MODELO_ARQ_VENDAS.format(ano=ano, mes=mes)
            texto = qualidade.converter_para_texto(
                df,
                colunas_data=["data_venda"],
                colunas_valor=vendas.COLUNAS_VALOR_VENDAS,
                colunas_texto=vendas.COLUNAS_TEXTO_VENDAS,
                colunas_hora=["hora_venda"],
            )
            texto = qualidade.injetar_problemas(
                texto,
                df,
                arquivo=nome,
                linha_inicial=1,
                colunas_data=["data_venda"],
                colunas_valor=vendas.COLUNAS_VALOR_VENDAS,
                coluna_sku="sku",
                nulos={"desconto": qualidade.REGRA_NULO_RECALCULAVEL},
                rng=rng_para(params.semente, config.FLUXO_QUALIDADE_VENDAS, ano * 100 + mes),
                registro=problemas,
                linhas_protegidas=(df["_tipo"] != "").to_numpy(),
                colunas_hora=["hora_venda"],
            )
            with EscritorCsv(saida / nome, vendas.COLUNAS_VENDAS) as escritor:
                escritor.escrever(texto)
                resumo.linhas_por_arquivo[nome] = escritor.linhas
            anomalias.extend(
                _linha_gabarito_venda(df, int(i), nome)
                for i in np.flatnonzero((df["_tipo"] != "").to_numpy())
            )
            avisar(f"vendas {ano}-{mes:02d}: {n_itens} itens")

        # vendedores com taxa de cancelamento anormal (resultado medido nos dados gerados)
        total_cupons = sum(c[0] for c in cupons_vendedor.values())
        taxa_geral = sum(c[1] for c in cupons_vendedor.values()) / max(1, total_cupons)
        loja_do_vendedor = {v.cod_vendedor: v.cod_loja for v in cat.vendedores}
        for i in np.flatnonzero(gerador_vendas.vendedor_cancela_muito):
            cod = cat.vendedores[i].cod_vendedor
            cupons, cancelados = cupons_vendedor[cod]
            anomalias.append(
                (
                    config.ANOMALIA_VENDEDOR_CANCELAMENTO,
                    PADRAO_ARQUIVO_VENDAS,
                    "",
                    cod,
                    "",
                    "",
                    loja_do_vendedor[cod],
                    f"{cancelados / max(1, cupons):.4f}",
                    f"cupons={cupons} | cancelados={cancelados} | taxa_geral={taxa_geral:.4f}",
                )
            )

        # ---- metas (derivadas do realizado) ----------------------------------------------
        metas = vendas.gerar_metas(
            receita_loja_setor, cat, meses, rng_para(params.semente, config.FLUXO_METAS)
        )
        resumo.linhas_por_arquivo[config.ARQ_METAS] = _gravar_df(
            qualidade.converter_para_texto(
                metas, ["competencia"], ["valor_meta"], ["cod_loja", "setor"]
            ),
            saida / config.ARQ_METAS,
        )
        metas_vendedor = vendas.gerar_metas_vendedor(
            receita_vendedor, cat, rng_para(params.semente, config.FLUXO_METAS, 1)
        )
        resumo.linhas_por_arquivo[config.ARQ_METAS_VENDEDOR] = _gravar_df(
            qualidade.converter_para_texto(
                metas_vendedor, ["competencia"], ["valor_meta"], ["cod_vendedor"]
            ),
            saida / config.ARQ_METAS_VENDEDOR,
        )

        # ---- despesas e orçamento ----------------------------------------------------------
        with (
            EscritorCsv(saida / config.ARQ_DESPESAS, mod_despesas.COLUNAS_DESPESAS) as esc_desp,
            EscritorCsv(saida / config.ARQ_ORCAMENTO, mod_despesas.COLUNAS_ORCAMENTO) as esc_orc,
        ):
            proximo_documento = 1
            receita_media = mod_despesas.receita_media_mensal(receita_loja_setor, cat, meses)
            for ano, mes in meses:
                if params.verificar_memoria:
                    verificar_memoria_livre()
                resultado, proximo_documento = mod_despesas.gerar_despesas_mes(
                    params=params,
                    cat=cat,
                    receita_media=receita_media,
                    feriados=sazon.feriados,
                    ano=ano,
                    mes=mes,
                    plano=plano,
                    rng=rng_para(params.semente, config.FLUXO_DESPESAS, ano * 100 + mes),
                    proximo_documento=proximo_documento,
                )
                df = resultado.despesas
                protegidas = ((df["_tipo"] != "") | df.index.isin(df["_ref"])).to_numpy()
                texto = qualidade.converter_para_texto(
                    df,
                    colunas_data=["data_lancamento"],
                    colunas_valor=["valor"],
                    colunas_texto=[
                        "numero_documento",
                        "cod_centro_custo",
                        "descricao",
                        "fornecedor",
                    ],
                )
                texto = qualidade.injetar_problemas(
                    texto,
                    df,
                    arquivo=config.ARQ_DESPESAS,
                    linha_inicial=esc_desp.linhas + 1,
                    colunas_data=["data_lancamento"],
                    colunas_valor=["valor"],
                    coluna_sku=None,
                    nulos={"descricao": qualidade.REGRA_NULO_PADRAO},
                    rng=rng_para(params.semente, config.FLUXO_QUALIDADE_DESPESAS, ano * 100 + mes),
                    registro=problemas,
                    linhas_protegidas=protegidas,
                )
                primeira = esc_desp.escrever(texto)
                for i in np.flatnonzero((df["_tipo"] != "").to_numpy()):
                    linha = df.iloc[i]
                    anomalias.append(
                        (
                            linha["_tipo"],
                            config.ARQ_DESPESAS,
                            primeira + int(i),
                            linha["numero_documento"],
                            f"{linha['data_lancamento']:%Y-%m-%d}",
                            linha["cod_centro_custo"],
                            "",
                            formatar_dinheiro(linha["valor"]),
                            linha["_detalhe"],
                        )
                    )
                for item in resultado.acima_orcado:
                    anomalias.append(
                        (
                            config.ANOMALIA_ACIMA_ORCADO,
                            config.ARQ_DESPESAS,
                            "",
                            f"{item['cod_centro_custo']}|{ano}-{mes:02d}",
                            f"{item['competencia']:%Y-%m-%d}",
                            item["cod_centro_custo"],
                            "",
                            formatar_dinheiro(item["valor"]),
                            item["detalhe"],
                        )
                    )
                orc = resultado.orcamento
                orc["competencia"] = pd.to_datetime(orc["competencia"])
                esc_orc.escrever(
                    qualidade.converter_para_texto(
                        orc, ["competencia"], ["valor_orcado"], ["cod_centro_custo"]
                    )
                )
                avisar(f"despesas {ano}-{mes:02d}: {len(df)} lançamentos")
            resumo.linhas_por_arquivo[config.ARQ_DESPESAS] = esc_desp.linhas
            resumo.linhas_por_arquivo[config.ARQ_ORCAMENTO] = esc_orc.linhas

    # ---- gabarito de anomalias -------------------------------------------------------------
    with RegistroCsv(saida / config.ARQ_ANOMALIAS, COLUNAS_ANOMALIAS) as registro:
        registro.adicionar((f"AN{k:04d}", *linha) for k, linha in enumerate(anomalias, start=1))
    resumo.linhas_por_arquivo[config.ARQ_ANOMALIAS] = len(anomalias)
    for linha in anomalias:
        resumo.anomalias_por_tipo[linha[0]] = resumo.anomalias_por_tipo.get(linha[0], 0) + 1

    problemas_df = pd.read_csv(
        saida / config.ARQ_PROBLEMAS, sep=config.SEPARADOR_CSV, usecols=["tipo_problema"]
    )
    resumo.problemas_por_tipo = problemas_df["tipo_problema"].value_counts().to_dict()
    resumo.linhas_por_arquivo[config.ARQ_PROBLEMAS] = len(problemas_df)

    resumo.memoria_livre_fim_gb = memoria_livre_gb()
    resumo.pico_memoria_processo_gb = pico_memoria_processo_gb()
    return resumo
