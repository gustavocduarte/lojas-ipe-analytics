"""Linha de comando do ETL.

    python -m src.etl carregar                      # todas as fontes de carga padrão
    python -m src.etl carregar --fonte lojas_ipe_erp
    python -m src.etl carregar --fonte lojas_ipe_erp --entidade lojas --entidade vendas
    python -m src.etl carregar --completo           # relê todos os arquivos, mesmo os inalterados
    python -m src.etl alertas                       # reavalia as regras de alerta (sem recarregar)
    python -m src.etl fontes                        # lista as fontes mapeadas

Códigos de saída: 0 = carga concluída; 1 = validação estrutural reprovou (dw intacto);
2 = erro de uso (argumentos, fonte inexistente, mapeamento inválido);
3 = erro de execução (banco, arquivo ilegível, memória insuficiente, outra carga em andamento).
"""

import argparse
import logging
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import psycopg

from src import banco, config
from src.etl import pipeline
from src.etl.leitura import ErroDeLeitura
from src.etl.mapeamento import Fonte, MapeamentoInvalido, carregar_fontes
from src.logs import configurar_logging
from src.memoria import MemoriaInsuficiente

log = logging.getLogger("src.etl")


def _criar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.etl", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="comando", required=True)
    carregar = sub.add_parser("carregar", help="lê as fontes, limpa, valida e carrega no dw")
    carregar.add_argument("--fonte", action="append", help="nome da fonte (repetível)")
    carregar.add_argument("--entidade", action="append", help="só estas entidades (com --fonte)")
    carregar.add_argument("--completo", action="store_true", help="relê arquivos inalterados")
    carregar.add_argument("--mapeamentos", type=Path, default=config.DIR_MAPEAMENTOS)
    carregar.add_argument("--relatorios", type=Path, default=config.DIR_PROCESSADOS)
    carregar.add_argument("-v", "--detalhado", action="store_true")
    avulso = sub.add_parser("alertas", help="reavalia as regras de alerta sobre o dw atual")
    avulso.add_argument("-v", "--detalhado", action="store_true")
    fontes = sub.add_parser("fontes", help="lista as fontes mapeadas")
    fontes.add_argument("--mapeamentos", type=Path, default=config.DIR_MAPEAMENTOS)
    return parser


def _escolher_fontes(todas: dict[str, Fonte], nomes: list[str] | None) -> list[Fonte]:
    if not nomes:
        return [f for f in todas.values() if f.carga_padrao]
    desconhecidas = [n for n in nomes if n not in todas]
    if desconhecidas:
        raise ValueError(f"fonte inexistente: {desconhecidas} (disponíveis: {sorted(todas)})")
    return [todas[n] for n in nomes]


def principal(
    argv: Sequence[str] | None = None,
    *,
    conexao: psycopg.Connection | None = None,
    verificar_memoria: bool = True,
    leitor_memoria: Callable[[], float] | None = None,
    vigia_intervalo_s: float = config.INTERVALO_VIGIA_MEMORIA_S,
    vigia_tolerancia_s: float = config.TOLERANCIA_PISO_MEMORIA_S,
) -> int:
    """Executa o comando e devolve o código de saída (`conexao`: banco injetado nos testes)."""
    try:
        args = _criar_parser().parse_args(argv)
    except SystemExit as saida:  # argparse sai com 2 em erro de uso (ou 0 em --help)
        return int(saida.code or 0)

    if args.comando in ("carregar", "alertas"):
        configurar_logging(args.detalhado)
    if args.comando == "alertas":
        return _alertas(
            conexao, verificar_memoria, leitor_memoria, vigia_intervalo_s, vigia_tolerancia_s
        )

    try:
        todas = carregar_fontes(args.mapeamentos)
        if args.comando == "fontes":
            for nome, fonte in todas.items():
                padrao = "carga padrão" if fonte.carga_padrao else "só com --fonte"
                print(f"{nome}: {len(fonte.entidades)} entidades, pasta {fonte.pasta} ({padrao})")
            return config.CODIGO_SAIDA_OK
        fontes = _escolher_fontes(todas, args.fonte)
        if args.entidade and (not args.fonte or len(fontes) != 1):
            raise ValueError("--entidade exige exatamente uma --fonte")
        if not fontes:
            raise ValueError("nenhuma fonte para carregar")
        for fonte in fontes:
            invalidas = set(args.entidade or []) - set(fonte.entidades)
            if invalidas:
                raise ValueError(f"entidades não mapeadas em '{fonte.nome}': {sorted(invalidas)}")
    except (MapeamentoInvalido, ValueError, FileNotFoundError) as erro:
        if args.comando == "carregar":
            log.error("erro de uso: %s", erro)
        else:
            print(f"erro de uso: {erro}")
        return config.CODIGO_SAIDA_ERRO_DE_USO

    proprio = conexao is None
    try:
        conexao = conexao or banco.conectar()
        modo = "completo" if args.completo else "incremental"
        for fonte in fontes:
            resultado = pipeline.carregar(
                conexao,
                fonte,
                entidades=args.entidade,
                modo=modo,
                pasta_relatorios=args.relatorios,
                verificar_memoria=verificar_memoria,
                leitor_memoria=leitor_memoria,
                vigia_intervalo_s=vigia_intervalo_s,
                vigia_tolerancia_s=vigia_tolerancia_s,
            )
            if not resultado.aprovada:
                log.error(
                    "validação reprovada; o dw não foi alterado (relatório: %s)",
                    resultado.caminho_relatorio,
                )
                return config.CODIGO_SAIDA_VALIDACAO_REPROVADA
        return config.CODIGO_SAIDA_OK
    except (
        MemoriaInsuficiente,
        pipeline.CargaEmAndamento,
        ErroDeLeitura,
        psycopg.Error,
        RuntimeError,
        OSError,
    ) as erro:
        log.error("erro de execução: %s", erro)
        return config.CODIGO_SAIDA_ERRO_DE_EXECUCAO
    finally:
        if proprio and conexao is not None:
            conexao.close()


def _alertas(conexao, verificar_memoria, leitor_memoria, intervalo_s, tolerancia_s) -> int:
    proprio = conexao is None
    try:
        conexao = conexao or banco.conectar()
        id_carga, resumo = pipeline.gerar_alertas_avulso(
            conexao,
            verificar_memoria=verificar_memoria,
            leitor_memoria=leitor_memoria,
            vigia_intervalo_s=intervalo_s,
            vigia_tolerancia_s=tolerancia_s,
        )
        for tipo in resumo["por_tipo"]:
            print(
                f"{tipo['tipo_alerta']:<32} detectados {tipo['detectados']:>5} | novos "
                f"{tipo['novos']:>4} | atualizados {tipo['atualizados']:>4} | inalterados "
                f"{tipo['inalterados']:>5} | reativados {tipo['reativados']:>3} | deixaram de "
                f"vigorar {tipo['deixaram_de_vigorar']:>4}"
            )
        desempenho = resumo["desempenho"]
        print(
            f"carga {id_carga}: {resumo['vigentes_independentes']} alertas independentes, "
            f"{resumo['vigentes_derivados']} derivados, {resumo['nao_vigentes']} não vigentes; "
            f"{desempenho['duracao_s']} s, pico {desempenho['pico_memoria_processo_gb']} GB"
        )
        return config.CODIGO_SAIDA_OK
    except (MemoriaInsuficiente, pipeline.CargaEmAndamento, psycopg.Error, RuntimeError) as erro:
        log.error("erro de execução: %s", erro)
        return config.CODIGO_SAIDA_ERRO_DE_EXECUCAO
    finally:
        if proprio and conexao is not None:
            conexao.close()


if __name__ == "__main__":
    sys.exit(principal())
