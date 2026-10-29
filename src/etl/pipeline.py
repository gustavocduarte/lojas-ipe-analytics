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
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import psycopg

from src import config
from src.etl import controle, relatorio, validacao
from src.etl.leitura import carregar_para_staging
from src.etl.mapeamento import Fonte
from src.memoria import (
    MemoriaInsuficiente,
    MemoriaRompida,
    VigiaMemoria,
    memoria_livre_gb,
    pico_memoria_processo_gb,
    verificar_memoria_livre,
)

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


def _checar_piso(leitor_memoria: Callable[[], float] | None) -> None:
    """Confere o piso de memória antes de começar (com `leitor_memoria`, uma memória simulada)."""
    if leitor_memoria is None:
        verificar_memoria_livre()
    elif (livre := leitor_memoria()) < config.MEMORIA_LIVRE_MINIMA_GB:
        raise MemoriaInsuficiente(f"memória livre {livre:.2f} GB abaixo do mínimo")


def carregar(
    conexao: psycopg.Connection,
    fonte: Fonte,
    *,
    entidades: list[str] | None = None,
    modo: str = "incremental",
    pasta_relatorios: Path = config.DIR_PROCESSADOS,
    verificar_memoria: bool = True,
    leitor_memoria: Callable[[], float] | None = None,
    vigia_intervalo_s: float = config.INTERVALO_VIGIA_MEMORIA_S,
    vigia_tolerancia_s: float = config.TOLERANCIA_PISO_MEMORIA_S,
) -> ResultadoCarga:
    """Executa a carga completa de uma fonte. Levanta exceção só para erros de execução; uma
    validação reprovada é um resultado normal (status 'reprovada').

    Com `verificar_memoria`, confere o piso antes de começar e deixa uma vigia conferindo a memória
    livre em paralelo durante toda a carga: se ela ficar abaixo do piso por mais de
    `vigia_tolerancia_s` segundos seguidos, a consulta em andamento é cancelada, a transação é
    desfeita (o dw fica como estava), a carga é marcada como erro e sobe MemoriaRompida.
    `leitor_memoria` troca a leitura real por uma simulada (testes).
    """
    if verificar_memoria:
        _checar_piso(leitor_memoria)
    if not conexao.execute("SELECT pg_try_advisory_lock(%s)", (config.CHAVE_TRAVA_ETL,)).fetchone()[
        0
    ]:
        raise CargaEmAndamento("já existe uma carga em andamento neste banco")
    conexao.commit()
    vigia = None
    if verificar_memoria:
        vigia = VigiaMemoria(
            intervalo_s=vigia_intervalo_s,
            tolerancia_s=vigia_tolerancia_s,
            leitor=leitor_memoria,
            ao_romper=conexao.cancel,  # interrompe a consulta SQL em andamento
        ).iniciar()
    try:
        return _carregar_com_trava(conexao, fonte, entidades, modo, pasta_relatorios, vigia)
    finally:
        if vigia is not None:
            vigia.parar()
        conexao.rollback()
        conexao.execute("SELECT pg_advisory_unlock(%s)", (config.CHAVE_TRAVA_ETL,))
        conexao.commit()


def _finalizar_com_erro(conexao, id_carga: int, erro: Exception) -> None:
    """Marca a carga como erro. Um cancelamento tardio da vigia pode atingir este UPDATE: repete."""
    for tentativa in range(2):
        try:
            controle.finalizar_carga(conexao, id_carga, controle.STATUS_ERRO, str(erro))
            return
        except psycopg.errors.QueryCanceled:
            conexao.rollback()
            if tentativa == 1:
                raise


def _carregar_com_trava(conexao, fonte, entidades, modo, pasta_relatorios, vigia):
    inicio = time.perf_counter()
    livre_inicio = memoria_livre_gb()
    log.info("carga da fonte '%s' (modo %s)", fonte.nome, modo)
    staging = carregar_para_staging(conexao, fonte, entidades=entidades, modo=modo, vigia=vigia)
    id_carga = staging.id_carga
    try:
        if vigia is not None:
            vigia.verificar()
        conexao.execute("CALL etl.carregar_dw(%s)", (id_carga,))
        if vigia is not None:
            vigia.verificar()
        validacoes = validacao.validar_estrutura(conexao, id_carga)
        coletado = relatorio.coletar(conexao, id_carga)
        falhas = validacao.reprovadas(validacoes)
        if vigia is not None:
            vigia.verificar()
            vigia.parar()  # daqui em diante só gravamos o resultado: nada a cancelar
        if falhas:
            conexao.rollback()  # o dw volta ao que era
            log.error("carga %d reprovada: %s", id_carga, [f.validacao for f in falhas])
        else:
            conexao.commit()
            controle.confirmar_arquivos(conexao, id_carga)
    except Exception as erro:
        conexao.rollback()  # o dw fica como estava
        if vigia is not None and vigia.rompido and not isinstance(erro, MemoriaRompida):
            erro = MemoriaRompida(vigia.motivo)  # a consulta foi cancelada pela vigia
        log.error("carga %d interrompida: %s", id_carga, erro)
        _finalizar_com_erro(conexao, id_carga, erro)
        raise erro

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
    if vigia is not None and vigia.minimo_gb is not None:
        desempenho["memoria_livre_minima_durante_a_carga_gb"] = round(vigia.minimo_gb, 2)
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
