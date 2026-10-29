"""Validações estruturais, sinais de negócio e relatório de qualidade da carga."""

import dataclasses
import json
import shutil

import pytest

from src.etl import relatorio, validacao
from src.etl.leitura import carregar_para_staging
from src.etl.mapeamento import carregar_fontes

pytestmark = pytest.mark.banco

SINAIS_ESPERADOS = {
    "venda_de_vendedor_inativo",
    "desconto_acima_do_limite",
    "margem_negativa",
    "venda_fora_do_horario",
    "cupom_duplicado",
    "vendedor_com_cancelamento_alto",
    "despesa_documento_repetido",
    "despesa_em_fim_de_semana_ou_feriado",
    "despesa_de_valor_atipico",
    "despesa_acima_do_orcado",
}


@pytest.fixture
def erp(dados_pequenos, tmp_path):
    params, _ = dados_pequenos
    pasta = tmp_path / "raw"
    shutil.copytree(params.diretorio_saida, pasta)
    return dataclasses.replace(carregar_fontes()["lojas_ipe_erp"], pasta=pasta)


@pytest.fixture
def carga_aberta(banco_com_ddl, erp):
    """Staging confirmado e dw carregado, mas com a transação do dw ainda ABERTA (como no
    pipeline: as validações rodam antes do commit e as tabelas _lim_* ainda existem)."""
    id_carga = carregar_para_staging(banco_com_ddl, erp).id_carga
    banco_com_ddl.execute("CALL etl.carregar_dw(%s)", (id_carga,))
    return banco_com_ddl, id_carga


def _por_nome(resultados):
    return {r.validacao: r for r in resultados}


class TestValidacoesEstruturais:
    def test_carga_do_erp_passa_em_todas(self, carga_aberta):
        con, id_carga = carga_aberta
        resultados = validacao.validar_estrutura(con, id_carga)
        assert validacao.reprovadas(resultados) == []
        nomes = set(_por_nome(resultados))
        assert {
            "chaves_fato_vendas",
            "chaves_fato_despesas",
            "chaves_metas_e_orcamento",
            "chaves_dimensoes",
            "soma_itens_igual_total_cupom",
            "consistencia_data_hora_vendas",
            "valores_nao_negativos",
            "contagem_vendas",
            "contagem_despesas",
            "contagem_lojas",
            "contagem_feriados",
        } <= nomes

    def test_total_do_cupom_diferente_da_soma_dos_itens_reprova(self, carga_aberta):
        con, id_carga = carga_aberta
        con.execute(
            "UPDATE _lim_vendas SET total_cupom = total_cupom + 1"
            " WHERE numero_cupom = (SELECT min(numero_cupom) FROM _lim_vendas)"
        )
        falhas = validacao.reprovadas(validacao.validar_estrutura(con, id_carga))
        assert [f.validacao for f in falhas] == ["soma_itens_igual_total_cupom"]
        assert falhas[0].quantidade == 1

    def test_cupom_duplicado_nao_quebra_a_soma(self, carga_aberta):
        con, id_carga = carga_aberta
        duplicados = con.execute(
            "SELECT count(*) FROM (SELECT 1 FROM dw.fato_vendas GROUP BY numero_cupom, numero_item"
            " HAVING count(*) > 1) x"
        ).fetchone()[0]
        assert duplicados > 0  # o conjunto de teste tem cupons repetidos (anomalia do gerador)
        assert not validacao.reprovadas(validacao.validar_estrutura(con, id_carga))

    def test_contagem_stg_diferente_de_dw_mais_rejeitados_reprova(self, carga_aberta):
        con, id_carga = carga_aberta
        con.execute(
            "DELETE FROM dw.fato_despesas WHERE sk_despesa = (SELECT min(sk_despesa)"
            " FROM dw.fato_despesas)"
        )
        falhas = validacao.reprovadas(validacao.validar_estrutura(con, id_carga))
        assert [f.validacao for f in falhas] == ["contagem_despesas"]

    def test_data_hora_incoerente_com_as_chaves_reprova(self, carga_aberta):
        con, id_carga = carga_aberta
        con.execute(
            "UPDATE dw.fato_vendas SET sk_hora = (sk_hora + 1) % 24"
            " WHERE sk_venda = (SELECT min(sk_venda) FROM dw.fato_vendas)"
        )
        falhas = validacao.reprovadas(validacao.validar_estrutura(con, id_carga))
        assert [f.validacao for f in falhas] == ["consistencia_data_hora_vendas"]

    def test_custo_negativo_reprova(self, carga_aberta):
        con, id_carga = carga_aberta
        con.execute(
            "UPDATE dw.fato_vendas SET custo = -5"
            " WHERE sk_venda = (SELECT min(sk_venda) FROM dw.fato_vendas)"
        )
        falhas = validacao.reprovadas(validacao.validar_estrutura(con, id_carga))
        assert [f.validacao for f in falhas] == ["valores_nao_negativos"]

    def test_cupom_com_item_rejeitado_fica_fora_da_soma_e_e_informado(self, banco_com_ddl, erp):
        arquivo = erp.pasta / "vendas_2024-03.csv"
        linhas = arquivo.read_text(encoding="utf-8").splitlines()
        cabecalho = linhas[0].split(";")
        partes = linhas[1].split(";")
        partes[cabecalho.index("sku")] = "XXX-9999"
        linhas[1] = ";".join(partes)
        arquivo.write_text("\n".join(linhas) + "\n", encoding="utf-8")
        id_carga = carregar_para_staging(banco_com_ddl, erp).id_carga
        banco_com_ddl.execute("CALL etl.carregar_dw(%s)", (id_carga,))
        resultado = _por_nome(validacao.validar_estrutura(banco_com_ddl, id_carga))
        assert validacao.reprovadas(list(resultado.values())) == []
        assert (
            "1 ignorados por terem item rejeitado"
            in resultado["soma_itens_igual_total_cupom"].detalhe
        )

    def test_mensagem_da_carga_reprovada(self):
        erro = validacao.CargaReprovada(
            [validacao.ResultadoValidacao("contagem_vendas", False, 3, "x")]
        )
        assert "contagem_vendas" in str(erro)


class TestSinaisDeNegocio:
    def test_todos_os_sinais_sao_calculados_sem_alterar_o_dw(self, carga_aberta):
        con, _ = carga_aberta
        antes = relatorio.contar_linhas_do_dw(con)
        sinais = validacao.calcular_sinais(con)
        assert {s.sinal for s in sinais} == SINAIS_ESPERADOS
        assert all(s.quantidade >= 0 and s.unidade and s.descricao for s in sinais)
        assert relatorio.contar_linhas_do_dw(con) == antes

    def _quantidade(self, con, nome):
        return {s.sinal: s.quantidade for s in validacao.calcular_sinais(con)}[nome]

    def test_cupom_duplicado_e_contado(self, carga_aberta):
        con, _ = carga_aberta
        assert self._quantidade(con, "cupom_duplicado") > 0

    def test_desconto_e_margem(self, carga_aberta):
        con, _ = carga_aberta
        base_desconto = self._quantidade(con, "desconto_acima_do_limite")
        base_margem = self._quantidade(con, "margem_negativa")
        con.execute(
            "UPDATE dw.fato_vendas SET desconto = quantidade * preco_unitario * 0.5,"
            " receita_liquida = quantidade * preco_unitario * 0.5,"
            " custo = quantidade * preco_unitario"
            " WHERE sk_venda = (SELECT max(sk_venda) FROM dw.fato_vendas WHERE desconto = 0)"
        )
        assert self._quantidade(con, "desconto_acima_do_limite") == base_desconto + 1
        assert self._quantidade(con, "margem_negativa") == base_margem + 1

    def test_venda_de_vendedor_inativo(self, carga_aberta):
        con, _ = carga_aberta
        base = self._quantidade(con, "venda_de_vendedor_inativo")
        con.execute(
            "UPDATE dw.dim_vendedor SET data_desligamento = data_admissao"
            " WHERE sk_vendedor = (SELECT sk_vendedor FROM dw.fato_vendas"
            " GROUP BY sk_vendedor ORDER BY count(*) DESC LIMIT 1)"
        )
        assert self._quantidade(con, "venda_de_vendedor_inativo") > base

    def test_venda_fora_do_horario(self, carga_aberta):
        con, _ = carga_aberta
        base = self._quantidade(con, "venda_fora_do_horario")
        con.execute(
            "UPDATE dw.fato_vendas SET data_hora_venda = data_hora_venda::DATE + TIME '03:00',"
            " sk_hora = 3 WHERE sk_venda = (SELECT min(sk_venda) FROM dw.fato_vendas)"
        )
        assert self._quantidade(con, "venda_fora_do_horario") == base + 1

    def test_despesas(self, carga_aberta):
        con, _ = carga_aberta
        docs = self._quantidade(con, "despesa_documento_repetido")
        atipicas = self._quantidade(con, "despesa_de_valor_atipico")
        con.execute(
            "UPDATE dw.fato_despesas SET numero_documento = 'DOC-REPETIDO', valor = valor * 100"
            " WHERE sk_despesa IN (SELECT sk_despesa FROM dw.fato_despesas"
            " WHERE valor > 0 ORDER BY sk_despesa LIMIT 2)"
        )
        assert self._quantidade(con, "despesa_documento_repetido") == docs + 1
        assert self._quantidade(con, "despesa_de_valor_atipico") >= atipicas + 1

    def test_producao_nao_cita_os_arquivos_de_gabarito(self):
        """ETL, procedures e DDL nunca mencionam os gabaritos: eles existem só para os testes."""
        from src import config

        proibidos = (config.ARQ_ANOMALIAS, config.ARQ_PROBLEMAS)
        arquivos = list(config.RAIZ_PROJETO.joinpath("src", "etl").glob("*.py"))
        arquivos += list(config.DIR_PROCEDURES.glob("*.sql")) + list(config.DIR_DDL.glob("*.sql"))
        arquivos += [config.RAIZ_PROJETO / "config" / "fontes" / "lojas_ipe_erp.yaml"]
        for arquivo in arquivos:
            texto = arquivo.read_text(encoding="utf-8")
            assert not any(nome in texto for nome in proibidos), arquivo.name


class TestRelatorio:
    def test_relatorio_completo_e_gravado_no_banco_e_em_json(self, carga_aberta, tmp_path):
        con, id_carga = carga_aberta
        coletado = relatorio.coletar(con, id_carga)
        resultados = validacao.validar_estrutura(con, id_carga)
        sinais = validacao.calcular_sinais(con)
        con.commit()
        validacao.gravar_validacoes(con, id_carga, resultados)
        validacao.gravar_sinais(con, id_carga, sinais)
        from src.etl import controle

        controle.finalizar_carga(con, id_carga, "concluida")
        doc = relatorio.montar(
            con, id_carga, coletado, resultados, sinais, {"pico_memoria_gb": 0.1}
        )
        caminho = relatorio.gravar(con, doc, tmp_path / "processed")

        assert caminho.name == "relatorio_carga_0001.json"
        em_arquivo = json.loads(caminho.read_text(encoding="utf-8"))
        no_banco = con.execute(
            "SELECT relatorio FROM etl.relatorios_qualidade WHERE id_carga = %s", (id_carga,)
        ).fetchone()[0]
        assert em_arquivo == no_banco
        assert em_arquivo["status"] == "concluida"
        assert em_arquivo["resumo"]["linhas_lidas"] == (
            em_arquivo["resumo"]["linhas_rejeitadas"] + em_arquivo["resumo"]["linhas_carregadas"]
        )
        assert em_arquivo["corrigidas_por_tipo"]["valor_texto_formato_br"] > 0
        assert em_arquivo["linhas_no_dw"]["dim_hora"] == 24
        assert {s["sinal"] for s in em_arquivo["sinais_de_negocio"]} == SINAIS_ESPERADOS
        assert all(v["ok"] for v in em_arquivo["validacoes_estruturais"])
        assert em_arquivo["desempenho"] == {"pico_memoria_gb": 0.1}
        assert {a["entidade"] for a in em_arquivo["arquivos"]} >= {"vendas", "lojas"}

    def test_validacoes_e_sinais_persistidos_por_carga(self, carga_aberta):
        con, id_carga = carga_aberta
        resultados = validacao.validar_estrutura(con, id_carga)
        sinais = validacao.calcular_sinais(con)
        validacao.gravar_validacoes(con, id_carga, resultados)
        validacao.gravar_sinais(con, id_carga, sinais)
        con.commit()
        assert con.execute("SELECT count(*) FROM etl.carga_validacoes").fetchone()[0] == len(
            resultados
        )
        assert con.execute("SELECT count(*) FROM etl.carga_sinais").fetchone()[0] == len(sinais)
