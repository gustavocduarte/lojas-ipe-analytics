"""Conexão com o PostgreSQL (credenciais sempre vindas do .env) e aplicação do DDL."""

import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from sqlalchemy import URL, Engine, create_engine

from src import config


def montar_url(servidor: str, porta: int, banco: str, usuario: str, senha: str) -> URL:
    """URL SQLAlchemy no formato postgresql+psycopg:// (a senha é escapada pelo SQLAlchemy)."""
    return URL.create(
        drivername=config.DRIVER_SQLALCHEMY,
        username=usuario,
        password=senha,
        host=servidor,
        port=porta,
        database=banco,
    )


def url_do_ambiente() -> URL:
    """Lê servidor, porta, banco, usuário e senha do .env / variáveis de ambiente."""
    load_dotenv()
    obrigatorias = (
        config.VAR_BD_NOME,
        config.VAR_BD_USUARIO,
        config.VAR_BD_SENHA,
    )
    faltando = [v for v in obrigatorias if not os.getenv(v)]
    if faltando:
        raise RuntimeError(f"Variáveis ausentes no .env: {', '.join(faltando)}")
    return montar_url(
        servidor=os.getenv(config.VAR_BD_SERVIDOR) or config.SERVIDOR_PADRAO_BANCO,
        porta=int(os.getenv(config.VAR_BD_PORTA) or config.PORTA_PADRAO_BANCO),
        banco=os.environ[config.VAR_BD_NOME],
        usuario=os.environ[config.VAR_BD_USUARIO],
        senha=os.environ[config.VAR_BD_SENHA],
    )


def criar_motor(url: URL | None = None) -> Engine:
    return create_engine(url or url_do_ambiente())


def scripts_ddl(diretorio: Path = config.DIR_DDL) -> list[Path]:
    """Scripts de DDL em ordem de execução (exclui os administrativos, prefixo 00_)."""
    return sorted(
        p for p in diretorio.glob("*.sql") if not p.name.startswith(config.PREFIXO_SCRIPT_ADMIN)
    )


def aplicar_ddl(conexao: psycopg.Connection, diretorio: Path = config.DIR_DDL) -> list[str]:
    """Executa os scripts de DDL na conexão recebida. Retorna os nomes dos scripts aplicados."""
    aplicados = []
    for script in scripts_ddl(diretorio):
        # Sem parâmetros o psycopg usa o protocolo simples, que aceita vários comandos por vez.
        conexao.execute(script.read_text(encoding="utf-8"))
        aplicados.append(script.name)
    conexao.commit()
    return aplicados


def aplicar_procedures(
    conexao: psycopg.Connection, diretorio: Path = config.DIR_PROCEDURES
) -> list[str]:
    """Cria ou substitui as procedures/funções de sql/procedures (podem ser reaplicadas)."""
    aplicados = []
    for script in sorted(diretorio.glob("*.sql")):
        conexao.execute(script.read_text(encoding="utf-8"))
        aplicados.append(script.name)
    conexao.commit()
    return aplicados


def aplicar_scripts(
    conexao: psycopg.Connection, nomes: list[str], diretorio: Path = config.DIR_DDL
) -> list[str]:
    """Executa só os scripts indicados (para bancos que já têm os anteriores aplicados)."""
    for nome in nomes:
        conexao.execute((diretorio / nome).read_text(encoding="utf-8"))
    conexao.commit()
    return list(nomes)


def conectar() -> psycopg.Connection:
    """Conexão psycopg com o banco do .env (usuário lojas_ipe)."""
    url = url_do_ambiente()
    return psycopg.connect(
        host=url.host,
        port=url.port,
        dbname=url.database,
        user=url.username,
        password=url.password,
    )


def _principal(argumentos: list[str]) -> None:
    """Sem argumentos: DDL completo (banco novo) e procedures. `--procedures`: só as procedures.
    Com nomes de scripts de DDL: aplica só esses (banco que já tem os anteriores)."""
    with conectar() as conexao:
        if argumentos == ["--procedures"]:
            aplicados = aplicar_procedures(conexao)
        elif argumentos:
            aplicados = aplicar_scripts(conexao, argumentos)
        else:
            aplicados = aplicar_ddl(conexao) + aplicar_procedures(conexao)
        for nome in aplicados:
            print(f"aplicado: {nome}")


if __name__ == "__main__":
    _principal(sys.argv[1:])
