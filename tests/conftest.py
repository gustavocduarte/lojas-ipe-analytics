"""Fixtures compartilhadas. Nada aqui acessa rede, banco real ou a pasta data/."""

import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import replace

import psycopg
import pytest
from psycopg import sql

from src import banco, config
from src.gerador.parametros import ParametrosGeracao
from src.gerador.principal import gerar_dados

LINHAS_VENDA_TESTE = 2_400  # volume pequeno: 100 linhas por mês
TENTATIVAS_APAGAR_BANCO = 20
ESPERA_APAGAR_BANCO_S = 0.5


@pytest.fixture(scope="session")
def dados_pequenos(tmp_path_factory):
    """Gera um conjunto pequeno de CSVs numa pasta temporária (uma vez por sessão de testes)."""
    pasta = tmp_path_factory.mktemp("raw_pequeno")
    params = ParametrosGeracao(
        diretorio_saida=pasta, total_linhas_venda=LINHAS_VENDA_TESTE, verificar_memoria=False
    )
    resumo = gerar_dados(params)
    return params, resumo


@pytest.fixture
def parametros_pequenos(tmp_path):
    return ParametrosGeracao(
        diretorio_saida=tmp_path, total_linhas_venda=LINHAS_VENDA_TESTE, verificar_memoria=False
    )


def com_saida(params: ParametrosGeracao, pasta, **mudancas) -> ParametrosGeracao:
    return replace(params, diretorio_saida=pasta, **mudancas)


def parametros_banco_de_teste() -> dict:
    """Acesso do usuário de testes (lojas_ipe_teste, CREATEDB, sem superusuário); vem do .env."""
    banco.load_dotenv()
    usuario = os.getenv(config.VAR_BD_TESTE_USUARIO)
    senha = os.getenv(config.VAR_BD_TESTE_SENHA)
    if not usuario or not senha:
        pytest.skip("BD_TESTE_USUARIO/BD_TESTE_SENHA não configurados")
    return {
        "host": os.getenv(config.VAR_BD_TESTE_SERVIDOR) or config.SERVIDOR_PADRAO_BANCO,
        "port": int(os.getenv(config.VAR_BD_TESTE_PORTA) or config.PORTA_PADRAO_BANCO),
        "user": usuario,
        "password": senha,
    }


@contextmanager
def banco_temporario():
    """Cria um banco descartável com nome único e o apaga ao final (só o dono consegue apagar)."""
    acesso = parametros_banco_de_teste()
    nome = f"teste_lojas_ipe_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(dbname="postgres", autocommit=True, **acesso) as con:
        con.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(nome)))
    try:
        with psycopg.connect(dbname=nome, **acesso) as con:
            yield con
    finally:
        _apagar_banco(acesso, nome)


def _apagar_banco(acesso: dict, nome: str) -> None:
    """DROP com FORCE. Se o autovacuum (que roda como superusuário) estiver conectado ao banco
    naquele instante, o usuário de testes não pode derrubá-lo: espera um pouco e tenta de novo."""
    comando = sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(nome))
    for tentativa in range(TENTATIVAS_APAGAR_BANCO):
        try:
            with psycopg.connect(dbname="postgres", autocommit=True, **acesso) as con:
                con.execute(comando)
            return
        except psycopg.errors.InsufficientPrivilege:
            if tentativa == TENTATIVAS_APAGAR_BANCO - 1:
                raise
            time.sleep(ESPERA_APAGAR_BANCO_S)


@pytest.fixture
def banco_de_teste():
    """Banco vazio, um por teste."""
    with banco_temporario() as con:
        yield con


@pytest.fixture
def banco_com_ddl():
    """Banco com todo o DDL (01 em diante) e as procedures aplicados, um por teste."""
    with banco_temporario() as con:
        banco.aplicar_ddl(con)
        banco.aplicar_procedures(con)
        yield con


@pytest.fixture(scope="module")
def banco_compartilhado():
    """Banco com DDL e procedures, um por módulo de testes (só para testes que não gravam nada)."""
    with banco_temporario() as con:
        banco.aplicar_ddl(con)
        banco.aplicar_procedures(con)
        yield con
