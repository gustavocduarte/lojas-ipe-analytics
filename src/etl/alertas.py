"""Geração de alertas (Fase 3) a partir do dw, com a mesma vigia de memória da carga.

As regras são SQL (sql/procedures/7x_*.sql, limites em etl.parametros_negocio). Aqui só
chamamos `etl.gerar_alertas`, protegemos a execução com a vigia de memória e resumimos o que
aconteceu para o relatório de qualidade e para a linha de comando.
"""

import logging
import time
from collections.abc import Callable

import psycopg

from src import config
from src.memoria import MemoriaRompida, VigiaMemoria, memoria_livre_gb, pico_memoria_processo_gb

log = logging.getLogger(__name__)

COLUNAS_POR_TIPO = (
    "tipo_alerta",
    "detectados",
    "novos",
    "atualizados",
    "inalterados",
    "reativados",
    "deixaram_de_vigorar",
)


def gerar(
    conexao: psycopg.Connection,
    id_carga: int,
    *,
    verificar_memoria: bool = True,
    leitor_memoria: Callable[[], float] | None = None,
    vigia_intervalo_s: float = config.INTERVALO_VIGIA_MEMORIA_S,
    vigia_tolerancia_s: float = config.TOLERANCIA_PISO_MEMORIA_S,
) -> dict:
    """Roda todas as regras ativas e grava os alertas na transação desta chamada.

    Se a memória livre ficar abaixo do piso por tempo demais, a consulta é cancelada, a transação
    é desfeita (nenhum alerta muda) e sobe MemoriaRompida. Devolve o resumo para o relatório.
    """
    inicio = time.perf_counter()
    livre_inicio = memoria_livre_gb()
    vigia = None
    if verificar_memoria:
        vigia = VigiaMemoria(
            intervalo_s=vigia_intervalo_s,
            tolerancia_s=vigia_tolerancia_s,
            leitor=leitor_memoria,
            ao_romper=conexao.cancel,
        ).iniciar()
    try:
        conexao.execute("CALL etl.gerar_alertas(%s)", (id_carga,))
        if vigia is not None:
            vigia.verificar()
            vigia.parar()
        conexao.commit()
    except Exception as erro:
        conexao.rollback()
        if vigia is not None and vigia.rompido and not isinstance(erro, MemoriaRompida):
            raise MemoriaRompida(vigia.motivo) from erro
        raise
    finally:
        if vigia is not None:
            vigia.parar()
    resumo = resumir(conexao, id_carga)
    resumo["desempenho"] = {
        "duracao_s": round(time.perf_counter() - inicio, 1),
        "pico_memoria_processo_gb": round(pico_memoria_processo_gb(), 2),
        "memoria_livre_inicio_gb": round(livre_inicio, 2),
        "memoria_livre_minima_durante_a_geracao_gb": (
            round(vigia.minimo_gb, 2) if vigia is not None and vigia.minimo_gb is not None else None
        ),
    }
    return resumo


def resumir(conexao: psycopg.Connection, id_carga: int) -> dict:
    """O que a geração fez (por tipo) e como estão os alertas agora (severidade e status)."""
    por_tipo = [
        dict(zip(COLUNAS_POR_TIPO, linha, strict=True))
        for linha in conexao.execute(
            f"SELECT {', '.join(COLUNAS_POR_TIPO)} FROM etl.carga_alertas WHERE id_carga = %s"
            " ORDER BY tipo_alerta",
            (id_carga,),
        )
    ]
    por_severidade = dict(
        conexao.execute(
            "SELECT severidade, count(*) FROM dw.alertas WHERE vigente AND independente"
            " GROUP BY severidade"
        ).fetchall()
    )
    por_status = dict(
        conexao.execute(
            "SELECT status, count(*) FROM dw.alertas WHERE vigente AND independente GROUP BY status"
        ).fetchall()
    )
    totais = conexao.execute(
        "SELECT count(*) FILTER (WHERE vigente AND independente),"
        " count(*) FILTER (WHERE vigente AND NOT independente),"
        " count(*) FILTER (WHERE NOT vigente) FROM dw.alertas"
    ).fetchone()
    return {
        "por_tipo": por_tipo,
        "vigentes_independentes": totais[0],
        "vigentes_derivados": totais[1],
        "nao_vigentes": totais[2],
        "por_severidade": por_severidade,
        "por_status": por_status,
    }
