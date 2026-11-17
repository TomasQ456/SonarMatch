"""Fixtures compartidas de pytest."""

import json
from pathlib import Path
from typing import Any

import pytest

RUTA_FIXTURE = Path(__file__).parent / "fixtures" / "catalogo_fixture.json"


@pytest.fixture(scope="session")
def datos_fixture() -> dict[str, Any]:
    return json.loads(RUTA_FIXTURE.read_text(encoding="utf-8"))
