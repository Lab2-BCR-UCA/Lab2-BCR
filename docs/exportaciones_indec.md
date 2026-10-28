# Exportaciones de biodiesel según INDEC (SCRUM-57)

## Por qué esta fuente

Las exportaciones son el componente que más mueve la producción de biodiesel.
Desde septiembre 2021 explican cerca del 100% de la variación mensual de la
producción (88% de la interanual); las ventas al corte, entre 8% y 12%.
Ejemplo: en agosto 2026 la producción subió 45.507 tn y las exportaciones
62.176 tn, mientras el mercado interno no se movió.

El problema es el calendario. La Secretaría de Energía publica las
exportaciones en el mismo archivo que la producción, con dos meses de rezago:
cuando la BCR estima el mes t, todavía no las tiene (rezago 1). INDEC publica
el comercio exterior del mes alrededor del **día 20 del mes siguiente**, antes
de que la BCR haga la estimación (días 22 a 28). Por eso entra con **rezago 0**.

## Cómo se baja (cada mes)

1. Entrar a https://comex.indec.gob.ar (Sistema de Consulta de Comercio
   Exterior de Bienes).
2. Completar:
   - Tipo de comercio: **Exportación**
   - Año: el año en curso
   - Período: **Mensual**
   - Consulta por país: **Total exportado** (no "Todos los países
     (desagregado)": el procesador lo rechaza)
   - Productos: **38260000** (Biodiésel y sus mezclas, sin aceites de petróleo
     o con un contenido ≤ 70%)
3. Descargar el CSV y ponerlo en `variables_externas/data/indec_biodiesel/`
   **con el nombre que le pone INDEC** (`Resultado de la búsqueda_<año>_<número>.csv`),
   y borrar el archivo anterior de ese año. El número del nombre es la fecha y
   hora de la descarga, y el procesador lo usa para el control del paso 4: si
   se renombra el archivo, hay que conservar el número.
4. Correr, desde la raíz del repo, indicando el último mes que ya publicó
   INDEC (por ejemplo, después del 20/11 se puede usar octubre):

   ```bash
   python variables_externas/procesar_indec_biodiesel.py --hasta 2026-10
   python scripts/build_db.py
   ```

5. Commitear el CSV anual, los dos CSV de `data/`, la copia nueva de
   `data/snapshots/` y el manifiesto.

El sistema solo permite bajar un año por vez. El histórico 2012-2026 ya está en
el repo (bajado el 27/10/2026).

## Formato de INDEC y salidas

El CSV de INDEC usa `;` como separador, `.` para miles y `,` para decimales. Un
mes con exportación tiene su fila; un mes sin exportación **no aparece**; un mes
con el monto protegido por secreto estadístico trae `s` en peso y valor.

`procesar_indec_biodiesel.py` escribe dos archivos, porque la base no admite
valores nulos:

| Archivo | Meses | Columnas |
|---|---|---|
| `data/exportaciones_biodiesel_indec.csv` | Todos los publicados (2012-01 en adelante) | `expo_indec_hubo` (1 si INDEC registra exportación, con monto o con `s`), `expo_indec_oculto` (1 si el monto viene con `s`) |
| `data/exportaciones_biodiesel_indec_tn.csv` | Solo los de monto visible | `expo_indec_tn` (toneladas, 0 si no hubo exportación), `expo_indec_fob_usd` |

A la base entran solo dos series, las que usa el modelo: `expo_indec_tn` y
`expo_indec_oculto`. Las otras dos columnas quedan en los CSV para consulta:
`expo_indec_hubo` se deduce de las anteriores (hubo exportación si las
toneladas son mayores a 0 o si el mes está oculto) y `expo_indec_fob_usd` no
hace falta porque se predicen toneladas. `expo_indec_tn` tiene
`huecos_esperados = si`: los meses ocultos aparecen como aviso de meses
faltantes, no como error.

**Último mes publicado (`--hasta`, obligatorio).** Un mes sin fila puede ser
"sin exportación" o "todavía no publicado", y el archivo no permite
distinguirlos. Si se corriera el procesador con un archivo viejo, el último mes
entraría como exportación 0 sin ningún aviso, y es la variable principal del
biodiesel. Por eso:

- `--hasta` es obligatorio: hay que decir hasta qué mes publicó INDEC.
- El procesador frena si el archivo del año de `--hasta` se bajó antes del día
  20 del mes siguiente (antes de que INDEC lo publicara). La fecha de descarga
  sale del número que INDEC pone en el nombre del archivo.
- También frena si hay dos archivos del mismo año o si falta el número en el
  nombre.

El día 20 es aproximado: si INDEC publica más tarde (por ejemplo el 22) y el
archivo se bajó el 21, el control no lo detecta. Ante la duda, bajar el
archivo después de ver publicado el informe de intercambio comercial del mes.

## Validación contra la Secretaría de Energía

Comparación mes a mes de 2012-01 a 2026-08 (176 meses):

| Prueba | Resultado |
|---|---|
| Coinciden en si hubo exportación en el mes | 175 de 176 meses (99,4%) |
| Correlación de las toneladas (meses con monto visible, n = 157) | 0,996 |
| Meses con exportación y monto visible | 131 |
| De esos, diferencia menor al 1% | 96 |
| De esos, diferencia mayor al 10% | 10 |

Las diferencias grandes son barcos que cada fuente anotó en meses vecinos: lo
que le falta a un mes le sobra al siguiente (por ejemplo, julio-agosto 2024:
−19.500 tn y +19.500 tn). INDEC registra la exportación en el mes en que
termina la carga del barco. El único desacuerdo en "hubo o no hubo" es octubre
2019 (INDEC con `s`, Secretaría con 0), probablemente por el mismo motivo.

Con datos al 27/10/2026, INDEC ya muestra **50.000 tn exportadas en septiembre
2026**, un mes que la Secretaría publica recién a principios de noviembre.

## Secreto estadístico (`s`)

INDEC oculta el monto cuando publicarlo permitiría identificar a una empresa
(Ley 17.622, art. 10). No hay una regla publicada del tipo "menos de N
exportadores".

- Hay **19 meses con `s`**, todos desde 2018 (1 en 2018, 1 en 2019, 2 en 2020,
  2 en 2021, 3 en 2022, 5 en 2023, 1 en 2024, 1 en 2025 y 3 en 2026).
- En el backtest (septiembre 2021 a agosto 2025) hay 35 meses con exportación
  y **12 con `s`**.
- Según la Secretaría, esos meses fueron siempre chicos: entre 0 y 50.482 tn,
  mediana **27.784 tn** (media 25.960). Los meses visibles desde 2018 tienen
  una mediana de 90.000 tn. Es consistente con que exportaron pocas empresas,
  aunque INDEC no lo dice.

**Tratamiento (en el constructor de features, SCRUM-59, no en la base):**

- Para entrenar no hay problema: el monto real de los meses ocultos ya lo
  publicó la Secretaría.
- Si el mes que se estima viene con `s`, se completa con la mediana de las
  exportaciones de la Secretaría en los meses ocultos anteriores, calculada
  solo con datos hasta t-1. Se agrega además el indicador `expo_indec_oculto`.

## Limitaciones

- **Versión revisada.** El histórico bajado es la versión actual de INDEC, que
  puede haber corregido las cifras provisorias publicadas en su momento. El
  backtest con estos datos es algo optimista. Desde ahora cada descarga queda
  versionada en `data/snapshots/`, así el registro de estimaciones usa lo que
  realmente se sabía.
- **Descarga manual.** El sistema de consulta de INDEC no tiene un endpoint de
  descarga documentado; el CSV del año se baja a mano cada mes.
- **Fecha de publicación.** Confirmar con la publicación de octubre (alrededor
  del 19/11/2026) que el sistema de consulta se actualiza el mismo día que el
  informe de Intercambio Comercial Argentino.

## Fuentes

- INDEC, Sistema de Consulta de Comercio Exterior de Bienes:
  https://comex.indec.gob.ar
- INDEC, Metodología de comercio exterior (publicación a los 20 días del
  cierre; registro por fecha de fin de carga):
  https://www.indec.gob.ar/ftp/cuadros/economia/metodologia_comex.pdf
- INDEC, Intercambio Comercial Argentino, septiembre 2026 (publicado el
  19/10/2026): https://www.indec.gob.ar/uploads/informesdeprensa/ica_10_263F42E3F39F.pdf
