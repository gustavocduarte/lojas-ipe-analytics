"""Probabilidade de bater a meta do mês: a lógica, sem banco (dados sintéticos escritos à mão)."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from src import config
from src.previsao import probabilidade as prob
from src.previsao import probabilidade_cortes as cortes_mod
from src.previsao import probabilidade_gravacao as gravacao
from src.previsao.painel import Painel
from src.previsao.probabilidade import REDE, ModeloErro

SIGMAS = [0.03, 0.05, 0.08, 0.11, 0.14]  # dispersão de ln R por faixa de dias que faltam
MESES = pd.to_datetime([f"2025-{m:02d}-01" for m in range(1, 7)])


def _amostras(rng, lojas=(1, 2, 3), meses=MESES, por_mes=8, sigmas=SIGMAS, vies=0.0, nivel="loja"):
    linhas = []
    for sk in lojas:
        for mes in meses:
            for faixa, sigma in enumerate(sigmas):
                for ln_r in rng.normal(vies, sigma, por_mes):
                    linhas.append((nivel, sk, mes, faixa, ln_r))
    return pd.DataFrame(linhas, columns=["nivel", "sk_loja", "mes", "faixa", "ln_r"])


def _modelo(seed=1, **kw) -> ModeloErro:
    return prob.ajustar_erro(_amostras(np.random.default_rng(seed), **kw))


def _p(modelo, dias, realizado, prev, meta=1000.0, nivel="loja", sk=1):
    p, motivo = prob.probabilidade_do_corte(modelo, nivel, sk, dias, realizado, prev, meta)
    assert motivo is None
    return p


# --- faixas e encolhimento ------------------------------------------------------------------------
def test_faixas_de_dias_que_faltam():
    assert prob.faixa_de_dias(0) == -1  # último dia do mês: não há incerteza
    assert [prob.faixa_de_dias(d) for d in (1, 5, 6, 10, 11, 15, 16, 22, 23, 31)] == [
        0, 0, 1, 1, 2, 2, 3, 3, 4, 4,
    ]  # fmt: skip


def test_peso_do_encolhimento_e_n_sobre_n_mais_k():
    assert config.PROB_SHRINKAGE_K == 4
    assert prob.peso_do_encolhimento(4) == pytest.approx(0.5)
    assert prob.peso_do_encolhimento(0) == 0
    assert prob.peso_do_encolhimento(12) == pytest.approx(0.75)


def test_parametros_da_loja_sao_a_mistura_com_peso_n_sobre_n_mais_k():
    rng = np.random.default_rng(3)
    estavel = _amostras(rng, lojas=(1, 2), meses=MESES, sigmas=[0.05] * 5)
    # a loja 9 tem só 4 meses e é bem mais instável e enviesada
    instavel = _amostras(rng, lojas=(9,), meses=MESES[:4], sigmas=[0.30] * 5, vies=0.2)
    m = prob.ajustar_erro(pd.concat([estavel, instavel], ignore_index=True))
    p, base = m.loja[(9, 0)], m.conjunto[0]
    assert p.n_meses == 4 and p.peso == pytest.approx(0.5)
    assert p.mu == pytest.approx(p.peso * p.mu_bruto + (1 - p.peso) * base.mu)
    assert p.sigma**2 == pytest.approx(p.peso * p.sigma_bruto**2 + (1 - p.peso) * base.sigma**2)
    assert base.sigma < p.sigma < p.sigma_bruto  # encolhida: entre a loja e o conjunto
    assert m.loja[(1, 0)].peso == pytest.approx(6 / 10)  # 6 meses: 6 / (6 + 4)


def test_peso_conta_meses_distintos_e_nao_cortes_do_mesmo_mes():
    # muitos cortes num mesmo mês continuam sendo 1 mês de evidência
    rng = np.random.default_rng(4)
    a = _amostras(rng, lojas=(1, 2), meses=MESES, por_mes=3)
    b = _amostras(rng, lojas=(5,), meses=MESES[:2], por_mes=40)
    m = prob.ajustar_erro(pd.concat([a, b], ignore_index=True))
    assert m.loja[(5, 0)].n_meses == 2
    assert m.loja[(5, 0)].peso == pytest.approx(2 / 6)


def test_faixa_com_poucos_meses_fica_sem_parametros():
    m = prob.ajustar_erro(
        _amostras(np.random.default_rng(5), meses=MESES[: config.PROB_MESES_MINIMOS - 1])
    )
    assert m.conjunto == {} and len(m.forma) == 0
    p, motivo = prob.probabilidade_do_corte(m, "loja", 1, 10, 100.0, 900.0, 1000.0)
    assert p is None and motivo == "sem_amostra_erro"  # nunca 50%


# --- propriedades da probabilidade ----------------------------------------------------------------
def test_no_ultimo_dia_do_mes_p_e_exatamente_0_ou_1_mesmo_sem_modelo():
    vazio = ModeloErro(meses_ate=None, n_meses=0, k=4)
    for modelo in (vazio, _modelo()):
        assert prob.probabilidade_do_corte(modelo, "loja", 1, 0, 1000.0, 0.0, 1000.0) == (1.0, None)
        assert prob.probabilidade_do_corte(modelo, "loja", 1, 0, 999.99, 0.0, 1000.0) == (0.0, None)
        assert prob.probabilidade_do_corte(modelo, "rede", REDE, 0, 5.0, 0.0, 1000.0) == (0.0, None)


def test_meta_ja_batida_vale_1_e_sem_meta_fica_sem_base():
    m = _modelo()
    assert prob.probabilidade_do_corte(m, "loja", 1, 20, 1200.0, 500.0, 1000.0) == (1.0, None)
    assert prob.probabilidade_do_corte(m, "loja", 1, 20, 100.0, 500.0, 0.0) == (None, "sem_meta")
    assert prob.probabilidade_do_corte(m, "loja", 1, 20, 100.0, 500.0, float("nan")) == (
        None,
        "sem_meta",
    )
    assert prob.probabilidade_do_corte(m, "loja", 1, 20, 100.0, 0.0, 1000.0) == (
        None,
        "sem_previsao",
    )


@pytest.mark.parametrize("dias", [3, 12, 28])
def test_p_cresce_com_o_realizado_e_com_a_cobertura_projetada(dias):
    m = _modelo()
    prev = 35.0 * dias
    realizados = np.linspace(0, 999, 60)
    ps = [_p(m, dias, r, prev) for r in realizados]
    assert all(b >= a for a, b in zip(ps, ps[1:], strict=False))  # nunca diminui
    assert ps[-1] > ps[0]
    assert 0 < min(ps) and max(ps) <= 1
    # projeção (= realizado + previsto) acima/abaixo da meta: P do lado certo de 50%
    assert _p(m, dias, 1000 - prev * 0.9, prev) > 0.5 > _p(m, dias, 1000 - prev * 1.1, prev)


def test_p_diminui_com_a_meta():
    m = _modelo()
    ps = [_p(m, 15, 500.0, 500.0, meta=x) for x in np.linspace(700, 1300, 40)]
    assert all(b <= a for a, b in zip(ps, ps[1:], strict=False))


def test_com_o_mesmo_desvio_relativo_p_fica_mais_perto_de_0_ou_1_com_menos_dias_restantes():
    m = _modelo()
    dias = [28, 18, 12, 8, 3]
    # projeção do mês sempre 5% acima (ou abaixo) da meta, em ritmo de 35 por dia
    acima = [_p(m, d, 1050 - 35.0 * d, 35.0 * d) for d in dias]
    abaixo = [_p(m, d, 950 - 35.0 * d, 35.0 * d) for d in dias]
    assert all(b >= a for a, b in zip(acima, acima[1:], strict=False)) and acima[-1] > 0.99
    assert all(b <= a for a, b in zip(abaixo, abaixo[1:], strict=False)) and abaixo[-1] < 0.01
    assert acima[0] < 0.9 and abaixo[0] > 0.1  # no começo do mês ainda há dúvida


def test_so_a_dispersao_menor_ja_aproxima_de_0_ou_1_mesmo_com_o_mesmo_nivel_de_resto():
    m = _modelo()
    # mesmo resto necessário (+3% sobre o previsto do resto), só muda a faixa
    maior = _p(m, 28, 1000 - 100.0 * 0.97, 100.0)  # faixa de 23-31 dias (sigma 0.14)
    menor = _p(m, 3, 1000 - 100.0 * 0.97, 100.0)  # faixa de 1-5 dias (sigma 0.03)
    assert menor > maior > 0.5


def test_a_rede_tem_dispersao_propria_e_nao_e_a_das_lojas():
    rng = np.random.default_rng(7)
    # erro-padrão do desvio-padrão amostral: sigma / sqrt(2 (N - 1)).
    # Conjunto: N = 3 lojas x 6 meses x 40 = 720 -> 0,20 / sqrt(1438) = 0,0053;
    # tolerância 0,02 = 3,8 EP.
    # Rede: N = 1 x 6 x 40 = 240 -> 0,04 / sqrt(478) = 0,0018; tolerância 0,01 = 5,5 EP.
    lojas = _amostras(rng, por_mes=40, sigmas=[0.20] * 5)
    rede = _amostras(rng, lojas=(REDE,), por_mes=40, sigmas=[0.04] * 5, nivel="rede")
    m = prob.ajustar_erro(pd.concat([lojas, rede], ignore_index=True))
    assert m.rede[2].sigma == pytest.approx(0.04, abs=0.01)
    assert m.conjunto[2].sigma == pytest.approx(0.20, abs=0.02)
    # os mesmos números: a rede (menos dispersa) fica mais decidida que a loja
    loja_p = _p(m, 12, 700.0, 350.0, nivel="loja")
    rede_p = _p(m, 12, 700.0, 350.0, nivel="rede", sk=REDE)
    assert rede_p > loja_p > 0.5


def test_cdf_da_forma_e_nao_decrescente():
    m = _modelo()
    zs = np.linspace(-6, 6, 200)
    assert all(m.cdf(b) >= m.cdf(a) for a, b in zip(zs, zs[1:], strict=False))
    assert 0 < m.cdf(-100) < 0.01 and 0.99 < m.cdf(100) < 1


# --- sem vazamento: cortes de teste ---------------------------------------------------------------
def _cortes(rng, mudar=None, meses=MESES):
    """Lojas 1 e 2 em seis meses (ou nos `meses` dados); cortes a 26, 20, 14, 8 e 2 dias do fim e
    o último."""
    linhas = []
    for mes in meses:
        for sk in (1, 2):
            for k in (26, 20, 14, 8, 2, 0):
                total_resto = 40.0 * k
                prev_resto = total_resto
                ln_r = rng.normal(0, SIGMAS[prob.faixa_de_dias(k)] if k else 0)
                real_resto = total_resto * np.exp(ln_r)
                realizado = 1000.0 - 40.0 * k + rng.normal(0, 5)
                if mudar is not None and mes == mudar:
                    real_resto = real_resto * 0.3  # desfecho muito pior só neste mês
                linhas.append(
                    {
                        "nivel": "loja", "sk_loja": sk, "corte": mes + pd.Timedelta(days=30 - k),
                        "mes": mes, "dias_restantes": k, "faixa": prob.faixa_de_dias(k),
                        "realizado_ate": realizado, "prev_resto": prev_resto,
                        "real_resto": real_resto, "meta": 1000.0, "base": True, "motivo": None,
                        "lojas_incluidas": None, "lojas_total": None,
                    }
                )  # fmt: skip
    return pd.DataFrame(linhas)


def test_so_passado_nao_usa_o_mes_avaliado_nem_os_posteriores():
    base = _cortes(np.random.default_rng(11))
    # o futuro (jun/2025) é tornado muito pior: as probabilidades de jan a mai não podem mudar
    futuro = base.copy()
    mascara = futuro["mes"] == MESES[5]
    futuro.loc[mascara, "real_resto"] = futuro.loc[mascara, "real_resto"] * 0.3
    a, _ = prob.calcular_probabilidades(base, "so_passado")
    b, _ = prob.calcular_probabilidades(futuro, "so_passado")
    # nem as de junho mudam: o desfecho de um mês nunca entra no ajuste dele nem dos anteriores
    pd.testing.assert_series_equal(a["probabilidade"], b["probabilidade"])
    # mas uma mudança em jan/2025 (passado de todos) muda as dos meses seguintes
    passado = base.copy()
    m = passado["mes"] == MESES[0]
    passado.loc[m, "real_resto"] = passado.loc[m, "real_resto"] * 0.3
    c, _ = prob.calcular_probabilidades(passado, "so_passado")
    depois = (a["mes"] > MESES[0]) & a["probabilidade"].notna() & a["dias_restantes"].between(1, 99)
    assert not np.allclose(a.loc[depois, "probabilidade"], c.loc[depois, "probabilidade"])


def test_so_passado_usa_so_meses_fechados_anteriores_e_o_primeiro_mes_fica_sem_base():
    cortes = _cortes(np.random.default_rng(12))
    com_p, modelos = prob.calcular_probabilidades(cortes, "so_passado")
    assert modelos[MESES[0]].meses_ate is None  # nada antes de janeiro
    assert modelos[MESES[4]].meses_ate == MESES[3] and modelos[MESES[4]].n_meses == 4
    jan = com_p[(com_p["mes"] == MESES[0]) & (com_p["dias_restantes"] > 0)]
    assert (
        jan["probabilidade"].isna().all() and (jan["motivo_sem_base"] == "sem_amostra_erro").all()
    )
    fim = com_p[com_p["dias_restantes"] == 0]  # último dia: 0 ou 1, também em janeiro
    assert set(fim["probabilidade"].unique()) <= {0.0, 1.0}


MESES_9 = pd.to_datetime([f"2025-{m:02d}-01" for m in range(1, 10)])


def test_janela_recente_guarda_os_ultimos_n_meses_distintos():
    a = _amostras(np.random.default_rng(3), meses=MESES_9, por_mes=2)
    ultimos = prob.janela_recente(a, 6)
    assert sorted(ultimos["mes"].unique()) == list(MESES_9[3:])
    assert len(prob.janela_recente(a, None)) == len(a)
    poucos = a[a["mes"] < MESES_9[4]]
    assert len(prob.janela_recente(poucos, 6)) == len(poucos)  # menos de 6 meses: fica tudo
    assert prob.janela_recente(a.iloc[0:0], 6).empty


def test_so_passado_usa_so_os_ultimos_6_meses_e_exige_o_minimo_de_3():
    assert config.PROB_JANELA_MESES == 6 and config.PROB_MESES_MINIMOS == 3
    base = _cortes(np.random.default_rng(21), meses=MESES_9)
    a, modelos = prob.calcular_probabilidades(base, "so_passado")
    assert modelos[MESES_9[8]].n_meses == 6  # março a agosto: fora janeiro e fevereiro
    assert modelos[MESES_9[8]].meses_ate == MESES_9[7]
    assert modelos[MESES_9[3]].n_meses == 3  # o mínimo: jan, fev e mar
    # com 2 meses de passado não há base; com 3, há
    cedo = a[(a["mes"] == MESES_9[2]) & (a["dias_restantes"] > 0)]
    ok = a[(a["mes"] == MESES_9[3]) & (a["dias_restantes"] > 0)]
    assert (cedo["motivo_sem_base"] == "sem_amostra_erro").all() and cedo[
        "probabilidade"
    ].isna().all()
    assert ok["probabilidade"].notna().all()
    # um desfecho antigo (jan) está fora da janela de setembro: nada muda lá, mas muda em abril
    velho = base.copy()
    m = velho["mes"] == MESES_9[0]
    velho.loc[m, "real_resto"] = velho.loc[m, "real_resto"] * 0.3
    b, _ = prob.calcular_probabilidades(velho, "so_passado")
    set_ = a["mes"] == MESES_9[8]
    pd.testing.assert_series_equal(a.loc[set_, "probabilidade"], b.loc[set_, "probabilidade"])
    abril = (a["mes"] == MESES_9[3]) & (a["dias_restantes"] > 0)
    assert not np.allclose(a.loc[abril, "probabilidade"], b.loc[abril, "probabilidade"])
    # sem janela (todo o passado) o desfecho de janeiro chega até setembro
    c, _ = prob.calcular_probabilidades(base, "so_passado", janela_meses=None)
    d, _ = prob.calcular_probabilidades(velho, "so_passado", janela_meses=None)
    assert not np.allclose(
        c.loc[set_ & (c["dias_restantes"] > 0), "probabilidade"],
        d.loc[set_ & (d["dias_restantes"] > 0), "probabilidade"],
    )


def test_leave_one_month_out_tira_o_mes_avaliado_mas_usa_os_posteriores():
    base = _cortes(np.random.default_rng(13))
    a, _ = prob.calcular_probabilidades(base, "leave_one_month_out")
    # piorar março muda as probabilidades dos OUTROS meses (usam março), não as de março
    pior = _cortes(np.random.default_rng(13), mudar=MESES[2])
    b, _ = prob.calcular_probabilidades(pior, "leave_one_month_out")
    marco = (a["mes"] == MESES[2]) & (a["dias_restantes"] > 0) & (a["realizado_ate"] < a["meta"])
    pd.testing.assert_series_equal(
        a.loc[marco, "probabilidade"], b.loc[marco, "probabilidade"], check_exact=False
    )
    outros = (a["mes"] != MESES[2]) & (a["dias_restantes"] > 0) & (a["realizado_ate"] < a["meta"])
    assert not np.allclose(a.loc[outros, "probabilidade"], b.loc[outros, "probabilidade"])


def test_esquema_desconhecido_e_recusado():
    with pytest.raises(ValueError, match="esquema"):
        prob.calcular_probabilidades(_cortes(np.random.default_rng(1)), "tudo")


def test_loja_sem_base_fica_sem_probabilidade_nunca_com_50_por_cento():
    cortes = _cortes(np.random.default_rng(14))
    nova = cortes["sk_loja"] == 2
    cortes.loc[nova, "base"] = False
    cortes.loc[nova, "motivo"] = "loja_nova"
    cortes.loc[nova, ["prev_resto"]] = np.nan
    com_p, _ = prob.calcular_probabilidades(cortes, "so_passado")
    sem = com_p[com_p["sk_loja"] == 2]
    assert sem["probabilidade"].isna().all() and (sem["motivo_sem_base"] == "loja_nova").all()
    assert not (com_p.loc[com_p["sk_loja"] == 1, "probabilidade"] == 0.5).any()


# --- calibração ----------------------------------------------------------------------------------
def test_intervalo_de_wilson():
    baixo, alto = prob.intervalo_wilson(0.5, 100)
    assert (baixo, alto) == pytest.approx((0.4188, 0.5812), abs=1e-3)
    b0, a0 = prob.intervalo_wilson(0.0, 10)
    assert b0 == 0.0 and 0 < a0 < 0.3
    assert all(np.isnan(prob.intervalo_wilson(0.5, 0)))


def _para_avaliar(n=100, p=0.9, acertos=90):
    return pd.DataFrame(
        {
            "nivel": "loja", "sk_loja": np.arange(n) % 10,
            "mes": MESES[0] + pd.to_timedelta(np.arange(n) // 10 * 31, "D"),
            "faixa": 2, "dias_restantes": 10, "probabilidade": p, "meta": 1000.0,
            "realizado_ate": 500.0,
            "real_resto": [600.0 if i < acertos else 100.0 for i in range(n)],
        }
    )  # fmt: skip


def test_brier_ece_e_referencias():
    r = prob.avaliar(_para_avaliar(), "so_passado")
    resumo = r[(r["tipo"] == "resumo") & (r["faixa_dias"] == 0)].iloc[0]
    assert resumo["n"] == 100 and resumo["observado"] == pytest.approx(0.9)
    assert resumo["brier"] == pytest.approx((90 * 0.1**2 + 10 * 0.9**2) / 100)
    assert resumo["brier_50"] == pytest.approx(0.25)
    assert resumo["brier_frequencia"] == pytest.approx(0.9 * 0.1)
    assert resumo["ece"] == pytest.approx(0.0, abs=1e-12)  # previsto 90% e observado 90%
    faixa = r[(r["tipo"] == "faixa") & (r["faixa_dias"] == 0)].iloc[0]
    assert (faixa["prob_inicio"], faixa["prob_fim"]) == pytest.approx((0.9, 1.0))
    assert faixa["n_unidades"] == 100 and faixa["ic_baixo"] < 0.9 < faixa["ic_alto"]


def test_ece_mede_o_desvio_entre_previsto_e_observado():
    r = prob.avaliar(_para_avaliar(p=0.9, acertos=50), "so_passado")
    assert r[(r["tipo"] == "resumo") & (r["faixa_dias"] == 0)].iloc[0]["ece"] == pytest.approx(0.4)


def test_calibracao_ignora_ultimo_dia_meta_batida_e_sem_probabilidade():
    d = _para_avaliar()
    extras = d.iloc[:3].copy()
    extras["dias_restantes"] = [0, 10, 10]
    extras["realizado_ate"] = [500.0, 1200.0, 500.0]  # 2º: meta já batida
    extras["probabilidade"] = [0.9, 1.0, np.nan]  # 3º: sem base
    r = prob.avaliar(pd.concat([d, extras], ignore_index=True), "so_passado")
    assert r[(r["tipo"] == "resumo") & (r["faixa_dias"] == 0)].iloc[0]["n"] == 100


def test_soma_dos_n_das_faixas_bate_com_o_n_do_resumo():
    rng = np.random.default_rng(21)
    d = _para_avaliar(n=200)
    d["probabilidade"] = rng.uniform(0.01, 0.99, 200)
    r = prob.avaliar(d, "leave_one_month_out")
    for _, g in r.groupby(["nivel", "faixa_dias"]):
        assert g.loc[g["tipo"] == "faixa", "n"].sum() == g.loc[g["tipo"] == "resumo", "n"].iloc[0]


# --- formas gravadas ------------------------------------------------------------------------------
def test_ajuste_gravado_tem_parametros_e_101_quantis_da_forma():
    cortes = _cortes(np.random.default_rng(15))
    _, modelos = prob.calcular_probabilidades(cortes, "so_passado")
    linhas = prob.linhas_do_ajuste(modelos)
    forma = linhas[linhas["nivel"] == "forma"]
    assert forma.groupby("meses_ate").size().eq(config.PROB_QUANTIS_FORMA).all()
    assert forma.groupby("meses_ate")["z"].apply(lambda s: s.is_monotonic_increasing).all()
    assert set(linhas["nivel"]) == {"loja", "conjunto", "forma"}
    assert linhas.loc[linhas["nivel"] == "loja", "sk_loja"].notna().all()


def test_formatar_para_gravar_deixa_a_rede_sem_loja():
    cortes = _cortes(np.random.default_rng(16))
    rede = cortes[cortes["sk_loja"] == 1].assign(
        nivel="rede", sk_loja=REDE, lojas_incluidas=2, lojas_total=2
    )
    com_p, _ = prob.calcular_probabilidades(
        pd.concat([cortes, rede], ignore_index=True), "so_passado"
    )
    com_p = com_p.assign(projecao=com_p["realizado_ate"] + com_p["prev_resto"])
    q = gravacao.formatar_probabilidades(com_p)
    assert q.loc[q["nivel"] == "rede", "sk_loja"].isna().all()
    assert q.loc[q["nivel"] == "loja", "sk_loja"].notna().all()
    assert list(q.columns) == gravacao.COLUNAS_PROBABILIDADE
    assert (q["probabilidade"].dropna().between(0, 1)).all()


# --- cortes diários a partir do painel ------------------------------------------------------------
def _painel_pequeno():
    datas = pd.date_range("2025-01-01", "2025-03-31", freq="D")
    valores = np.full((3, len(datas)), 100.0)
    valores[2, :] = 50.0
    valores[2, : (pd.Timestamp("2025-03-10") - datas[0]).days] = np.nan  # loja 2 abre em 10/03
    return Painel(datas, [(1, "A"), (1, "B"), (2, "A")], valores)


def _modelo_constante(painel, alvo):
    return np.full((len(painel.chaves), len(alvo)), 100.0)


METAS = {(1, pd.Timestamp("2025-03-01")): 100000.0, (2, pd.Timestamp("2025-03-01")): 5000.0}


def test_cortes_somam_realizado_previsto_e_real_do_resto():
    c = cortes_mod.montar_cortes(
        _painel_pequeno(), METAS, date(2025, 3, 20), date(2025, 3, 31), modelo=_modelo_constante,
    )  # fmt: skip
    loja1 = c[(c["nivel"] == "loja") & (c["sk_loja"] == 1)].set_index("corte")
    d20 = loja1.loc["2025-03-20"]
    assert d20["realizado_ate"] == 2 * 100 * 20  # 1 a 20/03, duas séries
    assert d20["prev_resto"] == 2 * 100 * 11 and d20["real_resto"] == 2 * 100 * 11
    assert d20["dias_restantes"] == 11 and d20["faixa"] == 2 and d20["base"]
    d31 = loja1.loc["2025-03-31"]
    assert d31["dias_restantes"] == 0 and d31["prev_resto"] == 0 and d31["real_resto"] == 0
    assert d31["faixa"] == -1


def test_loja_nova_fica_sem_base_e_fora_da_rede():
    c = cortes_mod.montar_cortes(
        _painel_pequeno(), METAS, date(2025, 3, 5), date(2025, 3, 31), modelo=_modelo_constante,
    )  # fmt: skip
    nova = c[(c["nivel"] == "loja") & (c["sk_loja"] == 2)]
    assert nova["corte"].min() == pd.Timestamp("2025-03-10")  # antes de abrir não há linha
    assert (
        not nova["base"].any() and (nova["motivo"] == "loja_nova").all()
    )  # nem em 31/03 (22 dias)
    assert nova["prev_resto"].isna().all()
    rede = c[c["nivel"] == "rede"].set_index("corte")
    assert (rede["sk_loja"] == REDE).all()
    assert rede.loc["2025-03-05", "lojas_total"] == 1  # a loja 2 ainda nem abriu
    assert (
        rede.loc["2025-03-20", "lojas_total"] == 2
        and rede.loc["2025-03-20", "lojas_incluidas"] == 1
    )
    assert rede.loc["2025-03-20", "meta"] == 100000.0  # a meta da loja nova não entra
    assert rede.loc["2025-03-20", "realizado_ate"] == 4000.0
    resumo = cortes_mod.resumo_sem_base(c)
    assert resumo["lojas_afetadas"] == [2] and resumo["cortes_por_loja"][2] == 22
    assert resumo["cortes_rede_com_loja_de_fora"] == 22


def test_loja_sem_meta_do_mes_fica_fora_da_rede():
    sem_meta = {k: v for k, v in METAS.items() if k[0] == 2}
    c = cortes_mod.montar_cortes(
        _painel_pequeno(), sem_meta, date(2025, 3, 20), date(2025, 3, 20), modelo=_modelo_constante,
    )  # fmt: skip
    rede = c[c["nivel"] == "rede"].iloc[0]
    assert not rede["base"] and rede["motivo"] == "loja_nova"


def test_mes_incompleto_no_painel_nao_tem_desfecho():
    datas = pd.date_range("2025-03-01", "2025-03-20", freq="D")
    painel = Painel(datas, [(1, "A")], np.full((1, len(datas)), 100.0))
    c = cortes_mod.montar_cortes(
        painel, METAS, datas[10].date(), datas[-1].date(), modelo=_modelo_constante
    )
    assert c["real_resto"].isna().all()


def test_subcomando_probabilidade_no_parser():
    from src.previsao.__main__ import _criar_parser

    args = _criar_parser().parse_args(
        ["probabilidade", "--gravar", "--lojas", "Ipê Brasília, Ipê Recife"]
    )
    assert args.comando == "probabilidade" and args.gravar
    assert [n.strip() for n in args.lojas.split(",")] == ["Ipê Brasília", "Ipê Recife"]
