"""Calendário brasileiro: feriados nacionais e datas móveis (páscoa, carnaval, Black Friday...)."""

from datetime import date, timedelta

from src import config


def pascoa(ano: int) -> date:
    """Domingo de Páscoa (algoritmo de Meeus/Jones/Butcher)."""
    a = ano % 19
    b, c = divmod(ano, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    mes, dia = divmod(h + l_ - 7 * m + 114, 31)
    return date(ano, mes, dia + 1)


def carnaval(ano: int) -> date:
    """Terça-feira de carnaval (ponto facultativo, não entra como feriado nacional)."""
    return pascoa(ano) - timedelta(days=config.DIAS_CARNAVAL_ANTES_PASCOA)


def black_friday(ano: int) -> date:
    """Sexta-feira seguinte ao Dia de Ação de Graças (4ª quinta-feira de novembro)."""
    primeiro = date(ano, 11, 1)
    primeira_quinta = primeiro + timedelta(days=(3 - primeiro.weekday()) % 7)
    return primeira_quinta + timedelta(weeks=3, days=1)


def dia_das_maes(ano: int) -> date:
    """Segundo domingo de maio."""
    primeiro = date(ano, 5, 1)
    primeiro_domingo = primeiro + timedelta(days=(6 - primeiro.weekday()) % 7)
    return primeiro_domingo + timedelta(weeks=1)


def feriados_nacionais(ano: int) -> dict[date, str]:
    """Feriados nacionais do ano (inclui Sexta-feira Santa)."""
    feriados = {date(ano, mes, dia): nome for mes, dia, nome in config.FERIADOS_FIXOS}
    feriados[pascoa(ano) - timedelta(days=config.DIAS_SEXTA_SANTA_ANTES_PASCOA)] = (
        "Sexta-feira Santa"
    )
    if ano >= config.ANO_INICIO_CONSCIENCIA_NEGRA:
        mes, dia, nome = config.FERIADO_CONSCIENCIA_NEGRA
        feriados[date(ano, mes, dia)] = nome
    return dict(sorted(feriados.items()))


def feriados_do_periodo(inicio: date, fim: date) -> dict[date, str]:
    feriados: dict[date, str] = {}
    for ano in range(inicio.year, fim.year + 1):
        feriados.update(feriados_nacionais(ano))
    return {d: n for d, n in feriados.items() if inicio <= d <= fim}


def ultimo_dia_do_mes(ano: int, mes: int) -> date:
    return date(ano + (mes == 12), mes % 12 + 1, 1) - timedelta(days=1)


def dias_do_mes(ano: int, mes: int, inicio: date, fim: date) -> list[date]:
    """Dias do mês que estão dentro do período [inicio, fim]."""
    d = max(date(ano, mes, 1), inicio)
    ultimo = min(ultimo_dia_do_mes(ano, mes), fim)
    dias = []
    while d <= ultimo:
        dias.append(d)
        d += timedelta(days=1)
    return dias


def eh_fim_de_semana(d: date) -> bool:
    return d.weekday() >= config.DIA_SEMANA_FIM_DE_SEMANA_INICIO


def meses_do_periodo(inicio: date, fim: date) -> list[tuple[int, int]]:
    """Lista (ano, mes) cobrindo o período."""
    meses = []
    ano, mes = inicio.year, inicio.month
    while (ano, mes) <= (fim.year, fim.month):
        meses.append((ano, mes))
        ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    return meses


def campanhas_do_ano(ano: int) -> list[tuple[str, date, date]]:
    """Campanhas promocionais do ano (nome, início, fim), em ordem de início."""
    campanhas = [
        (nome, date(ano, *inicio), date(ano, *fim)) for nome, inicio, fim in config.CAMPANHAS_FIXAS
    ]
    maes = dia_das_maes(ano)
    campanhas.append(
        ("Dia das Mães", maes - timedelta(days=config.DIAS_CAMPANHA_DIA_DAS_MAES), maes)
    )
    sexta = black_friday(ano)
    campanhas.append(
        (
            "Black Friday",
            sexta + timedelta(days=min(config.BLACK_FRIDAY_FATORES)),
            sexta + timedelta(days=max(config.BLACK_FRIDAY_FATORES)),
        )
    )
    return sorted(campanhas, key=lambda c: c[1])
