"""Evaluación social: subconjunto, split, ausencia de fuga, calibración de β, grupos y reportes."""

import json
from pathlib import Path

import numpy as np
import pytest

from sonarmatch.adapters.inbound import cli
from sonarmatch.config import ConfigMotor
from sonarmatch.domain.indice import IndiceCatalogo
from sonarmatch.domain.pipeline import MotorRecomendacion
from sonarmatch.evaluation.datasets import PerfilEvaluacion, emparejar
from sonarmatch.evaluation.protocol import dividir_usuarios, ocultar
from sonarmatch.evaluation.social import (
    BETAS,
    ResultadoSocial,
    bootstrap_pareado,
    conclusion,
    ejecutar_social,
    perfiles_de_amigos,
    preparar_casos_sociales,
)

SHOEGAZE = (0, 1, 2, 3, 4, 5, 6, 10, 11, 12, 13, 14)
POST_ROCK = (16, 17, 18, 19, 2, 12, 14, 15, 9, 7)


def usuarios(n: int) -> list[PerfilEvaluacion]:
    """Usuarios de shoegaze (pares) y de post-rock (impares), 10 artistas cada uno."""
    salida = []
    for k in range(n):
        base = SHOEGAZE if k % 2 == 0 else POST_ROCK
        artistas = tuple((base[(k + j) % len(base)], float(1 + (k + j) % 5)) for j in range(10))
        salida.append(PerfilEvaluacion(f"u{k}", tuple(dict(artistas).items())))
    return salida


def amistades(n: int) -> dict[str, frozenset[str]]:
    """Cadena u0–u1–…; u0 tiene además 6 amigos (grupo «más de 5»)."""
    rel: dict[str, set[str]] = {f"u{k}": set() for k in range(n)}
    for k in range(n - 1):
        rel[f"u{k}"].add(f"u{k + 1}")
        rel[f"u{k + 1}"].add(f"u{k}")
    for k in range(2, 8):
        rel["u0"].add(f"u{k}")
        rel[f"u{k}"].add("u0")
    return {u: frozenset(v) for u, v in rel.items()}


def como_amigo(perfiles: list[PerfilEvaluacion]) -> dict[str, PerfilEvaluacion]:
    return {p.usuario: p for p in perfiles}


def test_sin_fuga_y_amigos_intactos(motor: MotorRecomendacion) -> None:
    perfiles = usuarios(12)
    ami = amistades(12)
    casos = preparar_casos_sociales(motor, perfiles, ami, como_amigo(perfiles), 42)
    for p, c in zip(perfiles, casos, strict=True):
        _, ocultos = ocultar(p, 42)
        assert c.ocultos == ocultos
        assert not set(c.perfil.indices) & c.ocultos  # ocultos nunca son semillas propias
        assert {a.apodo for a in c.amigos} == ami[p.usuario]
        for amigo in c.amigos:  # a los amigos no se les quita nada
            original = {i for i, _ in como_amigo(perfiles)[amigo.apodo].artistas}
            assert set(amigo.perfil.indices) == original
    assert any(c.homofilia > 0 for c in casos)


def test_amigos_sin_perfil_en_el_catalogo_se_ignoran(motor: MotorRecomendacion) -> None:
    perfiles = usuarios(2)
    casos = preparar_casos_sociales(
        motor, perfiles, {"u0": frozenset({"u1", "fantasma"})}, como_amigo(perfiles), 1
    )
    assert [a.apodo for a in casos[0].amigos] == ["u1"]
    assert casos[1].amigos == ()


def test_protocolo_social_completo(indice: IndiceCatalogo) -> None:
    perfiles = usuarios(14)
    ami = amistades(14)
    res = ejecutar_social(indice, perfiles, ami, como_amigo(perfiles), ConfigMotor(), "toy", 42)
    val, prueba = dividir_usuarios(perfiles, 42)  # todos tienen amigos: mismo split
    assert (res.usuarios_validacion, res.usuarios_prueba) == (len(val), len(prueba))
    assert set(res.p10_por_beta) == set(BETAS)
    assert res.beta in BETAS
    assert res.config.beta == res.beta
    sistemas = {f.sistema for f in res.filas}
    assert "actual (β = 0)" in sistemas
    assert any("sin R7" in s for s in sistemas)
    grupos = {f.grupo for f in res.filas}
    assert grupos == {"todos", "1–2", "3–5", "más de 5"}
    todos = [f for f in res.filas if f.grupo == "todos"]
    assert all(f.usuarios == len(prueba) for f in todos)
    por_grupo = sum(f.usuarios for f in res.filas if f.grupo != "todos") // 3
    assert por_grupo == len(prueba)
    lo, hi = res.ic_diferencia
    assert lo <= res.diferencia_p10 <= hi or lo == hi == 0


def test_beta_cero_en_la_comparacion_es_el_sistema_actual(indice: IndiceCatalogo) -> None:
    perfiles = usuarios(10)
    ami = amistades(10)
    res = ejecutar_social(indice, perfiles, ami, como_amigo(perfiles), ConfigMotor(), "toy", 7)
    _, prueba = dividir_usuarios(perfiles, 7)
    motor = MotorRecomendacion(indice, ConfigMotor())
    casos = preparar_casos_sociales(motor, prueba, ami, como_amigo(perfiles), 7)
    actual = next(f for f in res.filas if f.grupo == "todos" and f.sistema.startswith("actual"))
    p10 = np.mean(
        [
            len(
                {r.indice for r in motor.recomendar(c.perfil, ppr=c.ppr).recomendaciones}
                & c.ocultos
            )
            / 10
            for c in casos
        ]
    )
    assert actual.p10 == pytest.approx(p10)


def test_pocos_usuarios_con_amigos(indice: IndiceCatalogo) -> None:
    perfiles = usuarios(4)
    with pytest.raises(ValueError, match="con amigos"):
        ejecutar_social(indice, perfiles, {"u0": frozenset({"u1"})}, {}, ConfigMotor(), "t")


def test_bootstrap_pareado() -> None:
    assert bootstrap_pareado(np.array([]), 1) == (0.0, 0.0)
    lo, hi = bootstrap_pareado(np.full(50, 0.1), 1)
    assert lo == pytest.approx(0.1)
    assert hi == pytest.approx(0.1)
    lo, hi = bootstrap_pareado(np.array([-0.1, 0.1] * 30), 1)
    assert lo < 0 < hi


def _res(beta: float, diferencia: float, ic: tuple[float, float]) -> ResultadoSocial:
    return ResultadoSocial("t", 7, 3, beta, {}, [], diferencia, ic, 0.0, 0.0, 0)


@pytest.mark.parametrize(
    ("beta", "dif", "ic", "esperado"),
    [
        (0.0, 0.0, (0.0, 0.0), "No mejora"),
        (0.25, 0.05, (0.01, 0.09), "Mejora"),
        (0.25, -0.05, (-0.09, -0.01), "Empeora"),
        (0.25, 0.01, (-0.02, 0.04), "No hay mejora demostrable"),
    ],
)
def test_conclusion_honesta(
    beta: float, dif: float, ic: tuple[float, float], esperado: str
) -> None:
    assert conclusion(_res(beta, dif, ic)).startswith(f"**{esperado}")


def test_cli_evaluate_social_de_punta_a_punta(motor: MotorRecomendacion, tmp_path: Path) -> None:
    db = tmp_path / "c.db"
    assert cli.main(["ingest", "--fixture", "--db", str(db)]) == 0
    hetrec = tmp_path / "hetrec"
    hetrec.mkdir()
    ix = motor.indice
    (hetrec / "artists.dat").write_text(
        "id\tname\turl\tpictureURL\n"
        + "".join(f"{i + 1}\t{a.nombre}\thttp://x\thttp://y\n" for i, a in enumerate(ix.artistas)),
        encoding="utf-8",
    )
    perfiles = usuarios(12)
    filas = [f"{p.usuario[1:]}\t{i + 1}\t{int(w * 100)}" for p in perfiles for i, w in p.artistas]
    (hetrec / "user_artists.dat").write_bytes(
        ("userID\tartistID\tweight\r\n" + "\r\n".join(filas) + "\r\n").encode()
    )
    pares = [(a, b) for a, vs in amistades(12).items() for b in vs]
    (hetrec / "user_friends.dat").write_bytes(
        ("userID\tfriendID\r\n" + "".join(f"{a[1:]}\t{b[1:]}\r\n" for a, b in pares)).encode()
    )
    params = tmp_path / "params.json"
    salida = tmp_path / "rep"
    args = ["evaluate-social", "--db", str(db), "--ruta", str(hetrec), "--params", str(params),
            "--salida", str(salida)]  # fmt: skip
    assert cli.main(args) == 0
    texto = (salida / "resultados_social.md").read_text(encoding="utf-8")
    assert "## Conclusión" in texto
    assert "Homofilia" in texto
    assert (salida / "resultados_social.csv").exists()
    assert json.loads(params.read_text())["beta"] in BETAS
    assert cli.main([*args, "--db", str(tmp_path / "no.db")]) == 2
    assert cli.main([*args, "--ruta", str(tmp_path / "no")]) == 2
    (hetrec / "user_friends.dat").write_bytes(b"userID\tfriendID\r\n")
    assert cli.main([*args, "--sin-guardar-parametros"]) == 2


def test_perfiles_de_amigos_acepta_un_solo_artista(motor: MotorRecomendacion) -> None:
    filas = [("7", motor.indice.nombre(3), 10.0), ("8", "No Existe", 5.0)]
    amigos = perfiles_de_amigos(filas, motor.indice.por_nombre)
    assert list(amigos) == ["7"]
    assert amigos["7"].artistas == ((3, 3.0),)
    assert emparejar(filas, motor.indice.por_nombre) == []  # como usuario no es evaluable
