"""Melhor dia e melhor faixa de cada loja (sem banco)."""

import pandas as pd

from src.relatorios.consultas import destacar_o_melhor


def test_destaca_a_maior_receita_media_de_cada_loja():
    quadro = pd.DataFrame(
        {
            "cod_loja": ["L01", "L01", "L01", "L02", "L02"],
            "faixa": ["Manhã", "Tarde", "Noite", "Manhã", "Tarde"],
            "receita_media": [100.0, 300.0, 200.0, 50.0, 40.0],
        }
    )
    destacado = destacar_o_melhor(quadro, "Melhor faixa")
    assert list(destacado["destaque"]) == [None, "Melhor faixa", None, "Melhor faixa", None]
    assert "destaque" not in quadro.columns  # não altera o original


def test_empate_fica_com_o_primeiro_e_quadro_vazio_nao_quebra():
    empate = pd.DataFrame({"cod_loja": ["L01"] * 2, "receita_media": [10.0, 10.0]})
    assert list(destacar_o_melhor(empate, "x")["destaque"]) == ["x", None]
    vazio = pd.DataFrame(columns=["cod_loja", "receita_media"])
    assert destacar_o_melhor(vazio, "x").empty
