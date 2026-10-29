"""Vigia de memória: lógica de tempo (relógio e memória simulados, sem esperar de verdade)."""

import time

import pytest

from src import config
from src.memoria import MemoriaRompida, VigiaMemoria


class Cenario:
    """Memória e relógio simulados: `passo` avança o relógio e lê a memória do momento."""

    def __init__(self):
        self.agora = 0.0
        self.livre = 1.0

    def relogio(self):
        return self.agora

    def leitor(self):
        return self.livre

    def passo(self, vigia, segundos, livre):
        self.agora += segundos
        self.livre = livre
        vigia.amostrar()


@pytest.fixture
def cenario():
    return Cenario()


@pytest.fixture
def chamadas():
    return []


@pytest.fixture
def vigia(cenario, chamadas):
    return VigiaMemoria(
        piso_gb=0.4,
        tolerancia_s=5.0,
        leitor=cenario.leitor,
        relogio=cenario.relogio,
        ao_romper=lambda: chamadas.append("cancelou"),
    )


def test_padroes_vem_do_config():
    vigia = VigiaMemoria()
    assert vigia.piso_gb == config.MEMORIA_LIVRE_MINIMA_GB
    assert vigia.intervalo_s == config.INTERVALO_VIGIA_MEMORIA_S
    assert vigia.tolerancia_s == config.TOLERANCIA_PISO_MEMORIA_S


def test_memoria_boa_nunca_rompe(vigia, cenario, chamadas):
    for _ in range(10):
        cenario.passo(vigia, 2, 0.8)
    vigia.verificar()
    assert not vigia.rompido and chamadas == []
    assert vigia.minimo_gb == 0.8


def test_queda_curta_e_tolerada(vigia, cenario, chamadas):
    cenario.passo(vigia, 0, 0.3)
    cenario.passo(vigia, 2, 0.3)
    cenario.passo(vigia, 2, 0.3)  # 4 s abaixo do piso: ainda dentro da tolerância
    cenario.passo(vigia, 2, 0.6)  # recuperou
    vigia.verificar()
    assert not vigia.rompido and chamadas == []
    assert vigia.minimo_gb == 0.3


def test_quedas_curtas_separadas_nao_se_somam(vigia, cenario, chamadas):
    for _ in range(4):
        cenario.passo(vigia, 0, 0.3)
        cenario.passo(vigia, 4, 0.3)
        cenario.passo(vigia, 1, 0.9)  # volta ao normal e zera a contagem
    assert not vigia.rompido and chamadas == []


def test_queda_prolongada_rompe_e_cancela_uma_so_vez(vigia, cenario, chamadas):
    cenario.passo(vigia, 0, 0.3)
    cenario.passo(vigia, 5, 0.3)  # exatamente a tolerância: ainda não
    assert not vigia.rompido
    cenario.passo(vigia, 2, 0.28)  # 7 s seguidos abaixo do piso
    assert vigia.rompido and chamadas == ["cancelou"]
    cenario.passo(vigia, 10, 0.2)
    assert chamadas == ["cancelou"]  # cancela só uma vez
    with pytest.raises(MemoriaRompida, match="abaixo de 0.40 GB por 7 s"):
        vigia.verificar()


def test_rompimento_e_uma_memoria_insuficiente():
    from src.memoria import MemoriaInsuficiente

    assert issubclass(MemoriaRompida, MemoriaInsuficiente)


def test_thread_de_verdade_com_memoria_simulada(chamadas):
    leituras = []

    def leitor():
        leituras.append(1)
        return 0.1  # sempre abaixo do piso

    with VigiaMemoria(
        intervalo_s=0.02,
        tolerancia_s=0.1,
        leitor=leitor,
        ao_romper=lambda: chamadas.append("cancelou"),
    ) as vigia:
        limite = time.monotonic() + 3
        while not vigia.rompido and time.monotonic() < limite:
            time.sleep(0.01)
        assert vigia.rompido
    assert chamadas == ["cancelou"]
    quantidade = len(leituras)
    time.sleep(0.1)
    assert len(leituras) == quantidade  # a thread parou ao sair do bloco
