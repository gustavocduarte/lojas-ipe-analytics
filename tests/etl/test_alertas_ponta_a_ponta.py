"""Alertas de ponta a ponta contra os GABARITOS (só para teste; a produção nunca os lê).

Gera 60 mil itens, carrega pelo pipeline (que gera os alertas) e mede, regra a regra, quantas
anomalias injetadas foram detectadas e quantos alertas EXTRAS apareceram — cada extra precisa de
explicação conhecida. Escreve o quadro de acerto em stdout (pytest -s) e num JSON em tmp.
"""

import dataclasses
import json
from collections import Counter, defaultdict

import pytest

from src import config
from src.etl import pipeline
from src.etl.mapeamento import carregar_fontes
from src.gerador.parametros import ParametrosGeracao
from src.gerador.principal import gerar_dados
from tests.gerador.utilitarios import ler_csv

pytestmark = pytest.mark.banco

LINHAS_VENDA = 60_000
MIN_CUPONS_NA_JANELA = 30  # 60 mil itens ~ 20 mil cupons: janelas de 3 meses têm bem menos de 100

PARA_ALERTA = {  # tipo no gabarito -> tipo do alerta
    config.ANOMALIA_DESCONTO_ACIMA_LIMITE: "desconto_acima_limite",
    config.ANOMALIA_MARGEM_NEGATIVA: "margem_negativa",
    config.ANOMALIA_FORA_HORARIO: "venda_fora_horario",
    config.ANOMALIA_CUPOM_DUPLICADO: "cupom_duplicado",
    config.ANOMALIA_DESPESA_DUPLICADA: "despesa_documento_repetido",
    config.ANOMALIA_FIM_SEMANA_FERIADO: "despesa_fim_semana_feriado",
    config.ANOMALIA_VALOR_ATIPICO: "despesa_valor_atipico",
    config.ANOMALIA_CENTRO_CUSTO_ERRADO: "despesa_centro_incompativel",
    config.ANOMALIA_ACIMA_ORCADO: "despesa_acima_orcado",
    config.ANOMALIA_VENDEDOR_CANCELAMENTO: "vendedor_cancelamento_alto",
}
POR_ITEM_OU_CUPOM = (
    config.ANOMALIA_DESCONTO_ACIMA_LIMITE,
    config.ANOMALIA_MARGEM_NEGATIVA,
    config.ANOMALIA_FORA_HORARIO,
    config.ANOMALIA_CUPOM_DUPLICADO,
    config.ANOMALIA_DESPESA_DUPLICADA,
    config.ANOMALIA_ACIMA_ORCADO,
)


@pytest.fixture(scope="module")
def pasta(tmp_path_factory):
    params = ParametrosGeracao(
        diretorio_saida=tmp_path_factory.mktemp("raw_alertas"),
        total_linhas_venda=LINHAS_VENDA,
        verificar_memoria=False,
    )
    gerar_dados(params)
    return params.diretorio_saida


@pytest.fixture(scope="module")
def carga(banco_compartilhado, pasta, tmp_path_factory):
    banco_compartilhado.execute(
        "UPDATE etl.parametros_negocio SET valor = %s WHERE chave = 'cancelamento_min_cupons'",
        (MIN_CUPONS_NA_JANELA,),
    )
    banco_compartilhado.commit()
    fonte = dataclasses.replace(carregar_fontes()["lojas_ipe_erp"], pasta=pasta)
    resultado = pipeline.carregar(
        banco_compartilhado,
        fonte,
        verificar_memoria=False,
        pasta_relatorios=tmp_path_factory.mktemp("relatorios"),
    )
    return banco_compartilhado, resultado


@pytest.fixture(scope="module")
def gabarito(pasta):
    return ler_csv(pasta / config.ARQ_ANOMALIAS).to_dict("records")


@pytest.fixture(scope="module")
def alertas(carga):
    con, _ = carga
    cursor = con.execute(
        "SELECT chave_alerta, tipo_alerta, severidade, independente, vigente, status, explicacao,"
        " detalhe FROM dw.alertas"
    )
    nomes = [c.name for c in cursor.description]
    return [dict(zip(nomes, linha, strict=True)) for linha in cursor.fetchall()]


def _chave_injetada(a: dict) -> str:
    tipo = PARA_ALERTA[a["tipo_anomalia"]]
    if a["tipo_anomalia"] in POR_ITEM_OU_CUPOM:
        return f"{tipo}|{a['identificador']}"
    return f"{tipo}|{a['arquivo']}|{a['linha_arquivo']}"


@pytest.fixture(scope="module")
def injetados(gabarito):
    por_tipo = defaultdict(set)
    for a in gabarito:
        if a["tipo_anomalia"] != config.ANOMALIA_VENDEDOR_CANCELAMENTO:
            por_tipo[PARA_ALERTA[a["tipo_anomalia"]]].add(_chave_injetada(a))
    return por_tipo


@pytest.fixture(scope="module")
def detectados(alertas):
    """Chaves dos alertas vigentes por tipo (para orçado, só os independentes)."""
    por_tipo = defaultdict(set)
    for a in alertas:
        if a["vigente"] and (a["independente"] or a["tipo_alerta"] != "despesa_acima_orcado"):
            por_tipo[a["tipo_alerta"]].add(a["chave_alerta"])
    return por_tipo


REGRAS_EXATAS = [
    "desconto_acima_limite",
    "margem_negativa",
    "venda_fora_horario",
    "cupom_duplicado",
    "despesa_documento_repetido",
    "despesa_fim_semana_feriado",
]


@pytest.mark.parametrize("tipo", REGRAS_EXATAS)
def test_regras_sem_ruido_detectam_todos_e_nenhum_extra(tipo, injetados, detectados):
    assert injetados[tipo], tipo
    assert detectados[tipo] == injetados[tipo]


def test_valor_atipico_detecta_todos_os_injetados(injetados, detectados, alertas):
    tipo = "despesa_valor_atipico"
    faltam = injetados[tipo] - detectados[tipo]
    extras = detectados[tipo] - injetados[tipo]
    assert not faltam
    assert not extras, sorted(extras)  # nenhum valor natural passa de 5x a mediana do centro


def test_centro_incompativel_detecta_os_12_mesmo_contaminando_o_aprendizado(
    injetados, detectados, alertas
):
    tipo = "despesa_centro_incompativel"
    assert len(injetados[tipo]) == config.QUANTIDADE_ANOMALIAS[config.ANOMALIA_CENTRO_CUSTO_ERRADO]
    assert injetados[tipo] <= detectados[tipo]
    assert not detectados[tipo] - injetados[tipo]
    # contaminação real: nas descrições que têm erro, o tipo dominante não é 100%
    participacoes = {
        a["detalhe"]["descricao"]: a["detalhe"]["participacao"]
        for a in alertas
        if a["tipo_alerta"] == tipo
    }
    assert participacoes and all(0.9 <= p < 1.0 for p in participacoes.values())


def test_orcado_todos_os_injetados_sao_independentes_e_os_demais_sao_derivados(injetados, alertas):
    tipo = "despesa_acima_orcado"
    orcado = [a for a in alertas if a["tipo_alerta"] == tipo and a["vigente"]]
    independentes = {a["chave_alerta"] for a in orcado if a["independente"]}
    derivados = {a["chave_alerta"] for a in orcado if not a["independente"]}
    assert injetados[tipo] <= independentes
    extras_independentes = independentes - injetados[tipo]
    # todo estouro a mais é consequência de outro alerta (derivado): nenhum independente extra
    assert not extras_independentes, sorted(extras_independentes)
    assert derivados  # estouros causados por atípico, duplicidade ou centro errado
    assert {a["severidade"] for a in orcado if not a["independente"]} == {"baixa"}


def test_derivados_estao_ligados_as_origens(carga):
    con, _ = carga
    sem_vinculo = con.execute(
        "SELECT count(*) FROM dw.alertas a WHERE a.tipo_alerta = 'despesa_acima_orcado'"
        " AND a.vigente AND NOT a.independente"
        " AND NOT EXISTS (SELECT 1 FROM dw.alerta_vinculos v"
        "                  WHERE v.sk_alerta_derivado = a.sk_alerta)"
    ).fetchone()[0]
    assert sem_vinculo == 0
    tipos_de_origem = {
        t
        for (t,) in con.execute(
            "SELECT DISTINCT o.tipo_alerta FROM dw.alerta_vinculos v"
            " JOIN dw.alertas o ON o.sk_alerta = v.sk_alerta_origem"
        )
    }
    assert tipos_de_origem <= {
        "despesa_valor_atipico",
        "despesa_documento_repetido",
        "despesa_centro_incompativel",
    }


def test_cancelamento_alto_os_dois_vendedores_dominam_as_janelas(carga, gabarito):
    con, _ = carga
    marcados = {
        a["identificador"]
        for a in gabarito
        if a["tipo_anomalia"] == config.ANOMALIA_VENDEDOR_CANCELAMENTO
    }
    por_vendedor = Counter()
    for (chave,) in con.execute(
        "SELECT chave_alerta FROM dw.alertas WHERE tipo_alerta = 'vendedor_cancelamento_alto'"
        " AND vigente"
    ):
        por_vendedor[chave.split("|")[1]] += 1
    assert marcados <= set(por_vendedor)
    janelas_dos_marcados = [por_vendedor[v] for v in marcados]
    outros = {v: n for v, n in por_vendedor.items() if v not in marcados}
    assert min(janelas_dos_marcados) >= 6  # aparecem em boa parte dos meses
    # nenhum outro vendedor aparece de forma persistente (ruído de amostra pequena)
    assert all(n <= 2 for n in outros.values()), outros


def test_nenhuma_regra_de_venda_de_vendedor_inativo_dispara(alertas):
    assert not [a for a in alertas if a["tipo_alerta"] == "venda_vendedor_inativo"]


def test_alertas_novos_e_independentes_no_inicio(alertas):
    assert {a["status"] for a in alertas} == {"novo"}
    assert all(a["explicacao"] for a in alertas)


def test_quadro_de_acerto(injetados, detectados, alertas, tmp_path):
    quadro = {}
    for tipo, injetadas in injetados.items():
        achados = detectados[tipo]
        quadro[tipo] = {
            "injetados": len(injetadas),
            "detectados": len(injetadas & achados),
            "extras": len(achados - injetadas),
        }
    por_tipo = Counter(a["tipo_alerta"] for a in alertas if a["vigente"] and a["independente"])
    quadro["_todos_os_alertas_independentes"] = dict(por_tipo)
    (tmp_path / "quadro_acerto.json").write_text(json.dumps(quadro, indent=2), encoding="utf-8")
    print("\nQUADRO DE ACERTO", json.dumps(quadro, indent=2, ensure_ascii=False))
    assert all(
        q["detectados"] == q["injetados"] for k, q in quadro.items() if not k.startswith("_")
    )
