"""Raíz de composición: conecta los adaptadores de salida con los servicios de aplicación."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from sonarmatch.adapters.outbound.sqlite_repository import RepositorioSQLite
from sonarmatch.application.perfiles import PerfilesNoDisponibles, ServicioPerfiles
from sonarmatch.application.recommend_service import ServicioRecomendacion
from sonarmatch.config import RUTA_CALIBRADOS, ConfigMotor
from sonarmatch.domain.indice import IndiceCatalogo
from sonarmatch.domain.pipeline import MotorRecomendacion
from sonarmatch.ports.inbound import (
    ConsultarCatalogo,
    ExplicarRecomendacion,
    GestionarPerfiles,
    RecomendarArtistas,
    RegistrarFeedback,
)

MENSAJE_INGESTA = (
    "Ejecuta la ingesta: python -m sonarmatch.adapters.inbound.cli ingest "
    "(o, sin API key, con --fixture para cargar el catálogo de demostración)."
)


@dataclass(frozen=True)
class Servicios:
    """Los puertos de entrada ya conectados (``perfiles`` tiene valor por defecto: es aditivo)."""

    recomendar: RecomendarArtistas
    catalogo: ConsultarCatalogo
    explicar: ExplicarRecomendacion
    feedback: RegistrarFeedback
    perfiles: GestionarPerfiles = field(default_factory=PerfilesNoDisponibles)


def crear_servicios(db_path: str, config_path: str | None = None) -> Servicios:
    """Carga el catálogo desde SQLite y construye en memoria todas las estructuras (una vez).

    Los hiperparámetros salen de ``config_path``, de SONARMATCH_PARAMS o de
    reports/parametros_calibrados.json, en ese orden; si no existen, de config.py.
    Lanza FileNotFoundError si la base no existe o está vacía.
    """
    if not Path(db_path).exists():
        raise FileNotFoundError(f"No existe la base {db_path}. {MENSAJE_INGESTA}")
    repo = RepositorioSQLite(db_path)
    repo.crear_esquema()
    if repo.contar_artistas() == 0:
        raise FileNotFoundError(f"La base {db_path} no tiene artistas. {MENSAJE_INGESTA}")
    ruta = Path(config_path or os.environ.get("SONARMATCH_PARAMS") or RUTA_CALIBRADOS)
    motor = MotorRecomendacion(
        IndiceCatalogo.construir(repo.cargar_catalogo()), ConfigMotor.desde_json(ruta)
    )
    servicio = ServicioRecomendacion(motor, repo)
    return Servicios(
        recomendar=servicio,
        catalogo=servicio,
        explicar=servicio,
        feedback=servicio,
        perfiles=ServicioPerfiles(repo),
    )
