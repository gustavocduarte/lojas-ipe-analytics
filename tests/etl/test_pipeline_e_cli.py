"""Pipeline completo, idempotência, carga incremental por fonte e linha de comando."""

import json
import shutil

import psycopg
import pytest

from src import config
from src.etl import controle, pipeline, relatorio, validacao
from src.etl.__main__ import principal
from src.etl.mapeamento import carregar_fonte
from src.memoria import MemoriaInsuficiente
from tests.conftest import parametros_banco_de_teste
from tests.gerador.utilitarios import ler_vendas

pytestmark = pytest.mark.banco

TABELAS_E_ORDEM = {
    "dim_tempo": "sk_tempo",
    "dim_hora": "sk_hora",
    "dim_loja": "sk_loja",
    "dim_loja_horario": "sk_loja, dia_semana",
    "dim_produto": "sk_produto",
    "dim_vendedor": "sk_vendedor",
    "dim_cliente": "sk_cliente",
    "dim_forma_pagamento": "sk_forma_pagamento",
    "dim_campanha": "sk_campanha",
    "dim_centro_custo": "sk_centro_custo",
    "fato_vendas": "sk_venda",
    "fato_meta_vendas": "sk_meta",
    "fato_meta_vendedor": "sk_meta_vendedor",
    "fato_despesas": "sk_despesa",
    "fato_orcamento_despesas": "sk_orcamento",
}


@pytest.fixture
def ambiente(dados_pequenos, tmp_path):
    """Pasta com cópia dos CSVs e uma pasta de mapeamentos apontando para ela."""
    params, _ = dados_pequenos
    raw = tmp_path / "raw"
    shutil.copytree(params.diretorio_saida, raw)
    mapeamentos = tmp_path / "fontes"
    mapeamentos.mkdir()
    original = (config.DIR_MAPEAMENTOS / "lojas_ipe_erp.yaml").read_text(encoding="utf-8")
    texto = original.replace("pasta: data/raw", f"pasta: {raw.as_posix()}")
    (mapeamentos / "lojas_ipe_erp.yaml").write_text(texto, encoding="utf-8")
    return raw, mapeamentos, tmp_path / "processed"


def _rodar(con, ambiente, *extra):
    _, mapeamentos, relatorios = ambiente
    return principal(
        ["carregar", "--mapeamentos", str(mapeamentos), "--relatorios", str(relatorios), *extra],
        conexao=con,
        verificar_memoria=False,
    )


def _impressao_digital(con):
    """Hash do conteúdo de cada tabela do dw (linhas inteiras, em ordem fixa)."""
    return {
        tabela: con.execute(
            f"SELECT md5(string_agg(t::TEXT, '|' ORDER BY {ordem})) FROM dw.{tabela} t"
        ).fetchone()[0]
        for tabela, ordem in TABELAS_E_ORDEM.items()
    }


class TestIdempotencia:
    def test_rodar_duas_vezes_da_exatamente_o_mesmo_dw(self, banco_com_ddl, ambiente):
        assert _rodar(banco_com_ddl, ambiente) == 0
        antes = _impressao_digital(banco_com_ddl)
        contagens = relatorio.contar_linhas_do_dw(banco_com_ddl)

        assert _rodar(banco_com_ddl, ambiente) == 0  # incremental: nada novo
        assert _impressao_digital(banco_com_ddl) == antes
        assert _rodar(banco_com_ddl, ambiente, "--completo") == 0  # relê tudo e reaplica
        assert _impressao_digital(banco_com_ddl) == antes
        assert relatorio.contar_linhas_do_dw(banco_com_ddl) == contagens

    def test_so_as_duplicatas_do_erp_aparecem_repetidas(self, banco_com_ddl, ambiente):
        _rodar(banco_com_ddl, ambiente)
        _rodar(banco_com_ddl, ambiente, "--completo")
        raw, _, _ = ambiente
        no_dw = banco_com_ddl.execute("SELECT count(*) FROM dw.fato_vendas").fetchone()[0]
        assert no_dw == len(ler_vendas(raw))
        repetidos = banco_com_ddl.execute(
            "SELECT count(*) FROM (SELECT 1 FROM dw.fato_vendas GROUP BY numero_cupom, numero_item"
            " HAVING count(*) > 1) x"
        ).fetchone()[0]
        ids = ler_vendas(raw)
        esperados = int(ids.duplicated(["numero_cupom", "numero_item"], keep="first").sum())
        assert repetidos == esperados > 0

    def test_segunda_carga_incremental_nao_le_nada(self, banco_com_ddl, ambiente):
        _rodar(banco_com_ddl, ambiente)
        _rodar(banco_com_ddl, ambiente)
        situacoes = {
            s
            for (s,) in banco_com_ddl.execute(
                "SELECT situacao FROM etl.carga_arquivos WHERE id_carga = 2"
            )
        }
        assert situacoes == {"inalterado"}
        doc = banco_com_ddl.execute(
            "SELECT relatorio FROM etl.relatorios_qualidade WHERE id_carga = 2"
        ).fetchone()[0]
        assert doc["resumo"]["linhas_lidas"] == 0
        assert doc["status"] == "concluida"


class TestCargaIncremental:
    def test_arquivo_novo_entra_sem_mexer_no_resto(self, banco_com_ddl, ambiente):
        raw, _, _ = ambiente
        mes_novo = raw / "vendas_2025-12.csv"
        guardado = mes_novo.read_bytes()
        mes_novo.unlink()  # começa sem o último mês
        _rodar(banco_com_ddl, ambiente)
        antes = banco_com_ddl.execute("SELECT count(*) FROM dw.fato_vendas").fetchone()[0]
        outras = banco_com_ddl.execute(
            "SELECT md5(string_agg(t::TEXT, '|' ORDER BY sk_venda)) FROM dw.fato_vendas t"
        ).fetchone()[0]

        mes_novo.write_bytes(guardado)  # chega o arquivo do mês seguinte
        assert _rodar(banco_com_ddl, ambiente) == 0
        carregados = banco_com_ddl.execute(
            "SELECT arquivo FROM etl.carga_arquivos WHERE id_carga = 2 AND situacao = 'carregado'"
        ).fetchall()
        assert carregados == [("vendas_2025-12.csv",)]
        depois = banco_com_ddl.execute("SELECT count(*) FROM dw.fato_vendas").fetchone()[0]
        assert depois > antes
        anteriores = banco_com_ddl.execute(
            "SELECT md5(string_agg(t::TEXT, '|' ORDER BY sk_venda)) FROM dw.fato_vendas t"
            " WHERE arquivo_origem <> 'vendas_2025-12.csv'"
        ).fetchone()[0]
        assert anteriores == outras

    def test_carga_de_uma_so_entidade_pela_linha_de_comando(self, banco_com_ddl, ambiente):
        assert (
            _rodar(banco_com_ddl, ambiente, "--fonte", "lojas_ipe_erp", "--entidade", "lojas") == 0
        )
        assert banco_com_ddl.execute("SELECT count(*) FROM dw.dim_loja").fetchone()[0] == 15
        assert banco_com_ddl.execute("SELECT count(*) FROM dw.fato_vendas").fetchone()[0] == 0

    def test_cada_fonte_tem_sua_carga_e_arquivos_proprios(self, banco_com_ddl, ambiente):
        _rodar(banco_com_ddl, ambiente)
        fontes = {
            f
            for (f,) in banco_com_ddl.execute("SELECT DISTINCT fonte FROM etl.arquivos_processados")
        }
        assert fontes == {"lojas_ipe_erp"}


class TestReprovacao:
    def test_validacao_estrutural_reprovada_deixa_o_dw_intacto(
        self, banco_com_ddl, ambiente, monkeypatch
    ):
        raw, mapeamentos, relatorios = ambiente
        (raw / "vendas_2025-12.csv").rename(raw / "guardado.tmp")
        assert _rodar(banco_com_ddl, ambiente) == 0
        antes = _impressao_digital(banco_com_ddl)
        rejeitados_antes = banco_com_ddl.execute("SELECT count(*) FROM stg.rejeitados").fetchone()[
            0
        ]
        (raw / "guardado.tmp").rename(raw / "vendas_2025-12.csv")

        original = validacao.validar_estrutura

        def reprovar(conexao, id_carga):
            return [
                *original(conexao, id_carga),
                validacao.ResultadoValidacao("falha_simulada", False, 1, "teste"),
            ]

        monkeypatch.setattr(validacao, "validar_estrutura", reprovar)
        assert _rodar(banco_com_ddl, ambiente) == 1

        assert _impressao_digital(banco_com_ddl) == antes  # nada mudou no dw
        assert banco_com_ddl.execute("SELECT count(*) FROM stg.rejeitados").fetchone()[0] == (
            rejeitados_antes
        )
        status, mensagem = banco_com_ddl.execute(
            "SELECT status, mensagem FROM etl.cargas WHERE id_carga = 2"
        ).fetchone()
        assert status == "reprovada"
        assert "falha_simulada" in mensagem
        doc = json.loads((relatorios / "relatorio_carga_0002.json").read_text(encoding="utf-8"))
        assert doc["status"] == "reprovada"
        assert [v["validacao"] for v in doc["validacoes_estruturais"] if not v["ok"]] == [
            "falha_simulada"
        ]
        assert doc["sinais_de_negocio"] == []
        # o arquivo não foi dado como processado: a próxima carga (sem o defeito) o lê
        monkeypatch.setattr(validacao, "validar_estrutura", original)
        assert _rodar(banco_com_ddl, ambiente) == 0
        assert banco_com_ddl.execute("SELECT count(*) FROM dw.fato_vendas").fetchone()[0] > 0
        lidas = controle.linhas_lidas_por_arquivo(banco_com_ddl, 3)
        assert lidas["vendas_2025-12.csv"] > 0


class TestLinhaDeComando:
    def test_fonte_inexistente_e_erro_de_uso(self, banco_com_ddl, ambiente):
        assert _rodar(banco_com_ddl, ambiente, "--fonte", "nao_existe") == 2

    def test_entidade_sem_fonte_unica_e_erro_de_uso(self, banco_com_ddl, ambiente):
        assert _rodar(banco_com_ddl, ambiente, "--entidade", "lojas") == 2

    def test_entidade_inexistente_e_erro_de_uso(self, banco_com_ddl, ambiente):
        assert _rodar(banco_com_ddl, ambiente, "--fonte", "lojas_ipe_erp", "--entidade", "x") == 2

    def test_argumento_desconhecido_e_erro_de_uso(self):
        assert principal(["carregar", "--nao-existe"]) == 2
        assert principal([]) == 2

    def test_mapeamento_invalido_e_erro_de_uso(self, banco_com_ddl, ambiente):
        _, mapeamentos, _ = ambiente
        (mapeamentos / "quebrada.yaml").write_text("fonte: x\nentidades: {}\n", encoding="utf-8")
        assert _rodar(banco_com_ddl, ambiente) == 2

    def test_arquivo_com_cabecalho_errado_e_erro_de_execucao(self, banco_com_ddl, ambiente):
        raw, _, _ = ambiente
        (raw / "lojas.csv").write_text("a;b\n1;2\n", encoding="utf-8")
        assert _rodar(banco_com_ddl, ambiente) == 3
        status = banco_com_ddl.execute("SELECT status FROM etl.cargas").fetchone()[0]
        assert status == "erro"

    def test_carga_em_andamento_trava_a_segunda(self, banco_com_ddl, ambiente):
        nome = banco_com_ddl.info.dbname
        with psycopg.connect(dbname=nome, **parametros_banco_de_teste()) as outra:
            outra.execute("SELECT pg_advisory_lock(%s)", (config.CHAVE_TRAVA_ETL,))
            assert _rodar(banco_com_ddl, ambiente) == 3

    def test_listar_fontes(self, capsys):
        assert principal(["fontes"]) == 0
        assert "lojas_ipe_erp" in capsys.readouterr().out

    def test_memoria_insuficiente_e_erro_de_execucao(self, banco_com_ddl, ambiente, monkeypatch):
        _, mapeamentos, relatorios = ambiente

        def sem_memoria():
            raise MemoriaInsuficiente("memória livre abaixo do mínimo")

        monkeypatch.setattr(pipeline, "verificar_memoria_livre", sem_memoria)
        codigo = principal(
            ["carregar", "--mapeamentos", str(mapeamentos), "--relatorios", str(relatorios)],
            conexao=banco_com_ddl,
        )
        assert codigo == 3
        assert banco_com_ddl.execute("SELECT count(*) FROM etl.cargas").fetchone()[0] == 0


def test_fonte_de_carga_nao_padrao_fica_de_fora(tmp_path):
    yaml = (config.DIR_MAPEAMENTOS / "lojas_ipe_erp.yaml").read_text(encoding="utf-8")
    caminho = tmp_path / "f.yaml"
    caminho.write_text(
        yaml.replace("fonte: lojas_ipe_erp", "fonte: x\ncarga_padrao: false"), encoding="utf-8"
    )
    assert carregar_fonte(caminho).carga_padrao is False
