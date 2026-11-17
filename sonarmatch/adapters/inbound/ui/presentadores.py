"""Funciones puras de presentación para la interfaz de SonarMatch.

No contienen dependencias directas con Streamlit para permitir pruebas unitarias completas.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from sonarmatch.ports.inbound import (
    EntradaArtista,
    Estrategia,
    MotivoNo,
    ParametrosMotor,
    SolicitudRecomendacion,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sonarmatch.ports.inbound import EfectoContrafactual

UMBRAL_MILLON = 1_000_000
UMBRAL_MIL = 1_000
MIN_ARTISTAS = 5
MAX_ARTISTAS = 20

ORDEN_APORTES: tuple[tuple[str, str], ...] = (
    ("s_tags", "Etiquetas"),
    ("s_grafo", "Conexiones"),
    ("p_nov", "Novedad"),
    ("s_onto", "Afinidad de género"),
)

ETIQUETAS_APORTES: dict[str, str] = dict(ORDEN_APORTES)

NOMBRES_ESTRATEGIA: dict[str, str] = {
    "grafo": "Grafo (Principal)",
    "contenido": "Contenido (Respaldo)",
    "popularidad": "Popularidad (Respaldo)",
}

TEXTOS_MOTIVO_NO: dict[str, str] = {
    "ya_en_entrada": "Ya está entre los artistas de tu perfil.",
    "no_en_catalogo": "No está en el catálogo de SonarMatch.",
    "no_conectado": "No está conectado con tus artistas en el grafo de similitud.",
    "descartado_por_regla": (
        "Fue descartado por las reglas ontológicas debido a incompatibilidad de género."
    ),
    "puntaje_insuficiente": (
        "Fue evaluado como candidato, pero su puntaje quedó por debajo del décimo."
    ),
    "desplazado_por_diversidad": (
        "Alcanzó un puntaje alto, pero fue desplazado por diversidad para evitar redundancia."
    ),
}


def formatear_oyentes(oyentes: int) -> str:
    """Formatea la cantidad de oyentes en español (ej. '12,3 mil', '2,1 M')."""
    if oyentes < 0:
        return str(oyentes)
    if oyentes >= UMBRAL_MILLON:
        millones = oyentes / UMBRAL_MILLON
        val_str = f"{millones:.1f}".replace(".", ",")
        if val_str.endswith(",0"):
            val_str = val_str[:-2]
        return f"{val_str} M"
    if oyentes >= UMBRAL_MIL:
        miles = oyentes / UMBRAL_MIL
        val_str = f"{miles:.1f}".replace(".", ",")
        if val_str.endswith(",0"):
            val_str = val_str[:-2]
        return f"{val_str} mil"
    return str(oyentes)


def etiqueta_aporte(clave: str) -> str:
    """Retorna el nombre comprensible del componente de aporte."""
    return ETIQUETAS_APORTES.get(clave, clave)


def preparar_datos_grafica_aportes(aportes: dict[str, float]) -> list[dict[str, Any]]:
    """Convierte el diccionario de aportes a filas para visualización con Altair."""
    return [
        {"componente": etiqueta, "valor": float(aportes.get(clave, 0.0))}
        for clave, etiqueta in ORDEN_APORTES
    ]


def preparar_datos_comparativa_aportes(
    aportes_candidato: dict[str, float],
    nombre_candidato: str,
    aportes_decimo: dict[str, float],
    nombre_decimo: str,
) -> list[dict[str, Any]]:
    """Prepara filas para comparar aportes de un candidato con el décimo recomendado."""
    filas: list[dict[str, Any]] = []
    for clave, etiqueta in ORDEN_APORTES:
        filas.append(
            {
                "artista": f"10.°: {nombre_decimo}",
                "componente": etiqueta,
                "valor": float(aportes_decimo.get(clave, 0.0)),
            }
        )
    for clave, etiqueta in ORDEN_APORTES:
        filas.append(
            {
                "artista": f"Consultado: {nombre_candidato}",
                "componente": etiqueta,
                "valor": float(aportes_candidato.get(clave, 0.0)),
            }
        )
    return filas


def texto_insignia(estrategia: Estrategia | str) -> str:
    """Retorna el texto de la insignia según la estrategia ('Principal' o 'Respaldo')."""
    if estrategia == "grafo":
        return "Principal"
    return "Respaldo"


def validar_cantidad_artistas(n: int) -> bool:
    """Valida si la cantidad de artistas seleccionados está en el rango de 5 a 20."""
    return MIN_ARTISTAS <= n <= MAX_ARTISTAS


def texto_contador_artistas(n: int) -> str:
    """Genera el texto del contador de artistas seleccionados (ej. '3 de 5-20')."""
    return f"{n} de {MIN_ARTISTAS}–{MAX_ARTISTAS}"  # noqa: RUF001 — guion de rango exigido por la especificación


def construir_solicitud(
    artistas: Sequence[tuple[str, float]] | dict[str, float],
    parametros: ParametrosMotor | None = None,
) -> SolicitudRecomendacion:
    """Construye un DTO SolicitudRecomendacion a partir de pares (nombre, peso) o dict."""
    if isinstance(artistas, dict):
        entradas = tuple(EntradaArtista(nombre=k, peso=float(v)) for k, v in artistas.items())
    else:
        entradas = tuple(EntradaArtista(nombre=k, peso=float(v)) for k, v in artistas)
    return SolicitudRecomendacion(artistas=entradas, parametros=parametros)


def texto_motivo_no(motivo: MotivoNo | str) -> str:
    """Retorna una explicación en lenguaje natural para un valor de MotivoNo."""
    return TEXTOS_MOTIVO_NO.get(str(motivo), f"Motivo: {motivo}")


def filas_tabla_contrafactual(
    efectos: Sequence[EfectoContrafactual],
) -> list[dict[str, str]]:
    """Construye las filas formateadas para la tabla de efectos contrafactuales."""
    filas: list[dict[str, str]] = []
    for efecto in efectos:
        pos_sin = (
            f"#{efecto.posicion_sin_artista}"
            if efecto.posicion_sin_artista is not None
            else "fuera de la lista"
        )
        puntaje_str = (
            f"{efecto.puntaje_sin_artista:.4f}" if efecto.puntaje_sin_artista is not None else "—"
        )
        filas.append(
            {
                "Artista de tu lista": efecto.artista_usuario,
                "Posición original": f"#{efecto.posicion_original}",
                "Posición sin artista": pos_sin,
                "Cambio": f"#{efecto.posicion_original} → {pos_sin}",
                "Puntaje sin artista": puntaje_str,
            }
        )
    return filas


def son_parametros_iguales(p1: ParametrosMotor, p2: ParametrosMotor, tol: float = 1e-4) -> bool:
    """Verifica si dos configuraciones de parámetros son numéricamente equivalentes."""
    return (
        math.isclose(p1.a, p2.a, abs_tol=tol)
        and math.isclose(p1.b, p2.b, abs_tol=tol)
        and math.isclose(p1.c, p2.c, abs_tol=tol)
        and math.isclose(p1.d, p2.d, abs_tol=tol)
        and math.isclose(p1.lambda_mmr, p2.lambda_mmr, abs_tol=tol)
    )


def resolver_parametros(
    actuales: ParametrosMotor, por_defecto: ParametrosMotor, tol: float = 1e-4
) -> ParametrosMotor | None:
    """Devuelve None si los parámetros coinciden con los valores por defecto."""
    if son_parametros_iguales(actuales, por_defecto, tol=tol):
        return None
    return actuales


def filtrar_catalogo_por_que_no(catalogo: Sequence[str], recomendados: Sequence[str]) -> list[str]:
    """Filtra del catálogo los artistas que ya fueron recomendados."""
    excluidos = {nombre.strip().casefold() for nombre in recomendados}
    return [artista for artista in catalogo if artista.strip().casefold() not in excluidos]


def formatear_latencia(latencia_ms: float) -> str:
    """Formatea la latencia de respuesta en milisegundos."""
    return f"{latencia_ms:.1f} ms"


def formatear_resumen_estrategias(estrategias_usadas: dict[str, int]) -> str:
    """Formatea el conteo de estrategias utilizadas en las recomendaciones."""
    if not estrategias_usadas:
        return "Sin estrategias registradas"
    partes = [
        f"{NOMBRES_ESTRATEGIA.get(clave, clave)}: {cantidad}"
        for clave, cantidad in estrategias_usadas.items()
        if cantidad > 0
    ]
    return " · ".join(partes) if partes else "Sin estrategias registradas"
