"""Orquestra uma carga: arquivos -> staging -> dw (numa transação) -> validações -> relatório.

Fluxo de cada fonte:
  1. lê os arquivos para o staging e confirma (o staging é reaproveitável);
  2. numa única transação, roda as procedures stg -> dw e as validações estruturais;
  3. se alguma validação estrutural falhar, desfaz tudo: o dw fica como estava e a carga é marcada
     como reprovada (os arquivos não contam como processados e serão relidos na próxima vez);
  4. senão, confirma o dw e marca os arquivos como processados;
  5. grava validações, sinais de negócio e o relatório de qualidade.
"""

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import psycopg

from src import config
from src.etl import controle, relatorio, validacao
from src.etl.leitura import carregar_para_staging
from src.etl.mapeamento import Fonte
from src.memoria import memoria_livre_gb, pico_memoria_processo_gb, verificar_memoria_livre

log = logging.getLogger(__name__)


class CargaEmAndamento(RuntimeError):
    """Outra carga está rodando (trava de sessão do PostgreSQL)."""


@dataclass
class ResultadoCarga:
    fonte: str
    id_carga: int
    status: str  # concluida ou reprovada
    relatorio: dict
    caminho_relatorio: Path
    reprovadas: list[validacao.ResultadoValidacao] = field(default_factory=list)

    @property
    def aprovada(self) -> bool:
        return self.status == controle.STATUS_CONCLUIDA


def carregar(
    conexao: psycopg.Connection,
    fonte: Fonte,
    *,
    entidades: list[str] | None = None,
    modo: str = "incremental",
    pasta_relatorios: Path = config.DIR_PROCESSADOS,
    verificar_memoria: bool = True,
) -> ResultadoCarga:
    """Executa a carga completa de uma fonte. Levanta exceção só para erros de execução; uma
    validação reprovada é um resultado normal (status 'reprovada')."""
    if verificar_memoria:
        verificar_memoria_livre()
    if not conexao.execute("SELECT pg_try_advisory_lock(%s)", (config.CHAVE_TRAVA_ETL,)).fetchone()[
        0
    ]:
        raise CargaEmAndamento("já existe uma carga em andamento neste banco")
    conexao.commit()
    try:
        return _carregar_com_trava(
            conexao, fonte, entidades, modo, pasta_relatorios, verificar_memoria
        )
    finally:
        conexao.rollback()
        conexao.execute("SELECT pg_advisory_unlock(%s)", (config.CHAVE_TRAVA_ETL,))
        conexao.commit()


def _carregar_com_trava(conexao, fonte, entidades, modo, pasta_relatorios, verificar_memoria):
    inicio = time.perf_counter()
    livre_inicio = memoria_livre_gb()
    log.info("carga da fonte '%s' (modo %s)", fonte.nome, modo)
    staging = carregar_para_staging(conexao, fonte, entidades=entidades, modo=modo)
    id_carga = staging.id_carga
    try:
        if verificar_memoria:
            verificar_memoria_livre()
        conexao.execute("CALL etl.carregar_dw(%s)", (id_carga,))
        validacoes = validacao.validar_estrutura(conexao, id_carga)
        coletado = relatorio.coletar(conexao, id_carga)
        falhas = validacao.reprovadas(validacoes)
        if falhas:
            conexao.rollback()  # o dw volta ao que era
            log.error("carga %d reprovada: %s", id_carga, [f.validacao for f in falhas])
        else:
            conexao.commit()
            controle.confirmar_arquivos(conexao, id_carga)
    except Exception as erro:
        conexao.rollback()
        controle.finalizar_carga(conexao, id_carga, controle.STATUS_ERRO, str(erro))
        raise

    aprovada = not falhas
    sinais = validacao.calcular_sinais(conexao) if aprovada else []
    validacao.gravar_validacoes(conexao, id_carga, validacoes)
    validacao.gravar_sinais(conexao, id_carga, sinais)
    mensagem = (
        None if aprovada else "validações reprovadas: " + ", ".join(f.validacao for f in falhas)
    )
    status = controle.STATUS_CONCLUIDA if aprovada else controle.STATUS_REPROVADA
    controle.finalizar_carga(conexao, id_carga, status, mensagem)

    desempenho = {
        "duracao_total_s": round(time.perf_counter() - inicio, 1),
        "pico_memoria_processo_gb": round(pico_memoria_processo_gb(), 2),
        "memoria_livre_inicio_gb": round(livre_inicio, 2),
        "memoria_livre_fim_gb": round(memoria_livre_gb(), 2),
    }
    documento = relatorio.montar(conexao, id_carga, coletado, validacoes, sinais, desempenho)
    caminho = relatorio.gravar(conexao, documento, pasta_relatorios)
    log.info(
        "carga %d %s: %d linhas lidas, %d rejeitadas, %d células corrigidas (relatório: %s)",
        id_carga,
        status,
        documento["resumo"]["linhas_lidas"],
        documento["resumo"]["linhas_rejeitadas"],
        documento["resumo"]["celulas_corrigidas"],
        caminho,
    )
    return ResultadoCarga(fonte.nome, id_carga, status, documento, caminho, falhas)
