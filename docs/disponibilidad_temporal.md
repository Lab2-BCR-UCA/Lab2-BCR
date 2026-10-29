# Disponibilidad temporal de las variables (SCRUM-26)

Objetivo: no usar información que la BCR **no tendría** en el momento de
estimar. La tabla legible por código está en
[`data/disponibilidad_variables.csv`](../data/disponibilidad_variables.csv) y
es la que leen los notebooks para armar las features.

## Momento de estimación

- La BCR publica el IACA del mes `t` a **fines de `t+1`**. Ejemplo: el IACA de
  julio-2026 salió el **28/8/2026**.
- **Confirmado en la reunión del 20/10 (Belén Maldonado):** no hay inconveniente
  en **esperar a que los datos estén disponibles** antes de correr la
  estimación; cuando una fuente no publica a tiempo, la bolsa **estima** ese
  dato. Es decir, la estimación no tiene un corte rígido anterior al día 25-27:
  la BCR dispone de los datos del mes `t` (o de su propia estimación) al momento
  de estimar.
- **Validación de los rezagos (criterio del DoD):** no existe una fecha de
  cierre fija; la validación es precisamente que la BCR confirmó que **no hay
  corte rígido** y espera / estima los datos. Con eso queda cerrado el punto
  "rezagos validados contra la fecha de cierre real".
- La Secretaría de Energía publica la producción con **dos meses de rezago**
  (a principios de noviembre, septiembre). Al estimar `t`, el último dato de
  producción disponible es `t-1` (confirmado por la BCR, mail del 9/10). Esto
  coincide con el walk-forward del protocolo de evaluación.

**Regla:** una variable externa del mes `t` puede usarse sin rezago
(`rezago_min = 0`) si la BCR la tiene al estimar. Tras la confirmación del
20/10, esto incluye las ventas de combustible y la molienda de soja, que se
publican entre los días 25-27 de `t+1`: la BCR las espera. Las variables que
derivan del archivo de producción (corte efectivo, exportaciones) heredan su
rezago de 2 meses y quedan en `rezago_min = 1`.

Convención de rezago (la misma del EDA de variables externas): rezago `k`
significa usar `x[t-k]` para estimar `y[t]`.

## Tabla

| Variable | Fuente | Frecuencia | Publica el mes `t` | ¿Mismo mes? | Rezago mín. | Estado |
|---|---|---|---|---|---|---|
| Producción biodiesel / bioetanol (target) | Secretaría de Energía | Mensual | Principios de `t+2` | No | **1** | Confirmado (mail BCR) |
| Tipo de cambio | BCRA | Diaria | Cierre de `t` | Sí | **0** | Confirmado |
| Precio pizarra soja / maíz | Cámara Arbitral (BCR) | Diaria | Cierre de `t` | Sí | **0** | Confirmado |
| Precio regulado biodiesel / bioetanol caña / maíz | Secretaría de Energía | Mensual (por resolución) | Antes o al inicio de `t` | Sí | **0** | Confirmado |
| Molienda de soja | SAGyP | Mensual | Días 22-28 de `t+1` | Sí | **0** | Confirmado (reunión 20/10) |
| Ventas de gasoil / nafta | Secretaría de Energía (SESCO) | Mensual | Días 25-27 de `t+1` | Sí | **0** | Confirmado (reunión 20/10) |
| Corte nominal | Boletín Oficial / Sec. Energía | Mensual (por norma) | Vigente desde la norma | Sí | **0** | Confirmado |
| Corte efectivo | Sec. Energía (ventas al corte) | Mensual | Principios de `t+2` | No | **1** | Confirmado |
| Aceite de soja | Banco Mundial (Pink Sheet) | Mensual | Principios de `t+1` | Sí | **0** | Confirmado (SCRUM-49, publica días 2-4 de `t+1`) |
| Azúcar (precio internacional) | Banco Mundial (Pink Sheet) | Mensual | Principios de `t+1` | Sí | **0** | Mismo archivo que el aceite (SCRUM-58) |
| IPC | INDEC | Mensual | ~día 13 de `t+1` | Sí | **0** | Según calendario de la fuente (SCRUM-50) |
| Margen doméstico biodiesel | Derivada (precio / aceite × TC) | Mensual | Dentro de `t+1` | Sí | **0** | Confirmado (sigue al aceite, SCRUM-49) |
| Margen bioetanol de maíz | Derivada (precio / pizarra maíz) | Mensual | Cierre de `t` | Sí | **0** | Confirmado (SCRUM-52) |
| Exportaciones de biodiesel | Secretaría de Energía | Mensual | Principios de `t+2` | No | **1** | Confirmado |

### Evidencia por variable

- **Precios regulados:** se fijan por resolución para el mes. El IACA de
  julio-2026 ya cita los precios de julio (biodiesel 1.924.080 $/tn, bioetanol
  caña 1.043,6 $/l y maíz 956,5 $/l), iguales a los de `data/`.
- **Tipo de cambio y pizarra:** series diarias; el promedio mensual de `t`
  está completo al cierre de `t`.
- **Molienda de soja y ventas de combustible:** se publican entre los días
  22 y 27 de `t+1`. En la reunión del 20/10 Belén confirmó que la bolsa espera
  a que estén disponibles (o las estima), así que el dato de `t` está al
  estimar. Por eso pasan a `rezago_min = 0` (antes estaban en 1 por prudencia).
- **Corte nominal:** lo fija la norma y se conoce de antemano; es una variable
  de régimen.
- **Corte efectivo y exportaciones:** derivan del archivo de producción de la
  Secretaría, que llega con 2 meses de rezago, así que el último disponible es
  `t-1`.
- **Aceite de soja (Banco Mundial):** el Excel se actualiza en los primeros
  días hábiles de `t+1` (el dato de septiembre 2026 salió el 2/10/2026 y la
  próxima edición está anunciada para el 3/11/2026), antes de que salga la
  producción de `t`. Confirmado en SCRUM-49; detalle en `docs/aceite_soja.md`.
- **Margen doméstico del biodiesel:** sus tres insumos (precio regulado, tipo
  de cambio y aceite) son de rezago 0 y están confirmados, así que también
  queda confirmado.
- **Azúcar (Banco Mundial):** sale del mismo Excel que el aceite de soja
  (columna "Sugar, world", USD/kg), así que tiene el mismo calendario y
  rezago 0. Es el precio internacional: los ingenios venden sobre todo en el
  mercado interno, así que es una aproximación (SCRUM-58).
- **IPC:** INDEC publica el IPC de `t` alrededor del día 13 de `t+1`.

## Impacto en el modelo

El cambio de las ventas de combustible y la molienda a `rezago_min = 0` es
favorable: en el EDA la correlación de las ventas de nafta con bioetanol de
maíz y caña es mucho mayor en rezago 0 (≈ 0,49-0,50) que en rezago 1
(≈ 0,27-0,30), y lo mismo la molienda de soja con el biodiesel (0,34 en rezago
0 contra 0,17 en rezago 4).

## Nota sobre `db/series.csv`

Las variables que ya existen están en `db/series.csv`. El alta de las nuevas
(corte, aceite de soja, IPC, márgenes) en `db/series.csv` **se mueve a los
tickets de datos SCRUM-48 a 52**, que son los que generan las columnas: ahí se
agregan con su `serie_id` y `columna_origen` reales. Esta tabla de
disponibilidad ya fija el rezago que deberán usar. (Decisión de alcance a
confirmar con el equipo; de aceptarse, sacar ese ítem del DoD del 26 y pasarlo
a 48-52.)

## Limitación: versiones de los datos

La BCR no puede reconstruir qué versión de cada dato tenía en cada fecha (mail
del 9/10: el historial de SharePoint mezcla información confidencial y
rehacerlo es muy costoso). Por lo tanto esta tabla controla **qué mes** de
cada variable se usa, pero no **qué versión**: el backtest usa los valores
actuales, que pueden incluir revisiones posteriores (por ejemplo, los
provisorios de la SE). El registro mensual de estimaciones (SCRUM-44) servirá
para medir esto hacia adelante.

## Limitación: dato real vs. estimación de la BCR en rezago 0

La molienda de soja y las ventas de combustible quedan en `rezago_min = 0`
porque la BCR espera a que se publiquen. Pero la propia BCR aclaró que, cuando
**no** salen a tiempo, usa una **estimación propia** en lugar del dato real. El
backtest, en cambio, usa siempre el **dato real** de ese mes. Por lo tanto, en
los meses en que la BCR haya trabajado con su estimación, el backtest es
**algo optimista** respecto de la información que ellos tenían realmente. No es
leakage de futuro (el dato es del mes `t`, no posterior), pero sí una ventaja
de calidad de dato que conviene tener presente al comparar contra el modelo de
la BCR.
