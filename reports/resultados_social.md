# Evaluación de la dimensión social

- Dataset: hetrec (data/hetrec2011-lastfm-2k) sobre data/sonarmatch.db (5000 artistas), parámetros de reports/parametros_calibrados.json
- Usuarios con al menos un amigo: 1286 en validación, 551 en prueba (mismo split 70/30 y semilla que el protocolo base). Todos los amigos se consideran con consentimiento.
- β calibrado en validación: β = 0.00 → P@10 0.089, β = 0.10 → P@10 0.101, β = 0.25 → P@10 0.118, β = 0.50 → P@10 0.131, β = 0.75 → P@10 0.128. Elegido: **β = 0.50**.
- Amigos activos (con artistas en el catálogo) por usuario de prueba: mediana 6; 0 usuarios sin ninguno.
- Homofilia: en promedio, el 45.6 % de los artistas ocultos de un usuario aparece en el perfil de algún amigo.

## Conclusión

**Mejora.** Con β = 0.50, P@10 sube +0.050 en prueba (IC 95 % de la diferencia pareada: [+0.042, +0.058], que no incluye 0).

## Discusión

- **Homofilia frente a influencia.** HetRec es observacional: si los amigos ayudan, no se puede saber si es porque se parecen (homofilia) o porque se influyen (influencia). El sistema solo aprovecha la correlación, y para recomendar eso basta.
- El 45.6 % de los artistas ocultos está en el perfil de algún amigo: los amigos aportan artistas que el grafo de similitud no alcanzaba desde el perfil propio.
- **Dispersión del grafo social.** Mediana de 6 amigos activos (con artistas en el catálogo) por usuario de prueba; todos tienen al menos uno, así que β actúa sobre cada usuario.

## Resultados en prueba

| Amigos activos | Sistema | Usuarios | P@10 | R@10 | Novedad ↓ | ILS |
|---|---|---:|---:|---:|---:|---:|
| todos | actual (β = 0) | 551 | 0.084 | 0.125 | 0.689 | 0.395 |
| todos | con amigos (β = 0.50) | 551 | 0.134 | 0.190 | 0.765 | 0.298 |
| todos | con amigos sin R7 (β = 0.50) | 551 | 0.135 | 0.191 | 0.767 | 0.301 |
| 1–2 | actual (β = 0) | 119 | 0.066 | 0.107 | 0.686 | 0.360 |
| 1–2 | con amigos (β = 0.50) | 119 | 0.084 | 0.133 | 0.763 | 0.184 |
| 1–2 | con amigos sin R7 (β = 0.50) | 119 | 0.084 | 0.133 | 0.763 | 0.184 |
| 3–5 | actual (β = 0) | 135 | 0.084 | 0.142 | 0.683 | 0.390 |
| 3–5 | con amigos (β = 0.50) | 135 | 0.127 | 0.200 | 0.751 | 0.266 |
| 3–5 | con amigos sin R7 (β = 0.50) | 135 | 0.127 | 0.200 | 0.751 | 0.266 |
| más de 5 | actual (β = 0) | 297 | 0.092 | 0.125 | 0.694 | 0.410 |
| más de 5 | con amigos (β = 0.50) | 297 | 0.158 | 0.209 | 0.773 | 0.358 |
| más de 5 | con amigos sin R7 (β = 0.50) | 297 | 0.159 | 0.211 | 0.776 | 0.365 |
