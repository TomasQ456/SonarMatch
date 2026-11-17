"""Ontología de géneros: DAG con raíz virtual, ruptura de ciclos, profundidad y Wu-Palmer.

- Las aristas van de padre a hijo (P279 "subclase de" invertida).
- Ciclos: se recorre el grafo en profundidad (DFS) desde las raíces en orden lexicográfico
  y luego desde los nodos aún no visitados, también en orden; cada arista que vuelve a un nodo
  que está en la pila (arista de retroceso) se elimina. El resultado es un DAG y depende solo de
  los identificadores, así que la ruptura es determinista. Las aristas rotas se registran.
- Profundidad: distancia más corta desde la raíz virtual (raíz = 0, géneros sin padre = 1).
- Wu-Palmer: sim(g, h) = max_{LCS ∈ ancestros comunes} 2·prof(LCS) / (prof(g) + prof(h)).
  Con varios padres, la profundidad por camino más corto puede hacer que un ancestro común
  profundo supere ese cociente; por eso el valor se acota a 1.
"""

from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

RAIZ = "__raiz__"


@dataclass(frozen=True)
class AristaRota:
    padre: str
    hijo: str


@dataclass
class Ontologia:
    padres: dict[str, tuple[str, ...]]  # tras romper ciclos; los huérfanos cuelgan de RAIZ
    hijos: dict[str, tuple[str, ...]]
    profundidad: dict[str, int]
    aristas_rotas: tuple[AristaRota, ...]
    etiquetas: dict[str, str] = field(default_factory=dict)  # id -> nombre legible
    _ancestros: dict[str, frozenset[str]] = field(default_factory=dict, repr=False)

    @classmethod
    def construir(
        cls, padres_crudos: Mapping[str, Iterable[str]], etiquetas: Mapping[str, str] | None = None
    ) -> "Ontologia":
        nodos = set(padres_crudos)
        for ps in padres_crudos.values():
            nodos.update(ps)
        nodos.discard(RAIZ)
        hijos_crudos: dict[str, list[str]] = {n: [] for n in nodos}
        for hijo, ps in padres_crudos.items():
            for p in set(ps):
                if p not in (hijo, RAIZ):
                    hijos_crudos[p].append(hijo)
        rotas = _romper_ciclos(nodos, {k: sorted(v) for k, v in hijos_crudos.items()})
        rotas_set = {(r.padre, r.hijo) for r in rotas}
        padres: dict[str, list[str]] = {n: [] for n in nodos}
        for p, hs in hijos_crudos.items():
            for h in hs:
                if (p, h) not in rotas_set:
                    padres[h].append(p)
        padres_final = {n: tuple(sorted(ps)) if ps else (RAIZ,) for n, ps in padres.items()}
        padres_final[RAIZ] = ()
        hijos: dict[str, list[str]] = {n: [] for n in padres_final}
        for n, ps in padres_final.items():
            for p in ps:
                hijos[p].append(n)
        hijos_final = {n: tuple(sorted(hs)) for n, hs in hijos.items()}
        return cls(
            padres=padres_final,
            hijos=hijos_final,
            profundidad=_profundidades(hijos_final),
            aristas_rotas=tuple(rotas),
            etiquetas=dict(etiquetas or {}),
        )

    @property
    def generos(self) -> list[str]:
        return sorted(n for n in self.padres if n != RAIZ)

    def nombre(self, genero: str) -> str:
        return self.etiquetas.get(genero, genero)

    def ancestros(self, genero: str) -> frozenset[str]:
        """Ancestros incluyendo el propio género y la raíz virtual."""
        if genero not in self._ancestros:
            vistos = {genero}
            pila = [genero]
            while pila:
                for p in self.padres.get(pila.pop(), ()):
                    if p not in vistos:
                        vistos.add(p)
                        pila.append(p)
            self._ancestros[genero] = frozenset(vistos)
        return self._ancestros[genero]

    def descendientes(self, genero: str) -> frozenset[str]:
        vistos = {genero}
        pila = [genero]
        while pila:
            for h in self.hijos.get(pila.pop(), ()):
                if h not in vistos:
                    vistos.add(h)
                    pila.append(h)
        return frozenset(vistos)

    def lcs(self, g: str, h: str) -> tuple[str, ...]:
        """Ancestros comunes de máxima profundidad (puede haber varios con varios padres)."""
        comunes = self.ancestros(g) & self.ancestros(h)
        mejor = max(self.profundidad[a] for a in comunes)
        return tuple(sorted(a for a in comunes if self.profundidad[a] == mejor))

    def wu_palmer(self, g: str, h: str) -> float:
        if g == h:
            return 1.0
        dg, dh = self.profundidad[g], self.profundidad[h]
        comunes = self.ancestros(g) & self.ancestros(h)
        prof_lcs = max(self.profundidad[a] for a in comunes)
        return min(1.0, 2.0 * prof_lcs / (dg + dh))

    def matriz_wu_palmer(self, generos: Sequence[str]) -> npt.NDArray[np.float64]:
        """Matriz de similitud entre ``generos``, vectorizada por ancestro.

        Se recorren los ancestros en orden creciente de profundidad y se escribe su profundidad
        en el bloque de pares que lo tienen como ancestro común; al final cada par conserva la
        profundidad del ancestro común más profundo.
        """
        pos = {g: i for i, g in enumerate(generos)}
        n = len(generos)
        lcs = np.zeros((n, n))
        miembros: dict[str, list[int]] = {}
        for g in generos:
            for a in self.ancestros(g):
                miembros.setdefault(a, []).append(pos[g])
        for a in sorted(miembros, key=lambda x: (self.profundidad[x], x)):
            idx = np.array(miembros[a])
            lcs[np.ix_(idx, idx)] = self.profundidad[a]
        prof = np.array([self.profundidad[g] for g in generos], dtype=float)
        suma = prof[:, None] + prof[None, :]
        sim = np.minimum(1.0, 2.0 * lcs / np.where(suma > 0, suma, 1.0))
        np.fill_diagonal(sim, 1.0)
        return sim


def _romper_ciclos(nodos: set[str], hijos: Mapping[str, list[str]]) -> list[AristaRota]:
    """DFS iterativo en orden lexicográfico; elimina aristas de retroceso."""
    tiene_padre = {h for hs in hijos.values() for h in hs}
    orden = sorted(n for n in nodos if n not in tiene_padre) + sorted(nodos)
    estado: dict[str, int] = {}  # 1 = en pila, 2 = terminado
    rotas: list[AristaRota] = []
    for inicio in orden:
        if inicio in estado:
            continue
        estado[inicio] = 1
        pila: list[tuple[str, int]] = [(inicio, 0)]
        while pila:
            nodo, i = pila[-1]
            hs = hijos[nodo]
            if i == len(hs):
                estado[nodo] = 2
                pila.pop()
                continue
            pila[-1] = (nodo, i + 1)
            h = hs[i]
            if estado.get(h) == 1:
                rotas.append(AristaRota(nodo, h))
            elif h not in estado:
                estado[h] = 1
                pila.append((h, 0))
    return rotas


def _profundidades(hijos: Mapping[str, tuple[str, ...]]) -> dict[str, int]:
    prof = {RAIZ: 0}
    cola = deque([RAIZ])
    while cola:
        n = cola.popleft()
        for h in hijos[n]:
            if h not in prof:
                prof[h] = prof[n] + 1
                cola.append(h)
    return prof
