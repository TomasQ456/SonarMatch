"""Motor de encadenamiento hacia adelante con refracción, punto fijo y traza.

- Hechos: ``Hecho(predicado, args, confianza)``. Su clave lógica es (predicado, args); si se
  vuelve a derivar con mayor confianza, se actualiza (y su justificación también).
- Reglas: datos (``Regla``) con id, descripción, fase, condición y acción. La condición recorre
  la base de hechos (y el contexto) y produce ``Coincidencia``s; la acción produce hechos nuevos.
- Refracción: cada regla se dispara una sola vez por combinación de premisas (incluida su
  confianza y las ligaduras de variables).
- Ejecución: por fases; dentro de cada fase se repite hasta el punto fijo (ninguna regla
  agrega ni mejora hechos) o hasta el tope de iteraciones.
- Traza: cada hecho derivado guarda ``Justificacion(regla_id, premisas)`` y cada disparo queda
  registrado; ``cadena`` reconstruye los disparos que llevaron a un hecho.
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Generic, TypeVar

Valor = str | int | float
Clave = tuple[str, tuple[Valor, ...]]
C = TypeVar("C")
EPS_CONFIANZA = 1e-12


@dataclass(frozen=True)
class Hecho:
    predicado: str
    args: tuple[Valor, ...] = ()
    confianza: float = 1.0

    @property
    def clave(self) -> Clave:
        return (self.predicado, self.args)


@dataclass(frozen=True)
class Justificacion:
    regla_id: str
    premisas: tuple[Hecho, ...]


@dataclass(frozen=True)
class Coincidencia:
    premisas: tuple[Hecho, ...]
    ligaduras: tuple[Valor, ...] = ()


@dataclass(frozen=True)
class Disparo:
    regla_id: str
    coincidencia: Coincidencia
    conclusiones: tuple[Hecho, ...]  # hechos nuevos o mejorados por este disparo
    fase: str
    iteracion: int


@dataclass(frozen=True)
class Regla(Generic[C]):
    id: str
    nombre: str
    descripcion: str
    fase: str
    condicion: Callable[["BaseHechos", C], Iterable[Coincidencia]]
    accion: Callable[[Coincidencia, C], Iterable[Hecho]]
    redactar: Callable[[Disparo, C], str]


class BaseHechos:
    def __init__(self, hechos: Iterable[Hecho] = ()) -> None:
        self._hechos: dict[Clave, Hecho] = {}
        self._justificaciones: dict[Clave, Justificacion] = {}
        for h in hechos:
            self.agregar(h)

    def agregar(self, hecho: Hecho, justificacion: Justificacion | None = None) -> bool:
        """Agrega o mejora (mayor confianza) un hecho. Devuelve True si cambió la base."""
        actual = self._hechos.get(hecho.clave)
        if actual is not None and hecho.confianza <= actual.confianza + EPS_CONFIANZA:
            return False
        self._hechos[hecho.clave] = hecho
        if justificacion is not None:
            self._justificaciones[hecho.clave] = justificacion
        return True

    def obtener(self, predicado: str, *args: Valor) -> Hecho | None:
        return self._hechos.get((predicado, tuple(args)))

    def todos(self, predicado: str) -> list[Hecho]:
        return sorted(
            (h for h in self._hechos.values() if h.predicado == predicado),
            key=lambda h: tuple(str(a) for a in h.args),
        )

    def justificacion(self, hecho: Hecho) -> Justificacion | None:
        return self._justificaciones.get(hecho.clave)

    def __len__(self) -> int:
        return len(self._hechos)

    def __contains__(self, hecho: object) -> bool:
        return isinstance(hecho, Hecho) and hecho.clave in self._hechos


@dataclass
class ResultadoFase:
    fase: str
    disparos: list[Disparo]
    iteraciones: int
    punto_fijo: bool


@dataclass
class MotorReglas(Generic[C]):
    reglas: Sequence[Regla[C]]
    max_iteraciones: int = 50
    _refraccion: set[tuple[str, tuple[Valor, ...], tuple[tuple[Clave, float], ...]]] = field(
        default_factory=set
    )
    disparos: list[Disparo] = field(default_factory=list)

    def ejecutar_fase(self, base: BaseHechos, contexto: C, fase: str) -> ResultadoFase:
        reglas = [r for r in self.reglas if r.fase == fase]
        disparos: list[Disparo] = []
        for iteracion in range(1, self.max_iteraciones + 1):
            cambio = False
            for regla in reglas:
                for coincidencia in list(regla.condicion(base, contexto)):
                    clave = (
                        regla.id,
                        coincidencia.ligaduras,
                        tuple((p.clave, p.confianza) for p in coincidencia.premisas),
                    )
                    if clave in self._refraccion:
                        continue
                    self._refraccion.add(clave)
                    just = Justificacion(regla.id, coincidencia.premisas)
                    nuevos = tuple(
                        h for h in regla.accion(coincidencia, contexto) if base.agregar(h, just)
                    )
                    cambio = cambio or bool(nuevos)
                    disparos.append(Disparo(regla.id, coincidencia, nuevos, fase, iteracion))
            if not cambio:
                self.disparos.extend(disparos)
                return ResultadoFase(fase, disparos, iteracion, punto_fijo=True)
        self.disparos.extend(disparos)
        return ResultadoFase(fase, disparos, self.max_iteraciones, punto_fijo=False)

    def regla(self, regla_id: str) -> Regla[C]:
        return next(r for r in self.reglas if r.id == regla_id)

    def disparo_de(self, hecho: Hecho) -> Disparo | None:
        """Último disparo que produjo (o mejoró) el hecho con su confianza actual."""
        for d in reversed(self.disparos):
            if any(c == hecho for c in d.conclusiones):
                return d
        return None

    def cadena(self, hechos: Iterable[Hecho]) -> list[Disparo]:
        """Disparos que sostienen los hechos dados, en orden causal (premisas antes)."""
        orden: list[Disparo] = []
        vistos: set[int] = set()

        def visitar(h: Hecho, profundidad: int) -> None:
            d = self.disparo_de(h)
            if d is None or id(d) in vistos or profundidad > self.max_iteraciones:
                return
            vistos.add(id(d))
            for p in d.coincidencia.premisas:
                visitar(p, profundidad + 1)
            orden.append(d)

        for h in hechos:
            visitar(h, 0)
        return orden

    def redactar(self, disparos: Iterable[Disparo], contexto: C) -> tuple[str, ...]:
        return tuple(self.regla(d.regla_id).redactar(d, contexto) for d in disparos)
