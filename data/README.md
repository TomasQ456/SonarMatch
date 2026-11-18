# data/

Todo lo de esta carpeta está en `.gitignore`, salvo este archivo y `mapeo_manual.csv`.

- `sonarmatch.db`: base SQLite. Se crea con
  `python -m sonarmatch.adapters.inbound.cli ingest` (necesita `LASTFM_API_KEY` en `.env` o en
  el entorno; `MB_USER_AGENT` es opcional, ver `.env.example`) o, sin API key, con
  `ingest --fixture`, que carga el catálogo **sintético** de demostración (51 artistas). Con
  `--semillas-hetrec data/hetrec2011-lastfm-2k` la búsqueda empieza también por los artistas
  más escuchados de HetRec, para que el catálogo empareje con más usuarios de la evaluación.
- `mapeo_manual.csv` (`tag,qid,comentario`): mapeos de etiquetas a géneros de Wikidata
  revisados a mano; tienen prioridad sobre el mapeo automático.
- `hetrec2011-lastfm-2k/`: dataset HetRec 2011 Last.fm 2K de GroupLens, para la evaluación.
  Descárgalo de <https://files.grouplens.org/datasets/hetrec2011/hetrec2011-lastfm-2k.zip> y extrae
  `artists.dat`, `user_artists.dat`, `user_friends.dat` (y `tags.dat` y
  `user_taggedartists.dat` para `scripts/mapeo_hetrec.py`) en esa carpeta. Luego:
  `python -m sonarmatch.adapters.inbound.cli evaluate`
  (o `evaluate --dataset csv --ruta perfiles.csv` con columnas `user_id,artist_name,peso`) y
  `python -m sonarmatch.adapters.inbound.cli evaluate-social` (dimensión social).
