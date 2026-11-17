"""Reglas R1–R6 (un caso que dispara y otro que no), encadenamiento y ajustes de parámetros."""

import numpy as np
import pytest
from juguete import catalogo_juguete

from sonarmatch.config import ConfigMotor
from sonarmatch.domain.indice import IndiceCatalogo
from sonarmatch.domain.models import EntradaPerfil
from sonarmatch.domain.pipeline import MotorRecomendacion
from sonarmatch.domain.razonamiento import (
    OpcionesMotor,
    PerfilRazonado,
    Pesos,
    aplicar_ajustes,
    restringir_terminos,
)
from sonarmatch.domain.rules.engine import Hecho


@pytest.fixture(scope="module")
def ix() -> IndiceCatalogo:
    return IndiceCatalogo.construir(catalogo_juguete())


@pytest.fixture
def motor(ix: IndiceCatalogo) -> MotorRecomendacion:
    return MotorRecomendacion(ix, ConfigMotor())


def razonar(motor: MotorRecomendacion, *nombres: str, **kw: object) -> PerfilRazonado:
    perfil = motor.perfil([EntradaPerfil(n, 3) for n in nombres])
    return motor.razonar(perfil, **kw)


def afinidades(pr: PerfilRazonado) -> dict[str, float]:
    return {str(h.args[0]): h.confianza for h in pr.base.todos("afinidad")}


def disparadas(pr: PerfilRazonado) -> set[str]:
    return {d.regla_id for d in pr.motor.disparos if d.conclusiones}


# ------------------------------------------------------------------------- R1
def test_r1_dispara_con_dos_subgeneros(motor: MotorRecomendacion) -> None:
    pr = razonar(motor, "Dream A", "Shoe A")
    assert afinidades(pr) == {"indie": pytest.approx(1.0)}  # 0,5 + 0,5 (tope 1)


def test_r1_no_dispara_con_un_solo_subgenero(motor: MotorRecomendacion) -> None:
    pr = razonar(motor, "Dream A", "Dream B")
    assert "R1" not in disparadas(pr)
    assert not afinidades(pr)


def test_r1_no_dispara_si_un_subgenero_pesa_menos_que_theta1(ix: IndiceCatalogo) -> None:
    motor = MotorRecomendacion(ix, ConfigMotor(theta1_r1=0.6))
    assert not afinidades(razonar(motor, "Dream A", "Shoe A"))


def test_r1_encadena_dos_niveles(motor: MotorRecomendacion) -> None:
    pr = razonar(motor, "Dream A", "Shoe A", "Post A")
    af = afinidades(pr)
    assert af["indie"] == pytest.approx(2 / 3)
    assert af["alt"] == pytest.approx(1.0)  # indie (inferido, 2/3) + post-rock (1/3)
    alt = pr.base.obtener("afinidad", "alt")
    assert alt is not None
    cadena = pr.motor.cadena([alt])
    assert [d.regla_id for d in cadena] == ["R1", "R1"]
    assert cadena[0].coincidencia.ligaduras == ("indie",)
    assert Hecho("afinidad", ("indie",), pytest.approx(2 / 3)) == cadena[1].coincidencia.premisas[0]
    assert "rock" not in af  # profundidad 1


def test_r1_no_aplica_a_profundidad_menor_que_dos(motor: MotorRecomendacion) -> None:
    # alt y heavy son subgéneros de rock (profundidad 1): no se infiere afinidad(rock)
    pr = razonar(motor, "Alt A", "Heavy A")
    assert not afinidades(pr)
    # en cambio post-rock y noise rock sí dan afinidad(alt) (profundidad 2)
    assert afinidades(razonar(motor, "Post A", "Noise A")) == {"alt": pytest.approx(1.0)}


# ------------------------------------------------------------------------- R2
def test_r2_explora_hermanos_y_aporta_candidatos(
    motor: MotorRecomendacion, ix: IndiceCatalogo
) -> None:
    pr = razonar(motor, "Dream A", "Shoe A")
    assert {str(h.args[0]) for h in pr.base.todos("explorar")} == {"slow"}
    candidatos = {ix.nombre(i) for i in pr.candidatos_r2()}
    assert candidatos == {"Slow A", "Slow B"}


def test_r2_respeta_m_y_excluye_la_entrada(ix: IndiceCatalogo) -> None:
    motor = MotorRecomendacion(ix, ConfigMotor(m_r2=1))
    pr = razonar(motor, "Dream A", "Shoe A", "Slow B")  # slow ya está en el perfil
    assert "slow" not in {str(h.args[0]) for h in pr.base.todos("explorar")}
    pr2 = razonar(motor, "Dream A", "Shoe A")
    assert len(pr2.candidatos_r2()) == 1


def test_r2_no_dispara_sin_afinidad(motor: MotorRecomendacion) -> None:
    pr = razonar(motor, "Dream A", "Dream B")
    assert not pr.base.todos("explorar")
    assert not pr.candidatos_r2()


# ------------------------------------------------------------------------- R3 / R4
def test_r3_perfil_nicho(motor: MotorRecomendacion, ix: IndiceCatalogo) -> None:
    pr = razonar(motor, "Slow A", "Slow B", "Dream A")
    assert float(np.median([800, 900, 1000])) < ix.percentil_oyentes(25)
    assert "R3" in disparadas(pr)
    assert pr.pesos.c > ConfigMotor().c


def test_r4_perfil_mainstream(motor: MotorRecomendacion) -> None:
    pr = razonar(motor, "Thrash A", "Thrash B", "Big Pop")
    assert "R4" in disparadas(pr)
    assert "R3" not in disparadas(pr)
    assert pr.pesos.c < ConfigMotor().c


def test_r3_r4_no_disparan_con_perfil_intermedio(motor: MotorRecomendacion) -> None:
    pr = razonar(motor, "Post A", "Noise A", "Alt A")
    assert not {"R3", "R4"} & disparadas(pr)
    assert pr.pesos == Pesos.desde_config(ConfigMotor()).renormalizado()


# ------------------------------------------------------------------------- R5
def test_r5_descarta_generos_incompatibles(motor: MotorRecomendacion, ix: IndiceCatalogo) -> None:
    res = motor.recomendar(
        motor.perfil([EntradaPerfil(n, 3) for n in ("Dream A", "Shoe A", "Slow A")])
    )
    assert res.traza is not None
    descartados = {ix.nombre(i) for i in res.traza.descartes}
    assert descartados == {"Ambient A", "Ambient B"}  # LCS = raíz → sim 0 < 0,2
    assert "Thrash A" in {ix.nombre(i) for i in res.traza.candidatos} - descartados
    assert not descartados & {r.nombre for r in res.recomendaciones}


def test_r5_no_dispara_sin_reglas_ni_en_respaldo(
    motor: MotorRecomendacion, ix: IndiceCatalogo
) -> None:
    perfil = motor.perfil([EntradaPerfil(n, 3) for n in ("Dream A", "Shoe A", "Slow A")])
    res = motor.recomendar(perfil, opciones=OpcionesMotor(usar_reglas=False))
    assert res.traza is not None
    assert not res.traza.descartes
    # La estrategia de contenido no aplica R5: puede devolver artistas que R5 descartaría.
    pr = motor.razonar(perfil)
    nombres = {r.nombre for r in motor.contenido.recomendar(pr, 20, pr.entrada)}
    assert "Ambient A" in nombres


# ------------------------------------------------------------------------- R6
def test_r6_perfil_eclectico_baja_lambda(motor: MotorRecomendacion) -> None:
    pr = razonar(motor, "Dream A", "Thrash A", "Ambient A")
    assert "R6" in disparadas(pr)
    assert pr.pesos.lambda_mmr == pytest.approx(ConfigMotor().lambda_mmr - 0.1)


def test_r6_no_dispara_con_perfil_coherente(motor: MotorRecomendacion) -> None:
    pr = razonar(motor, "Dream A", "Shoe A")
    assert "R6" not in disparadas(pr)
    assert pr.pesos.lambda_mmr == pytest.approx(ConfigMotor().lambda_mmr)


# ------------------------------------------------------------------------- ajustes
def test_ajustes_se_suman_acotan_y_renormalizan() -> None:
    base = Pesos(0.3, 0.35, 0.15, 0.2, 0.7)
    p = aplicar_ajustes(base, [("c", 0.1), ("c", 0.1)])
    assert p.c == pytest.approx(0.35 / 1.2)
    assert p.a + p.b + p.c + p.d == pytest.approx(1)
    acotado = aplicar_ajustes(
        Pesos(0.5, 0.45, 0.05, 0.0, 0.05), [("c", -0.1), ("lambda_mmr", -0.1)]
    )
    assert acotado.c == 0
    assert acotado.lambda_mmr == 0
    assert acotado.a == pytest.approx(0.5 / 0.95)
    tope = aplicar_ajustes(Pesos(0.0, 0.0, 0.95, 0.05, 0.95), [("c", 0.1), ("lambda_mmr", 0.1)])
    assert tope.c == pytest.approx(1 / 1.05)
    assert tope.lambda_mmr == 1


def test_ajustes_no_se_aplican_con_parametros_del_usuario(motor: MotorRecomendacion) -> None:
    usuario = Pesos(0.25, 0.25, 0.25, 0.25, 0.5)
    pr = razonar(motor, "Slow A", "Slow B", "Dream A", parametros=usuario)
    assert "R3" in disparadas(pr)  # la regla se evalúa...
    assert pr.pesos == usuario  # ...pero sus ajustes no se aplican
    assert pr.pesos_usuario


def test_parametros_del_usuario_se_renormalizan(motor: MotorRecomendacion) -> None:
    pr = razonar(motor, "Post A", "Noise A", parametros=Pesos(1, 1, 0, 0, 0.5))
    assert (pr.pesos.a, pr.pesos.b) == (0.5, 0.5)


def test_restringir_terminos_para_ablacion() -> None:
    p = restringir_terminos(
        Pesos(0.3, 0.35, 0.15, 0.2, 0.7), frozenset({"s_tags", "s_grafo", "p_nov"})
    )
    assert p.d == 0
    assert p.a + p.b + p.c == pytest.approx(1)
    assert restringir_terminos(p, frozenset()) == p
    with pytest.raises(ValueError, match="positivo"):
        Pesos(0, 0, 0, 0, 0.5).renormalizado()
