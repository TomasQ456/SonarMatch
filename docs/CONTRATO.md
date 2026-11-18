# Contrato backend ↔ frontend

El frontend (Streamlit) habla con el backend **solo** a través de este contrato.
Nadie lo modifica por su cuenta: las solicitudes de cambio van en
[`docs/SOLICITUDES_CONTRATO.md`](SOLICITUDES_CONTRATO.md) y el responsable del backend decide y documenta.

## Archivos

| Archivo | Contenido |
|---|---|
| `sonarmatch/ports/inbound.py` | DTOs, `ErrorEntradaInvalida`, `ErrorPerfil` y los cinco protocolos (fuente de verdad) |
| `sonarmatch/bootstrap.py` | `Servicios` (dataclass con los cinco puertos) y `crear_servicios(db_path)` |
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
    perfiles: GestionarPerfiles = PerfilesNoDisponibles()  # perfiles y amigos (ver abajo)
```

`perfiles` tiene valor por defecto para que el cambio sea aditivo: si no se pasa, cada llamada
lanza `ErrorPerfil("La gestión de perfiles no está disponible…")`.

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
  Desde la dimensión social, `aportes` incluye siempre `s_social` (0 si no hay amigos activos);
  `s_grafo + s_social` es el término de grafo y los cinco siguen sumando `puntaje`.
- **`estrategias_usadas`**: conteo por estrategia de las recomendaciones devueltas.
- **`artistas_no_encontrados`**: nombres de entrada que no están en el catálogo (se ignoran al recomendar).
- **Contrafactual**: costoso; llamarlo solo bajo demanda. `posicion_sin_artista=None` significa que
  el artista saldría de los candidatos. `efectos` viene de mayor a menor impacto.
- **`por_que_no`**: diagnostica el primer motivo que aplique en este orden: `ya_en_entrada`,
  `no_en_catalogo`, `no_conectado` (o `no_conectado_ni_por_amigos` si hay amigos activos),
  `descartado_por_regla`, `puntaje_insuficiente`, `desplazado_por_diversidad`. `aportes` vacío si
  no fue candidato. La interfaz debe tolerar motivos nuevos (texto de reserva).
- **Feedback**: `valoracion` es `1` (👍) o `-1` (👎).
- **`crear_servicios(db_path)`**: lanza `FileNotFoundError` si la base no existe (mensaje con el
  comando de ingesta). Construye todo en memoria: el frontend debe cachearlo (`st.cache_resource`).

## Dimensión social (cambios aditivos)

Todo lo nuevo tiene valor por defecto: el código que no lo usa sigue funcionando igual.

| Dónde | Nuevo | Por defecto | Significado |
|---|---|---|---|
| `SolicitudRecomendacion` | `apodo: str \| None` | `None` | Si viene, se usan sus amigos que comparten gustos. Apodo inexistente → `ErrorPerfil`. |
| `ParametrosMotor` | `beta: float` | `0.25` | Peso de los amigos en PPR: s = (1 − β)·s_propio + β·s_amigos. En `[0, 1]`. |
| `RecomendacionDTO.aportes` | clave `s_social` | `0.0` | Parte del término de grafo que viene de los amigos. |
| `RecomendacionDTO` | `amigos_origen: tuple[str, ...]` | `()` | Apodos de los amigos que más aportaron (solo con consentimiento). |
| `EfectoContrafactual` | `tipo: TipoEfecto` | `"artista"` | `"artista"`, `"amigo"` (en `artista_usuario` va el apodo) o `"amigos"` (va `"todos tus amigos"`). |
| `MotivoNo` | `no_conectado_ni_por_amigos` | — | Inalcanzable en el grafo desde los artistas del usuario y los de sus amigos. |

**Amigos activos**: los amigos del apodo con `comparte_gustos = True`, y solo si β > 0. Sin
amigos activos el resultado es idéntico al de antes (`s_social = 0`, `amigos_origen = ()`, sin
efectos de tipo amigo). Los amigos sin consentimiento nunca se usan ni se nombran.

### `GestionarPerfiles` y `ErrorPerfil`

```python
class GestionarPerfiles(Protocol):
    def guardar_perfil(self, apodo, artistas: tuple[EntradaArtista, ...], comparte_gustos: bool) -> PerfilDTO
    def obtener_perfil(self, apodo) -> PerfilDTO
    def agregar_amigo(self, apodo, apodo_amigo) -> None
    def quitar_amigo(self, apodo, apodo_amigo) -> None
    def listar_amigos(self, apodo) -> tuple[AmigoDTO, ...]   # AmigoDTO(apodo, comparte_gustos)
```

- **Apodo**: se normaliza (sin espacios extremos, en minúsculas) y debe tener 3–30 caracteres
  de `a-z 0-9 . _ -`. Es único: `Ana_M` y `ana_m` son el mismo perfil.
- **`guardar_perfil`**: crea el perfil o, si el apodo existe, reemplaza sus artistas y su
  consentimiento. Los artistas siguen las mismas reglas que una solicitud (5–20, pesos en
  `[1, 5]`, sin vacíos ni repetidos). `comparte_gustos` es el consentimiento explícito.
- **Amistades**: bidireccionales (agregar a B desde A hace a A amigo de B), sin duplicados ni
  autoamistad.
- **`listar_amigos`**: ordenado por apodo; nunca expone los artistas de los amigos.
- **`ErrorPerfil`** (subclase de `ErrorEntradaInvalida`, mensaje en español listo para mostrar):
  apodo inválido o inexistente, artistas inválidos al guardar, autoamistad, amistad repetida
  al agregar o inexistente al quitar.
- **Sin autenticación** (limitación del prototipo): quien conoce un apodo puede cargar y
  sobrescribir ese perfil. El consentimiento solo controla qué ven y usan los amigos.

## Servicios falsos (`crear_servicios_falsos()`)

Deterministas (salvo los perfiles, que se pueden modificar). Los dobles registran sus llamadas para las pruebas:
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
| `Swans` | `no_conectado_ni_por_amigos` |

- `contrafactual`: el primer artista de la entrada saca la recomendación de la lista
  (`posicion_sin_artista=None`).

**Perfiles de ejemplo** (`PERFILES_FALSOS`, `AMISTADES_FALSAS`; `servicios.perfiles` es el
servicio real sobre un repositorio en memoria, así que valida igual que el real):

| Apodo | Comparte gustos | Amigos |
|---|---|---|
| `demo` | sí | `ana_m`, `juanp`, `luis_priv` |
| `ana_m` | sí | `demo`, `juanp` |
| `juanp` | sí | `demo`, `ana_m` |
| `luis_priv` | **no** (nunca se usa ni se nombra) | `demo` |
| `solo` | no | ninguno |

- Con `apodo="demo"` y β > 0: las primeras 3 recomendaciones de grafo tienen `s_social > 0`,
  `amigos_origen ⊆ {ana_m, juanp}` y la explicación "El N % viene de lo que escuchan ana_m y
  juanp"; la primera añade el paso R7 a la cadena. El contrafactual añade un efecto
  `"todos tus amigos"` (tipo `amigos`) y uno por amigo activo (tipo `amigo`).
- Con β = 0, `apodo="solo"` o sin apodo: sin aporte social.
- `por_que_no("Sonic Youth")` da `no_conectado_ni_por_amigos` si hay amigos activos;
  `Swans` siempre da `no_conectado_ni_por_amigos`.
- Un apodo inexistente en la solicitud lanza `ErrorPerfil`.
- El servicio de perfiles es mutable: cada `crear_servicios_falsos()` crea uno nuevo.
