"""Desempenho do vendedor por setor (percentil 25 nos dias lotado) e a view do simulador."""

import dataclasses
import shutil

import numpy as np
import pandas as pd
import pytest

from src.etl.leitura import carregar_para_staging
from src.etl.mapeamento import carregar_fontes

pytestmark = pytest.mark.banco


@pytest.fixture
def banco_carregado(banco_com_ddl, dados_pequenos, tmp_path):
    params, _ = dados_pequenos
    pasta = tmp_path / "raw"
    shutil.copytree(params.diretorio_saida, pasta)
    fonte = dataclasses.replace(carregar_fontes()["lojas_ipe_erp"], pasta=pasta)
    id_carga = carregar_para_staging(banco_com_ddl, fonte).id_carga
    banco_com_ddl.execute("CALL etl.carregar_dw(%s)", (id_carga,))
    banco_com_ddl.commit()
    return banco_com_ddl


def _consulta(con, sql, params=None):
    cur = con.execute(sql, params or {})
    return pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])


def _gravar(con):
    ref = con.execute("SELECT dw.data_referencia()").fetchone()[0]
    con.execute("CALL dw.gravar_desempenho_vendedor_setor(%s)", (ref,))
    con.commit()
    return ref


def test_uma_linha_por_vendedor_ativo_e_setor_e_a_procedure_e_idempotente(banco_carregado):
    con = banco_carregado
    ref = _gravar(con)
    ativos = con.execute(
        "SELECT count(*) FROM dw.dim_vendedor WHERE data_admissao <= %s"
        " AND (data_desligamento IS NULL OR data_desligamento > %s)",
        (ref, ref),
    ).fetchone()[0]
    setores = con.execute("SELECT count(DISTINCT setor) FROM dw.dim_produto").fetchone()[0]
    total = con.execute("SELECT count(*) FROM dw.desempenho_vendedor_setor").fetchone()[0]
    assert total == ativos * setores
    _gravar(con)
    assert con.execute("SELECT count(*) FROM dw.desempenho_vendedor_setor").fetchone()[0] == total
    lotados = con.execute(
        "SELECT count(*) FROM dw.desempenho_vendedor_setor WHERE lotado_na_referencia"
    ).fetchone()[0]
    assert lotados == ativos  # cada vendedor ativo trabalha em exatamente um setor


def test_p25_bate_com_o_calculo_independente_incluindo_os_dias_sem_venda(banco_carregado):
    con = banco_carregado
    ref = _gravar(con)
    janela = int(con.execute("SELECT etl.parametro('simulador_janela_dias')").fetchone()[0])
    inicio = ref - pd.Timedelta(days=janela - 1)
    vendas = _consulta(
        con,
        "SELECT v.sk_vendedor, v.sk_loja, p.setor, t.data, v.receita_liquida r"
        " FROM dw.fato_vendas v JOIN dw.dim_tempo t USING (sk_tempo)"
        " JOIN dw.dim_produto p USING (sk_produto)"
        " WHERE v.status = 'Concluída' AND t.data BETWEEN %(i)s AND %(f)s",
        {"i": inicio, "f": ref},
    )
    vendas["r"] = vendas.r.astype(float)
    dias_da_loja = vendas.groupby("sk_loja").data.unique()
    historico = _consulta(
        con,
        "SELECT h.sk_vendedor, d.sk_loja, h.setor, h.data_inicio, h.data_fim,"
        " d.data_admissao, d.data_desligamento FROM dw.vendedor_setor_historico h"
        " JOIN dw.dim_vendedor d USING (sk_vendedor)",
    )
    desempenho = _consulta(
        con, "SELECT * FROM dw.desempenho_vendedor_setor WHERE dias_lotado >= 10"
    ).set_index(["sk_vendedor", "setor"])
    assert len(desempenho) > 0
    conferidos = 0
    for linha in historico.itertuples():
        chave = (linha.sk_vendedor, linha.setor)
        if chave not in desempenho.index or conferidos >= 15:
            continue
        # um vendedor com um único período no setor (os demais exigiriam somar períodos)
        if (
            (historico.sk_vendedor == linha.sk_vendedor) & (historico.setor == linha.setor)
        ).sum() > 1:
            continue
        fim = min(linha.data_fim or ref, ref)
        ini = max(linha.data_inicio, inicio)
        dias = [
            d for d in dias_da_loja[linha.sk_loja]
            if ini <= d <= fim and d >= linha.data_admissao
            and (linha.data_desligamento is None or d < linha.data_desligamento)
        ]  # fmt: skip
        do_vendedor = (
            vendas[(vendas.sk_vendedor == linha.sk_vendedor) & (vendas.setor == linha.setor)]
            .groupby("data")
            .r.sum()
        )
        serie = np.array([do_vendedor.get(d, 0.0) for d in dias])
        linha_dw = desempenho.loc[chave]
        assert linha_dw.dias_lotado == len(dias)
        assert float(linha_dw.p25_diaria) == pytest.approx(np.percentile(serie, 25), abs=0.011)
        assert float(linha_dw.media_diaria) == pytest.approx(serie.mean(), abs=0.011)
        assert linha_dw.dias_com_venda == (serie > 0).sum()
        conferidos += 1
    assert conferidos > 0


def test_pouco_historico_usa_o_fallback_e_a_confianca_acompanha_os_dias(banco_carregado):
    con = banco_carregado
    _gravar(con)
    minimo = int(con.execute("SELECT etl.parametro('simulador_min_dias_historico')").fetchone()[0])
    alta = int(con.execute("SELECT etl.parametro('simulador_dias_confianca_alta')").fetchone()[0])
    d = _consulta(con, "SELECT * FROM dw.desempenho_vendedor_setor")
    proprio = d[d.dias_lotado >= minimo]
    assert (~proprio.usa_fallback).all()
    assert (proprio.valor_conservador == proprio.p25_diaria).all()
    assert (proprio[proprio.dias_lotado >= alta].confianca == "alta").all()
    assert (proprio[proprio.dias_lotado < alta].confianca == "media").all()
    fallback = d[d.dias_lotado < minimo]
    assert len(fallback) > 0 and fallback.usa_fallback.all()
    com_base = fallback[fallback.valor_conservador.notna()]
    assert (com_base.valor_conservador == com_base.p25_fallback).all()
    assert com_base.confianca.isin(["baixa", "muito_baixa"]).all()
    assert (fallback[fallback.valor_conservador.isna()].confianca == "sem_base").all()
    assert (fallback.nivel_fallback.dropna().isin(["loja", "rede"])).all()


def test_view_do_simulador_respeita_a_demanda_do_setor_e_so_projeta_dias_futuros(banco_carregado):
    con = banco_carregado
    ref = _gravar(con)
    base = _consulta(
        con,
        "SELECT sk_loja, setor, media_loja_setor FROM dw.desempenho_vendedor_setor"
        " WHERE media_loja_setor > 0 LIMIT 1",
    ).iloc[0]
    for k, fator in enumerate((1.0, 0.1), start=1):  # um dia normal e um de demanda muito baixa
        con.execute(
            "INSERT INTO dw.previsao_vendas (granularidade, data, sk_loja, setor, valor_previsto,"
            " valor_baixo, valor_alto, versao_modelo, treino_ate, nivel) VALUES"
            " ('dia', %s + %s, %s, %s, %s, 0, %s, 'teste@1', %s, 'loja_setor')",
            (ref, k, int(base.sk_loja), base.setor, float(base.media_loja_setor) * fator,
             float(base.media_loja_setor) * 2, ref),
        )  # fmt: skip
    con.commit()
    v = _consulta(con, "SELECT * FROM dw.vw_simulador_troca")
    assert len(v) > 0 and (v.dia > ref).all()
    assert set(v.setor_destino) == {base.setor} and (v.dia.nunique() == 2)
    v["teto"] = v.demanda_restante.astype(float)
    cheia = v.base_conservadora.astype(float) * v.fator_sazonal.astype(float)
    assert (v.projecao_dia.astype(float) <= v.teto + 1e-6).all()
    assert (v.projecao_dia.astype(float) <= cheia + 1e-6).all()
    assert (v.projecao_dia.astype(float) >= 0).all()
    assert (v.demanda_restante.astype(float) <= v.demanda_prevista.astype(float) + 1e-6).all()


def test_backtest_do_simulador_avalia_trocas_e_placebo_e_grava_de_forma_idempotente(
    banco_carregado, dados_pequenos
):
    import pandas as pd

    from src import config
    from src.simulador import backtest

    con = banco_carregado
    _gravar(con)
    historico = backtest.Historico(con)
    trocas = backtest.eventos_de_troca(historico)
    assert len(trocas) == len(
        pd.read_csv(dados_pequenos[0].diretorio_saida / config.ARQ_TROCAS_SETOR, sep=";")
    )
    resultado = backtest.executar(historico)
    assert "trocas" in set(resultado.grupo) <= {"trocas", "placebo"}  # placebo exige histórico
    assert set(resultado.horizonte_dias) == set(config.SIMULADOR_HORIZONTES_DIAS)
    assert resultado.cobertura_conservadora.between(0, 1).all()
    assert (resultado.semanas == resultado.eventos * resultado.horizonte_dias // 7).all()
    assert (resultado.wape >= 0).all()
    # o método conservador nunca projeta mais do que o central (p25 <= média nos mesmos dias)
    chave = ["grupo", "horizonte_dias"]
    c = resultado[resultado.metodo == "completo"].set_index(chave)
    m = resultado[resultado.metodo == "completo_central"].set_index(chave)
    assert (c.vies <= m.vies + 1e-9).all()
    n = backtest.gravar(con, resultado)
    assert backtest.gravar(con, resultado) == n
    assert con.execute("SELECT count(*) FROM dw.simulador_backtest").fetchone()[0] == n
