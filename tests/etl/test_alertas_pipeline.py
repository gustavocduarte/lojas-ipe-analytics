"""Alertas no pipeline e na linha de comando: gerados após a carga, no relatório, reavaliáveis."""

import dataclasses
import json
import shutil

import pytest

from src import config
from src.etl import alertas, pipeline, relatorio
from src.etl.__main__ import principal
from src.etl.mapeamento import carregar_fontes

pytestmark = pytest.mark.banco


@pytest.fixture
def ambiente(dados_pequenos, tmp_path):
    """CSVs copiados + pasta de mapeamentos apontando para eles."""
    params, _ = dados_pequenos
    raw = tmp_path / "raw"
    shutil.copytree(params.diretorio_saida, raw)
    mapeamentos = tmp_path / "fontes"
    mapeamentos.mkdir()
    original = (config.DIR_MAPEAMENTOS / "lojas_ipe_erp.yaml").read_text(encoding="utf-8")
    (mapeamentos / "lojas_ipe_erp.yaml").write_text(
        original.replace("pasta: data/raw", f"pasta: {raw.as_posix()}"), encoding="utf-8"
    )
    return raw, mapeamentos, tmp_path / "relatorios"


def _cli(con, ambiente, *argumentos, **extra):
    _, mapeamentos, relatorios = ambiente
    return principal(
        [
            "carregar",
            "--mapeamentos",
            str(mapeamentos),
            "--relatorios",
            str(relatorios),
            *argumentos,
        ],
        conexao=con,
        verificar_memoria=extra.pop("verificar_memoria", False),
        **extra,
    )


def _contagem(con):
    return con.execute("SELECT count(*) FROM dw.alertas").fetchone()[0]


class TestAlertasDepoisDaCarga:
    def test_carga_com_dados_novos_gera_alertas_e_os_poe_no_relatorio(
        self, banco_com_ddl, ambiente
    ):
        assert _cli(banco_com_ddl, ambiente) == 0
        assert _contagem(banco_com_ddl) > 0
        doc = banco_com_ddl.execute(
            "SELECT relatorio FROM etl.relatorios_qualidade WHERE id_carga = 1"
        ).fetchone()[0]
        resumo = doc["alertas"]
        assert resumo["vigentes_independentes"] > 0
        assert {t["tipo_alerta"] for t in resumo["por_tipo"]} >= {
            "desconto_acima_limite",
            "margem_negativa",
            "despesa_acima_orcado",
        }
        assert all(t["novos"] == t["detectados"] for t in resumo["por_tipo"])  # banco novo
        assert set(resumo["desempenho"]) >= {"duracao_s", "pico_memoria_processo_gb"}
        assert sum(resumo["por_severidade"].values()) == resumo["vigentes_independentes"]

    def test_carga_sem_dado_novo_nao_regera_alertas(self, banco_com_ddl, ambiente):
        _cli(banco_com_ddl, ambiente)
        antes = _contagem(banco_com_ddl)
        _cli(banco_com_ddl, ambiente)
        assert _contagem(banco_com_ddl) == antes
        assert (
            banco_com_ddl.execute(
                "SELECT count(*) FROM etl.carga_alertas WHERE id_carga = 2"
            ).fetchone()[0]
            == 0
        )

    def test_recarga_completa_nao_duplica_e_preserva_o_status(self, banco_com_ddl, ambiente):
        _cli(banco_com_ddl, ambiente)
        con = banco_com_ddl
        sk, chave = con.execute(
            "SELECT sk_alerta, chave_alerta FROM dw.alertas WHERE tipo_alerta = 'margem_negativa'"
            " ORDER BY chave_alerta LIMIT 1"
        ).fetchone()
        con.execute("CALL dw.tratar_alerta(%s, 'falso_positivo', 'ana', 'conferido')", (sk,))
        con.commit()
        antes = _contagem(con)
        assert _cli(con, ambiente, "--completo") == 0
        assert _contagem(con) == antes
        status = con.execute(
            "SELECT status, vigente FROM dw.alertas WHERE chave_alerta = %s", (chave,)
        )
        assert status.fetchone() == ("falso_positivo", True)
        assert con.execute(
            "SELECT sum(novos), sum(atualizados) FROM etl.carga_alertas WHERE id_carga = 2"
        ).fetchone() == (0, 0)

    def test_alertas_nao_entram_na_impressao_digital_das_tabelas_da_fase_2(
        self, banco_com_ddl, ambiente
    ):
        _cli(banco_com_ddl, ambiente)
        assert "alertas" not in relatorio.TABELAS_DW


class TestComandoAlertas:
    def test_reavalia_depois_de_mudar_um_parametro(self, banco_com_ddl, ambiente, capsys):
        _cli(banco_com_ddl, ambiente)
        vigentes = banco_com_ddl.execute(
            "SELECT count(*) FROM dw.alertas"
            " WHERE tipo_alerta = 'desconto_acima_limite' AND vigente"
        ).fetchone()[0]
        assert vigentes > 0
        banco_com_ddl.execute(
            "UPDATE etl.parametros_negocio SET valor = 0.99 WHERE chave = 'desconto_maximo'"
        )
        banco_com_ddl.commit()
        assert principal(["alertas"], conexao=banco_com_ddl, verificar_memoria=False) == 0
        saida = capsys.readouterr().out
        assert "desconto_acima_limite" in saida and "alertas independentes" in saida
        depois = banco_com_ddl.execute(
            "SELECT count(*) FROM dw.alertas"
            " WHERE tipo_alerta = 'desconto_acima_limite' AND vigente"
        ).fetchone()[0]
        assert depois == 0
        carga = banco_com_ddl.execute(
            "SELECT fonte, modo, status FROM etl.cargas ORDER BY id_carga DESC LIMIT 1"
        ).fetchone()
        assert carga == ("alertas", "completo", "concluida")

    def test_erro_na_geracao_apos_a_carga_vai_para_o_relatorio_e_sai_com_4(
        self, banco_com_ddl, ambiente, monkeypatch
    ):
        def quebrar(*args, **kwargs):
            raise RuntimeError("regra quebrada")

        monkeypatch.setattr(alertas, "gerar", quebrar)
        assert _cli(banco_com_ddl, ambiente) == 4
        _, _, relatorios = ambiente
        doc = json.loads((relatorios / "relatorio_carga_0001.json").read_text(encoding="utf-8"))
        assert doc["alertas"] == {"erro": "regra quebrada"}
        assert doc["status"] == "concluida"  # o dw foi carregado; só os alertas falharam
        assert banco_com_ddl.execute("SELECT count(*) FROM dw.fato_vendas").fetchone()[0] > 0

    def test_memoria_rompida_durante_os_alertas_desfaz_so_os_alertas(
        self, banco_com_ddl, ambiente, monkeypatch
    ):
        estado = {"alertas_comecaram": False}
        original = alertas.gerar

        def marcando(*args, **kwargs):
            estado["alertas_comecaram"] = True
            return original(*args, **kwargs)

        monkeypatch.setattr(alertas, "gerar", marcando)
        codigo = _cli(
            banco_com_ddl,
            ambiente,
            verificar_memoria=True,
            leitor_memoria=lambda: 0.1 if estado["alertas_comecaram"] else 1.0,
            vigia_intervalo_s=0.01,
            vigia_tolerancia_s=0.03,
        )
        assert codigo == 4  # dw carregado; só os alertas foram desfeitos
        assert _contagem(banco_com_ddl) == 0  # nenhum alerta ficou pela metade
        assert banco_com_ddl.execute("SELECT count(*) FROM dw.fato_vendas").fetchone()[0] > 0
        _, _, relatorios = ambiente
        doc = json.loads((relatorios / "relatorio_carga_0001.json").read_text(encoding="utf-8"))
        assert "memória livre abaixo" in doc["alertas"]["erro"]

    def test_comando_avulso_respeita_a_trava_de_carga(self, banco_com_ddl):
        import psycopg

        from tests.conftest import parametros_banco_de_teste

        with psycopg.connect(
            dbname=banco_com_ddl.info.dbname, **parametros_banco_de_teste()
        ) as outra:
            outra.execute("SELECT pg_advisory_lock(%s)", (config.CHAVE_TRAVA_ETL,))
            assert principal(["alertas"], conexao=banco_com_ddl, verificar_memoria=False) == 3

    def test_pipeline_pode_dispensar_os_alertas(self, banco_com_ddl, ambiente):
        raw, _, relatorios = ambiente
        fonte = dataclasses.replace(carregar_fontes()["lojas_ipe_erp"], pasta=raw)
        resultado = pipeline.carregar(
            banco_com_ddl, fonte, verificar_memoria=False, pasta_relatorios=relatorios,
            gerar_alertas=False,
        )  # fmt: skip
        assert resultado.aprovada and resultado.alertas == {} and _contagem(banco_com_ddl) == 0
