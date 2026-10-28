"""Fatores de sazonalidade do varejo brasileiro, por dia e por setor."""

from datetime import date, timedelta

from src import calendario, config


class Sazonalidade:
    def __init__(self, data_inicio: date, data_fim: date) -> None:
        self.data_inicio = data_inicio
        anos = range(data_inicio.year, data_fim.year + 1)
        self.feriados = calendario.feriados_do_periodo(
            date(data_inicio.year, 1, 1), date(data_fim.year, 12, 31)
        )
        self._eventos: dict[date, float] = {}
        for ano in anos:
            self._aplicar(calendario.black_friday(ano), config.BLACK_FRIDAY_FATORES)
            self._aplicar(calendario.dia_das_maes(ano), config.DIA_DAS_MAES_FATORES)
            self._aplicar(calendario.carnaval(ano), config.CARNAVAL_FATORES)
        self._janela_black_friday = {
            calendario.black_friday(ano) + timedelta(days=off): True
            for ano in anos
            for off in config.BLACK_FRIDAY_FATORES
        }

    def _aplicar(self, ancora: date, fatores: dict[int, float]) -> None:
        for deslocamento, fator in fatores.items():
            self._eventos[ancora + timedelta(days=deslocamento)] = fator

    def em_black_friday(self, d: date) -> bool:
        return d in self._janela_black_friday

    def fator_dia(self, d: date) -> float:
        """Intensidade relativa de vendas no dia: mês x dia da semana x eventos x tendência."""
        fator = config.FATOR_SAZONAL_MES[d.month] * config.FATOR_DIA_SEMANA[d.weekday()]
        fator *= (1 + config.CRESCIMENTO_ANUAL_VENDAS) ** (
            (d - self.data_inicio).days / config.DIAS_POR_ANO
        )
        fator *= self._eventos.get(d, 1.0)

        if d.month == 12 and config.NATAL_JANELA_DIAS[0] <= d.day <= config.NATAL_JANELA_DIAS[1]:
            fator *= config.NATAL_FATOR_JANELA
        if (d.month, d.day) == (12, 25):
            fator *= config.NATAL_FATOR_DIA
        elif (d.month, d.day) == (1, 1):
            fator *= config.ANO_NOVO_FATOR_DIA
        elif (d.month, d.day) == (12, 31):
            fator *= config.VESPERA_ANO_NOVO_FATOR
        elif d in self.feriados:
            fator *= config.FATOR_FERIADO_NACIONAL

        inicio_aulas, fim_aulas = config.VOLTA_AS_AULAS_DIAS
        if d.month == 2 and inicio_aulas <= d.day <= fim_aulas:
            fator *= config.VOLTA_AS_AULAS_FATOR
        return fator

    def multiplicador_setor(self, d: date, setor: str) -> float:
        mult = config.MULT_SETOR_MES.get(d.month, {}).get(setor, 1.0)
        if self.em_black_friday(d):
            mult *= config.MULT_SETOR_BLACK_FRIDAY.get(setor, 1.0)
        return mult
