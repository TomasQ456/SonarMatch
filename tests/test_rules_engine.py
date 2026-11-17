"""Motor de reglas: punto fijo, refracción, tope de iteraciones y traza."""

from collections.abc import Iterator

from sonarmatch.domain.rules.engine import (
    BaseHechos,
    Coincidencia,
    Disparo,
    Hecho,
    MotorReglas,
    Regla,
)


def _red(d: Disparo, ctx: None) -> str:
    return f"{d.regla_id}:{[h.args for h in d.conclusiones]}"


def _cond_transitiva(base: BaseHechos, ctx: None) -> Iterator[Coincidencia]:
    for a in base.todos("padre"):
        for b in base.todos("ancestro") + base.todos("padre"):
            if a.args[1] == b.args[0]:
                yield Coincidencia((a, b), (a.args[0], b.args[1]))


def _acc_transitiva(c: Coincidencia, ctx: None) -> list[Hecho]:
    return [Hecho("ancestro", c.ligaduras)]


TRANSITIVA = Regla(
    "T", "transitiva", "padre∘ancestro", "f", _cond_transitiva, _acc_transitiva, _red
)


def test_llega_a_punto_fijo_con_cierre_transitivo() -> None:
    base = BaseHechos([Hecho("padre", (x, y)) for x, y in [("a", "b"), ("b", "c"), ("c", "d")]])
    motor = MotorReglas([TRANSITIVA], max_iteraciones=10)
    res = motor.ejecutar_fase(base, None, "f")
    assert res.punto_fijo
    ancestros = {h.args for h in base.todos("ancestro")}
    assert ancestros == {("a", "c"), ("b", "d"), ("a", "d")}
    # Una vuelta más no cambia nada: ya es punto fijo.
    n = len(base)
    assert motor.ejecutar_fase(base, None, "f").punto_fijo
    assert len(base) == n


def test_refraccion_una_vez_por_combinacion_de_premisas() -> None:
    llamadas: list[tuple[str, ...]] = []

    def accion(c: Coincidencia, ctx: None) -> list[Hecho]:
        llamadas.append(tuple(str(p.args) for p in c.premisas))
        return [Hecho("visto", c.premisas[0].args)]

    def cond(base: BaseHechos, ctx: None) -> Iterator[Coincidencia]:
        for h in base.todos("x"):
            yield Coincidencia((h,))

    regla = Regla("R", "r", "", "f", cond, accion, _red)
    base = BaseHechos([Hecho("x", (1,)), Hecho("x", (2,))])
    motor = MotorReglas([regla], max_iteraciones=10)
    motor.ejecutar_fase(base, None, "f")
    motor.ejecutar_fase(base, None, "f")
    assert llamadas == [("(1,)",), ("(2,)",)]  # una vez cada uno pese a dos ejecuciones
    # Si la premisa cambia de confianza es otra combinación y vuelve a disparar.
    base.agregar(Hecho("x", (1,), 0.5))  # menor confianza: no cambia la base
    base.agregar(Hecho("x", (1,), 1.5))
    motor.ejecutar_fase(base, None, "f")
    assert len(llamadas) == 3


def test_respeta_el_tope_de_iteraciones() -> None:
    def cond(base: BaseHechos, ctx: None) -> Iterator[Coincidencia]:
        yield Coincidencia((max(base.todos("n"), key=lambda h: int(h.args[0])),))

    def accion(c: Coincidencia, ctx: None) -> list[Hecho]:
        return [Hecho("n", (int(c.premisas[0].args[0]) + 1,))]

    regla = Regla("INF", "infinita", "", "f", cond, accion, _red)
    base = BaseHechos([Hecho("n", (0,))])
    res = MotorReglas([regla], max_iteraciones=7).ejecutar_fase(base, None, "f")
    assert not res.punto_fijo
    assert res.iteraciones == 7
    assert len(base.todos("n")) == 8


def test_traza_registra_regla_y_premisas() -> None:
    base = BaseHechos([Hecho("padre", (x, y)) for x, y in [("a", "b"), ("b", "c"), ("c", "d")]])
    motor = MotorReglas([TRANSITIVA], max_iteraciones=10)
    motor.ejecutar_fase(base, None, "f")
    ad = base.obtener("ancestro", "a", "d")
    assert ad is not None
    just = base.justificacion(ad)
    assert just is not None
    assert just.regla_id == "T"
    assert {p.args for p in just.premisas} in ({("a", "b"), ("b", "d")}, {("a", "c"), ("c", "d")})
    for p in just.premisas:
        assert p in base
    cadena = motor.cadena([ad])
    assert cadena[-1].conclusiones == (ad,)
    # Las premisas derivadas aparecen antes que el hecho que sostienen.
    producidos = [h for d in cadena for h in d.conclusiones]
    assert all(producidos.index(p) < producidos.index(ad) for p in just.premisas if p in producidos)
    assert motor.redactar(cadena, None)[-1].startswith("T:")
    assert base.justificacion(Hecho("padre", ("a", "b"))) is None
    assert motor.cadena([Hecho("padre", ("a", "b"))]) == []


def test_fases_separadas() -> None:
    otra = Regla("O", "otra", "", "g", _cond_transitiva, _acc_transitiva, _red)
    base = BaseHechos([Hecho("padre", ("a", "b")), Hecho("padre", ("b", "c"))])
    motor = MotorReglas([otra], max_iteraciones=5)
    assert motor.ejecutar_fase(base, None, "f").disparos == []
    assert not base.todos("ancestro")
    assert motor.ejecutar_fase(base, None, "g").disparos
    assert motor.regla("O") is otra
