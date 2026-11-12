# Pipeline de estimación mensual (SCRUM-38)

Código: `scripts/pipeline.py`.
Pruebas: `scripts/test_pipeline.py`.

## 1. Qué hace

Un solo comando deja la estimación del mes, su explicación y el registro:

1. **Descargas**: producción, granos, tipo de cambio, precios regulados,
   molienda, gasoil y nafta, aceite de soja y azúcar. Cada fuente se prueba
   hasta 3 veces, con pausas de 10 y 30 segundos. Si sigue fallando, avisa y
   sigue con los datos que ya había; si es la producción, frena (sin ella no
   se sabe qué mes estimar). Cuando el problema es que el sitio no responde, lo
   dice así: no es un error del programa.

   Con la producción se sabe el mes a estimar. **Si todavía no es el día 28 del
   mes siguiente**, avisa en ese momento que no se puede estimar y desde qué
   fecha volver a correr (las ventas de gasoil salen los días 25-27). Igual
   arma la base y completa los reales (pasos 3 y 4) y termina ahí.
2. **Exportaciones de INDEC**: procesa el CSV anual hasta el mes a estimar. El
   CSV se baja a mano (`docs/exportaciones_indec.md`). Distingue tres casos:
   INDEC todavía no publicó el mes (aviso: hay que esperar, sale alrededor del
   día 20), falta el CSV del año, o el CSV es viejo porque se bajó antes de que
   INDEC publicara el mes (hay que bajarlo de nuevo).
3. **Base**: `build_db.py`.
4. **Registro**: completa el real de las estimaciones anteriores que ya se
   publicaron (SCRUM-44). Va antes del control de los datos del mes, así se
   completan aunque después no se pueda estimar.
5. **Estimación**: el mes siguiente al último dato de producción, con el modelo
   final de cada serie (`results/comparacion_final_eleccion.csv`, SCRUM-34):
   suma contable para biodiésel y elastic net para bioetanol maíz, caña y total.
   El modelo se reentrena con todos los datos hasta el mes anterior, igual que
   en la evaluación.
6. **Contribuciones**: qué factores explican cada estimación (SCRUM-35).
7. **Registro**: agrega cada estimación con la variación del IACA que se
   publicaría (y la réplica del X-13 BCR para comparar), y sus contribuciones
   en `data/registro_contribuciones.csv`. Antes de escribir valida todo junto
   (ver la sección 3); si algo no cierra, no escribe ninguno de los dos
   archivos.

Salida: el registro, las contribuciones y un resumen en pantalla con la
estimación, la variación del IACA y los tres factores que más pesan en cada
serie. Los informes para la BCR (Excel y HTML) salen de lo que devuelve
`pipeline.correr()`.

Si todavía no están las ventas de gasoil o las exportaciones de INDEC del mes
a estimar, frena antes de estimar y dice cuál falta: la suma contable no puede
estimar sin ellas. Las ventas de gasoil salen los días 25-27 del mes siguiente
y las exportaciones de INDEC alrededor del día 20, así que la corrida mensual
va desde el 28.

Cuando frena por eso (antes del 28, porque faltan esos datos o porque el sitio
de la producción no responde) termina con
`NO SE ESTIMÓ (no es un error)` y código de salida 0: no hay nada roto, hay que
volver a correr más tarde. Los errores de verdad terminan con `ERROR` y código 1.

## 2. Uso

Desde la raíz del repo:

```bash
python scripts/pipeline.py                    # corrida mensual completa
python scripts/pipeline.py --sin-descargas    # con los datos que ya están
python scripts/pipeline.py --simular 2026-09  # demo con un mes ya publicado
```

`--simular` hace como si el mes no se hubiera publicado: oculta en memoria la
producción desde ese mes, estima y compara con el real. No descarga ni toca el
registro real: escribe en `results/simulacion/`.

## 3. Dónde queda cada cosa

| Archivo | Qué es | ¿Se versiona? |
|---|---|---|
| `data/registro_estimaciones.csv` | Registro de estimaciones (SCRUM-44) | Sí |
| `data/registro_contribuciones.csv` | Contribuciones de cada estimación del modelo final, una fila por factor, unidas por `estimacion_id` | Sí |
| `results/simulacion/` | Simulaciones | No |

**Contribuciones.** Columnas: `estimacion_id`, `factor`, `aporte` (tn o m³),
`aporte_variacion_produccion_pp` y `nota`. La serie y el mes salen del
registro por `estimacion_id`. Los puntos son de variación de la **producción**
contra el real del mes anterior, sin desestacionalizar: **no son puntos del
IACA**.

Siguen las mismas reglas que el registro (solo se agregan filas) y además,
antes de escribir los dos CSV, `registro.agregar` controla que:

- solo haya contribuciones de las estimaciones del modelo final de esta
  corrida, todas y ninguna de más (la fila del X-13 BCR no lleva);
- no esté la fila `total` (es la suma de las demás) ni factores repetidos;
- no haya vacíos ni valores no numéricos;
- los aportes de cada estimación sumen el pronóstico del registro;
- las filas anteriores de los dos archivos no cambien.

Escribe los dos en temporales, los vuelve a leer y controlar, y recién ahí los
reemplaza. La base las carga en la tabla `registro_contribuciones` y el Excel
del registro (`python scripts/registro.py exportar`) las trae en la hoja
"contribuciones", con la aclaración de que los puntos son de producción.

En la PC de la BCR el registro vive en la carpeta `data/` del proyecto. Como
ahí no se commitea, **conviene copiar los dos CSV del registro a un lugar con
respaldo** después de cada corrida.

## 4. Verificación

`python scripts/test_pipeline.py` simula la corrida en tres meses del holdout
(noviembre 2025, julio 2026 con la exportación oculta por INDEC y septiembre
2026) y comprueba que:

- el pronóstico es el mismo de `results/modelo_final_predicciones.csv`
  (SCRUM-34);
- la variación del IACA, del modelo final y del X-13 BCR, es la misma de
  `results/iaca_holdout_detalle.csv` (SCRUM-42);
- las contribuciones suman el pronóstico y el aviso de exportación estimada
  aparece solo en julio.

**Con qué datos.** La simulación no usa `data/bcr.db`, que cambia con cada
descarga: arma aparte, en `results/simulacion/base_evaluacion/` (no se
versiona), una base solo con las copias de
`data/snapshots/` hasta el **05/11/2026** (`FECHA_DATOS_EVALUACION` en la
prueba), que es la versión de los datos con que se corrió la evaluación. Así da
lo mismo en cualquier clon del repo, aunque antes se hayan bajado datos nuevos
(por ejemplo, una pizarra de la CAC más nueva cambia apenas el bioetanol de
maíz). Lo único que necesita es `data/snapshots/` completo, como está en el
repo; si falta alguna copia, lo dice. No toca la base ni el registro.

Si la prueba falla, el mensaje dice qué número no coincide. Las causas
posibles son un cambio en el código de un modelo, o que se rehízo la
evaluación con datos más nuevos y hay que actualizar `FECHA_DATOS_EVALUACION`.

También prueba que frene si faltan gasoil o exportaciones del mes, y que las
contribuciones no se repitan ni se pisen.

También prueba, sin red y sin X-13, que antes del 28 frene con la fecha para
volver a correr y complete igual los reales, que las descargas se reintenten y
digan cuándo el sitio no responde, y los tres avisos de INDEC.

Probado en Linux con Python 3.13.16, pandas 3.0.5, numpy 2.5.3,
scikit-learn 1.9.1, scipy 1.18.1, statsmodels 0.15.0, openpyxl 3.1.5 y
x13binary 1.1.61, y en Windows con un entorno nuevo (Python 3.14, en una ruta
con espacio y tilde): pasan las pruebas, la simulación y la corrida con
`--sin-descargas`. El X-13 da distinto en algunos meses entre Windows y Linux
(`docs/comparacion_final.md`, sección 8), así que la variación del IACA
registrada en la BCR puede diferir de la nuestra en esos meses. Es la que la
BCR publicaría con su máquina.

## 5. Si algo falla

| Mensaje | Qué hacer |
|---|---|
| `FALLÓ <fuente>: el sitio no responde` | No es un error del programa: el sitio está caído o no contesta (ya se reintentó 3 veces). Sigue con los datos anteriores de esa fuente. Si es la producción, termina con `NO SE ESTIMÓ (no es un error): El sitio de la Secretaría de Energía no responde…`, porque sin ella no se sabe qué mes estimar: esperar unas horas y volver a correr. El portal datos.energia.gob.ar no sirve de alternativa porque baja del mismo servidor. |
| `ERROR: No se pudo descargar la producción…` | La producción falló por otra causa (por ejemplo, cambió el archivo de la Secretaría). Pasarle el mensaje al equipo. |
| `FALLÓ <fuente>: <otro mensaje>` | Puede ser un cambio en el archivo de la fuente. Pasarle el mensaje al equipo. |
| `Todavía no se puede estimar <mes>. Volver a correr desde el <fecha>` | Es antes del 28 del mes siguiente. Igual se completaron los reales; volver a correr desde esa fecha. |
| `aviso INDEC todavía no publicó` | INDEC publica alrededor del día 20 del mes siguiente. Esperar. |
| `FALTA el CSV de INDEC` | Bajar el CSV del año (`docs/exportaciones_indec.md`) y volver a correr. |
| `VIEJO el CSV de INDEC` | Se bajó antes de que INDEC publicara el mes. Bajarlo de nuevo, borrar el anterior y volver a correr. |
| `Todavía no están los datos de <mes>` | Gasoil o exportaciones del mes no salieron todavía (por ejemplo, salieron tarde). Volver a correr cuando salgan. |
| `Ya está registrada` | Ese mes ya se estimó en esa misma corrida. |
