"""El contrato y los servicios falsos que usa el frontend."""

import inspect
from dataclasses import replace
from typing import get_args

import pytest

from sonarmatch import bootstrap
from sonarmatch.application.validation import normalizar_nombre, validar_solicitud
from sonarmatch.ports import inbound
from sonarmatch.ports.inbound import (
    EntradaArtista,
    ErrorEntradaInvalida,
    Estrategia,
    MotivoNo,
    ParametrosMotor,
    SolicitudRecomendacion,
)
from sonarmatch.testing.fakes import (
    CATALOGO_FALSO,
    ENTRADA_FALSA,
    POR_QUE_NO_FALSO,
    crear_servicios_falsos,
)


def _solicitud(n: int = 6, parametros: ParametrosMotor | None = None) -> SolicitudRecomendacion:
    return SolicitudRecomendacion(
        tuple(EntradaArtista(nombre, 1 + i % 5) for i, nombre in enumerate(ENTRADA_FALSA[:n])),
        parametros,
    )


PROTOCOLOS = {
    "recomendar": inbound.RecomendarArtistas,
    "catalogo": inbound.ConsultarCatalogo,
    "explicar": inbound.ExplicarRecomendacion,
    "feedback": inbound.RegistrarFeedback,
}


@pytest.mark.parametrize(("campo", "protocolo"), PROTOCOLOS.items())
def test_falsos_cumplen_los_cuatro_protocolos(campo: str, protocolo: type) -> None:
    servicio = getattr(crear_servicios_falsos(), campo)
    metodos = [m for m in vars(protocolo) if not m.startswith("_")]
    assert metodos
    for metodo in metodos:
        esperado = inspect.signature(getattr(protocolo, metodo))
        real = inspect.signature(getattr(servicio, metodo))
        assert list(real.parameters) == list(esperado.parameters)[1:]


def test_recomendar_devuelve_diez_con_aportes_que_suman_el_puntaje() -> None:
    resp = crear_servicios_falsos().recomendar.recomendar(_solicitud())
    assert len(resp.recomendaciones) == 10
    for r in resp.recomendaciones:
        assert set(r.aportes) == {"s_tags", "s_grafo", "p_nov", "s_onto"}
        assert sum(r.aportes.values()) == pytest.approx(r.puntaje)
        assert r.cadena_inferencia
        assert set(r.artistas_origen) <= set(ENTRADA_FALSA)
    assert {r.estrategia for r in resp.recomendaciones} == set(get_args(Estrategia))
    assert sum(resp.estrategias_usadas.values()) == 10
    assert resp.artistas_no_encontrados == ()


def test_recomendar_es_determinista_y_respeta_parametros() -> None:
    s = crear_servicios_falsos()
    assert s.recomendar.recomendar(_solicitud()) == s.recomendar.recomendar(_solicitud())
    solo_tags = ParametrosMotor(a=1, b=0, c=0, d=0, lambda_mmr=0.5)
    r = s.recomendar.recomendar(_solicitud(parametros=solo_tags)).recomendaciones[0]
    assert r.aportes["s_tags"] == pytest.approx(r.puntaje)
    assert r.aportes["s_grafo"] == 0


def test_reporta_artistas_no_encontrados() -> None:
    sol = _solicitud(5)
    sol = replace(sol, artistas=(*sol.artistas, EntradaArtista("Artista Inexistente", 3)))
    resp = crear_servicios_falsos().recomendar.recomendar(sol)
    assert resp.artistas_no_encontrados == ("Artista Inexistente",)


@pytest.mark.parametrize("motivo", get_args(MotivoNo))
def test_por_que_no_cubre_cada_motivo(motivo: str) -> None:
    nombres = {v: k for k, v in POR_QUE_NO_FALSO.items()}
    nombres.update({"ya_en_entrada": ENTRADA_FALSA[0], "no_en_catalogo": "Nadie Conocido"})
    nombres.setdefault("puntaje_insuficiente", "Deftones")
    dto = crear_servicios_falsos().explicar.por_que_no(_solicitud(), nombres[motivo])
    assert dto.motivo == motivo
    assert dto.explicacion
    fue_candidato = motivo in ("puntaje_insuficiente", "desplazado_por_diversidad")
    assert (dto.posicion_previa_mmr is not None) == fue_candidato
    assert bool(dto.aportes) == fue_candidato
    assert bool(dto.cadena_regla) == (motivo == "descartado_por_regla")
    assert (dto.similar_a is not None) == (motivo == "desplazado_por_diversidad")


def test_contrafactual_ordena_por_impacto() -> None:
    s = crear_servicios_falsos()
    rec = s.recomendar.recomendar(_solicitud()).recomendaciones[1]
    cf = s.explicar.contrafactual(_solicitud(), rec.artista_id)
    assert cf.nombre == rec.nombre
    assert len(cf.efectos) == 6
    assert cf.efectos[0].posicion_sin_artista is None
    assert all(e.posicion_original == 2 for e in cf.efectos)
    assert cf.efectos[0].artista_usuario in cf.resumen


def test_feedback_y_catalogo() -> None:
    s = crear_servicios_falsos()
    s.feedback.registrar("sesion", 1000, 1, "grafo")
    assert s.feedback.registros == [("sesion", 1000, 1, "grafo")]  # type: ignore[attr-defined]  # atributo propio del doble
    assert s.catalogo.nombres_artistas() == sorted(CATALOGO_FALSO)
    p = s.catalogo.parametros_por_defecto()
    assert p.a + p.b + p.c + p.d == pytest.approx(1)


@pytest.mark.parametrize(
    "solicitud",
    [
        _solicitud(4),
        _solicitud(21) if len(ENTRADA_FALSA) >= 21 else _solicitud(4),
        SolicitudRecomendacion((*_solicitud(5).artistas, EntradaArtista("beach  HOUSE", 2))),
        SolicitudRecomendacion((*_solicitud(5).artistas[:4], EntradaArtista("X", 6))),
        SolicitudRecomendacion((*_solicitud(5).artistas[:4], EntradaArtista("X", 0.5))),
        SolicitudRecomendacion((*_solicitud(5).artistas[:4], EntradaArtista("  ", 3))),
        _solicitud(5, ParametrosMotor(a=1.5, b=0, c=0, d=0, lambda_mmr=0.5)),
        _solicitud(5, ParametrosMotor(a=0, b=0, c=0, d=0, lambda_mmr=0.5)),
    ],
    ids=["4", "21", "duplicado", "peso>5", "peso<1", "vacio", "param>1", "pesos_cero"],
)
def test_entrada_invalida(solicitud: SolicitudRecomendacion) -> None:
    with pytest.raises(ErrorEntradaInvalida):
        crear_servicios_falsos().recomendar.recomendar(solicitud)


@pytest.mark.parametrize("n", [5, 20])
def test_limites_validos(n: int) -> None:
    validar_solicitud(_solicitud(n))


def test_normalizar_nombre() -> None:
    assert normalizar_nombre("  Beach   HOUSE ") == "beach house"


def test_bootstrap_sin_base_explica_como_ingerir(tmp_path: object) -> None:
    with pytest.raises(FileNotFoundError, match="ingest"):
        bootstrap.crear_servicios(str(tmp_path) + "/no_existe.db")
