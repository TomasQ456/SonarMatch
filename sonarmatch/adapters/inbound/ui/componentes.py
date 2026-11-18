"""Componentes visuales en Streamlit para la interfaz de SonarMatch."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

import altair as alt
import streamlit as st

from sonarmatch.adapters.inbound.ui.presentadores import (
    ORDEN_APORTES,
    filas_tabla_contrafactual,
    filtrar_catalogo_por_que_no,
    formatear_estado_amigo,
    formatear_latencia,
    formatear_oyentes,
    formatear_resumen_estrategias,
    preparar_datos_comparativa_aportes,
    preparar_datos_grafica_aportes,
    resolver_parametros,
    texto_contador_artistas,
    texto_insignia,
    texto_motivo_no,
    validar_cantidad_artistas,
)
from sonarmatch.ports.inbound import (
    ContrafactualDTO,
    EntradaArtista,
    ErrorEntradaInvalida,
    ExplicarRecomendacion,
    GestionarPerfiles,
    ParametrosMotor,
    PorQueNoDTO,
    RecomendacionDTO,
    RegistrarFeedback,
    RespuestaRecomendacion,
    SolicitudRecomendacion,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

MSG_ERROR_GENERICO = (
    "Ocurrió un error inesperado al procesar la operación. Por favor, intenta de nuevo."
)
PREFIJO_BTN_QUITAR_AMIGO = "btn_quitar_amigo_"


def _restablecer_parametros(por_defecto: ParametrosMotor) -> None:
    """Restablece en session_state los valores por defecto de los sliders del motor."""
    st.session_state["param_a"] = float(por_defecto.a)
    st.session_state["param_b"] = float(por_defecto.b)
    st.session_state["param_c"] = float(por_defecto.c)
    st.session_state["param_d"] = float(por_defecto.d)
    st.session_state["param_lambda"] = float(por_defecto.lambda_mmr)
    st.session_state["param_beta"] = float(por_defecto.beta)


def dibujar_sidebar(por_defecto: ParametrosMotor) -> ParametrosMotor | None:
    """Dibuja la barra lateral de modo exploración y retorna los parámetros o None."""
    st.sidebar.header("Modo exploración")
    st.sidebar.caption(
        "Ajusta los pesos del motor híbrido. Si mantienes los valores por defecto, "
        "el motor aplicará los pesos calibrados y ajustes por reglas."
    )

    st.session_state.setdefault("param_a", float(por_defecto.a))
    st.session_state.setdefault("param_b", float(por_defecto.b))
    st.session_state.setdefault("param_c", float(por_defecto.c))
    st.session_state.setdefault("param_d", float(por_defecto.d))
    st.session_state.setdefault("param_lambda", float(por_defecto.lambda_mmr))
    st.session_state.setdefault("param_beta", float(por_defecto.beta))

    a = st.sidebar.slider(
        "a — Etiquetas (S_tags)",
        min_value=0.0,
        max_value=1.0,
        step=0.05,
        key="param_a",
    )
    b = st.sidebar.slider(
        "b — Conexiones en grafo (S_grafo)",
        min_value=0.0,
        max_value=1.0,
        step=0.05,
        key="param_b",
    )
    c = st.sidebar.slider(
        "c — Novedad (P_nov)",
        min_value=0.0,
        max_value=1.0,
        step=0.05,
        key="param_c",
    )
    d = st.sidebar.slider(
        "d — Afinidad de género (S_onto)",
        min_value=0.0,
        max_value=1.0,
        step=0.05,
        key="param_d",
    )
    lambda_mmr = st.sidebar.slider(
        "λ — Diversidad (MMR)",
        min_value=0.0,
        max_value=1.0,
        step=0.05,
        key="param_lambda",
    )
    beta = st.sidebar.slider(
        "β — Peso de amigos (social)",
        min_value=0.0,
        max_value=1.0,
        step=0.05,
        key="param_beta",
    )

    st.sidebar.button(
        "Restablecer valores",
        key="btn_restablecer_parametros",
        on_click=_restablecer_parametros,
        args=(por_defecto,),
    )

    actuales = ParametrosMotor(
        a=float(a),
        b=float(b),
        c=float(c),
        d=float(d),
        lambda_mmr=float(lambda_mmr),
        beta=float(beta),
    )
    return resolver_parametros(actuales, por_defecto)


def _procesar_cargar_perfil(perfiles: GestionarPerfiles, apodo: str) -> None:
    """Carga un perfil guardado y actualiza artistas, pesos y consentimiento en session_state."""
    try:
        perfil = perfiles.obtener_perfil(apodo)
    except ErrorEntradaInvalida as exc:
        st.error(str(exc))
        return
    except Exception:
        logger.exception("Error inesperado al cargar el perfil %s", apodo)
        st.error(MSG_ERROR_GENERICO)
        return

    st.session_state["comparte_gustos"] = bool(perfil.comparte_gustos)
    st.session_state["artistas_seleccionados"] = [e.nombre for e in perfil.artistas]
    for entrada in perfil.artistas:
        st.session_state[f"peso_{entrada.nombre}"] = float(entrada.peso)
    st.success(f"Perfil «{perfil.apodo}» cargado correctamente.")


def dibujar_mi_perfil(perfiles: GestionarPerfiles) -> tuple[str, bool, bool]:
    """Dibuja la sección 'Mi perfil' y retorna (apodo, comparte_gustos, guardar_click)."""
    st.subheader("Mi perfil")
    st.caption(
        "Aviso: no hay contraseñas; el apodo te identifica y cualquiera que conozca tu apodo "
        "puede cargar o reemplazar tu perfil."
    )
    st.session_state.setdefault("apodo_usuario", "")
    apodo = st.text_input(
        "Tu apodo",
        key="apodo_usuario",
        placeholder="Ej. demo (3 a 30 caracteres)",
    )

    if st.session_state.get("btn_cargar_perfil"):
        _procesar_cargar_perfil(perfiles, apodo)

    st.session_state.setdefault("comparte_gustos", False)
    comparte_gustos = st.checkbox(
        "Compartir mis gustos con mis amigos",
        key="comparte_gustos",
    )
    st.caption(
        "Tus artistas se usan para recomendar a tus amigos y tu apodo puede aparecer en sus "
        "explicaciones. Si no marcas la casilla, tus gustos no se usan ni se te nombra."
    )

    col_cargar, col_guardar = st.columns(2)
    col_cargar.button("Cargar perfil", key="btn_cargar_perfil")
    guardar_click = col_guardar.button("Guardar mi perfil", key="btn_guardar_perfil")
    return apodo, bool(comparte_gustos), guardar_click


def guardar_perfil_actual(
    perfiles: GestionarPerfiles,
    apodo: str,
    entradas: Sequence[tuple[str, float]],
    comparte_gustos: bool,
) -> None:
    """Guarda el perfil del usuario con los artistas y pesos actuales."""
    artistas_dto = tuple(EntradaArtista(nombre=n, peso=float(p)) for n, p in entradas)
    try:
        guardado = perfiles.guardar_perfil(apodo, artistas_dto, comparte_gustos)
    except ErrorEntradaInvalida as exc:
        st.error(str(exc))
        return
    except Exception:
        logger.exception("Error inesperado al guardar el perfil %s", apodo)
        st.error(MSG_ERROR_GENERICO)
        return

    st.success(f"Perfil «{guardado.apodo}» guardado correctamente.")


def _amigo_por_quitar_en_lista() -> str | None:
    """Detecta si se presionó algún botón individual 'Quitar' en la lista de amigos."""
    for clave, valor in list(st.session_state.items()):
        if isinstance(clave, str) and clave.startswith(PREFIJO_BTN_QUITAR_AMIGO) and valor:
            return clave.removeprefix(PREFIJO_BTN_QUITAR_AMIGO)
    return None


def _ejecutar_cambio_amistad(
    perfiles: GestionarPerfiles, apodo: str, apodo_amigo: str, *, agregar: bool
) -> None:
    """Agrega o quita un amigo manejando ErrorPerfil y errores inesperados."""
    try:
        if agregar:
            perfiles.agregar_amigo(apodo, apodo_amigo)
            st.success(f"Se agregó a «{apodo_amigo.strip().casefold()}» a tus amigos.")
        else:
            perfiles.quitar_amigo(apodo, apodo_amigo)
            st.success(f"Se quitó a «{apodo_amigo.strip().casefold()}» de tus amigos.")
    except ErrorEntradaInvalida as exc:
        st.error(str(exc))
    except Exception:
        logger.exception("Error inesperado al actualizar amistad para %s", apodo)
        st.error(MSG_ERROR_GENERICO)


def dibujar_seccion_amigos(perfiles: GestionarPerfiles, apodo: str) -> None:
    """Dibuja la sección 'Amigos' para agregar, listar y quitar amigos."""
    st.subheader("Amigos")
    st.session_state.setdefault("apodo_amigo_input", "")
    apodo_amigo = st.text_input(
        "Apodo de tu amigo",
        key="apodo_amigo_input",
        placeholder="Ej. ana_m",
    )
    col_agregar, col_quitar = st.columns(2)
    agregar_click = col_agregar.button("Agregar amigo", key="btn_agregar_amigo")
    quitar_click = col_quitar.button("Quitar amigo", key="btn_quitar_amigo")

    amigo_fila = _amigo_por_quitar_en_lista()
    if agregar_click:
        _ejecutar_cambio_amistad(perfiles, apodo, apodo_amigo, agregar=True)
    elif quitar_click:
        _ejecutar_cambio_amistad(perfiles, apodo, apodo_amigo, agregar=False)
    elif amigo_fila is not None:
        _ejecutar_cambio_amistad(perfiles, apodo, amigo_fila, agregar=False)

    if not apodo.strip():
        st.caption("Ingresa tu apodo en «Mi perfil» para ver y gestionar tu lista de amigos.")
        return

    try:
        amigos = perfiles.listar_amigos(apodo)
    except ErrorEntradaInvalida:
        st.caption("Guarda un perfil válido con este apodo para consultar tu lista de amigos.")
        return
    except Exception:
        logger.exception("Error inesperado al listar amigos de %s", apodo)
        st.error(MSG_ERROR_GENERICO)
        return

    if not amigos:
        st.caption("Aún no tienes amigos en tu lista.")
        return

    for amigo in amigos:
        col_info, col_btn = st.columns([4, 1])
        col_info.markdown(formatear_estado_amigo(amigo))
        col_btn.button("Quitar", key=f"{PREFIJO_BTN_QUITAR_AMIGO}{amigo.apodo}")


def dibujar_entrada(catalogo: Sequence[str]) -> tuple[list[tuple[str, float]], bool]:
    """Dibuja el selector de artistas de entrada, sus pesos y el botón de recomendar."""
    st.subheader("Tu perfil musical")
    opciones = list(catalogo)
    previos = st.session_state.get("artistas_seleccionados")
    if isinstance(previos, list):
        for item in previos:
            if isinstance(item, str) and item not in opciones:
                opciones.append(item)

    seleccionados: list[str] = st.multiselect(
        "Elige entre 5 y 20 artistas que escuchas",
        options=opciones,
        key="artistas_seleccionados",
        placeholder="Busca y selecciona artistas...",
        accept_new_options=True,
    )

    cantidad = len(seleccionados)
    st.markdown(f"**Artistas seleccionados:** {texto_contador_artistas(cantidad)}")

    entradas: list[tuple[str, float]] = []
    if seleccionados:
        st.caption("Asigna un peso de afinidad (1 a 5) para cada artista elegido:")
        for nombre in seleccionados:
            clave_peso = f"peso_{nombre}"
            st.session_state.setdefault(clave_peso, 3.0)
            peso = st.slider(
                f"Peso para {nombre}",
                min_value=1.0,
                max_value=5.0,
                step=0.5,
                key=clave_peso,
            )
            entradas.append((nombre, float(peso)))

    habilitado = validar_cantidad_artistas(cantidad)
    recomendar_click = st.button(
        "Recomendar",
        key="btn_recomendar",
        type="primary",
        disabled=not habilitado,
    )
    return entradas, recomendar_click


def dibujar_encabezado_resultados(respuesta: RespuestaRecomendacion) -> None:
    """Muestra la latencia, el conteo por estrategia y los artistas no encontrados."""
    st.subheader("Artistas recomendados")
    latencia_txt = formatear_latencia(respuesta.latencia_ms)
    estrategias_txt = formatear_resumen_estrategias(respuesta.estrategias_usadas)
    st.markdown(f"**Latencia:** {latencia_txt} · **Estrategias:** {estrategias_txt}")
    st.caption(
        "El orden combina puntaje y diversidad (MMR), por lo que los puntajes mostrados "
        "no siempre decrecen."
    )

    if respuesta.artistas_no_encontrados:
        nombres = ", ".join(respuesta.artistas_no_encontrados)
        st.warning(f"Artistas no encontrados en el catálogo (se ignoraron): {nombres}")


def _crear_grafica_aportes(aportes: dict[str, float]) -> alt.Chart:
    """Construye la barra horizontal apilada con los 5 componentes de aporte."""
    datos = preparar_datos_grafica_aportes(aportes)
    orden_etiquetas = [etiqueta for _, etiqueta in ORDEN_APORTES]
    return alt.Chart({"values": datos}, mark="bar", height=55).encode(
        x=alt.X("sum(valor):Q", title="Aporte al puntaje"),
        color=alt.Color(
            "componente:N",
            title="Componente",
            sort=orden_etiquetas,
        ),
        tooltip=["componente:N", "valor:Q"],
    )


def _crear_grafica_comparativa(dto: PorQueNoDTO, decimo: RecomendacionDTO) -> alt.Chart:
    """Construye la barra comparativa entre el artista consultado y el décimo recomendado."""
    datos = preparar_datos_comparativa_aportes(
        dto.aportes, dto.nombre, decimo.aportes, decimo.nombre
    )
    orden_etiquetas = [etiqueta for _, etiqueta in ORDEN_APORTES]
    return alt.Chart({"values": datos}, mark="bar", height=110).encode(
        y=alt.Y("artista:N", title="Artista"),
        x=alt.X("sum(valor):Q", title="Puntaje por componente"),
        color=alt.Color(
            "componente:N",
            title="Componente",
            sort=orden_etiquetas,
        ),
        tooltip=["artista:N", "componente:N", "valor:Q"],
    )


def _procesar_voto_tarjeta(
    rec: RecomendacionDTO, feedback: RegistrarFeedback, sesion_id: str
) -> bool:
    """Registra el voto si se presionó 👍 o 👎 y retorna si el artista ya fue votado."""
    votos: dict[int, int] = st.session_state.setdefault("votos_emitidos", {})
    key_pos = f"voto_pos_{rec.artista_id}"
    key_neg = f"voto_neg_{rec.artista_id}"

    if rec.artista_id not in votos:
        valoracion: Literal[-1, 1] | None = None
        if st.session_state.get(key_pos):
            valoracion = 1
        elif st.session_state.get(key_neg):
            valoracion = -1

        if valoracion is not None:
            try:
                feedback.registrar(sesion_id, rec.artista_id, valoracion, rec.estrategia)
                votos[rec.artista_id] = valoracion
            except ErrorEntradaInvalida as exc:
                st.error(str(exc))
            except Exception:
                logger.exception("Error al registrar feedback para %s", rec.artista_id)
                st.error(MSG_ERROR_GENERICO)

    ya_votado = rec.artista_id in votos
    col_pos, col_neg, col_msg = st.columns([1, 1, 6])
    col_pos.button("👍", key=key_pos, disabled=ya_votado)
    col_neg.button("👎", key=key_neg, disabled=ya_votado)
    if ya_votado:
        col_msg.success("¡Gracias! Tu valoración fue registrada.")
    return ya_votado


def _dibujar_expander_por_que(
    rec: RecomendacionDTO,
    solicitud: SolicitudRecomendacion,
    explicar: ExplicarRecomendacion,
) -> None:
    """Dibuja el expander '¿Por qué?' con la cadena de inferencia y el contrafactual."""
    with st.expander("¿Por qué?"):
        if rec.cadena_inferencia:
            pasos = "\n".join(
                f"{idx}. {paso}" for idx, paso in enumerate(rec.cadena_inferencia, start=1)
            )
            st.markdown(f"**Cadena de inferencia:**\n{pasos}")

        btn_cf = st.button(
            "¿Qué pasaría sin cada uno de mis artistas?",
            key=f"btn_contrafactual_{rec.artista_id}",
        )
        contrafactuales: dict[int, ContrafactualDTO] = st.session_state.setdefault(
            "contrafactuales", {}
        )

        if btn_cf and rec.artista_id not in contrafactuales:
            try:
                contrafactuales[rec.artista_id] = explicar.contrafactual(solicitud, rec.artista_id)
            except ErrorEntradaInvalida as exc:
                st.error(str(exc))
            except Exception:
                logger.exception("Error al calcular contrafactual para %s", rec.artista_id)
                st.error(MSG_ERROR_GENERICO)

        if rec.artista_id in contrafactuales:
            cf = contrafactuales[rec.artista_id]
            st.markdown(f"**Resumen:** {cf.resumen}")
            st.table(filas_tabla_contrafactual(cf.efectos))


def dibujar_tarjeta_recomendacion(
    posicion: int,
    rec: RecomendacionDTO,
    solicitud: SolicitudRecomendacion,
    explicar: ExplicarRecomendacion,
    feedback: RegistrarFeedback,
    sesion_id: str,
) -> None:
    """Dibuja una tarjeta individual de recomendación con gráfica, votos y explicación."""
    with st.container(border=True):
        insignia = texto_insignia(rec.estrategia)
        oyentes_txt = formatear_oyentes(rec.oyentes)
        st.markdown(
            f"### #{posicion} · {rec.nombre} — Puntaje: `{rec.puntaje:.2f}` "
            f"(`{insignia}` · {rec.estrategia})"
        )
        st.caption(f"Oyentes: {oyentes_txt}")

        st.altair_chart(_crear_grafica_aportes(rec.aportes), width="stretch")
        st.write(rec.explicacion)

        if rec.etiquetas_clave:
            st.markdown(f"**Etiquetas clave:** {', '.join(rec.etiquetas_clave)}")
        if rec.artistas_origen:
            st.markdown(f"**Artistas origen:** {', '.join(rec.artistas_origen)}")
        if rec.amigos_origen:
            st.markdown(f"**Amigos origen:** {', '.join(rec.amigos_origen)}")

        _procesar_voto_tarjeta(rec, feedback, sesion_id)
        _dibujar_expander_por_que(rec, solicitud, explicar)


def _mostrar_detalle_por_que_no(
    dto: PorQueNoDTO, recomendaciones: Sequence[RecomendacionDTO]
) -> None:
    """Muestra el diagnóstico detallado de por qué un artista no fue recomendado."""
    st.markdown(f"**Motivo ({dto.motivo}):** {texto_motivo_no(dto.motivo)}")
    st.markdown(f"**Explicación:** {dto.explicacion}")

    if dto.cadena_regla:
        reglas = "\n".join(f"{idx}. {r}" for idx, r in enumerate(dto.cadena_regla, start=1))
        st.markdown(f"**Regla que lo descartó:**\n{reglas}")

    if dto.similar_a:
        st.markdown(f"**Desplazado por similitud con:** {dto.similar_a}")

    if dto.aportes and recomendaciones:
        decimo = recomendaciones[-1]
        st.markdown(f"**Comparación de aportes frente al 10.° recomendado ({decimo.nombre}):**")
        st.altair_chart(_crear_grafica_comparativa(dto, decimo), width="stretch")


def dibujar_seccion_por_que_no(
    catalogo: Sequence[str],
    respuesta: RespuestaRecomendacion,
    solicitud: SolicitudRecomendacion,
    explicar: ExplicarRecomendacion,
) -> None:
    """Dibuja la sección '¿Por qué no recomendaste…?' debajo de los resultados."""
    st.divider()
    st.subheader("¿Por qué no recomendaste…?")
    recomendados = [r.nombre for r in respuesta.recomendaciones]
    opciones = filtrar_catalogo_por_que_no(catalogo, recomendados)

    actual = st.session_state.get("select_por_que_no")
    if isinstance(actual, str) and actual and actual not in opciones:
        opciones = [*opciones, actual]

    artista_consulta = st.selectbox(
        "Consulta un artista que no apareció en el top 10",
        options=opciones,
        key="select_por_que_no",
        accept_new_options=True,
    )

    if st.button(
        "Explicar ausencia",
        key="btn_por_que_no",
        disabled=not bool(artista_consulta),
    ) and isinstance(artista_consulta, str):
        try:
            st.session_state["resultado_por_que_no"] = explicar.por_que_no(
                solicitud, artista_consulta
            )
        except ErrorEntradaInvalida as exc:
            st.error(str(exc))
        except Exception:
            logger.exception("Error al consultar por_que_no para %s", artista_consulta)
            st.error(MSG_ERROR_GENERICO)

    resultado = st.session_state.get("resultado_por_que_no")
    if isinstance(resultado, PorQueNoDTO):
        _mostrar_detalle_por_que_no(resultado, respuesta.recomendaciones)
