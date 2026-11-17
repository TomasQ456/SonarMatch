"""Evaluación offline: cargadores, métricas, protocolo y reportes."""

import csv
import json
from pathlib import Path

import numpy as np
import pytest
import scipy.sparse as sp

from sonarmatch.adapters.inbound import cli
from sonarmatch.config import ConfigMotor
from sonarmatch.domain.indice import IndiceCatalogo
from sonarmatch.domain.pipeline import MotorRecomendacion
from sonarmatch.evaluation import datasets, metrics, protocol
from sonarmatch.evaluation.datasets import PerfilEvaluacion


# ---------------------------------------------------------------- métricas
def test_precision_y_recall() -> None:
    recs = list(range(10))
    assert metrics.precision_en_k(recs, {1, 3, 42}) == pytest.approx(0.2)
    assert metrics.recall_en_k(recs, {1, 3, 42}) == pytest.approx(2 / 3)
    assert metrics.recall_en_k(recs, set()) == 0.0
    assert metrics.precision_en_k([1, 2], {1, 2}) == pytest.approx(0.2)  # siempre sobre k


def test_novedad_es_percentil_medio_de_oyentes() -> None:
    pct = metrics.percentiles_popularidad(np.array([10.0, 1000.0, 10.0, 5.0]))
    assert pct.tolist() == [0.75, 1.0, 0.75, 0.25]
    assert metrics.novedad([1], pct) > metrics.novedad([3], pct)  # más popular, menos novedoso
    assert metrics.novedad([], pct) == 0.0
    assert metrics.percentiles_popularidad(np.array([])).size == 0


def test_ils_y_cobertura() -> None:
    x = sp.csr_matrix(np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]]))
    assert metrics.ils([0, 1], x) == pytest.approx(1.0)
    assert metrics.ils([0, 1, 2], x) == pytest.approx(1 / 3)
    assert metrics.ils([0], x) == 0.0
    assert metrics.cobertura_catalogo([[0, 1], [1, 2]], 6) == pytest.approx(0.5)
    assert metrics.cobertura_catalogo([], 0) == 0.0
    assert metrics.percentil([1.0, 2.0, 3.0], 50) == 2.0
    assert metrics.percentil([], 95) == 0.0


# ---------------------------------------------------------------- datasets
def escribir_hetrec(d: Path) -> None:
    d.mkdir()
    (d / "artists.dat").write_text(
        'id\tname\turl\tpictureURL\n1\tSlowdive\tu\tp\n2\t"Weird" Al\tu\tp\n3\tDesconocido\tu\tp\n',
        encoding="utf-8",
    )
    filas = ["userID\tartistID\tweight"] + [f"7\t{a}\t{w}" for a, w in [(1, 500), (2, 20), (3, 9)]]
    filas += ["8\t1\t3", "8\t99\t4"]
    (d / "user_artists.dat").write_bytes("\r\n".join(filas).encode() + b"\r\n")


def test_leer_hetrec_formato_real(tmp_path: Path) -> None:
    escribir_hetrec(tmp_path / "h")
    filas = datasets.leer_hetrec(tmp_path / "h")
    assert filas == [("7", "Slowdive", 500.0), ("7", '"Weird" Al', 20.0), ("7", "Desconocido", 9.0),
                     ("8", "Slowdive", 3.0)]  # fmt: skip
    por_nombre = {"slowdive": 0, '"weird" al': 5}
    perfiles = datasets.cargar_perfiles("hetrec", tmp_path / "h", por_nombre, minimo=2)
    assert perfiles == [PerfilEvaluacion("7", ((0, 5.0), (5, 1.0)))]  # escalado por rango


def test_pesos_por_rango() -> None:
    assert datasets.pesos_por_rango([5, 4, 3, 2, 1]) == [5.0, 4.0, 3.0, 2.0, 1.0]
    assert datasets.pesos_por_rango([7, 7, 100]) == [1.0, 1.0, 5.0]
    assert datasets.pesos_por_rango([10, 900, 30]) == [1.0, 5.0, 3.0]
    assert datasets.pesos_por_rango([42]) == [3.0]
    assert datasets.pesos_por_rango([]) == []


def test_leer_csv_y_acotar(tmp_path: Path) -> None:
    ruta = tmp_path / "p.csv"
    ruta.write_text("user_id,artist_name,peso\nu,Slowdive,9\nu,Lush,0.5\nu,Slowdive,2\nv,Lush,3\n")
    perfiles = datasets.cargar_perfiles("csv", ruta, {"slowdive": 1, "lush": 2}, minimo=2)
    assert perfiles == [PerfilEvaluacion("u", ((1, 5.0), (2, 1.0)))]
    malo = tmp_path / "m.csv"
    malo.write_text("user,artist\n")
    with pytest.raises(ValueError, match="faltan columnas"):
        datasets.leer_csv(malo)
    with pytest.raises(ValueError, match="desconocido"):
        datasets.cargar_perfiles("xml", ruta, {})


# ---------------------------------------------------------------- protocolo
def perfiles_sinteticos(indice: IndiceCatalogo, n_usuarios: int = 10) -> list[PerfilEvaluacion]:
    """Usuarios con artistas vecinos en el grafo (ventanas sobre el orden del catálogo)."""
    return [
        PerfilEvaluacion(
            f"u{k}", tuple((i % indice.n, float(1 + i % 5)) for i in range(k * 4, k * 4 + 10))
        )
        for k in range(n_usuarios)
    ]


def test_division_es_determinista_y_disjunta(indice: IndiceCatalogo) -> None:
    perfiles = perfiles_sinteticos(indice)
    val, prueba = protocol.dividir_usuarios(perfiles, 42)
    assert (len(val), len(prueba)) == (7, 3)
    assert {p.usuario for p in val}.isdisjoint({p.usuario for p in prueba})
    assert protocol.dividir_usuarios(perfiles, 42) == (val, prueba)
    assert protocol.dividir_usuarios(perfiles, 7) != (val, prueba)


def test_ocultar_veinte_por_ciento_minimo_dos() -> None:
    largo = PerfilEvaluacion("x", tuple((i, float(i % 5 + 1)) for i in range(30)))
    visibles, ocultos = protocol.ocultar(largo, 1)
    assert len(ocultos) == 6
    assert len(visibles) == 20  # 24 visibles recortados al límite de la interfaz, por peso
    restantes = sorted((w for i, w in largo.artistas if i not in ocultos), reverse=True)
    assert sorted((w for _, w in visibles), reverse=True) == restantes[:20]
    assert ocultos.isdisjoint(i for i, _ in visibles)
    assert protocol.ocultar(largo, 1) == (visibles, ocultos)
    corto = PerfilEvaluacion("y", tuple((i, 3.0) for i in range(8)))
    vis, ocu = protocol.ocultar(corto, 1)
    assert (len(vis), len(ocu)) == (6, 2)


def test_grilla_con_pesos_positivos() -> None:
    combos = list(protocol.simplex(0.1))
    assert len(combos) == 84
    assert all(min(c) > 0 and sum(c) == pytest.approx(1.0) for c in combos)
    base = ConfigMotor()
    grilla = list(protocol.grilla(base, 0.25))
    assert grilla[0] == base
    assert len(grilla) == 1 + 1 * len(protocol.LAMBDAS) * len(protocol.TAUS)


def test_linea_base_popularidad_excluye_entrada(motor: MotorRecomendacion) -> None:
    indice = motor.indice
    casos = protocol.preparar_casos(motor, perfiles_sinteticos(indice, 2), 3)
    m = protocol.evaluar_popularidad(indice, casos)
    top = sorted(range(indice.n), key=lambda i: -indice.oyentes[i])
    assert m.novedad > 0.7  # recomienda lo más escuchado
    assert m.usuarios == 2
    caso = casos[0]
    recs = [i for i in top if i not in caso.perfil.indices][:10]
    assert m.p10 >= 0
    assert len(recs) == 10


def test_protocolo_completo_y_reportes(indice: IndiceCatalogo, tmp_path: Path) -> None:
    res = protocol.ejecutar_protocolo(
        indice, perfiles_sinteticos(indice), ConfigMotor(), "demo", paso=0.5
    )
    assert res.configuraciones_probadas == 1  # paso 0,5 no admite cuatro pesos positivos
    assert [m.sistema for m in res.filas] == [
        "línea base: popularidad",
        "sistema completo",
        *protocol.ABLACIONES,
    ]
    completo = res.filas[1]
    assert completo.latencia_p95_ms is not None
    assert completo.contrafactual_p95_ms is not None
    assert set(completo.reglas) == set(protocol.REGLAS)
    assert all(0 <= v <= 1 for v in [*completo.reglas.values(), *completo.respaldo.values()])
    assert res.filas[2].latencia_p95_ms is None  # solo el sistema completo mide tiempos
    ruta_csv, ruta_md = protocol.escribir_reportes(res, tmp_path)
    with ruta_csv.open(encoding="utf-8") as f:
        filas = list(csv.DictReader(f))
    assert list(filas[0]) == protocol.COLUMNAS
    assert len(filas) == 9
    md = ruta_md.read_text(encoding="utf-8")
    assert "| sin S_onto |" in md
    assert "no son concluyentes" in md  # 3 usuarios de prueba


def test_sin_usuarios_suficientes(indice: IndiceCatalogo) -> None:
    with pytest.raises(ValueError, match="no se puede evaluar"):
        protocol.ejecutar_protocolo(indice, perfiles_sinteticos(indice, 1), ConfigMotor(), "x")


def test_cli_evaluate_de_punta_a_punta(motor: MotorRecomendacion, tmp_path: Path) -> None:
    db = tmp_path / "c.db"
    assert cli.main(["ingest", "--fixture", "--db", str(db)]) == 0
    ruta = tmp_path / "perfiles.csv"
    with ruta.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["user_id", "artist_name", "peso"])
        for p in perfiles_sinteticos(motor.indice):
            w.writerows((p.usuario, motor.indice.nombre(i), peso) for i, peso in p.artistas)
    salida = tmp_path / "rep"
    args = ["evaluate", "--db", str(db), "--dataset", "csv", "--ruta", str(ruta),
            "--salida", str(salida), "--paso", "0.5"]  # fmt: skip
    assert cli.main(args) == 0
    assert (salida / "resultados.csv").exists()
    guardados = json.loads((salida / "parametros_calibrados.json").read_text())
    assert guardados["a"] == ConfigMotor().a
    assert cli.main([*args, "--ruta", str(tmp_path / "no.csv")]) == 2
    assert cli.main([*args, "--db", str(tmp_path / "no.db")]) == 2
    vacio = tmp_path / "vacio.csv"
    vacio.write_text("user_id,artist_name,peso\n")
    assert cli.main([*args, "--ruta", str(vacio)]) == 2
