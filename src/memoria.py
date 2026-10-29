"""Controle de memória: o computador do projeto tem pouca RAM livre."""

import threading
import time
from collections.abc import Callable

import psutil

from src import config


class MemoriaInsuficiente(RuntimeError):
    """Memória livre abaixo do mínimo configurado para uma execução pesada."""


def memoria_livre_gb() -> float:
    return psutil.virtual_memory().available / config.BYTES_POR_GB


def verificar_memoria_livre(minimo_gb: float = config.MEMORIA_LIVRE_MINIMA_GB) -> float:
    """Retorna a memória livre em GB ou levanta MemoriaInsuficiente se estiver abaixo do mínimo."""
    livre = memoria_livre_gb()
    if livre < minimo_gb:
        raise MemoriaInsuficiente(
            f"Memória livre {livre:.2f} GB abaixo do mínimo de {minimo_gb:.2f} GB: "
            "feche programas e tente de novo."
        )
    return livre


def pico_memoria_processo_gb() -> float:
    """Pico de memória do processo atual (working set de pico no Windows; RSS atual nos demais)."""
    info = psutil.Process().memory_info()
    return getattr(info, "peak_wset", info.rss) / config.BYTES_POR_GB


class MemoriaRompida(MemoriaInsuficiente):
    """A memória livre ficou abaixo do piso, por tempo demais, no meio de uma execução."""


class VigiaMemoria:
    """Confere a memória livre de tempos em tempos, em paralelo à execução.

    Se ela ficar abaixo do piso por mais de `tolerancia_s` segundos SEGUIDOS, a vigia se marca como
    rompida e chama `ao_romper` (uma só vez) — por exemplo, `conexao.cancel` para interromper a
    consulta SQL em andamento. Quem executa chama `verificar()` nos pontos seguros para levantar
    MemoriaRompida. `leitor` e `relogio` podem ser trocados para simular a memória nos testes.
    """

    def __init__(
        self,
        *,
        piso_gb: float = config.MEMORIA_LIVRE_MINIMA_GB,
        intervalo_s: float = config.INTERVALO_VIGIA_MEMORIA_S,
        tolerancia_s: float = config.TOLERANCIA_PISO_MEMORIA_S,
        leitor: Callable[[], float] | None = None,
        relogio: Callable[[], float] = time.monotonic,
        ao_romper: Callable[[], None] | None = None,
    ) -> None:
        self.piso_gb, self.intervalo_s, self.tolerancia_s = piso_gb, intervalo_s, tolerancia_s
        self._leitor = leitor or memoria_livre_gb
        self._relogio = relogio
        self._ao_romper = ao_romper
        self._abaixo_desde: float | None = None
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None
        self.minimo_gb: float | None = None  # menor valor visto
        self.motivo: str | None = None

    @property
    def rompido(self) -> bool:
        return self.motivo is not None

    def amostrar(self) -> None:
        """Uma leitura: atualiza o mínimo e decide se o piso foi rompido por tempo demais."""
        livre = self._leitor()
        agora = self._relogio()
        self.minimo_gb = livre if self.minimo_gb is None else min(self.minimo_gb, livre)
        if livre >= self.piso_gb:
            self._abaixo_desde = None
            return
        if self._abaixo_desde is None:
            self._abaixo_desde = agora
        duracao = agora - self._abaixo_desde
        if duracao > self.tolerancia_s and not self.rompido:
            self.motivo = (
                f"memória livre abaixo de {self.piso_gb:.2f} GB por {duracao:.0f} s seguidos "
                f"(atual {livre:.2f} GB); carga abortada"
            )
            if self._ao_romper is not None:
                self._ao_romper()

    def verificar(self) -> None:
        if self.motivo is not None:
            raise MemoriaRompida(self.motivo)

    def _laco(self) -> None:
        while not self._parar.wait(self.intervalo_s):
            self.amostrar()

    def iniciar(self) -> "VigiaMemoria":
        self._thread = threading.Thread(target=self._laco, name="vigia-memoria", daemon=True)
        self._thread.start()
        return self

    def parar(self) -> None:
        self._parar.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def __enter__(self) -> "VigiaMemoria":
        return self.iniciar()

    def __exit__(self, *_) -> None:
        self.parar()
