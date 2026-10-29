"""Leitura -> staging com COPY e controle de cargas, num banco de teste."""

import dataclasses
import shutil

import pytest

from src.etl import controle
from src.etl.contrato import CONTRATO
from src.etl.leitura import ErroDeLeitura, carregar_para_staging
from src.etl.mapeamento import carregar_fontes
from tests.gerador.utilitarios import ler_csv, ler_vendas

pytestmark = pytest.mark.banco


@pytest.fixture
def erp(dados_pequenos, tmp_path):
    """A fonte ERP apontando para uma cópia dos CSVs gerados (os testes podem alterar a cópia)."""
    params, _ = dados_pequenos
    pasta = tmp_path / "raw"
    shutil.copytree(params.diretorio_saida, pasta)
    fonte = carregar_fontes()["lojas_ipe_erp"]
    return dataclasses.replace(fonte, pasta=pasta)


def _contar(con, tabela):
    return con.execute(f"SELECT count(*) FROM stg.{tabela}").fetchone()[0]


def test_toda_linha_dos_csvs_chega_ao_staging_como_texto_cru(banco_com_ddl, erp):
    resultado = carregar_para_staging(banco_com_ddl, erp)
    for entidade, mapa in erp.entidades.items():
        esperado = sum(len(ler_csv(a)) for a in sorted(erp.pasta.glob(mapa.arquivo)))
        assert _contar(banco_com_ddl, entidade) == esperado, entidade
    assert resultado.linhas_lidas == sum(_contar(banco_com_ddl, e) for e in CONTRATO)
    assert {a.situacao for a in resultado.arquivos} == {"carregado"}


def test_origem_da_linha_e_valores_crus_preservados(banco_com_ddl, erp):
    carregar_para_staging(banco_com_ddl, erp)
    vendas = ler_vendas(erp.pasta)
    amostra = vendas.sample(50, random_state=1)
    for _, linha in amostra.iterrows():
        gravada = banco_com_ddl.execute(
            "SELECT id_venda_erp, data_venda, receita_liquida, cod_cliente"
            " FROM stg.vendas WHERE arquivo_origem = %s AND linha_origem = %s",
            (linha["arquivo"], int(linha["linha"])),
        ).fetchone()
        assert gravada[0] == linha["id_venda_erp"]
        assert gravada[1] == linha["data_venda"]  # sem corrigir formato
        assert gravada[2] == linha["receita_liquida"]
        assert gravada[3] == (linha["cod_cliente"] or None)  # vazio vira NULL


def test_formatos_sujos_continuam_no_staging(banco_com_ddl, erp):
    carregar_para_staging(banco_com_ddl, erp)
    iso = banco_com_ddl.execute("SELECT count(*) FROM stg.vendas WHERE data_venda ~ '^\\d{4}-'")
    assert iso.fetchone()[0] > 0
    br = banco_com_ddl.execute("SELECT count(*) FROM stg.vendas WHERE receita_liquida LIKE '%,%'")
    assert br.fetchone()[0] > 0


def test_carga_e_arquivos_ficam_registrados(banco_com_ddl, erp):
    resultado = carregar_para_staging(banco_com_ddl, erp)
    carga = banco_com_ddl.execute(
        "SELECT fonte, modo, status, fim FROM etl.cargas WHERE id_carga = %s", (resultado.id_carga,)
    ).fetchone()
    assert carga[:3] == ("lojas_ipe_erp", "incremental", "em_andamento")
    lidas = controle.linhas_lidas_por_arquivo(banco_com_ddl, resultado.id_carga)
    assert lidas["vendas_2024-01.csv"] == len(ler_csv(erp.pasta / "vendas_2024-01.csv"))
    assert len(lidas) == len(resultado.arquivos)
    controle.finalizar_carga(banco_com_ddl, resultado.id_carga, "concluida")
    fim = banco_com_ddl.execute(
        "SELECT status, fim IS NOT NULL FROM etl.cargas WHERE id_carga = %s", (resultado.id_carga,)
    ).fetchone()
    assert fim == ("concluida", True)


def test_incremental_pula_arquivo_inalterado_e_recarrega_o_que_mudou(banco_com_ddl, erp):
    primeira = carregar_para_staging(banco_com_ddl, erp)
    controle.confirmar_arquivos(banco_com_ddl, primeira.id_carga)
    total = _contar(banco_com_ddl, "vendas")

    segunda = carregar_para_staging(banco_com_ddl, erp)
    assert {a.situacao for a in segunda.arquivos} == {"inalterado"}
    assert segunda.linhas_lidas == 0
    assert _contar(banco_com_ddl, "vendas") == total

    arquivo = erp.pasta / "vendas_2024-01.csv"
    linhas = arquivo.read_text(encoding="utf-8").splitlines()
    arquivo.write_text("\n".join(linhas[:-1]) + "\n", encoding="utf-8")  # uma venda a menos
    terceira = carregar_para_staging(banco_com_ddl, erp)
    recarregados = [a for a in terceira.arquivos if a.situacao == "carregado"]
    assert [a.arquivo for a in recarregados] == ["vendas_2024-01.csv"]
    assert _contar(banco_com_ddl, "vendas") == total - 1


def test_completo_relê_tudo_sem_duplicar(banco_com_ddl, erp):
    primeira = carregar_para_staging(banco_com_ddl, erp)
    controle.confirmar_arquivos(banco_com_ddl, primeira.id_carga)
    contagens = {e: _contar(banco_com_ddl, e) for e in CONTRATO}
    completa = carregar_para_staging(banco_com_ddl, erp, modo="completo")
    assert {a.situacao for a in completa.arquivos} == {"carregado"}
    assert {e: _contar(banco_com_ddl, e) for e in CONTRATO} == contagens


def test_carga_por_entidade(banco_com_ddl, erp):
    resultado = carregar_para_staging(banco_com_ddl, erp, entidades=["lojas", "produtos"])
    assert {a.entidade for a in resultado.arquivos} == {"lojas", "produtos"}
    assert _contar(banco_com_ddl, "lojas") == 15
    assert _contar(banco_com_ddl, "vendas") == 0


def test_arquivo_com_cabecalho_errado_marca_a_carga_com_erro_e_nao_deixa_lixo(banco_com_ddl, erp):
    (erp.pasta / "lojas.csv").write_text("a;b\n1;2\n", encoding="utf-8")
    with pytest.raises(ErroDeLeitura):
        carregar_para_staging(banco_com_ddl, erp, entidades=["produtos", "lojas"])
    assert _contar(banco_com_ddl, "produtos") == 0  # tudo ou nada
    status = banco_com_ddl.execute("SELECT status, mensagem FROM etl.cargas").fetchone()
    assert status[0] == "erro"
    assert "ausentes no cabeçalho" in status[1]


def test_entidade_nao_mapeada(banco_com_ddl, erp):
    with pytest.raises(ErroDeLeitura, match="não mapeadas"):
        carregar_para_staging(banco_com_ddl, erp, entidades=["inexistente"])
