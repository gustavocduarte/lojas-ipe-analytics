"""A vigia de memória durante uma carga de verdade (memória simulada): cancela a consulta SQL em
andamento, desfaz a transação, marca a carga como erro e o CLI sai com o código 3."""

import dataclasses
import shutil

import pytest

from src import config
from src.etl import controle, pipeline, relatorio
from src.etl.__main__ import principal
from src.etl.mapeamento import carregar_fontes
from src.memoria import MemoriaInsuficiente, MemoriaRompida

pytestmark = pytest.mark.banco

INTERVALO_S = 0.1
TOLERANCIA_S = 0.4


@pytest.fixture
def erp(dados_pequenos, tmp_path):
    params, _ = dados_pequenos
    pasta = tmp_path / "raw"
    shutil.copytree(params.diretorio_saida, pasta)
    return dataclasses.replace(carregar_fontes()["lojas_ipe_erp"], pasta=pasta)


class MemoriaQueCai:
    """Memória boa até o staging terminar; depois abaixo do piso (com a consulta SQL rodando)."""

    def __init__(self, monkeypatch):
        self.staging_pronto = False
        original = pipeline.carregar_para_staging

        def com_marca(*args, **kwargs):
            resultado = original(*args, **kwargs)
            self.staging_pronto = True
            return resultado

        monkeypatch.setattr(pipeline, "carregar_para_staging", com_marca)

    def __call__(self) -> float:
        return 0.1 if self.staging_pronto else 1.0


def _linhas_do_dw(con):
    return relatorio.contar_linhas_do_dw(con)


def test_memoria_rompida_na_etapa_sql_aborta_e_deixa_o_dw_como_estava(
    banco_com_ddl, erp, tmp_path, monkeypatch
):
    memoria = MemoriaQueCai(monkeypatch)
    with pytest.raises(MemoriaRompida, match="abaixo de 0.40 GB"):
        pipeline.carregar(
            banco_com_ddl,
            erp,
            leitor_memoria=memoria,
            vigia_intervalo_s=INTERVALO_S,
            vigia_tolerancia_s=TOLERANCIA_S,
            pasta_relatorios=tmp_path / "relatorios",
        )
    con = banco_com_ddl
    assert all(n == 0 for n in _linhas_do_dw(con).values())  # nem dim_hora/dim_tempo sobraram
    status, mensagem = con.execute("SELECT status, mensagem FROM etl.cargas").fetchone()
    assert status == "erro"
    assert "memória livre abaixo de 0.40 GB" in mensagem and "carga abortada" in mensagem
    assert con.execute("SELECT count(*) FROM etl.arquivos_processados").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM etl.carga_tabelas").fetchone()[0] == 0
    # a trava da carga foi liberada e a conexão continua usável: com memória normal tudo carrega
    resultado = pipeline.carregar(
        con, erp, verificar_memoria=False, pasta_relatorios=tmp_path / "relatorios"
    )
    assert resultado.aprovada
    assert _linhas_do_dw(con)["fato_vendas"] > 0
    assert con.execute("SELECT count(*) FROM stg.vendas WHERE id_carga = 2").fetchone()[0] > 0


def test_cli_sai_com_codigo_3_quando_a_memoria_rompe(banco_com_ddl, erp, tmp_path, monkeypatch):
    memoria = MemoriaQueCai(monkeypatch)
    mapeamentos = tmp_path / "fontes"
    mapeamentos.mkdir()
    texto = (config.DIR_MAPEAMENTOS / "lojas_ipe_erp.yaml").read_text(encoding="utf-8")
    (mapeamentos / "lojas_ipe_erp.yaml").write_text(
        texto.replace("pasta: data/raw", f"pasta: {erp.pasta.as_posix()}"), encoding="utf-8"
    )
    codigo = principal(
        ["carregar", "--mapeamentos", str(mapeamentos), "--relatorios", str(tmp_path / "rel")],
        conexao=banco_com_ddl,
        leitor_memoria=memoria,
        vigia_intervalo_s=INTERVALO_S,
        vigia_tolerancia_s=TOLERANCIA_S,
    )
    assert codigo == config.CODIGO_SAIDA_ERRO_DE_EXECUCAO == 3
    assert all(n == 0 for n in _linhas_do_dw(banco_com_ddl).values())
    assert banco_com_ddl.execute("SELECT status FROM etl.cargas").fetchone()[0] == "erro"


def test_memoria_baixa_na_etapa_de_staging_tambem_aborta(banco_com_ddl, erp, tmp_path):
    """Queda desde o primeiro momento depois da checagem inicial: vale para o staging também."""
    leituras = iter([1.0])  # a checagem inicial vê memória boa; depois fica sempre baixa

    def leitor():
        return next(leituras, 0.1)

    with pytest.raises(MemoriaRompida):
        pipeline.carregar(
            banco_com_ddl,
            erp,
            leitor_memoria=leitor,
            vigia_intervalo_s=0.05,
            vigia_tolerancia_s=0.15,
            pasta_relatorios=tmp_path,
        )
    assert all(n == 0 for n in _linhas_do_dw(banco_com_ddl).values())
    status, mensagem = banco_com_ddl.execute("SELECT status, mensagem FROM etl.cargas").fetchone()
    assert status == "erro" and "carga abortada" in mensagem


def test_queda_curta_nao_aborta_e_o_minimo_vai_para_o_relatorio(banco_com_ddl, erp, tmp_path):
    chamadas = iter(range(1_000_000))

    def leitor():
        n = next(chamadas)
        return 0.1 if 3 <= n <= 5 else 1.0  # três leituras baixas (~0,3 s) e volta ao normal

    resultado = pipeline.carregar(
        banco_com_ddl,
        erp,
        leitor_memoria=leitor,
        vigia_intervalo_s=0.1,
        vigia_tolerancia_s=5.0,
        pasta_relatorios=tmp_path,
    )
    assert resultado.aprovada
    desempenho = resultado.relatorio["desempenho"]
    assert desempenho["memoria_livre_minima_durante_a_carga_gb"] == 0.1


def test_memoria_baixa_antes_de_comecar_nem_abre_a_carga(banco_com_ddl, erp, tmp_path):
    with pytest.raises(MemoriaInsuficiente) as erro:
        pipeline.carregar(banco_com_ddl, erp, leitor_memoria=lambda: 0.1, pasta_relatorios=tmp_path)
    assert not isinstance(erro.value, MemoriaRompida)
    assert banco_com_ddl.execute("SELECT count(*) FROM etl.cargas").fetchone()[0] == 0


def test_carga_normal_nao_dispara_a_vigia(banco_com_ddl, erp, tmp_path):
    resultado = pipeline.carregar(
        banco_com_ddl, erp, leitor_memoria=lambda: 2.0, pasta_relatorios=tmp_path
    )
    assert resultado.aprovada
    assert controle.linhas_lidas_por_arquivo(banco_com_ddl, resultado.id_carga)
