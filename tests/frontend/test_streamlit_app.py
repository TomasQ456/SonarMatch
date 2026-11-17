"""Pruebas de integración de la interfaz Streamlit con AppTest."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, get_args

import pytest
from streamlit.testing.v1 import AppTest

from sonarmatch.adapters.inbound import streamlit_app
from sonarmatch.bootstrap import Servicios
from sonarmatch.ports.inbound import (
    ContrafactualDTO,
    ErrorEntradaInvalida,
    Estrategia,
    MotivoNo,
    PorQueNoDTO,
    RespuestaRecomendacion,
    SolicitudRecomendacion,
)
from sonarmatch.testing.fakes import (
    ENTRADA_FALSA,
    PARAMETROS_FALSOS,
    POR_QUE_NO_FALSO,
    RECOMENDACIONES_FALSAS,
    CatalogoFalso,
    ExplicadorFalso,
    FeedbackFalso,
    RecomendadorFalso,
    crear_servicios_falsos,
)

if TYPE_CHECKING:
    from _pytest.logging import LogCaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

RUTA_APP = Path(streamlit_app.__file__).resolve()
SCRIPT_EJECUTAR_APP = (
    "from sonarmatch.adapters.inbound.streamlit_app import ejecutar_app\nejecutar_app()\n"
)


def _crear_apptest(servicios: Servicios | None = None) -> tuple[AppTest, Servicios]:
    serv = servicios or crear_servicios_falsos()
    at = AppTest.from_string(SCRIPT_EJECUTAR_APP, default_timeout=10)
    at.session_state["_servicios"] = serv
    at.run()
    return at, serv


def _recomendar_base(n: int = 6, servicios: Servicios | None = None) -> tuple[AppTest, Servicios]:
    at, serv = _crear_apptest(servicios)
    at.multiselect(key="artistas_seleccionados").set_value(list(ENTRADA_FALSA[:n])).run()
    at.button(key="btn_recomendar").click().run()
    return at, serv


def test_carga_inicial_sin_errores() -> None:
    at, _ = _crear_apptest()
    assert not at.exception
    assert any("SonarMatch" in t.value for t in at.title)
    assert any("0 de 5–20" in m.value for m in at.markdown)
    assert at.button(key="btn_recomendar").disabled is True

    assert at.slider(key="param_a").value == pytest.approx(PARAMETROS_FALSOS.a)
    assert at.slider(key="param_b").value == pytest.approx(PARAMETROS_FALSOS.b)
    assert at.slider(key="param_c").value == pytest.approx(PARAMETROS_FALSOS.c)
    assert at.slider(key="param_d").value == pytest.approx(PARAMETROS_FALSOS.d)
    assert at.slider(key="param_lambda").value == pytest.approx(PARAMETROS_FALSOS.lambda_mmr)


@pytest.mark.parametrize(
    ("cantidad", "debe_deshabilitar"),
    [
        (0, True),
        (4, True),
        (5, False),
        (12, False),
        (20, False),
        (21, True),
    ],
)
def test_boton_recomendar_segun_rango_de_artistas(cantidad: int, debe_deshabilitar: bool) -> None:
    at, _ = _crear_apptest()
    seleccion = list(ENTRADA_FALSA[:cantidad])
    at.multiselect(key="artistas_seleccionados").set_value(seleccion).run()
    assert not at.exception
    assert any(f"{cantidad} de 5–20" in m.value for m in at.markdown)
    assert at.button(key="btn_recomendar").disabled is debe_deshabilitar


def test_flujo_completo_recomendacion_y_persistencia_estado() -> None:
    at, serv = _crear_apptest()
    seleccion = list(ENTRADA_FALSA[:6])
    at.multiselect(key="artistas_seleccionados").set_value(seleccion).run()
    at.slider(key=f"peso_{seleccion[0]}").set_value(4.5).run()

    at.button(key="btn_recomendar").click().run()
    assert not at.exception

    recomendador = serv.recomendar
    assert isinstance(recomendador, RecomendadorFalso)
    assert len(recomendador.llamadas) == 1
    solicitud = recomendador.llamadas[0]
    assert solicitud.parametros is None
    assert len(solicitud.artistas) == 6
    assert solicitud.artistas[0].nombre == seleccion[0]
    assert solicitud.artistas[0].peso == pytest.approx(4.5)

    textos_md = "\n".join(m.value for m in at.markdown)
    textos_cap = "\n".join(c.value for c in at.caption)

    assert "123.4 ms" in textos_md
    assert "Grafo (Principal): 6" in textos_md
    assert "Contenido (Respaldo): 2" in textos_md
    assert "Popularidad (Respaldo): 2" in textos_md
    assert "`Principal`" in textos_md
    assert "`Respaldo`" in textos_md

    for idx, (nombre, _, _) in enumerate(RECOMENDACIONES_FALSAS, start=1):
        assert f"#{idx} · {nombre}" in textos_md

    assert "412 mil" in textos_cap
    assert "2,1 M" in textos_cap

    # Mover un slider sin presionar Recomendar no recalcula ni pierde resultados
    at.slider(key="param_a").set_value(0.6).run()
    assert len(recomendador.llamadas) == 1
    assert "Wild Nothing" in "\n".join(m.value for m in at.markdown)


def test_parametros_personalizados_slider_d_y_restablecer() -> None:
    at, serv = _crear_apptest()
    recomendador = serv.recomendar
    assert isinstance(recomendador, RecomendadorFalso)

    at.multiselect(key="artistas_seleccionados").set_value(list(ENTRADA_FALSA[:5])).run()
    at.slider(key="param_d").set_value(0.55).run()
    at.button(key="btn_recomendar").click().run()

    assert len(recomendador.llamadas) == 1
    param_enviado = recomendador.llamadas[0].parametros
    assert param_enviado is not None
    assert param_enviado.d == pytest.approx(0.55)
    assert param_enviado.a == pytest.approx(PARAMETROS_FALSOS.a)

    # Restablecer parámetros devuelve los sliders al valor por defecto y envía None
    at.button(key="btn_restablecer_parametros").click().run()
    assert at.slider(key="param_d").value == pytest.approx(PARAMETROS_FALSOS.d)

    at.button(key="btn_recomendar").click().run()
    assert len(recomendador.llamadas) == 2
    assert recomendador.llamadas[1].parametros is None


def test_cadena_inferencia_visible_en_expander() -> None:
    at, _ = _recomendar_base(5)
    assert len(at.expander) == 10
    textos_md = "\n".join(m.value for m in at.markdown)
    assert "Cadena de inferencia:" in textos_md
    assert "1. R1: escuchas shoegaze y slowcore" in textos_md
    assert "2. R2: afinidad(rock alternativo)" in textos_md
    assert "3. R3: la mediana de oyentes" in textos_md


def test_registro_feedback_y_deshabilitado_tras_votar() -> None:
    at, serv = _recomendar_base(5)
    feedback = serv.feedback
    recomendador = serv.recomendar
    assert isinstance(feedback, FeedbackFalso)
    assert isinstance(recomendador, RecomendadorFalso)

    assert at.button(key="voto_pos_1000").disabled is False
    assert at.button(key="voto_neg_1000").disabled is False

    at.button(key="voto_pos_1000").click().run()
    assert not at.exception
    assert len(feedback.registros) == 1
    sesion_id, artista_id, valoracion, estrategia = feedback.registros[0]
    assert isinstance(sesion_id, str)
    assert len(sesion_id) > 10
    assert artista_id == 1000
    assert valoracion == 1
    assert estrategia == "grafo"

    assert at.button(key="voto_pos_1000").disabled is True
    assert at.button(key="voto_neg_1000").disabled is True
    assert any("valoración fue registrada" in s.value for s in at.success)

    # Forzar segundo clic en la misma tarjeta (👎 tras 👍) no vuelve a registrar
    btn_neg_1000 = at.button(key="voto_neg_1000")
    btn_neg_1000.proto.disabled = False
    btn_neg_1000.click().run()
    assert not at.exception
    assert len(feedback.registros) == 1

    # Voto negativo en otra tarjeta (respaldo popularidad: id 1008)
    at.button(key="voto_neg_1008").click().run()
    assert len(feedback.registros) == 2
    assert feedback.registros[1] == (sesion_id, 1008, -1, "popularidad")
    assert at.button(key="voto_pos_1008").disabled is True
    assert at.button(key="voto_neg_1008").disabled is True

    # Votar no recalcula las recomendaciones
    assert len(recomendador.llamadas) == 1


def test_voto_doble_en_misma_tarjeta_no_registra_segundo_voto() -> None:
    at, serv = _recomendar_base(5)
    feedback = serv.feedback
    assert isinstance(feedback, FeedbackFalso)

    at.button(key="voto_pos_1000").click().run()
    assert len(feedback.registros) == 1

    btn_neg = at.button(key="voto_neg_1000")
    btn_neg.proto.disabled = False
    btn_neg.click().run()
    assert not at.exception
    assert len(feedback.registros) == 1
    assert feedback.registros[0][1:] == (1000, 1, "grafo")


def test_aviso_artistas_no_encontrados() -> None:
    at, _ = _crear_apptest()
    seleccion = [*ENTRADA_FALSA[:5], "Banda Imaginaria 99"]
    at.multiselect(key="artistas_seleccionados").set_value(seleccion).run()
    at.button(key="btn_recomendar").click().run()

    assert not at.exception
    assert len(at.warning) == 1
    assert "Banda Imaginaria 99" in at.warning[0].value


def test_contrafactual_bajo_demanda_y_cacheado() -> None:
    at, serv = _recomendar_base(5)
    explicador = serv.explicar
    assert isinstance(explicador, ExplicadorFalso)

    # No se llama al recomendar
    assert explicador.llamadas_contrafactual == []
    assert len(at.table) == 0

    # Se llama solo al presionar el botón de la tarjeta
    at.button(key="btn_contrafactual_1000").click().run()
    assert not at.exception
    assert explicador.llamadas_contrafactual == [1000]
    assert len(at.table) == 1
    texto_tabla = at.table[0].value.to_string()
    assert "fuera de la lista" in texto_tabla
    assert "Beach House" in texto_tabla
    assert any("Sin Beach House, Wild Nothing saldría de la lista" in m.value for m in at.markdown)

    # Al volver a presionar o interactuar, usa el caché en session_state sin rellamar al puerto
    at.button(key="btn_contrafactual_1000").click().run()
    assert explicador.llamadas_contrafactual == [1000]
    assert len(at.table) == 1


@pytest.mark.parametrize("motivo", get_args(MotivoNo))
def test_por_que_no_cubre_todos_los_motivos(motivo: str) -> None:
    at, serv = _recomendar_base(5)
    explicador = serv.explicar
    assert isinstance(explicador, ExplicadorFalso)

    nombres_por_motivo: dict[str, str] = {v: k for k, v in POR_QUE_NO_FALSO.items()}
    nombres_por_motivo["ya_en_entrada"] = ENTRADA_FALSA[0]
    nombres_por_motivo["no_en_catalogo"] = "Artista Fuera De Catalogo"
    nombres_por_motivo.setdefault("puntaje_insuficiente", "Deftones")

    nombre_consulta = nombres_por_motivo[motivo]
    sb = at.selectbox(key="select_por_que_no")

    # Los artistas ya recomendados no deben aparecer en las opciones del selectbox
    nombres_recomendados = {n for n, _, _ in RECOMENDACIONES_FALSAS}
    assert not nombres_recomendados.intersection(sb.options)

    if nombre_consulta not in sb.options:
        sb.options.append(nombre_consulta)
    sb.set_value(nombre_consulta).run()
    at.button(key="btn_por_que_no").click().run()

    assert not at.exception
    assert explicador.llamadas_por_que_no == [nombre_consulta]

    textos_md = "\n".join(m.value for m in at.markdown)
    assert f"Motivo ({motivo}):" in textos_md

    if motivo == "descartado_por_regla":
        assert "Regla que lo descartó:" in textos_md
        assert "R5:" in textos_md
    if motivo == "desplazado_por_diversidad":
        assert "Desplazado por similitud con:" in textos_md
        assert "Wild Nothing" in textos_md
    if motivo in ("puntaje_insuficiente", "desplazado_por_diversidad"):
        assert "Comparación de aportes frente al 10.° recomendado" in textos_md


@dataclass
class _RecomendadorError:
    error: Exception

    def recomendar(self, solicitud: SolicitudRecomendacion) -> RespuestaRecomendacion:
        raise self.error


@dataclass
class _ExplicadorError:
    error: Exception

    def contrafactual(self, solicitud: SolicitudRecomendacion, artista_id: int) -> ContrafactualDTO:
        raise self.error

    def por_que_no(self, solicitud: SolicitudRecomendacion, nombre_artista: str) -> PorQueNoDTO:
        raise self.error


@dataclass
class _FeedbackError:
    error: Exception

    def registrar(
        self, sesion_id: str, artista_id: int, valoracion: Literal[-1, 1], estrategia: Estrategia
    ) -> None:
        raise self.error


def test_manejo_error_entrada_invalida() -> None:
    msg = "La solicitud contiene artistas duplicados."
    serv_err = Servicios(
        recomendar=_RecomendadorError(ErrorEntradaInvalida(msg)),
        catalogo=CatalogoFalso(),
        explicar=ExplicadorFalso(),
        feedback=FeedbackFalso(),
    )
    at, _ = _recomendar_base(5, servicios=serv_err)
    assert not at.exception
    assert any(msg in e.value for e in at.error)

    # También en contrafactual, por_que_no y feedback cuando ya hay resultados
    serv_parcial = Servicios(
        recomendar=RecomendadorFalso(),
        catalogo=CatalogoFalso(),
        explicar=_ExplicadorError(ErrorEntradaInvalida("Error validación explicar")),
        feedback=_FeedbackError(ErrorEntradaInvalida("Error validación feedback")),
    )
    at2, _ = _recomendar_base(5, servicios=serv_parcial)
    at2.button(key="voto_pos_1000").click().run()
    assert any("Error validación feedback" in e.value for e in at2.error)

    at2.button(key="btn_contrafactual_1000").click().run()
    assert any("Error validación explicar" in e.value for e in at2.error)

    at2.button(key="btn_por_que_no").click().run()
    assert any("Error validación explicar" in e.value for e in at2.error)


def test_manejo_error_generico_sin_exponer_traceback(caplog: LogCaptureFixture) -> None:
    secreto = "Detalle interno sensible de SQLite"
    serv_err = Servicios(
        recomendar=_RecomendadorError(RuntimeError(secreto)),
        catalogo=CatalogoFalso(),
        explicar=ExplicadorFalso(),
        feedback=FeedbackFalso(),
    )
    at, _ = _recomendar_base(5, servicios=serv_err)
    assert not at.exception
    assert len(at.error) == 1
    assert "error inesperado" in at.error[0].value.lower()
    assert secreto not in at.error[0].value
    assert "Error inesperado al generar recomendaciones" in caplog.text

    # Error genérico en contrafactual, por_que_no y feedback
    serv_parcial = Servicios(
        recomendar=RecomendadorFalso(),
        catalogo=CatalogoFalso(),
        explicar=_ExplicadorError(RuntimeError(secreto)),
        feedback=_FeedbackError(RuntimeError(secreto)),
    )
    at2, _ = _recomendar_base(5, servicios=serv_parcial)
    at2.button(key="voto_pos_1000").click().run()
    at2.button(key="btn_contrafactual_1000").click().run()
    at2.button(key="btn_por_que_no").click().run()
    assert not at2.exception
    assert all(secreto not in e.value for e in at2.error)


def test_mensaje_claro_cuando_falta_base_de_datos(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    streamlit_app._cargar_servicios_cacheados.clear()
    monkeypatch.delenv("SONARMATCH_FAKE", raising=False)
    monkeypatch.setenv("SONARMATCH_DB", str(tmp_path / "inexistente.db"))

    at = AppTest.from_string(SCRIPT_EJECUTAR_APP, default_timeout=10).run()
    assert not at.exception
    assert len(at.error) == 1
    assert "python -m sonarmatch.adapters.inbound.cli ingest" in at.error[0].value


def test_obtener_servicios_modo_fake_y_error_generico_inicio(
    monkeypatch: MonkeyPatch,
) -> None:
    streamlit_app._cargar_servicios_cacheados.clear()
    monkeypatch.setenv("SONARMATCH_FAKE", "1")

    at_file = AppTest.from_file(str(RUTA_APP), default_timeout=10).run()
    assert not at_file.exception
    assert any("SonarMatch" in t.value for t in at_file.title)

    at_func = AppTest.from_string(SCRIPT_EJECUTAR_APP, default_timeout=10).run()
    assert not at_func.exception
    assert any("SonarMatch" in t.value for t in at_func.title)

    # Error genérico al inicializar servicios (ej. NotImplementedError cuando el archivo existe)
    def _fallar() -> Servicios:
        raise RuntimeError("Fallo al abrir recursos")

    monkeypatch.setattr(streamlit_app, "obtener_servicios", _fallar)
    at_err = AppTest.from_string(SCRIPT_EJECUTAR_APP, default_timeout=10).run()
    assert not at_err.exception
    assert len(at_err.error) == 1
    assert "error inesperado" in at_err.error[0].value.lower()
    assert "Fallo al abrir recursos" not in at_err.error[0].value
