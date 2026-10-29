"""Relatório de qualidade da carga: lidas, corrigidas, rejeitadas, carregadas e validações.

Montado em duas etapas, porque numa carga reprovada as tabelas de contagem são desfeitas junto
com o dw: `coletar` lê tudo ainda dentro da transação da carga e `montar` junta com o resultado.
O relatório vai para o banco (etl.relatorios_qualidade, JSONB) e para um JSON em data/processed/.
"""

import json
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from src import config
from src.etl.validacao import ResultadoValidacao, SinalNegocio

TABELAS_DW = (
    "dim_tempo",
    "dim_hora",
    "dim_loja",
    "dim_loja_horario",
    "dim_produto",
    "dim_vendedor",
    "dim_cliente",
    "dim_forma_pagamento",
    "dim_campanha",
    "dim_centro_custo",
    "fato_vendas",
    "fato_meta_vendas",
    "fato_meta_vendedor",
    "fato_despesas",
    "fato_orcamento_despesas",
)
AMOSTRA_REJEITADOS_POR_MOTIVO = 5
MODELO_ARQUIVO_RELATORIO = "relatorio_carga_{id_carga:04d}.json"


def _linhas(conexao, consulta, parametros=()):
    cursor = conexao.execute(consulta, parametros)
    nomes = [c.name for c in cursor.description]
    return [dict(zip(nomes, linha, strict=True)) for linha in cursor.fetchall()]


def coletar(conexao: psycopg.Connection, id_carga: int) -> dict:
    """Lê contagens, correções e rejeitados da carga (chamar antes de commit/rollback)."""
    return {
        "tabelas": _linhas(
            conexao,
            "SELECT entidade, lidas, rejeitadas, carregadas, inseridas, atualizadas,"
            " sem_alteracao, removidas FROM etl.carga_tabelas WHERE id_carga = %s"
            " ORDER BY entidade",
            (id_carga,),
        ),
        "correcoes": _linhas(
            conexao,
            "SELECT entidade, coluna, tipo_problema, quantidade FROM etl.carga_correcoes"
            " WHERE id_carga = %s ORDER BY entidade, coluna, tipo_problema",
            (id_carga,),
        ),
        "rejeitadas_por_motivo": _linhas(
            conexao,
            "SELECT entidade, coluna, motivo, count(*) AS quantidade FROM stg.rejeitados"
            " WHERE id_carga = %s GROUP BY 1, 2, 3 ORDER BY 1, 2, 3",
            (id_carga,),
        ),
        "amostra_rejeitados": _linhas(
            conexao,
            "SELECT entidade, arquivo_origem, linha_origem, coluna, valor_original, motivo FROM ("
            " SELECT j.*, row_number() OVER (PARTITION BY entidade, motivo"
            "   ORDER BY arquivo_origem, linha_origem) AS ordem"
            " FROM stg.rejeitados j WHERE id_carga = %s) x WHERE ordem <= %s"
            " ORDER BY entidade, motivo, arquivo_origem, linha_origem",
            (id_carga, AMOSTRA_REJEITADOS_POR_MOTIVO),
        ),
        "arquivos": _linhas(
            conexao,
            "SELECT entidade, arquivo, situacao, linhas_lidas, linhas_ignoradas"
            " FROM etl.carga_arquivos WHERE id_carga = %s ORDER BY entidade, arquivo",
            (id_carga,),
        ),
    }


def contar_linhas_do_dw(conexao: psycopg.Connection) -> dict[str, int]:
    return {
        tabela: conexao.execute(f"SELECT count(*) FROM dw.{tabela}").fetchone()[0]
        for tabela in TABELAS_DW
    }


def montar(
    conexao: psycopg.Connection,
    id_carga: int,
    coletado: dict,
    validacoes: list[ResultadoValidacao],
    sinais: list[SinalNegocio],
    desempenho: dict | None = None,
) -> dict:
    """Junta o que foi coletado com o resultado das validações e o estado final do dw."""
    carga = _linhas(
        conexao,
        "SELECT fonte, modo, status, mensagem, inicio, fim FROM etl.cargas WHERE id_carga = %s",
        (id_carga,),
    )[0]
    por_tipo: dict[str, int] = {}
    for correcao in coletado["correcoes"]:
        tipo = correcao["tipo_problema"]
        por_tipo[tipo] = por_tipo.get(tipo, 0) + correcao["quantidade"]
    rejeitadas_por_motivo: dict[str, int] = {}
    for item in coletado["rejeitadas_por_motivo"]:
        rejeitadas_por_motivo[item["motivo"]] = (
            rejeitadas_por_motivo.get(item["motivo"], 0) + item["quantidade"]
        )
    tabelas = coletado["tabelas"]
    return {
        "id_carga": id_carga,
        "fonte": carga["fonte"],
        "modo": carga["modo"],
        "status": carga["status"],
        "mensagem": carga["mensagem"],
        "inicio": carga["inicio"],
        "fim": carga["fim"],
        "duracao_segundos": (
            round((carga["fim"] - carga["inicio"]).total_seconds(), 1) if carga["fim"] else None
        ),
        "resumo": {
            "linhas_lidas": sum(t["lidas"] for t in tabelas),
            "celulas_corrigidas": sum(por_tipo.values()),
            "linhas_rejeitadas": sum(t["rejeitadas"] for t in tabelas),
            "linhas_carregadas": sum(t["carregadas"] for t in tabelas),
        },
        "arquivos": coletado["arquivos"],
        "tabelas": tabelas,
        "corrigidas_por_tipo": dict(sorted(por_tipo.items())),
        "correcoes": coletado["correcoes"],
        "rejeitadas_por_motivo": dict(sorted(rejeitadas_por_motivo.items())),
        "rejeitadas_detalhe": coletado["rejeitadas_por_motivo"],
        "amostra_rejeitados": coletado["amostra_rejeitados"],
        "validacoes_estruturais": [
            {"validacao": v.validacao, "ok": v.ok, "quantidade": v.quantidade, "detalhe": v.detalhe}
            for v in validacoes
        ],
        "sinais_de_negocio": [
            {
                "sinal": s.sinal,
                "unidade": s.unidade,
                "quantidade": s.quantidade,
                "descricao": s.descricao,
            }
            for s in sinais
        ],
        "linhas_no_dw": contar_linhas_do_dw(conexao),
        "desempenho": desempenho or {},
    }


def _serializar(valor):
    if isinstance(valor, datetime):
        return valor.isoformat(timespec="seconds")
    return str(valor)


def gravar(
    conexao: psycopg.Connection,
    relatorio: dict,
    pasta: Path = config.DIR_PROCESSADOS,
) -> Path:
    """Grava o relatório no banco (JSONB) e em arquivo JSON. Devolve o caminho do arquivo."""
    texto = json.dumps(relatorio, ensure_ascii=False, indent=2, default=_serializar)
    documento = json.loads(texto)  # datas já como texto
    conexao.execute(
        "INSERT INTO etl.relatorios_qualidade (id_carga, relatorio) VALUES (%s, %s)"
        " ON CONFLICT (id_carga) DO UPDATE SET relatorio = EXCLUDED.relatorio, gerado_em = now()",
        (relatorio["id_carga"], Jsonb(documento)),
    )
    conexao.commit()
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / MODELO_ARQUIVO_RELATORIO.format(id_carga=relatorio["id_carga"])
    caminho.write_text(texto + "\n", encoding="utf-8")
    return caminho
