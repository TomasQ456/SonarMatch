"""Configuración: valores por defecto y carga de parámetros calibrados."""

import json
from dataclasses import replace
from pathlib import Path

from sonarmatch.config import ConfigMotor


def test_valores_por_defecto_de_la_especificacion() -> None:
    c = ConfigMotor()
    assert (c.a, c.b, c.c, c.d, c.lambda_mmr) == (0.3, 0.35, 0.15, 0.2, 0.7)
    assert c.a + c.b + c.c + c.d == 1
    assert (c.ppr_damping, c.ppr_tolerancia, c.ppr_max_iter, c.top_k_ppr) == (0.85, 1e-6, 100, 200)
    assert (c.theta1_r1, c.theta5_r5, c.m_r2, c.umbral_difuso) == (0.1, 0.2, 20, 90)


def test_ida_y_vuelta_json(tmp_path: Path) -> None:
    ruta = tmp_path / "sub" / "calibrados.json"
    original = replace(ConfigMotor(), a=0.5, tau=0.01)
    original.a_json(ruta)
    assert ConfigMotor.desde_json(ruta) == original
    datos = json.loads(ruta.read_text())
    datos["desconocida"] = 1
    ruta.write_text(json.dumps(datos))
    assert ConfigMotor.desde_json(ruta) == original
    assert ConfigMotor.desde_json(tmp_path / "no.json") == ConfigMotor()
