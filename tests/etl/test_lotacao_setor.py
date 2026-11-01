"""Carga da lotação por setor (stg -> dw.vendedor_setor_historico): validações e idempotência."""

import dataclasses
import shutil
from datetime import timedelta

import pytest

from src import config
from src.etl import pipeline
from src.etl.leitura import carregar_para_staging
from src.etl.mapeamento import carregar_fontes
from tests.gerador.utilitarios import data, ler_csv

pytestmark = pytest.mark.banco


@pytest.fixture
def erp(dados_pequenos, tmp_path):
    params, _ = dados_pequenos
    pasta = tmp_path / "raw"
    shutil.copytree(params.diretorio_saida, pasta)
    return dataclasses.replace(carregar_fontes()["lojas_ipe_erp"], pasta=pasta)


def _carregar(con, fonte, **opcoes):
    id_carga = carregar_para_staging(con, fonte, **opcoes).id_carga
    con.execute("CALL etl.carregar_dw(%s)", (id_carga,))
    con.commit()
    return id_carga


def _editar(pasta, linha, coluna, valor):
    """Troca uma célula de lotacao_setor.csv (linha = posição de dados, 1 = a primeira)."""
    caminho = pasta / config.ARQ_LOTACAO_SETOR
    linhas = caminho.read_text(encoding="utf-8").splitlines()
    cabecalho = linhas[0].split(";")
    partes = linhas[linha].split(";")
    partes[cabecalho.index(coluna)] = valor
    linhas[linha] = ";".join(partes)
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")


def _rejeitados(con):
    return {
        (lin, col): m
        for lin, col, m in con.execute(
            "SELECT linha_origem, coluna, motivo FROM stg.rejeitados"
            " WHERE entidade = 'lotacao_setor'"
        )
    }


def _contar(con):
    return con.execute("SELECT count(*) FROM dw.vendedor_setor_historico").fetchone()[0]


def test_toda_linha_do_arquivo_vira_um_periodo_no_dw(banco_com_ddl, erp):
    _carregar(banco_com_ddl, erp)
    arquivo = ler_csv(erp.pasta / config.ARQ_LOTACAO_SETOR)
    assert _contar(banco_com_ddl) == len(arquivo) > 185
    assert not _rejeitados(banco_com_ddl)
    periodos = banco_com_ddl.execute(
        "SELECT d.cod_vendedor, h.setor, h.data_inicio, h.data_fim, h.motivo"
        " FROM dw.vendedor_setor_historico h JOIN dw.dim_vendedor d USING (sk_vendedor)"
    ).fetchall()
    do_dw = {(c, i): (s, f, m) for c, s, i, f, m in periodos}
    for linha in arquivo.itertuples():
        chave = (linha.cod_vendedor, data(linha.data_inicio))
        fim = data(linha.data_fim) if linha.data_fim else None
        assert do_dw[chave] == (linha.setor, fim, linha.motivo)


def test_trocas_do_gabarito_aparecem_como_viradas_de_periodo_no_dw(banco_com_ddl, erp):
    _carregar(banco_com_ddl, erp)
    sql = (
        "SELECT h.setor FROM dw.vendedor_setor_historico h"
        " JOIN dw.dim_vendedor d USING (sk_vendedor)"
        " WHERE d.cod_vendedor = %s AND %s::DATE BETWEEN h.data_inicio"
        " AND COALESCE(h.data_fim, 'infinity')"
    )
    for t in ler_csv(erp.pasta / config.ARQ_TROCAS_SETOR).itertuples():
        dia = data(t.data_troca)
        antes = banco_com_ddl.execute(sql, (t.cod_vendedor, dia - timedelta(days=1))).fetchone()[0]
        depois = banco_com_ddl.execute(sql, (t.cod_vendedor, dia)).fetchone()[0]
        assert (antes, depois) == (t.setor_origem, t.setor_destino)


def test_periodos_de_um_vendedor_nunca_se_sobrepoem_e_a_validacao_estrutural_passa(
    banco_com_ddl, erp, tmp_path
):
    resultado = pipeline.carregar(
        banco_com_ddl, erp, verificar_memoria=False, pasta_relatorios=tmp_path / "relatorios"
    )
    sobrepostos = banco_com_ddl.execute(
        "SELECT count(*) FROM dw.vendedor_setor_historico a JOIN dw.vendedor_setor_historico b"
        " ON a.sk_vendedor = b.sk_vendedor AND a.sk_lotacao < b.sk_lotacao"
        " WHERE a.data_inicio <= COALESCE(b.data_fim, 'infinity')"
        " AND b.data_inicio <= COALESCE(a.data_fim, 'infinity')"
    ).fetchone()[0]
    assert sobrepostos == 0
    validacoes = dict(
        banco_com_ddl.execute(
            "SELECT validacao, ok FROM etl.carga_validacoes WHERE id_carga = %s",
            (resultado.id_carga,),
        ).fetchall()
    )
    assert validacoes["lotacao_sem_sobreposicao"] is True
    assert validacoes["contagem_lotacao_setor"] is True


def test_linhas_invalidas_sao_rejeitadas_com_o_motivo(banco_com_ddl, erp):
    arquivo = ler_csv(erp.pasta / config.ARQ_LOTACAO_SETOR)
    # linhas 1..: vendedor que não existe, setor que não existe, datas ruins, fim antes do início
    _editar(erp.pasta, 1, "cod_vendedor", "V9999")
    _editar(erp.pasta, 2, "setor", "Brinquedos")
    _editar(erp.pasta, 3, "data_inicio", "31/02/2024")
    _editar(erp.pasta, 4, "data_fim", "01/01/2000")
    _editar(erp.pasta, 5, "data_inicio", "01/01/1990")  # antes da admissão
    _carregar(banco_com_ddl, erp)
    rejeitados = _rejeitados(banco_com_ddl)
    assert rejeitados[(1, "cod_vendedor")] == "vendedor_inexistente"
    assert rejeitados[(2, "setor")] == "setor_inexistente"
    assert rejeitados[(3, "data_inicio")] == "data_invalida"
    assert rejeitados[(4, "data_fim")] == "fim_antes_do_inicio"
    assert rejeitados[(5, "data_inicio")] == "inicio_antes_da_admissao"
    assert _contar(banco_com_ddl) == len(arquivo) - 5


def test_periodo_depois_do_desligamento_e_periodo_sobreposto_sao_rejeitados(banco_com_ddl, erp):
    vendedores = ler_csv(erp.pasta / config.ARQ_VENDEDORES)
    arquivo = ler_csv(erp.pasta / config.ARQ_LOTACAO_SETOR)
    desligado = vendedores[vendedores.data_desligamento != ""].cod_vendedor.iloc[0]
    ultima = arquivo.index[arquivo.cod_vendedor == desligado].tolist()[-1]
    _editar(erp.pasta, ultima + 1, "data_fim", "")  # período aberto de quem foi desligado
    quem_troca = ler_csv(erp.pasta / config.ARQ_TROCAS_SETOR).cod_vendedor.iloc[0]
    linhas = arquivo.index[arquivo.cod_vendedor == quem_troca].tolist()
    inicio_do_primeiro = data(arquivo.data_inicio[linhas[0]])
    dentro = (inicio_do_primeiro + timedelta(days=10)).strftime(config.FORMATO_DATA_BR)
    _editar(erp.pasta, linhas[1] + 1, "data_inicio", dentro)  # começa dentro do período anterior
    _carregar(banco_com_ddl, erp)
    rejeitados = _rejeitados(banco_com_ddl)
    assert rejeitados[(ultima + 1, "data_fim")] == "periodo_depois_do_desligamento"
    assert rejeitados[(linhas[1] + 1, "data_inicio")] == "periodo_sobreposto"
    assert _contar(banco_com_ddl) == len(arquivo) - 2


def test_segunda_carga_nao_muda_nada_e_periodo_que_saiu_do_arquivo_sai_do_dw(banco_com_ddl, erp):
    _carregar(banco_com_ddl, erp)
    total = _contar(banco_com_ddl)
    id_segunda = _carregar(banco_com_ddl, erp, modo="completo")
    inseridas, atualizadas = banco_com_ddl.execute(
        "SELECT inseridas, atualizadas FROM etl.carga_tabelas WHERE id_carga = %s"
        " AND entidade = 'lotacao_setor'",
        (id_segunda,),
    ).fetchone()
    assert (inseridas, atualizadas) == (0, 0) and _contar(banco_com_ddl) == total
    caminho = erp.pasta / config.ARQ_LOTACAO_SETOR
    linhas = caminho.read_text(encoding="utf-8").splitlines()
    quem_troca = ler_csv(erp.pasta / config.ARQ_TROCAS_SETOR).cod_vendedor.iloc[0]
    do_vendedor = [k for k, linha in enumerate(linhas) if linha.startswith(quem_troca + ";")]
    del linhas[do_vendedor[-1]]  # some o último período de quem trocou de setor
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    id_terceira = _carregar(banco_com_ddl, erp, modo="completo")
    removidas = banco_com_ddl.execute(
        "SELECT removidas FROM etl.carga_tabelas"
        " WHERE id_carga = %s AND entidade = 'lotacao_setor'",
        (id_terceira,),
    ).fetchone()[0]
    assert removidas == 1 and _contar(banco_com_ddl) == total - 1
