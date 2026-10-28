from datetime import date

from src import calendario, config
from src.gerador.sazonalidade import Sazonalidade


def test_pascoa_e_carnaval():
    assert calendario.pascoa(2024) == date(2024, 3, 31)
    assert calendario.pascoa(2025) == date(2025, 4, 20)
    assert calendario.carnaval(2024) == date(2024, 2, 13)
    assert calendario.carnaval(2025) == date(2025, 3, 4)


def test_datas_moveis_do_varejo():
    assert calendario.black_friday(2024) == date(2024, 11, 29)
    assert calendario.black_friday(2025) == date(2025, 11, 28)
    assert calendario.dia_das_maes(2024) == date(2024, 5, 12)
    assert calendario.dia_das_maes(2025) == date(2025, 5, 11)


def test_feriados_nacionais_de_2024():
    feriados = calendario.feriados_nacionais(2024)
    assert len(feriados) == 10
    assert feriados[date(2024, 3, 29)] == "Sexta-feira Santa"
    assert date(2024, 11, 20) in feriados


def test_consciencia_negra_so_vira_feriado_a_partir_de_2024():
    assert date(2023, 11, 20) not in calendario.feriados_nacionais(2023)


def test_dias_do_mes_respeita_o_periodo():
    dias = calendario.dias_do_mes(2024, 2, date(2024, 1, 1), date(2025, 12, 31))
    assert len(dias) == 29
    parcial = calendario.dias_do_mes(2024, 2, date(2024, 2, 10), date(2024, 2, 12))
    assert parcial == [date(2024, 2, 10), date(2024, 2, 11), date(2024, 2, 12)]


def test_meses_do_periodo():
    meses = calendario.meses_do_periodo(config.DATA_INICIO, config.DATA_FIM)
    assert len(meses) == 24
    assert meses[0] == (2024, 1) and meses[-1] == (2025, 12)


def test_sazonalidade_natal_black_friday_e_carnaval():
    s = Sazonalidade(config.DATA_INICIO, config.DATA_FIM)
    quarta_comum = date(2024, 9, 18)
    assert s.fator_dia(date(2024, 12, 23)) > 1.5 * s.fator_dia(quarta_comum)
    assert s.fator_dia(date(2024, 11, 29)) > 2 * s.fator_dia(date(2024, 11, 22))
    assert s.fator_dia(date(2024, 2, 13)) < s.fator_dia(date(2024, 2, 20))
    assert s.fator_dia(date(2024, 12, 25)) < 0.5 * s.fator_dia(date(2024, 12, 24))


def test_tendencia_de_crescimento():
    s = Sazonalidade(config.DATA_INICIO, config.DATA_FIM)
    assert s.fator_dia(date(2025, 9, 17)) > s.fator_dia(date(2024, 9, 18))


def test_mix_de_setor_black_friday_favorece_eletro():
    s = Sazonalidade(config.DATA_INICIO, config.DATA_FIM)
    assert s.multiplicador_setor(date(2024, 11, 29), "Eletro") > s.multiplicador_setor(
        date(2024, 11, 5), "Eletro"
    )
    assert s.multiplicador_setor(date(2024, 5, 8), "Alimentos") == 1.0
