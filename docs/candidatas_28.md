# Tabla de candidatas — EDA de variables externas (SCRUM-28)

Las candidatas se eligen por **mecanismo económico + disponibilidad a tiempo**
(SCRUM-26), no por significancia estadística. La CCF (correlación cruzada,
`results/ccf_candidatas.csv`) es **exploratoria**: se calcula sobre series
diferenciadas y **solo con datos anteriores a septiembre 2021** (anti-leakage),
y sirve para elegir qué rezagos probar, no para descartar.

## Nota metodológica

- **La CCF no descarta nada.** Mide solo relación lineal bivariada, tiene poca
  potencia con ~100 meses, y con ~180 pruebas se esperan ~9 falsos positivos al
  95%. La decisión de qué entra la toma el walk-forward (SCRUM-29/54).
- **Ojo con el `n` chico.** Las variables que arrancan en 2018 (precios
  regulados, margen) tienen una ventana pre-2021 de ~25-38 meses: su CCF es
  **poco confiable** (se sobreajusta fácil). Se mantienen por mecanismo, con la
  correlación marcada como evidencia débil.

## Candidatas

| Variable | Mecanismo económico | Target | Rezago mín. (disp.) | Rezagos a probar | CCF (mejor · n) | Evidencia |
|---|---|---|---|---|---|---|
| **ventas_nafta** | Volumen de nafta sobre el que se aplica el corte de etanol | bioetanol (maíz, caña, total) | 0 | 0, 1, 2 | +0,50/+0,57 @ rz0 · n≈107-139 | **Fuerte** |
| **ventas_gasoil** | Volumen de gasoil sobre el que se aplica el corte de biodiésel | biodiésel | 0 | 0, 1 | -0,27 @ rz5 · n≈134 | Media |
| **molienda_soja** | Disponibilidad de aceite (insumo del biodiésel) | biodiésel | 0 | 0, 1 | +0,33 @ rz0 · n=79 | Media |
| **margen_bioetanol_maiz** | Si el precio regulado no cubre el maíz, cae el incentivo a producir | bioetanol maíz | 0 | 0, 1 | +0,43 @ rz0 · n=38 | Débil (ventana corta) — por mecanismo |
| **margen_domestico_biodiesel** | Si el precio no cubre el aceite, las plantas no entregan al corte (2020) | biodiésel | 0 | 0, 1 | +0,27 @ rz1 · n=42 | Por mecanismo (**estrella**). CCF modesta por ventana corta (n=42); validación en el walk-forward |
| **precio_biodiesel** (regulado) | Precio de venta → rentabilidad | biodiésel | 0 | 0, 1 | +0,52 @ rz1 · n=27 (no confiable) | Débil — por mecanismo |
| **precio_bioetanol** (regulado) | Ídem para el etanol | bioetanol | 0 | 0, 1 | — | Por mecanismo |
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
| **tipo_cambio** @ rezago 8-9 | Correlación -0,5 en bioetanol pero con `n`=35 y rezago alto, sin mecanismo directo (el TC influye **a través del margen**, no solo). | No entra suelta; su efecto va por el margen. |
| Variables a **rezago ≥ 9** en general | Con ventana corta y muchos rezagos probados, un rezago alto "ganador" suele ser azar. | Se prueban solo los rezagos con mecanismo (0-2), no el "mejor" de la CCF. |

## Exportaciones

| Variable | Decisión |
|---|---|
| **exportaciones_biodiesel** (rz 1) | Mueven la serie (el desvío de agosto 2026 fue un embarque) pero el dato llega tarde y no hay fuente del mes en curso. Se incluye **solo para confirmar en el walk-forward que no aporta**, no como predictor. |

## Pendiente de datos

El **margen de biodiésel** (SCRUM-51) ya entró a la base y su CCF está calculada
(+0,27 @ rz1, n=42). Falta todavía el **corte** (SCRUM-48): cuando entre, se
recalcula la CCF y se completa su fila. El margen de biodiésel sigue siendo la
candidata de mayor valor esperado para esa serie, a validar en el walk-forward.
