"""Punto de entrada de la interfaz Streamlit de SonarMatch."""

from __future__ import annotations

import logging
import os
import uuid
from typing import TYPE_CHECKING

import streamlit as st

from sonarmatch.adapters.inbound.ui.componentes import (
    MSG_ERROR_GENERICO,
    dibujar_encabezado_resultados,
    dibujar_entrada,
    dibujar_seccion_por_que_no,
    dibujar_sidebar,
    dibujar_tarjeta_recomendacion,
)
from sonarmatch.adapters.inbound.ui.presentadores import construir_solicitud
from sonarmatch.bootstrap import Servicios, crear_servicios
from sonarmatch.ports.inbound import (
    ErrorEntradaInvalida,
    ParametrosMotor,
    RespuestaRecomendacion,
    SolicitudRecomendacion,
)
from sonarmatch.testing.fakes import crear_servicios_falsos

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

RUTA_DB_DEFECTO = "data/sonarmatch.db"


@st.cache_resource
def _cargar_servicios_cacheados(usar_falso: bool, db_path: str) -> Servicios:
    """Inicializa y cachea la raíz de composición según el modo configurado."""
    if usar_falso:
        return crear_servicios_falsos()
    return crear_servicios(db_path)


def obtener_servicios() -> Servicios:
    """Obtiene los servicios desde el entorno (SONARMATCH_FAKE=1 o SONARMATCH_DB)."""
    usar_falso = os.environ.get("SONARMATCH_FAKE") == "1"
    db_path = os.environ.get("SONARMATCH_DB", RUTA_DB_DEFECTO)
    return _cargar_servicios_cacheados(usar_falso, db_path)


def _asegurar_estado_sesion() -> str:
    """Garantiza que exista un identificador único de sesión en st.session_state."""
    if "sesion_id" not in st.session_state or not isinstance(st.session_state["sesion_id"], str):
        st.session_state["sesion_id"] = str(uuid.uuid4())
    return str(st.session_state["sesion_id"])


def _ejecutar_recomendacion(
    servicios: Servicios,
    entradas: Sequence[tuple[str, float]],
    parametros: ParametrosMotor | None,
) -> None:
    """Construye la solicitud, invoca el motor y guarda el resultado en session_state."""
    solicitud = construir_solicitud(entradas, parametros=parametros)
    try:
        respuesta = servicios.recomendar.recomendar(solicitud)
    except ErrorEntradaInvalida as exc:
        st.error(str(exc))
        return
    except Exception:
        logger.exception("Error inesperado al generar recomendaciones.")
        st.error(MSG_ERROR_GENERICO)
        return

    st.session_state["ultima_solicitud"] = solicitud
    st.session_state["ultima_respuesta"] = respuesta
    st.session_state["contrafactuales"] = {}
    st.session_state["votos_emitidos"] = {}
    st.session_state.pop("resultado_por_que_no", None)


def main(servicios: Servicios) -> None:
    """Dibuja la interfaz principal de SonarMatch recibiendo los servicios inyectados."""
    st.title("SonarMatch")
    st.caption(
        "Recomendador híbrido de artistas musicales con ontología de géneros, "
        "Personalized PageRank y explicaciones contrafactuales."
    )

    sesion_id = _asegurar_estado_sesion()
    por_defecto = servicios.catalogo.parametros_por_defecto()
    catalogo = servicios.catalogo.nombres_artistas()

    parametros = dibujar_sidebar(por_defecto)
    entradas, recomendar_click = dibujar_entrada(catalogo)

    if recomendar_click:
        _ejecutar_recomendacion(servicios, entradas, parametros)

    respuesta = st.session_state.get("ultima_respuesta")
    solicitud = st.session_state.get("ultima_solicitud")
    if isinstance(respuesta, RespuestaRecomendacion) and isinstance(
        solicitud, SolicitudRecomendacion
    ):
        dibujar_encabezado_resultados(respuesta)
        for idx, rec in enumerate(respuesta.recomendaciones, start=1):
            dibujar_tarjeta_recomendacion(
                posicion=idx,
                rec=rec,
                solicitud=solicitud,
                explicar=servicios.explicar,
                feedback=servicios.feedback,
                sesion_id=sesion_id,
            )
        dibujar_seccion_por_que_no(catalogo, respuesta, solicitud, servicios.explicar)


def ejecutar_app() -> None:
    """Punto de entrada que resuelve los servicios y maneja la falta de base de datos."""
    st.set_page_config(page_title="SonarMatch", layout="wide")
    try:
        servicios_activos = obtener_servicios()
    except FileNotFoundError as exc:
        st.title("SonarMatch")
        st.error(str(exc))
        return
    except Exception:
        logger.exception("Error inesperado al inicializar los servicios.")
        st.title("SonarMatch")
        st.error(MSG_ERROR_GENERICO)
        return

    main(servicios_activos)


if __name__ == "__main__":
    ejecutar_app()
