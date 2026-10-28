# Base de datos unificada (SCRUM-27)

Una base SQLite con todas las series mensuales del proyecto (producción y
variables externas), con historia de versiones: cada descarga que cambia un
dato se agrega sin pisar la anterior. Las variables derivadas (márgenes,
precios deflactados) se calculan dentro del armado y se versionan igual
(SCRUM-56).

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
              │   └──< registro_estimaciones   │
              └──< series_insumos              └──< descargas_insumos
```

| Tabla | Una fila por | Clave | Contenido |
|---|---|---|---|
| `fuentes` | archivo CSV de origen | `fuente` | Ruta y descripción. Sale de `db/fuentes.csv`. |
| `series` | variable mensual | `serie_id` | Fuente, columna de origen, unidad, tipo (`objetivo`, `auxiliar`, `externa`), rezago mínimo, si tiene huecos esperados, clase (`cruda` o `derivada`) y relleno (`ffill` o `ninguno`). Las crudas salen de `db/series.csv` y las derivadas de `db/derivadas.csv`; el rezago mínimo se toma de `data/disponibilidad_variables.csv` (SCRUM-26). |
| `series_insumos` | insumo de una derivada | `serie_id` + `insumo_serie_id` | Qué series crudas usa cada derivada. |
| `descargas` | versión cargada de una fuente | `descarga_id` | Fecha de descarga, archivo de la copia, hash, filas y origen (`commit`, `carga` o `derivada`). Las versiones de derivadas no tienen archivo y dicen de qué derivada son en `serie_derivada`. |
| `descargas_insumos` | insumo usado por una versión de una derivada | `descarga_id` + `insumo_descarga_id` | Linaje: con qué descargas de los insumos se calculó cada versión. |
| `observaciones` | serie, mes y versión | `serie_id` + `fecha` + `descarga_id` | El valor y, en producción, si era provisorio en esa versión. |
| `registro_estimaciones` | estimación de un modelo | `estimacion_id` | Vacía por ahora. La completa el pipeline (SCRUM-38 y SCRUM-44): pronóstico, modelo, configuración, versión de los datos usada y, cuando se publica, el real y el error. |

Vistas:

| Vista | Qué devuelve |
|---|---|
| `v_ultima_version` | Para cada serie y mes, el valor de la descarga más reciente. Formato largo. |
| `v_dataset_mensual` | Lo mismo, una fila por mes y una columna por serie. Se genera desde el catálogo, así una serie nueva aparece sola. |

Hoy son 10 fuentes y 36 series: 30 crudas (4 objetivo, que son biodiesel y
bioetanol total, de maíz y de caña; 6 auxiliares, que son ventas y
exportaciones del mismo archivo de producción; y 20 externas) y 6 derivadas:
los márgenes del bioetanol de maíz (SCRUM-52) y del biodiesel (SCRUM-51) y los
cuatro cortes efectivos (SCRUM-48, ver `docs/corte.md`).

### Consultas útiles

```sql
-- Todas las versiones de un dato (ej.: cómo se fue revisando julio 2026)
SELECT d.fecha_descarga, o.valor, o.provisorio
FROM observaciones o JOIN descargas d USING (descarga_id)
WHERE o.serie_id = 'produccion_biodiesel_tn' AND o.fecha = '2026-07-01'
ORDER BY d.fecha_descarga;

-- Con qué versiones de los insumos se calculó cada versión de una derivada
SELECT d.fecha_descarga AS version, i.fuente, i.fecha_descarga AS version_insumo
FROM descargas d
JOIN descargas_insumos l ON l.descarga_id = d.descarga_id
JOIN descargas i ON i.descarga_id = l.insumo_descarga_id
WHERE d.serie_derivada = 'margen_bioetanol_maiz'
ORDER BY 1, 2;

-- Qué se sabía en una fecha dada (base para backtests con versiones reales;
-- incluye las derivadas, coherentes con sus insumos a esa fecha)
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
| Derivada con función o insumo inexistente, o con una derivada como insumo | Error |
| Derivada con rezago menor que el de alguno de sus insumos | Error (sería leakage) |
| Derivada con valores infinitos (división por cero) | Error |
| Insumo con relleno `ffill` rellenado más de 3 meses al final | Aviso (puede ser una descarga atrasada) |

Hoy los únicos avisos son los huecos conocidos de los precios regulados:
28 meses en biodiesel y 41 en bioetanol (ver `docs/fuentes_series.md`). Son
meses sin resolución nueva: el precio anterior sigue vigente.

## Agregar una fuente o una serie

1. Si es un archivo nuevo, sumar una fila en `db/fuentes.csv`.
2. Sumar una fila por columna en `db/series.csv`, con `relleno = ffill` si el
   valor sigue vigente hasta el próximo dato (precios regulados) o `ninguno`.
3. Si es una variable nueva, sumarla en `data/disponibilidad_variables.csv`
   con su rezago mínimo.
4. Correr `python scripts/build_db.py` y commitear la copia nueva y el
   manifiesto.

## Variables derivadas

Una derivada se calcula a partir de otras series de la base (por ejemplo, el
margen del bioetanol a partir del precio regulado y la pizarra de maíz). No
se descarga ni se guarda en `data/snapshots/`: el armado la recalcula cada vez
desde las crudas, así nunca queda desactualizada respecto de sus insumos.

Cómo se versiona:

1. Las fechas de versión de una derivada son las fechas de descarga de sus
   insumos.
2. En cada fecha se toma el estado de los insumos tal como se conocía ese día,
   se aplica el relleno declarado y se calcula la fórmula.
3. Si el resultado cambió respecto de la versión anterior, se guarda una
   versión nueva con esa fecha y su linaje en `descargas_insumos`.

Así la consulta "qué se sabía en una fecha dada" devuelve la derivada
coherente con sus insumos a esa fecha, que es lo que necesitan los backtests.

**Relleno.** La columna `relleno` de `db/series.csv` dice cómo completar los
huecos de una serie cuando se usa como insumo. Los precios regulados van con
`ffill`: el precio sigue vigente hasta la siguiente resolución. El relleno se
aplica solo al calcular derivadas; las observaciones crudas quedan como
vinieron. Las fórmulas no rellenan por su cuenta.

Para agregar una derivada:

1. Escribir la fórmula en `scripts/derivadas.py` (la firma está explicada al
   principio del archivo).
2. Sumar una fila en `db/derivadas.csv` con la función y los insumos
   separados por `|`. Los insumos tienen que ser crudas.
3. Sumar la variable en `data/disponibilidad_variables.csv`, con un rezago
   mayor o igual al de sus insumos.
4. Correr `python scripts/build_db.py`. No hay copias nuevas que commitear por
   la derivada.

## Relación con otras partes del repo

- `scrape_produccion_se.py` también guarda copias fechadas en
  `data/historico/`, que no se versiona. Es redundante con `data/snapshots/`;
  se puede quitar más adelante.
- Por ahora los notebooks siguen leyendo los CSV. Pasar a `leer_dataset()` es
  opcional y conviene hacerlo al arrancar cada modelo (Sprint 3).
