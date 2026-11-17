# Contrato backend ↔ frontend

El frontend (Streamlit) habla con el backend **solo** a través de este contrato.
Nadie lo modifica por su cuenta: las solicitudes de cambio van en
[`docs/SOLICITUDES_CONTRATO.md`](SOLICITUDES_CONTRATO.md) y el responsable del backend decide y documenta.

## Archivos

| Archivo | Contenido |
|---|---|
| `sonarmatch/ports/inbound.py` | DTOs, `ErrorEntradaInvalida` y los cuatro protocolos (fuente de verdad) |
| `sonarmatch/bootstrap.py` | `Servicios` (dataclass con los cuatro puertos) y `crear_servicios(db_path)` |
| `sonarmatch/testing/fakes.py` | `crear_servicios_falsos()`: servicios deterministas sin base de datos |

Imports permitidos para la interfaz: `sonarmatch.ports.inbound`, `sonarmatch.bootstrap` y
`sonarmatch.testing.fakes` (lo verifica import-linter).

## `Servicios`

```python
@dataclass(frozen=True)
class Servicios:
    recomendar: RecomendarArtistas      # .recomendar(solicitud) -> RespuestaRecomendacion
    catalogo: ConsultarCatalogo         # .nombres_artistas(), .parametros_por_defecto()
    explicar: ExplicarRecomendacion     # .contrafactual(solicitud, artista_id), .por_que_no(solicitud, nombre)
    feedback: RegistrarFeedback         # .registrar(sesion_id, artista_id, valoracion, estrategia)
```

## Semántica

- **Validación** (`ErrorEntradaInvalida`, subclase de `ValueError`, con mensaje en español listo para
  mostrar): menos de 5 o más de 20 artistas, pesos fuera de `[1, 5]`, nombres vacíos o duplicados
  (comparación sin mayúsculas ni espacios extra), parámetros fuera de `[0, 1]` o `a+b+c+d = 0`.
  La lanzan `recomendar`, `contrafactual` y `por_que_no`.
- **Parámetros**: `parametros=None` usa los valores calibrados y permite que las reglas R3, R4 y R6
  los ajusten. Si se envían, se respetan; el backend renormaliza `a+b+c+d` a 1 (los sliders no
  necesitan sumar 1) y la cadena de inferencia indica que los ajustes de reglas no se aplicaron.
- **Recomendaciones**: exactamente 10 si el catálogo lo permite, ordenadas por posición.
  `aportes` tiene las claves `s_tags`, `s_grafo`, `p_nov`, `s_onto`; son los términos ya ponderados
  y suman `puntaje`. `artistas_origen` solo contiene artistas que el usuario puso.
- **`estrategias_usadas`**: conteo por estrategia de las recomendaciones devueltas.
- **`artistas_no_encontrados`**: nombres de entrada que no están en el catálogo (se ignoran al recomendar).
- **Contrafactual**: costoso; llamarlo solo bajo demanda. `posicion_sin_artista=None` significa que
  el artista saldría de los candidatos. `efectos` viene de mayor a menor impacto.
- **`por_que_no`**: diagnostica el primer motivo que aplique en este orden: `ya_en_entrada`,
  `no_en_catalogo`, `no_conectado`, `descartado_por_regla`, `puntaje_insuficiente`,
  `desplazado_por_diversidad`. `aportes` vacío si no fue candidato.
- **Feedback**: `valoracion` es `1` (👍) o `-1` (👎).
- **`crear_servicios(db_path)`**: lanza `FileNotFoundError` si la base no existe (mensaje con el
  comando de ingesta). Construye todo en memoria: el frontend debe cachearlo (`st.cache_resource`).

## Servicios falsos (`crear_servicios_falsos()`)

Deterministas. Los dobles registran sus llamadas para las pruebas:
`recomendar.llamadas`, `explicar.llamadas_contrafactual`, `explicar.llamadas_por_que_no`,
`feedback.registros`.

- Catálogo: `CATALOGO_FALSO` (entrada típica en `ENTRADA_FALSA`, 21 nombres).
- `recomendar` devuelve 10 recomendaciones (6 `grafo`, 2 `contenido`, 2 `popularidad`) menos las
  que el usuario ya puso, todas con `cadena_inferencia` no vacía. Los nombres fuera del catálogo
  aparecen en `artistas_no_encontrados`.
- `por_que_no` según el nombre:

| Nombre | Motivo |
|---|---|
| uno de la entrada | `ya_en_entrada` |
| fuera de `CATALOGO_FALSO` | `no_en_catalogo` |
| `Sonic Youth` | `no_conectado` |
| `Metallica` | `descartado_por_regla` (con `cadena_regla`) |
| `Deftones` (y cualquier otro del catálogo) | `puntaje_insuficiente` |
| `Whirr` | `desplazado_por_diversidad` (`similar_a="Wild Nothing"`) |

- `contrafactual`: el primer artista de la entrada saca la recomendación de la lista
  (`posicion_sin_artista=None`).
