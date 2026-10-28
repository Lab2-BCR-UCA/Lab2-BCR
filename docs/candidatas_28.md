# Tabla de candidatas — EDA de variables externas (SCRUM-28)

Las candidatas se eligen por **mecanismo económico + disponibilidad a tiempo**
(SCRUM-26), no por significancia estadística. La CCF (correlación cruzada,
`results/ccf_candidatas.csv`) es **exploratoria**: se calcula sobre series
diferenciadas (log-diff) y **desestacionalizadas** (resta de la media de cada
mes, calculada **solo con datos anteriores a septiembre 2021**, anti-leakage), y
sirve para elegir qué rezagos probar, no para descartar.

## Nota metodológica

- **La CCF no descarta nada.** Mide solo relación lineal bivariada, tiene poca
  potencia con ~100 meses, y con ~180 pruebas se esperan ~9 falsos positivos al
  95%. La decisión de qué entra la toma el walk-forward (SCRUM-29/54).
- **Ojo con el `n` chico.** Las variables que arrancan en 2018 (precios
  regulados, margen) tienen una ventana pre-2021 de ~25-38 meses: su CCF es
  **poco confiable**. Se mantienen por mecanismo.
- **Tras desestacionalizar, la señal de los márgenes se cae.** El margen de
  biodiésel y el de maíz solo "ganan" en rezagos altos (10-11), que son ruido;
  en los rezagos con mecanismo (0-1) no hay correlación. Se mantienen **por
  mecanismo** (su evidencia es el colapso de nivel de 2020, no la variación
  mensual), no por la CCF.
- **Biodiésel: ninguna variable interna tiene CCF fuerte.** Es coherente con la
  descomposición contable (las *exportaciones* explican los saltos mensuales).
  Esa variable entra por la vía de INDEC (ticket nuevo), no está en esta tabla.

## Candidatas

| Variable | Mecanismo económico | Target | Rezago mín. (disp.) | Rezagos a probar | CCF (mejor · n) | Evidencia |
|---|---|---|---|---|---|---|
| **ventas_nafta** | Volumen de nafta sobre el que se aplica el corte de etanol | bioetanol (maíz, caña, total) | 0 | 0, 1, 2 | +0,37 total / +0,47 maíz / +0,73 caña @ rz0 · n≈107-139 | **Fuerte** |
| **ventas_gasoil** | Volumen de gasoil sobre el que se aplica el corte de biodiésel | biodiésel | 0 | 0, 1 | -0,24 @ rz5 · n≈134 | Débil (rezago alto, sin mecanismo claro) |
| **molienda_soja** | Disponibilidad de aceite (insumo del biodiésel) | biodiésel | 0 | 0, 1 | +0,30 @ rz0 · n=79 | Media |
| **margen_bioetanol_maiz** | Si el precio regulado no cubre el maíz, cae el incentivo a producir | bioetanol maíz | 0 | 0, 1 | +0,40 @ rz11 · n=27 (rezago alto) → **sin evidencia en la CCF** | Por mecanismo |
| **margen_domestico_biodiesel** | Si el precio no cubre el aceite, las plantas no entregan al corte (2020) | biodiésel | 0 | 0, 1 | mejor @ rz10 · -0,33 · n=33 → **sin señal en rz 0-1** | Por mecanismo (evidencia = colapso de nivel 2020, no variación mensual) |
| **precio_biodiesel** (regulado) | Precio de venta → rentabilidad | biodiésel | 0 | 0, 1 | +0,45 @ rz0 · n=28 | Débil (n chico) |
| **precio_bioetanol** (regulado) | Ídem para el etanol | bioetanol | 0 | 0, 1 | sin CCF (n<24 pre-2021) | Por mecanismo |
| **corte_efectivo** | Cumplimiento real de la mezcla (varió 3%→7% con norma fija) | ambos | 1 | 1 | pendiente (SCRUM-48) | Por mecanismo (datos pendientes) |

## Variables de régimen (no candidatas principales)

| Variable | Rol |
|---|---|
| **corte_nominal** | Explica **saltos de nivel** por cambio de norma. En el backtest (desde sep-2021) cambia una sola vez en biodiésel y ninguna en bioetanol → sirve en el entrenamiento como régimen, no como predictor del mes a mes. |

## Candidatas débiles / que entran por otra vía

| Variable | Decisión |
|---|---|
| **precio_soja_pizarra**, **precio_maiz_pizarra** | Entran al modelo **vía el margen**, no sueltas: son el denominador del cociente. Sueltas, su CCF aparece en rezagos altos con `n` chico (poco confiable). |

## Probables falsos positivos (CCF alta sin mecanismo directo)

| Variable | Por qué se marca | Decisión |
|---|---|---|
| **tipo_cambio** @ rezago 9-10 | +0,23 a +0,34 en bioetanol pero con `n`≈33 y rezago alto, sin mecanismo directo (el TC influye **a través del margen**, no solo). | No entra suelta; su efecto va por el margen. |
| **margen** a rezago 4-11 contra series que no le corresponden (p. ej. margen de biodiésel contra bioetanol) | Rezago alto, `n` chico, sin mecanismo cruzado. | Azar; cada margen es candidato solo de su propia serie. |
| Variables a **rezago ≥ 9** en general | Con ventana corta y muchos rezagos probados, un rezago alto "ganador" suele ser azar. | Se prueban solo los rezagos con mecanismo (0-2), no el "mejor" de la CCF. |

## Exportaciones

| Variable | Decisión |
|---|---|
| **exportaciones_biodiesel** | Son lo que explica los **saltos mensuales** del biodiésel (la descomposición contable les atribuye ~100% de la variación). Entran por la vía de **INDEC** (rezago 0, verificado), que es un ticket de datos aparte; esta tabla es de variables externas de mercado interno. |

## Pendiente de datos

Falta el **corte** (SCRUM-48): cuando entre a la base se recalcula la CCF y se
completa su fila. Para biodiésel, el driver real (exportaciones de INDEC) y el
azúcar para la caña se suman cuando estén sus tickets de datos.
