"""Fixtures compartilhadas. Nada aqui acessa rede, banco real ou a pasta data/."""

from dataclasses import replace

import pytest

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
