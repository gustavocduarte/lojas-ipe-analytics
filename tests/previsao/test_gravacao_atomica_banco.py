"""A gravação da probabilidade é atômica: as três tabelas ficam gravadas juntas ou nenhuma."""

from types import SimpleNamespace

import numpy as np
import pytest

from src.previsao import probabilidade as prob
from src.previsao import probabilidade_execucao as execucao
from src.previsao import probabilidade_gravacao as gravacao
from tests.etl import base_alertas as b
from tests.previsao.test_probabilidade_meta import _cortes, _para_avaliar
from tests.previsao.test_probabilidade_meta_banco import (
    FIM,
    INICIO,
    _cortes_gravaveis,
    _inserir,
    _lojas,
    _n,
)

pytestmark = pytest.mark.banco

TABELAS = (
    "previsao_probabilidade_meta",
    "previsao_probabilidade_calibracao",
    "previsao_erro_resto",
)


@pytest.fixture
def base(banco_com_ddl):
    b.montar_base(banco_com_ddl, ano=2025)
    return banco_com_ddl


@pytest.fixture
def resultado(base, monkeypatch):
    sks = _lojas(base)
    calibracao = prob.avaliar(_para_avaliar(), "so_passado")
    _, modelos = prob.calcular_probabilidades(_cortes(np.random.default_rng(31)), "so_passado")
    ajuste = prob.linhas_do_ajuste(modelos)
    ajuste["sk_loja"] = ajuste["sk_loja"].map({1: sks[0], 2: sks[1]})
    monkeypatch.setattr(execucao.prob, "linhas_do_ajuste", lambda _modelos: ajuste)
    return SimpleNamespace(
        so_passado=_cortes_gravaveis(sks), calibracao=calibracao, modelos=modelos,
        inicio=INICIO.date(), fim=FIM.date(),
    )  # fmt: skip


def _foto(con) -> dict[str, list]:
    return {t: con.execute(f"SELECT * FROM dw.{t} ORDER BY 1").fetchall() for t in TABELAS}


def test_caminho_feliz_grava_as_tres_partes_com_o_mesmo_rotulo(base, resultado):
    linhas = execucao.gravar(base, resultado)
    assert all(n > 0 for n in linhas.values())
    rotulos = {
        t: {v for (v,) in base.execute(f"SELECT DISTINCT versao FROM dw.{t}")} for t in TABELAS
    }
    assert rotulos == {t: {"decomposicao@2/prob@1"} for t in TABELAS}
    assert gravacao.versao() == "decomposicao@2/prob@1"
    assert [_n(base, t) for t in TABELAS] == [
        linhas["probabilidades"], linhas["calibracao"], linhas["erro_resto"],
    ]  # fmt: skip


def test_falha_na_terceira_gravacao_nao_deixa_nada_gravado(base, resultado, monkeypatch):
    # uma gravação anterior (outro rótulo) que tem que continuar exatamente como estava
    _inserir(base, versao="antiga", probabilidade=0.3)
    base.commit()
    antes = _foto(base)
    real = gravacao.gravar_erro_resto

    def terceira_que_falha(conexao, ajuste, **kw):
        real(conexao, ajuste, **kw)  # escreve de verdade (na transação) e só depois falha
        raise RuntimeError("falha forçada na terceira gravação")

    monkeypatch.setattr(execucao.gravacao, "gravar_erro_resto", terceira_que_falha)
    with pytest.raises(RuntimeError, match="falha forçada"):
        execucao.gravar(base, resultado)
    assert _foto(base) == antes
    assert _n(base, "previsao_probabilidade_meta", "versao = 'decomposicao@2/prob@1'") == 0


def test_com_confirmar_falso_as_funcoes_nao_fazem_commit_nem_rollback(base, resultado):
    gravacao.gravar_probabilidades(
        base, resultado.so_passado, resultado.inicio, resultado.fim, confirmar=False
    )
    assert _n(base, "previsao_probabilidade_meta") > 0  # visível na própria transação
    base.rollback()  # quem chamou decide: aqui, desfaz
    assert _n(base, "previsao_probabilidade_meta") == 0
