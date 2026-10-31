"""Alertas de cancelamento alto: só a janela mais recente por vendedor (sem banco)."""

from datetime import date

import pandas as pd
from openpyxl import load_workbook

from src.relatorios import planilha
from src.relatorios.consultas import consolidar_cancelamentos
from src.relatorios.planilha import montar_pasta
from tests.relatorios.test_planilha import _dados


def _cancelamentos() -> pd.DataFrame:
    def linha(tipo, vendedor, mes, status="novo", explicacao="x"):
        return {
            "severidade": "Alta", "tipo": tipo, "data": mes, "loja_ou_centro": "Ipê 1",
            "vendedor": vendedor, "valor_envolvido": 10.0, "status": "Novo",
            "status_codigo": status, "explicacao": explicacao, "tipo_alerta": tipo,
            "cod_vendedor": vendedor,
        }  # fmt: skip

    cancel = "vendedor_cancelamento_alto"
    return pd.DataFrame(
        [
            linha(cancel, "V1", date(2025, 8, 31), explicacao="jan"),
            linha(cancel, "V1", date(2025, 9, 30)),
            linha(cancel, "V1", date(2025, 10, 31)),  # 3 seguidas, a mais recente fica
            linha(cancel, "V2", date(2025, 8, 31)),
            linha(cancel, "V2", date(2025, 10, 31)),  # mês 9 sem alerta: sequência de 1
            linha("desconto_acima_limite", "V1", date(2025, 10, 5)),
            linha(cancel, "V3", date(2025, 10, 31), status="resolvido"),  # tratado: sai
        ]
    )  # fmt: skip


def test_cancelamento_alto_fica_so_a_janela_mais_recente_com_a_sequencia():
    saida = consolidar_cancelamentos(_cancelamentos())
    cancel = saida[saida["tipo_alerta"] == "vendedor_cancelamento_alto"]
    assert cancel["cod_vendedor"].value_counts().max() == 1
    v1 = cancel[cancel["cod_vendedor"] == "V1"].iloc[0]
    assert v1["data"] == date(2025, 10, 31)
    assert v1["explicacao"].endswith("3 janelas seguidas desde 08/2025")
    v2 = cancel[cancel["cod_vendedor"] == "V2"].iloc[0]
    assert v2["data"] == date(2025, 10, 31) and "seguidas" not in v2["explicacao"]
    assert (saida["tipo_alerta"] == "desconto_acima_limite").sum() == 1


def test_aba_de_alertas_traz_no_maximo_um_cancelamento_por_vendedor(tmp_path):
    dados = _dados()
    dados.alertas = consolidar_cancelamentos(_cancelamentos())
    caminho = tmp_path / "c.xlsx"
    montar_pasta(dados).save(caminho)
    ws = load_workbook(caminho)[planilha.ABA_ALERTAS]
    vendedores = [
        ws.cell(i, 5).value for i in range(2, ws.max_row + 1)
        if ws.cell(i, 2).value == "vendedor_cancelamento_alto"
    ]  # fmt: skip
    assert len(vendedores) == len(set(vendedores)) == 3
