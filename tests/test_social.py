"""Dimensión social: mezcla de semillas, reutilización de PPR, aporte social, R7, contrafactuales
sociales, consentimiento y "¿por qué no?"."""

import dataclasses
from pathlib import Path

import numpy as np
import pytest

from sonarmatch.adapters.outbound.sqlite_repository import RepositorioSQLite, guardar_catalogo
from sonarmatch.application.perfiles import ServicioPerfiles
from sonarmatch.application.recommend_service import ServicioRecomendacion
from sonarmatch.config import ConfigMotor
from sonarmatch.domain.counterfactual import TODOS_TUS_AMIGOS, Contrafactuales, diagnosticar
from sonarmatch.domain.indice import IndiceCatalogo
from sonarmatch.domain.models import (
    Catalogo,
    ContextoSocial,
    EntradaPerfil,
    PerfilAmigo,
)
from sonarmatch.domain.pipeline import MotorRecomendacion, ResultadoConsulta
from sonarmatch.domain.razonamiento import OpcionesMotor
from sonarmatch.ports.inbound import (
    EntradaArtista,
    ErrorPerfil,
    ParametrosMotor,
    SolicitudRecomendacion,
)

SHOEGAZE = ("Slowdive", "Low", "Codeine", "Red House Painters", "My Bloody Valentine", "Lush")
POST_ROCK_A = (
    "Godspeed You! Black Emperor",
    "Explosions in the Sky",
    "Mogwai",
    "Sigur Rós",
    "Ride",
)
POST_ROCK_B = ("Mogwai", "Explosions in the Sky", "Godspeed You! Black Emperor", "Low", "Duster")
METAL = ("Metallica", "Slayer", "Megadeth", "Death", "Mayhem")


def _social(motor: MotorRecomendacion, beta: float, **amigos: tuple[str, ...]) -> ContextoSocial:
    return ContextoSocial(
        tuple(
            PerfilAmigo(apodo, motor.perfil([EntradaPerfil(n, 3) for n in nombres]))
            for apodo, nombres in amigos.items()
        ),
        beta,
    )


def _consulta(
    motor: MotorRecomendacion,
    social: ContextoSocial | None,
    opciones: OpcionesMotor | None = None,
    explicar: bool = True,
) -> ResultadoConsulta:
    perfil = motor.perfil([EntradaPerfil(n, 1 + i % 5) for i, n in enumerate(SHOEGAZE)])
    return motor.recomendar(perfil, None, opciones, explicar=explicar, social=social)


def _firma(res: ResultadoConsulta) -> list[tuple[object, ...]]:
    return [
        (r.indice, r.puntaje, tuple(sorted(r.aportes.items())), r.explicacion)
        for r in res.recomendaciones
    ]


# ------------------------------------------------------------------ mezcla de semillas
def test_beta_cero_es_identico_al_sistema_sin_amigos(motor: MotorRecomendacion) -> None:
    """Regresión: con β = 0 el resultado es idéntico (mismos puntajes exactos y textos)."""
    sin = _consulta(motor, None)
    con_beta_cero = _consulta(motor, _social(motor, 0.0, ana_m=POST_ROCK_A, juanp=POST_ROCK_B))
    assert _firma(con_beta_cero) == _firma(sin)
    assert con_beta_cero.extendido == sin.extendido
    assert con_beta_cero.perfil.sociales is None
    assert all(r.aportes["s_social"] == 0 for r in con_beta_cero.recomendaciones)


def test_amigos_sin_artistas_en_el_catalogo_equivalen_a_no_tener_amigos(
    motor: MotorRecomendacion,
) -> None:
    social = _social(motor, 0.5, fantasma=("No Existe", "Tampoco"))
    assert not social.activo
    assert _firma(_consulta(motor, social)) == _firma(_consulta(motor, None))


def test_beta_uno_solo_cuentan_los_amigos(motor: MotorRecomendacion) -> None:
    res = _consulta(motor, _social(motor, 1.0, ana_m=POST_ROCK_A))
    grafo = res.perfil.grafo()
    assert np.all(grafo.propio == 0)
    np.testing.assert_allclose(grafo.total, grafo.social)
    amigo = motor.perfil([EntradaPerfil(n, 3) for n in POST_ROCK_A])
    esperado = motor.columnas(list(amigo.indices)) @ np.asarray(amigo.pesos)
    np.testing.assert_allclose(grafo.total, esperado, atol=1e-15)
    assert res.traza is not None
    for i in res.traza.puntajes:
        assert res.traza.aportes[i]["s_grafo"] == pytest.approx(0, abs=1e-15)


def test_vector_mezclado_es_la_combinacion_lineal(motor: MotorRecomendacion) -> None:
    beta = 0.3
    res = _consulta(motor, _social(motor, beta, ana_m=POST_ROCK_A, juanp=POST_ROCK_B))
    grafo = res.perfil.grafo()
    yo = res.perfil.perfil
    propio = motor.columnas(list(yo.indices)) @ np.asarray(yo.pesos)
    amigos = [motor.perfil([EntradaPerfil(n, 3) for n in a]) for a in (POST_ROCK_A, POST_ROCK_B)]
    de_amigos = sum(motor.columnas(list(a.indices)) @ np.asarray(a.pesos) for a in amigos) / 2
    np.testing.assert_allclose(grafo.total, (1 - beta) * propio + beta * de_amigos, atol=1e-14)
    np.testing.assert_allclose(grafo.social, beta * de_amigos, atol=1e-14)


def test_no_recalcula_ppr_para_semillas_existentes(indice: IndiceCatalogo) -> None:
    motor = MotorRecomendacion(indice, ConfigMotor())
    _consulta(motor, None)
    assert motor.columnas_calculadas == len(SHOEGAZE)
    social = _social(motor, 0.25, ana_m=POST_ROCK_A, juanp=POST_ROCK_B)
    res = _consulta(motor, social)
    nuevas = set(POST_ROCK_A + POST_ROCK_B) - set(SHOEGAZE)  # Low es semilla del usuario
    assert motor.columnas_calculadas == len(SHOEGAZE) + len(nuevas)
    antes = motor.columnas_calculadas
    _consulta(motor, social)
    cf = Contrafactuales(motor, res, None, None, social)
    cf.ejecuciones()
    cf.ejecuciones_sociales()
    assert motor.columnas_calculadas == antes  # repetir y contrafactuales: todo del caché


def test_columna_cacheada_es_identica_a_una_recalculada(indice: IndiceCatalogo) -> None:
    motor = MotorRecomendacion(indice, ConfigMotor())
    lote = motor.columnas([2, 12, 16])
    sola = MotorRecomendacion(indice, ConfigMotor()).columnas([16])
    np.testing.assert_array_equal(lote[:, 2], sola[:, 0])
    np.testing.assert_array_equal(motor.columnas([16])[:, 0], sola[:, 0])


def test_cache_de_columnas_acotado(indice: IndiceCatalogo) -> None:
    motor = MotorRecomendacion(indice, ConfigMotor(max_columnas_cache=2))
    motor.columnas([1, 2, 3])
    assert motor.columnas_calculadas == 3
    motor.columnas([3])
    assert motor.columnas_calculadas == 3
    motor.columnas([1])
    assert motor.columnas_calculadas == 4  # 1 había salido del caché


# ------------------------------------------------------------------ aporte social exacto
def test_s_grafo_mas_s_social_es_el_termino_de_grafo_y_todo_suma_el_puntaje(
    motor: MotorRecomendacion,
) -> None:
    social = _social(motor, 0.4, ana_m=POST_ROCK_A, juanp=POST_ROCK_B)
    res = _consulta(motor, social)
    traza = res.traza
    assert traza is not None
    crudos = {i: t["s_grafo"] for i, t in traza.terminos_crudos.items()}
    lo, hi = min(crudos.values()), max(crudos.values())
    b = res.perfil.pesos.b
    for i, aportes in traza.aportes.items():
        termino = b * (crudos[i] - lo) / (hi - lo)
        assert aportes["s_grafo"] + aportes["s_social"] == pytest.approx(termino, abs=1e-12)
        assert sum(aportes.values()) == pytest.approx(traza.puntajes[i], abs=1e-12)
        partes = traza.aportes_amigos.get(i, {})
        assert sum(partes.values()) == pytest.approx(aportes["s_social"], abs=1e-12)
    assert any(a["s_social"] > 0 for a in traza.aportes.values())
    for r in res.recomendaciones:
        assert sum(r.aportes.values()) == pytest.approx(r.puntaje)


def test_explicacion_nombra_a_los_amigos_con_su_porcentaje(motor: MotorRecomendacion) -> None:
    res = _consulta(motor, _social(motor, 0.5, ana_m=POST_ROCK_A, juanp=POST_ROCK_B))
    con_amigos = [r for r in res.recomendaciones if r.explicacion and r.explicacion.amigos_origen]
    assert con_amigos
    for r in con_amigos:
        assert r.explicacion is not None
        pct = round(100 * r.aportes["s_social"] / r.puntaje)
        assert f"El {pct} % viene de lo que escuchan" in r.explicacion.texto
        assert set(r.explicacion.amigos_origen) <= {"ana_m", "juanp"}


def test_los_artistas_de_los_amigos_se_pueden_recomendar(motor: MotorRecomendacion) -> None:
    res = _consulta(motor, _social(motor, 0.6, ana_m=POST_ROCK_A, juanp=POST_ROCK_B))
    nombres = {r.nombre for r in res.recomendaciones}
    assert nombres & (set(POST_ROCK_A + POST_ROCK_B) - set(SHOEGAZE))
    assert not nombres & set(SHOEGAZE)  # solo se excluye lo que puso el usuario


# ------------------------------------------------------------------ R7
def _r7(res: ResultadoConsulta) -> list[str]:
    return [
        p
        for p in res.perfil.motor.redactar(res.perfil.motor.disparos, res.perfil.contexto)
        if p.startswith("R7:")
    ]


def test_r7_se_dispara_con_dos_amigos_que_escuchan_un_genero_nuevo(
    motor: MotorRecomendacion,
) -> None:
    res = _consulta(motor, _social(motor, 0.25, ana_m=POST_ROCK_A, juanp=POST_ROCK_B))
    pasos = _r7(res)
    assert any(
        p.startswith("R7: ana_m y juanp escuchan post-rock → exploré post-rock") for p in pasos
    )
    assert res.perfil.candidatos_r2()  # R7 agrega candidatos como R2
    con_r7 = [
        r
        for r in res.recomendaciones
        if r.explicacion and any(c.startswith("R7:") for c in r.explicacion.cadena_inferencia)
    ]
    assert con_r7
    for r in con_r7:
        assert r.explicacion is not None
        assert "Tus amigos ana_m y juanp escuchan post-rock" in r.explicacion.texto


def test_r7_no_se_dispara_con_un_solo_amigo(motor: MotorRecomendacion) -> None:
    res = _consulta(motor, _social(motor, 0.25, ana_m=POST_ROCK_A, otro=METAL))
    assert not any("post-rock" in p for p in _r7(res))


def test_r7_no_se_dispara_si_el_genero_ya_esta_en_el_perfil(motor: MotorRecomendacion) -> None:
    perfil = motor.perfil([EntradaPerfil(n, 3) for n in POST_ROCK_A])
    res = motor.recomendar(perfil, social=_social(motor, 0.25, a=POST_ROCK_A, b=POST_ROCK_B))
    assert not any("post-rock" in p for p in _r7(res))


def test_ablacion_sin_r7(motor: MotorRecomendacion) -> None:
    social = _social(motor, 0.25, ana_m=POST_ROCK_A, juanp=POST_ROCK_B)
    res = _consulta(motor, social, opciones=OpcionesMotor(sin_reglas=frozenset({"R7"})))
    assert _r7(res) == []
    assert "R7" not in res.reglas_disparadas()


# ------------------------------------------------------------------ contrafactuales sociales
def test_contrafactuales_sociales_coinciden_con_la_ejecucion_real(
    motor: MotorRecomendacion,
) -> None:
    social = _social(motor, 0.5, ana_m=POST_ROCK_A, juanp=POST_ROCK_B)
    res = _consulta(motor, social, explicar=False)
    cf = Contrafactuales(motor, res, None, None, social)
    sin_todos = _consulta(motor, None, explicar=False)
    sin_ana = _consulta(motor, social.sin("ana_m"), explicar=False)
    for r in res.recomendaciones:
        efectos = {(e.tipo, e.artista_usuario): e for e in cf.efectos(r.indice)}
        todos = efectos[("amigos", TODOS_TUS_AMIGOS)]
        assert todos.posicion_sin_artista == sin_todos.posicion(r.indice)
        assert efectos[("amigo", "ana_m")].posicion_sin_artista == sin_ana.posicion(r.indice)
        assert {t for t, _ in efectos} == {"artista", "amigo", "amigos"}
    assert any(
        e.impacto != 0
        for r in res.recomendaciones
        for e in cf.efectos(r.indice)
        if e.tipo != "artista"
    )


def test_sin_amigos_activos_no_hay_contrafactuales_sociales(motor: MotorRecomendacion) -> None:
    res = _consulta(motor, None)
    cf = Contrafactuales(motor, res, None, None, None)
    assert cf.ejecuciones_sociales() == {}
    assert {e.tipo for e in cf.efectos(res.recomendaciones[0].indice)} == {"artista"}


def test_por_que_no_conectado_ni_por_amigos(indice: IndiceCatalogo) -> None:
    motor = MotorRecomendacion(indice, ConfigMotor(top_k_ppr=5))
    social = _social(motor, 0.25, ana_m=POST_ROCK_A)
    con = _consulta(motor, social)
    sin = _consulta(motor, None)
    assert diagnosticar(motor, sin, SHOEGAZE, "Miles Davis").motivo == "no_conectado"
    d = diagnosticar(motor, con, SHOEGAZE, "Miles Davis")
    assert d.motivo == "no_conectado_ni_por_amigos"
    assert "amigos" in d.explicacion


# ------------------------------------------------------------------ servicio: consentimiento
@pytest.fixture
def servicio(tmp_path: Path, catalogo: Catalogo, indice: IndiceCatalogo) -> ServicioRecomendacion:
    repo = RepositorioSQLite(tmp_path / "s.db")
    guardar_catalogo(repo, catalogo)
    perfiles = ServicioPerfiles(repo)
    entradas = {
        "yo_mismo": (SHOEGAZE, False),
        "ana_m": (POST_ROCK_A, True),
        "juanp": (POST_ROCK_B, True),
        "luis_priv": (METAL, False),
    }
    for apodo, (nombres, comparte) in entradas.items():
        perfiles.guardar_perfil(apodo, tuple(EntradaArtista(n, 3) for n in nombres), comparte)
    for amigo in ("ana_m", "juanp", "luis_priv"):
        perfiles.agregar_amigo("yo_mismo", amigo)
    return ServicioRecomendacion(MotorRecomendacion(indice, ConfigMotor()), repo, perfiles)


def _sol(apodo: str | None = "yo_mismo", beta: float | None = None) -> SolicitudRecomendacion:
    p = None if beta is None else ParametrosMotor(0.3, 0.35, 0.15, 0.2, 0.7, beta)
    return SolicitudRecomendacion(tuple(EntradaArtista(n, 3) for n in SHOEGAZE), p, apodo)


def test_amigo_sin_consentimiento_nunca_se_usa_ni_se_nombra(
    servicio: ServicioRecomendacion,
) -> None:
    resp = servicio.recomendar(_sol())
    textos = " ".join(
        r.explicacion + " ".join(r.cadena_inferencia) + " ".join(r.amigos_origen)
        for r in resp.recomendaciones
    )
    assert "luis_priv" not in textos
    assert any(r.amigos_origen for r in resp.recomendaciones)
    social = servicio.contexto_social(_sol())
    assert social is not None
    assert {a.apodo for a in social.amigos} == {"ana_m", "juanp"}
    for r in resp.recomendaciones[:3]:
        cf = servicio.contrafactual(_sol(), r.artista_id)
        assert "luis_priv" not in {e.artista_usuario for e in cf.efectos}
        assert "luis_priv" not in cf.resumen


def test_quitar_el_consentimiento_equivale_a_no_tener_ese_amigo(
    servicio: ServicioRecomendacion,
) -> None:
    assert servicio.perfiles is not None
    antes = servicio.recomendar(_sol())
    servicio.perfiles.guardar_perfil(
        "luis_priv", tuple(EntradaArtista(n, 3) for n in METAL), comparte_gustos=False
    )
    servicio.perfiles.quitar_amigo("yo_mismo", "luis_priv")
    assert servicio.recomendar(_sol()).recomendaciones == antes.recomendaciones


def test_r7_ignora_amigos_sin_consentimiento(servicio: ServicioRecomendacion) -> None:
    assert servicio.perfiles is not None
    servicio.perfiles.guardar_perfil(
        "juanp", tuple(EntradaArtista(n, 3) for n in POST_ROCK_B), comparte_gustos=False
    )
    resp = servicio.recomendar(_sol())
    assert not any(c.startswith("R7:") for r in resp.recomendaciones for c in r.cadena_inferencia)


def test_cache_se_invalida_si_cambia_el_consentimiento(servicio: ServicioRecomendacion) -> None:
    assert servicio.perfiles is not None
    con = servicio.recomendar(_sol())
    for apodo, nombres in (("ana_m", POST_ROCK_A), ("juanp", POST_ROCK_B)):
        servicio.perfiles.guardar_perfil(
            apodo, tuple(EntradaArtista(n, 3) for n in nombres), comparte_gustos=False
        )
    sin = servicio.recomendar(_sol())
    assert all(r.aportes["s_social"] == 0 for r in sin.recomendaciones)
    assert con.recomendaciones != sin.recomendaciones


def test_servicio_con_beta_cero_y_sin_apodo_dan_lo_mismo(servicio: ServicioRecomendacion) -> None:
    sin_apodo = servicio.recomendar(_sol(None, 0.25))
    beta_cero = servicio.recomendar(_sol("yo_mismo", 0.0))
    assert [dataclasses.astuple(r) for r in beta_cero.recomendaciones] == [
        dataclasses.astuple(r) for r in sin_apodo.recomendaciones
    ]


def test_servicio_apodo_inexistente_o_sin_perfiles(
    servicio: ServicioRecomendacion, indice: IndiceCatalogo, tmp_path: Path
) -> None:
    with pytest.raises(ErrorPerfil, match="No existe"):
        servicio.recomendar(_sol("nadie"))
    sin_perfiles = ServicioRecomendacion(
        MotorRecomendacion(indice, ConfigMotor()), RepositorioSQLite(tmp_path / "x.db")
    )
    with pytest.raises(ErrorPerfil, match="no está disponible"):
        sin_perfiles.recomendar(_sol())


def test_por_que_no_y_contrafactual_del_servicio_con_amigos(
    servicio: ServicioRecomendacion,
) -> None:
    resp = servicio.recomendar(_sol())
    cf = servicio.contrafactual(_sol(), resp.recomendaciones[0].artista_id)
    assert {e.tipo for e in cf.efectos} == {"artista", "amigo", "amigos"}
    assert "todos tus amigos" in {e.artista_usuario for e in cf.efectos}
    assert servicio.parametros_por_defecto().beta == pytest.approx(ConfigMotor().beta)
