# Resultados de la evaluación offline

- Dataset: hetrec (data/hetrec2011-lastfm-2k) sobre data/sonarmatch.db (51 artistas)
- Usuarios: 8 en validación, 3 en prueba (20 % de artistas ocultos por usuario, mínimo 2).
- Grid search en validación: 757 configuraciones; mejor P@10 en validación = 0.175.
- Parámetros elegidos: a = 0.60, b = 0.10, c = 0.10, d = 0.20, λ = 0.90, τ = 0.00.
- Cobertura del mapeo de etiquetas (por peso): 86.1 %.
- **Atención:** solo 3 usuarios de prueba; las diferencias entre sistemas no son concluyentes.

## Comparación en prueba

| Sistema | P@10 | R@10 | Novedad ↓ | ILS | Cobertura |
|---|---:|---:|---:|---:|---:|
| línea base: popularidad | 0.100 | 0.500 | 0.895 | 0.063 | 23.5 % |
| sistema completo | 0.133 | 0.667 | 0.392 | 0.129 | 43.1 % |
| sin S_tags | 0.133 | 0.667 | 0.292 | 0.126 | 39.2 % |
| sin S_grafo | 0.133 | 0.667 | 0.392 | 0.129 | 43.1 % |
| sin P_nov | 0.133 | 0.667 | 0.458 | 0.120 | 49.0 % |
| sin S_onto | 0.133 | 0.667 | 0.380 | 0.105 | 41.2 % |
| sin reglas | 0.133 | 0.667 | 0.383 | 0.126 | 43.1 % |
| sin MMR | 0.133 | 0.667 | 0.348 | 0.173 | 41.2 % |
| sin respaldo | 0.133 | 0.667 | 0.392 | 0.129 | 43.1 % |

Novedad: percentil medio de oyentes de lo recomendado (menor = más nicho). ILS: coseno TF-IDF medio entre pares de la lista. Cobertura: fracción del catálogo recomendada al menos una vez.

## Sistema completo: respaldos, reglas y latencia

| Indicador | Valor |
|---|---:|
| Activación del respaldo contenido | 0.0 % |
| Activación del respaldo popularidad | 0.0 % |
| Consultas en que se dispara R1 | 33.3 % |
| Consultas en que se dispara R2 | 33.3 % |
| Consultas en que se dispara R3 | 0.0 % |
| Consultas en que se dispara R4 | 0.0 % |
| Consultas en que se dispara R5 | 0.0 % |
| Consultas en que se dispara R6 | 33.3 % |
| Latencia p50 de la recomendación | 9 ms |
| Latencia p95 de la recomendación | 9 ms |
| Latencia p95 del contrafactual | 37 ms |
