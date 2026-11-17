"""Validación de solicitudes según el contrato (compartida por el servicio real y los falsos)."""

from sonarmatch.ports.inbound import ErrorEntradaInvalida, SolicitudRecomendacion

MIN_ARTISTAS = 5
MAX_ARTISTAS = 20
PESO_MIN = 1.0
PESO_MAX = 5.0
PARAM_MIN = 0.0
PARAM_MAX = 1.0


def normalizar_nombre(nombre: str) -> str:
    """Forma canónica para comparar nombres: minúsculas, sin espacios extra."""
    return " ".join(nombre.casefold().split())


def validar_solicitud(solicitud: SolicitudRecomendacion) -> None:
    """Lanza ErrorEntradaInvalida si la solicitud no cumple el contrato."""
    n = len(solicitud.artistas)
    if n < MIN_ARTISTAS or n > MAX_ARTISTAS:
        raise ErrorEntradaInvalida(
            f"Se necesitan entre {MIN_ARTISTAS} y {MAX_ARTISTAS} artistas; se recibieron {n}."
        )
    vistos: set[str] = set()
    for entrada in solicitud.artistas:
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
    p = solicitud.parametros
    if p is not None:
        valores = {"a": p.a, "b": p.b, "c": p.c, "d": p.d, "lambda_mmr": p.lambda_mmr}
        for nombre, valor in valores.items():
            if not PARAM_MIN <= valor <= PARAM_MAX:
                raise ErrorEntradaInvalida(f"El parámetro {nombre} debe estar entre 0 y 1.")
        if p.a + p.b + p.c + p.d <= 0:
            raise ErrorEntradaInvalida("Al menos uno de los pesos a, b, c, d debe ser positivo.")
