"""Raíz de composición: conecta los adaptadores de salida con los servicios de aplicación."""

from dataclasses import dataclass
from pathlib import Path

from sonarmatch.ports.inbound import (
    ConsultarCatalogo,
    ExplicarRecomendacion,
    RecomendarArtistas,
    RegistrarFeedback,
)


@dataclass(frozen=True)
class Servicios:
    """Los cuatro puertos de entrada ya conectados."""

    recomendar: RecomendarArtistas
    catalogo: ConsultarCatalogo
    explicar: ExplicarRecomendacion
    feedback: RegistrarFeedback


def crear_servicios(db_path: str) -> Servicios:
    """Carga el catálogo desde SQLite y construye en memoria todas las estructuras (una vez).

    Lanza FileNotFoundError si la base no existe.
    """
    if not Path(db_path).exists():
        raise FileNotFoundError(
            f"No existe la base {db_path}. Ejecuta la ingesta: "
            "python -m sonarmatch.adapters.inbound.cli ingest"
        )
    raise NotImplementedError("El backend real se conecta en la fase 6.")
