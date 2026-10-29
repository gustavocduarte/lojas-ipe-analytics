"""Fixtures compartilhadas. Nada aqui acessa rede, banco real ou a pasta data/."""

import os
import uuid
from dataclasses import replace

import psycopg
import pytest
from psycopg import sql

from src import banco, config
from src.gerador.parametros import ParametrosGeracao
from src.gerador.principal import gerar_dados

LINHAS_VENDA_TESTE = 2_400  # volume pequeno: 100 linhas por mês


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


@pytest.fixture
def banco_de_teste():
    """Cria um banco descartável com nome único e o apaga ao final (só o dono consegue apagar)."""
    acesso = parametros_banco_de_teste()
    nome = f"teste_lojas_ipe_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(dbname="postgres", autocommit=True, **acesso) as con:
        con.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(nome)))
    try:
        with psycopg.connect(dbname=nome, **acesso) as con:
            yield con
    finally:
        with psycopg.connect(dbname="postgres", autocommit=True, **acesso) as con:
            con.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(nome))
            )


@pytest.fixture
def banco_com_ddl(banco_de_teste):
    """Banco de teste com todo o DDL (01 em diante) aplicado."""
    banco.aplicar_ddl(banco_de_teste)
    return banco_de_teste
