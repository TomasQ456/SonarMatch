"""Fixtures compartidas de pytest."""

import json
from pathlib import Path
from typing import Any

import pytest

from sonarmatch.config import ConfigMotor
from sonarmatch.domain.indice import IndiceCatalogo
from sonarmatch.domain.models import Catalogo
from sonarmatch.domain.pipeline import MotorRecomendacion
from sonarmatch.ingestion.fixture import catalogo_desde_json

RUTA_FIXTURE = Path(__file__).parent / "fixtures" / "catalogo_fixture.json"


@pytest.fixture(scope="session")
def datos_fixture() -> dict[str, Any]:
    return json.loads(RUTA_FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def catalogo() -> Catalogo:
    return catalogo_desde_json(RUTA_FIXTURE)


@pytest.fixture(scope="session")
def indice(catalogo: Catalogo) -> IndiceCatalogo:
    return IndiceCatalogo.construir(catalogo)


@pytest.fixture
def motor(indice: IndiceCatalogo) -> MotorRecomendacion:
    return MotorRecomendacion(indice, ConfigMotor())
