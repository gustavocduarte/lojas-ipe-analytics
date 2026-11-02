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


def test_fatia_do_dw_bate_com_o_estimador_independente_em_python(banco_carregado):
    from src import config
    from src.simulador import fatias

    con = banco_carregado
    ref = _gravar(con)
    k = float(con.execute("SELECT etl.parametro('simulador_k_encolhimento')").fetchone()[0])
    q = float(con.execute("SELECT etl.parametro('simulador_percentil_fatia')").fetchone()[0])
    historico = fatias.Historico(con)
    assert historico.fim == ref
    semanal = fatias.Semanal(historico)
    d = _consulta(con, "SELECT * FROM dw.desempenho_vendedor_setor")
    assert (d.k_encolhimento.astype(float) == k).all() and d.fatia_central.notna().all()
    assert (d.fatia_semanas > 0).sum() > 10
    conferidos = {"proprio": 0, "sem_historico": 0}
    for linha in d.sort_values(["sk_vendedor", "setor"]).itertuples():
        proprias = semanal.observacoes(linha.sk_vendedor, linha.setor, ref)
        conjunto = semanal.conjunto(linha.sk_loja, linha.setor, ref, linha.sk_vendedor)
        assert linha.fatia_semanas == len(proprias)
        esperado = fatias.estimar(proprias, conjunto, k, q)
        if esperado is None:
            continue
        assert float(linha.fatia_central) == pytest.approx(esperado[0], abs=2e-6)
        assert float(linha.fatia_conservadora) == pytest.approx(esperado[1], abs=2e-6)
        conferidos["proprio" if len(proprias) else "sem_historico"] += 1
        if min(conferidos.values()) >= 25:
            break
    assert conferidos["proprio"] > 0 and conferidos["sem_historico"] > 0
    assert (
        d.confianca_fatia[d.fatia_semanas >= config.SIMULADOR_SEMANAS_CORRELACAO] == "alta"
    ).all()


def test_view_do_simulador_e_semanal_e_projeta_fatia_vezes_a_demanda_do_setor(banco_carregado):
    con = banco_carregado
    ref = _gravar(con)
    alvo = _consulta(
        con,
        "SELECT sk_loja, setor FROM dw.desempenho_vendedor_setor WHERE fatia_central IS NOT NULL"
        " LIMIT 1",
    ).iloc[0]
    for dia in range(1, 11):  # uma semana inteira (1..7) e uma incompleta (8..10)
        con.execute(
            "INSERT INTO dw.previsao_vendas (granularidade, data, sk_loja, setor, valor_previsto,"
            " valor_baixo, valor_alto, versao_modelo, treino_ate, nivel) VALUES"
            " ('dia', %s + %s, %s, %s, 100, 0, 200, 'teste@1', %s, 'loja_setor')",
            (ref, dia, int(alvo.sk_loja), alvo.setor, ref),
        )
    con.commit()
    v = _consulta(con, "SELECT * FROM dw.vw_simulador_troca")
    assert len(v) > 0 and set(v.setor_destino) == {alvo.setor} and set(v.semana) == {1}
    assert (v.demanda_prevista_semana.astype(float) == 700).all()  # só a semana completa
    assert (v.semana_inicio == ref + pd.Timedelta(days=1)).all()
    esperado = v.fatia_central.astype(float) * 700
    assert np.allclose(v.projecao_central.astype(float), esperado, atol=1e-3)
    assert (v.projecao_conservadora.astype(float) <= v.projecao_central.astype(float) + 1e-3).all()
    assert v.confianca_fatia.notna().all() and (v.projecao_central.astype(float) >= 0).all()


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


def test_backtest_v2_fatias_semanais_tabela_e_gravacao_idempotente(banco_carregado):
    from src import config
    from src.simulador import fatias

    con = banco_carregado
    historico = fatias.Historico(con)
    semanal = fatias.Semanal(historico)
    itens = fatias.preparar(historico, semanal)
    assert itens
    for item in itens:
        assert ((item["proprias"] >= 0) & (item["proprias"] <= 1 + 1e-9)).all()
        assert len(item["previsto_semana"]) == len(item["real_semana"]) == 8
    ks = fatias.escolher_k(itens)
    assert list(ks.k) == list(config.SIMULADOR_K_GRADE)
    k = fatias.k_escolhido(ks)
    curva = fatias.curva_percentil(itens, k)
    # mais percentil, mais projeção: a cobertura nunca sobe
    for _, g in curva.groupby(["grupo", "horizonte_dias"]):
        assert g.sort_values("percentil").cobertura_conservadora.is_monotonic_decreasing
    percentil = fatias.escolher_percentil(curva)
    tabela = fatias.tabela_final(itens, k, percentil)
    assert {"v2_central", "v2_conservador", "completo_p25_diario", "ingenuo"} <= set(tabela.metodo)
    n = fatias.gravar(con, tabela, curva, k, percentil)
    assert fatias.gravar(con, tabela, curva, k, percentil) == n
    assert (
        con.execute("SELECT count(*) FROM dw.simulador_backtest WHERE versao = 'v2'").fetchone()[0]
        == n
    )
    assert con.execute("SELECT count(*) FROM dw.simulador_backtest_curva").fetchone()[0] == len(
        curva
    )
