# Base de datos unificada (SCRUM-27)

Una base SQLite con todas las series mensuales del proyecto (producción y
variables externas), con historia de versiones: cada descarga que cambia un
dato se agrega sin pisar la anterior.

## Uso

Desde la raíz del repo:

```
python scripts/build_db.py                      # guarda las versiones nuevas y arma la base
python scripts/build_db.py --solo-reconstruir   # arma la base solo con las versiones guardadas
python scripts/test_build_db.py                 # pruebas sobre una copia temporal del repo
```

La base queda en `data/bcr.db`. No se versiona: cada uno la genera en su
máquina y todos obtienen la misma, porque sale de archivos que sí están en el
repo.

Para leer el dataset desde un notebook:

```python
import sys; sys.path.insert(0, "../scripts")
from build_db import leer_dataset
df = leer_dataset("../data/bcr.db")   # una fila por mes, una columna por serie
```

## Cómo funcionan las versiones

La fuente de verdad son las **copias fechadas** en `data/snapshots/`, no la
base. La base es un derivado y se puede borrar y regenerar cuando se quiera.

1. Cada vez que corre, `build_db.py` compara cada CSV de `db/fuentes.csv` con
   la última copia guardada (por hash del contenido).
2. Si cambió, guarda una copia nueva en `data/snapshots/<fuente>/<fecha>.csv`
   y la anota en `data/snapshots/manifiesto.csv`.
3. Arma la base desde cero cargando todas las copias del manifiesto.

Fecha de cada copia:

- La **primera** copia de cada fuente toma la fecha del último commit que
  modificó el CSV (`origen = commit`): es lo más cercano a la fecha real de
  descarga que tenemos.
- Las **siguientes** toman la fecha del día (`origen = carga`), o la que se
  pase con `--fecha-descarga`.

Detalles:

- El hash se calcula con los saltos de línea unificados, así un clon en
  Windows no genera versiones falsas.
- Si una descarga nueva no pasa los controles, se deshace todo: no se guarda
  la copia, el manifiesto queda como estaba y la base anterior sigue intacta.
- Una copia editada a mano se detecta porque su hash no coincide con el del
  manifiesto.

**Importante:** las copias y el manifiesto se commitean. Son los que guardan
la historia.

## Esquema

```
fuentes ──< series ──< observaciones >── descargas >── fuentes
                  └──< registro_estimaciones
```

| Tabla | Una fila por | Clave | Contenido |
|---|---|---|---|
| `fuentes` | archivo CSV de origen | `fuente` | Ruta y descripción. Sale de `db/fuentes.csv`. |
| `series` | variable mensual | `serie_id` | Fuente, columna de origen, unidad, tipo (`objetivo`, `auxiliar`, `externa`), rezago mínimo y si tiene huecos esperados. Sale de `db/series.csv`; el rezago mínimo se toma de `data/disponibilidad_variables.csv` (SCRUM-26). |
| `descargas` | versión cargada de una fuente | `descarga_id` | Fecha de descarga, archivo de la copia, hash, filas y origen (`commit` o `carga`). |
| `observaciones` | serie, mes y versión | `serie_id` + `fecha` + `descarga_id` | El valor y, en producción, si era provisorio en esa versión. |
| `registro_estimaciones` | estimación de un modelo | `estimacion_id` | Vacía por ahora. La completa el pipeline (SCRUM-38 y SCRUM-44): pronóstico, modelo, configuración, versión de los datos usada y, cuando se publica, el real y el error. |

Vistas:

| Vista | Qué devuelve |
|---|---|
| `v_ultima_version` | Para cada serie y mes, el valor de la descarga más reciente. Formato largo. |
| `v_dataset_mensual` | Lo mismo, una fila por mes y una columna por serie. Se genera desde el catálogo, así una serie nueva aparece sola. |

Hoy son 8 fuentes y 26 series: 4 objetivo (biodiesel y bioetanol total, de
maíz y de caña), 6 auxiliares (ventas y exportaciones del mismo archivo de
producción) y 16 externas.

### Consultas útiles

```sql
-- Todas las versiones de un dato (ej.: cómo se fue revisando julio 2026)
SELECT d.fecha_descarga, o.valor, o.provisorio
FROM observaciones o JOIN descargas d USING (descarga_id)
WHERE o.serie_id = 'produccion_biodiesel_tn' AND o.fecha = '2026-07-01'
ORDER BY d.fecha_descarga;

-- Qué se sabía en una fecha dada (base para backtests con versiones reales)
SELECT o.serie_id, o.fecha, o.valor
FROM observaciones o JOIN descargas d USING (descarga_id)
WHERE d.fecha_descarga <= '2026-11-01'
  AND d.descarga_id = (
      SELECT MAX(d2.descarga_id) FROM observaciones o2 JOIN descargas d2 USING (descarga_id)
      WHERE o2.serie_id = o.serie_id AND o2.fecha = o.fecha AND d2.fecha_descarga <= '2026-11-01');
```

## Controles de calidad

Corren en cada armado. Si alguno falla, la base no se genera y se informa
qué serie, qué copia y qué mes.

| Control | Qué pasa si falla |
|---|---|
| Mes duplicado en un archivo | Error |
| Valores nulos | Error |
| Valores negativos | Error |
| Meses faltantes dentro del rango de la serie | Error, salvo en series con `huecos_esperados = si`, donde es un aviso |
| Columna del catálogo que no está en el archivo | Error |
| Copia modificada a mano (hash distinto) | Error |
| Serie con una variable que no está en la tabla de disponibilidad | Error |

Hoy los únicos avisos son los huecos conocidos de los precios regulados:
28 meses en biodiesel y 41 en bioetanol (ver `docs/fuentes_series.md`).

## Agregar una fuente o una serie

1. Si es un archivo nuevo, sumar una fila en `db/fuentes.csv`.
2. Sumar una fila por columna en `db/series.csv`.
3. Si es una variable nueva, sumarla en `data/disponibilidad_variables.csv`
   con su rezago mínimo.
4. Correr `python scripts/build_db.py` y commitear la copia nueva y el
   manifiesto.

## Relación con otras partes del repo

- `scrape_produccion_se.py` también guarda copias fechadas en
  `data/historico/`, que no se versiona. Es redundante con `data/snapshots/`;
  se puede quitar más adelante.
- Por ahora los notebooks siguen leyendo los CSV. Pasar a `leer_dataset()` es
  opcional y conviene hacerlo al arrancar cada modelo (Sprint 3).
