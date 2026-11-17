"""Base común de los clientes HTTP: límite de tasa, reintentos con backoff y caché."""

import json
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

import requests

log = logging.getLogger(__name__)
REINTENTABLES_HTTP = {429, 500, 502, 503, 504}


class Cache(Protocol):
    def cache_obtener(self, clave: str) -> object | None: ...
    def cache_guardar(self, clave: str, payload: object) -> None: ...


class FuenteError(RuntimeError):
    """Error no recuperable de una fuente externa."""


class ReintentableError(RuntimeError):
    """Error transitorio: se reintenta con backoff."""


@dataclass
class ClienteHTTP:
    intervalo: float  # segundos mínimos entre solicitudes (límite de tasa)
    user_agent: str
    reintentos: int = 4
    backoff: float = 1.0
    timeout: float = 30.0
    sesion: requests.Session = field(default_factory=requests.Session)
    dormir: Callable[[float], None] = time.sleep
    reloj: Callable[[], float] = time.monotonic
    _ultima: float | None = None

    def _esperar_turno(self) -> None:
        if self._ultima is not None:
            espera = self.intervalo - (self.reloj() - self._ultima)
            if espera > 0:
                self.dormir(espera)
        self._ultima = self.reloj()

    def get_json(
        self,
        url: str,
        params: Mapping[str, str | int],
        validar: Callable[[object], None] | None = None,
        cabeceras: Mapping[str, str] | None = None,
    ) -> object:
        """GET con reintentos; ``validar`` lanza ReintentableError o FuenteError si corresponde."""
        ultimo: Exception | None = None
        for intento in range(self.reintentos + 1):
            if intento:
                espera = self.backoff * 2 ** (intento - 1)
                log.warning("reintento %d en %.1fs (%s)", intento, espera, ultimo)
                self.dormir(espera)
            self._esperar_turno()
            try:
                resp = self.sesion.get(
                    url,
                    params=dict(params),
                    headers={"User-Agent": self.user_agent, **(cabeceras or {})},
                    timeout=self.timeout,
                )
                if resp.status_code in REINTENTABLES_HTTP:
                    raise ReintentableError(f"HTTP {resp.status_code}")
                datos: object = resp.json()
                if validar is not None:
                    validar(datos)
                if resp.status_code >= 400:  # noqa: PLR2004 — códigos HTTP de error del cliente
                    raise FuenteError(f"HTTP {resp.status_code}: {str(datos)[:200]}")
                return datos
            except (requests.ConnectionError, requests.Timeout, ReintentableError) as error:
                ultimo = error
            except json.JSONDecodeError as error:
                ultimo = ReintentableError(f"respuesta no JSON: {error}")
        raise FuenteError(f"sin respuesta válida tras {self.reintentos} reintentos: {ultimo}")


def con_cache(cache: Cache | None, clave: str, obtener: Callable[[], object]) -> object:
    if cache is not None:
        guardado = cache.cache_obtener(clave)
        if guardado is not None:
            return guardado
    datos = obtener()
    if cache is not None:
        cache.cache_guardar(clave, datos)
    return datos
