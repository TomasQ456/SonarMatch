"""Validación de solicitudes según el contrato (compartida por el servicio real y los falsos)."""

import re

from sonarmatch.domain.textos import normalizar_nombre
from sonarmatch.ports.inbound import (
    EntradaArtista,
    ErrorEntradaInvalida,
    ErrorPerfil,
    SolicitudRecomendacion,
)

__all__ = ["normalizar_apodo", "normalizar_nombre", "validar_artistas", "validar_solicitud"]

MIN_ARTISTAS = 5
MAX_ARTISTAS = 20
PESO_MIN = 1.0
PESO_MAX = 5.0
PARAM_MIN = 0.0
PARAM_MAX = 1.0
APODO = re.compile(r"[a-z0-9_.-]{3,30}")


def normalizar_apodo(apodo: str) -> str:
    """Apodo sin espacios extremos y en minúsculas; lanza ErrorPerfil si no es válido."""
    clave = apodo.strip().casefold()
    if not APODO.fullmatch(clave):
        raise ErrorPerfil(
            "El apodo debe tener entre 3 y 30 caracteres: letras sin tilde, números, "
            "punto, guion o guion bajo."
        )
    return clave


def validar_solicitud(solicitud: SolicitudRecomendacion) -> None:
    """Lanza ErrorEntradaInvalida (o ErrorPerfil por el apodo) si no cumple el contrato."""
    validar_artistas(solicitud.artistas)
    if solicitud.apodo is not None:
        normalizar_apodo(solicitud.apodo)
    p = solicitud.parametros
    if p is not None:
        valores = {
            "a": p.a,
            "b": p.b,
            "c": p.c,
            "d": p.d,
            "lambda_mmr": p.lambda_mmr,
            "beta": p.beta,
        }
        for nombre, valor in valores.items():
            if not PARAM_MIN <= valor <= PARAM_MAX:
                raise ErrorEntradaInvalida(f"El parámetro {nombre} debe estar entre 0 y 1.")
        if p.a + p.b + p.c + p.d <= 0:
            raise ErrorEntradaInvalida("Al menos uno de los pesos a, b, c, d debe ser positivo.")


def validar_artistas(artistas: tuple[EntradaArtista, ...]) -> None:
    """Entre 5 y 20 artistas, sin nombres vacíos ni repetidos y con pesos en [1, 5]."""
    n = len(artistas)
    if n < MIN_ARTISTAS or n > MAX_ARTISTAS:
        raise ErrorEntradaInvalida(
            f"Se necesitan entre {MIN_ARTISTAS} y {MAX_ARTISTAS} artistas; se recibieron {n}."
        )
    vistos: set[str] = set()
    for entrada in artistas:
        clave = normalizar_nombre(entrada.nombre)
        if not clave:
            raise ErrorEntradaInvalida("Hay un artista con nombre vacío.")
        if clave in vistos:
            raise ErrorEntradaInvalida(f"El artista «{entrada.nombre}» está repetido.")
        vistos.add(clave)
        if not PESO_MIN <= entrada.peso <= PESO_MAX:
            raise ErrorEntradaInvalida(
                f"El peso de «{entrada.nombre}» debe estar entre {PESO_MIN:g} y {PESO_MAX:g}."
            )
