"""Contrato social: servicio de perfiles y amistades, y comportamiento social de los fakes."""

import dataclasses

import pytest

from sonarmatch.application.perfiles import PerfilesNoDisponibles, ServicioPerfiles
from sonarmatch.application.validation import normalizar_apodo
from sonarmatch.bootstrap import Servicios
from sonarmatch.ports.inbound import (
    AmigoDTO,
    EntradaArtista,
    ErrorEntradaInvalida,
    ErrorPerfil,
    ParametrosMotor,
    SolicitudRecomendacion,
)
from sonarmatch.testing.fakes import (
    ENTRADA_FALSA,
    PARAMETROS_FALSOS,
    RepositorioPerfilesMemoria,
    crear_servicios_falsos,
)

ARTISTAS = tuple(EntradaArtista(n, 3) for n in ENTRADA_FALSA[:5])


def _servicio() -> ServicioPerfiles:
    return ServicioPerfiles(RepositorioPerfilesMemoria())


def _sol(apodo: str | None, beta: float | None = None) -> SolicitudRecomendacion:
    p = None if beta is None else dataclasses.replace(PARAMETROS_FALSOS, beta=beta)
    return SolicitudRecomendacion(ARTISTAS, p, apodo)


# ------------------------------------------------------------------ servicio de perfiles
def test_guardar_y_obtener_normaliza_el_apodo_y_respeta_el_consentimiento() -> None:
    s = _servicio()
    guardado = s.guardar_perfil("  Ana_M ", ARTISTAS, comparte_gustos=False)
    assert guardado.apodo == "ana_m"
    leido = s.obtener_perfil("ANA_M")
    assert leido == guardado
    assert leido.comparte_gustos is False
    assert [a.nombre for a in leido.artistas] == list(ENTRADA_FALSA[:5])


def test_guardar_de_nuevo_reemplaza_sin_duplicar() -> None:
    s = _servicio()
    s.guardar_perfil("ana_m", ARTISTAS, comparte_gustos=False)
    otros = tuple(EntradaArtista(n, 5) for n in ENTRADA_FALSA[5:11])
    s.guardar_perfil("Ana_M", otros, comparte_gustos=True)
    perfil = s.obtener_perfil("ana_m")
    assert perfil.comparte_gustos is True
    assert len(perfil.artistas) == len(otros)
    assert isinstance(s.repo, RepositorioPerfilesMemoria)
    assert list(s.repo.perfiles) == ["ana_m"]


@pytest.mark.parametrize("apodo", ["", "ab", "con espacio", "ñandú", "x" * 31])
def test_apodo_invalido_lanza_error_perfil(apodo: str) -> None:
    with pytest.raises(ErrorPerfil, match="apodo"):
        _servicio().guardar_perfil(apodo, ARTISTAS, comparte_gustos=True)


def test_artistas_invalidos_en_el_perfil_lanzan_error_perfil() -> None:
    with pytest.raises(ErrorPerfil, match="entre 5 y 20"):
        _servicio().guardar_perfil("ana_m", ARTISTAS[:4], comparte_gustos=True)


def test_error_perfil_es_un_error_de_entrada() -> None:
    assert issubclass(ErrorPerfil, ErrorEntradaInvalida)


def test_amistad_bidireccional_sin_duplicados_ni_autoamistad() -> None:
    s = _servicio()
    for apodo, comparte in (("ana_m", True), ("juanp", False), ("luz", True)):
        s.guardar_perfil(apodo, ARTISTAS, comparte_gustos=comparte)
    s.agregar_amigo("ana_m", "juanp")
    s.agregar_amigo("luz", "ana_m")
    assert s.listar_amigos("ana_m") == (AmigoDTO("juanp", False), AmigoDTO("luz", True))
    assert s.listar_amigos("juanp") == (AmigoDTO("ana_m", True),)
    with pytest.raises(ErrorPerfil, match="ya está"):
        s.agregar_amigo("juanp", "ANA_M")
    with pytest.raises(ErrorPerfil, match="ti mismo"):
        s.agregar_amigo("ana_m", " Ana_m ")
    s.quitar_amigo("juanp", "ana_m")
    assert s.listar_amigos("ana_m") == (AmigoDTO("luz", True),)
    with pytest.raises(ErrorPerfil, match="no está"):
        s.quitar_amigo("ana_m", "juanp")


def test_amigos_inexistentes_lanzan_error_perfil() -> None:
    s = _servicio()
    s.guardar_perfil("ana_m", ARTISTAS, comparte_gustos=True)
    with pytest.raises(ErrorPerfil, match="No existe"):
        s.agregar_amigo("ana_m", "nadie")
    with pytest.raises(ErrorPerfil, match="No existe"):
        s.listar_amigos("nadie")
    with pytest.raises(ErrorPerfil, match="No existe"):
        s.obtener_perfil("nadie")


def test_solo_cuentan_los_amigos_que_comparten() -> None:
    s = _servicio()
    for apodo, comparte in (("yo_mismo", False), ("ana_m", True), ("juanp", False)):
        s.guardar_perfil(apodo, ARTISTAS, comparte_gustos=comparte)
    s.agregar_amigo("yo_mismo", "ana_m")
    s.agregar_amigo("yo_mismo", "juanp")
    assert [p.apodo for p in s.amigos_que_comparten("yo_mismo")] == ["ana_m"]


def test_servicios_sin_perfiles_usa_implementacion_que_avisa() -> None:
    base = crear_servicios_falsos()
    s = Servicios(base.recomendar, base.catalogo, base.explicar, base.feedback)
    assert isinstance(s.perfiles, PerfilesNoDisponibles)
    llamadas = (
        lambda: s.perfiles.guardar_perfil("ana_m", ARTISTAS, True),
        lambda: s.perfiles.obtener_perfil("ana_m"),
        lambda: s.perfiles.agregar_amigo("ana_m", "juanp"),
        lambda: s.perfiles.quitar_amigo("ana_m", "juanp"),
        lambda: s.perfiles.listar_amigos("ana_m"),
    )
    for llamada in llamadas:
        with pytest.raises(ErrorPerfil, match="no está disponible"):
            llamada()


def test_normalizar_apodo() -> None:
    assert normalizar_apodo(" Juan.P-2 ") == "juan.p-2"


# ------------------------------------------------------------------ fakes con dimensión social
def test_fakes_traen_amigos_de_ejemplo_con_y_sin_consentimiento() -> None:
    amigos = crear_servicios_falsos().perfiles.listar_amigos("demo")
    assert {(a.apodo, a.comparte_gustos) for a in amigos} == {
        ("ana_m", True),
        ("juanp", True),
        ("luis_priv", False),
    }
    assert crear_servicios_falsos().perfiles.listar_amigos("solo") == ()


def test_con_apodo_hay_aporte_social_que_suma_el_puntaje_y_solo_nombra_amigos_que_comparten() -> (
    None
):
    resp = crear_servicios_falsos().recomendar.recomendar(_sol("demo"))
    sociales = [r for r in resp.recomendaciones if r.aportes["s_social"] > 0]
    assert sociales
    for r in resp.recomendaciones:
        assert sum(r.aportes.values()) == pytest.approx(r.puntaje)
        assert "luis_priv" not in r.explicacion
        assert "luis_priv" not in r.amigos_origen
        assert "luis_priv" not in " ".join(r.cadena_inferencia)
    for r in sociales:
        assert set(r.amigos_origen) <= {"ana_m", "juanp"}
        assert "% viene de lo que escuchan" in r.explicacion
    assert any(c.startswith("R7:") for c in resp.recomendaciones[0].cadena_inferencia)


@pytest.mark.parametrize(("apodo", "beta"), [("demo", 0.0), ("solo", 0.25), (None, 0.25)])
def test_sin_amigos_activos_no_hay_aporte_social(apodo: str | None, beta: float) -> None:
    resp = crear_servicios_falsos().recomendar.recomendar(_sol(apodo, beta))
    assert all(r.aportes["s_social"] == 0 for r in resp.recomendaciones)
    assert all(r.amigos_origen == () for r in resp.recomendaciones)


def test_apodo_inexistente_en_la_solicitud_lanza_error_perfil() -> None:
    with pytest.raises(ErrorPerfil, match="No existe"):
        crear_servicios_falsos().recomendar.recomendar(_sol("nadie"))


def test_beta_fuera_de_rango_es_invalida() -> None:
    p = ParametrosMotor(0.3, 0.3, 0.2, 0.2, 0.7, beta=1.5)
    with pytest.raises(ErrorEntradaInvalida, match="beta"):
        crear_servicios_falsos().recomendar.recomendar(SolicitudRecomendacion(ARTISTAS, p))


def test_contrafactual_con_amigos_incluye_todos_y_cada_amigo() -> None:
    dto = crear_servicios_falsos().explicar.contrafactual(_sol("demo"), 1000)
    tipos = {(e.tipo, e.artista_usuario) for e in dto.efectos if e.tipo != "artista"}
    assert tipos == {("amigos", "todos tus amigos"), ("amigo", "ana_m"), ("amigo", "juanp")}
    sin_amigos = crear_servicios_falsos().explicar.contrafactual(_sol(None), 1000)
    assert {e.tipo for e in sin_amigos.efectos} == {"artista"}


def test_por_que_no_distingue_no_conectado_ni_por_amigos() -> None:
    e = crear_servicios_falsos().explicar
    assert e.por_que_no(_sol(None), "Sonic Youth").motivo == "no_conectado"
    assert e.por_que_no(_sol("demo"), "Sonic Youth").motivo == "no_conectado_ni_por_amigos"
