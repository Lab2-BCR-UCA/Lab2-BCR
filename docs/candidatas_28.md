# Tabla de candidatas — EDA de variables externas (SCRUM-28)

Las candidatas se eligen por **mecanismo económico + disponibilidad a tiempo**
(SCRUM-26), no por significancia estadística. La CCF (correlación cruzada,
`results/ccf_candidatas.csv`) es **exploratoria**: se calcula sobre series
diferenciadas (log-diff, sin cruzar huecos) y **desestacionalizadas** (resta de
la media de cada mes, calculada **solo con datos anteriores a septiembre
2021**, anti-leakage), en la **ventana del protocolo** (desde el inicio de cada
serie) y **solo en los rezagos con mecanismo** (0-3 y 12). Sirve para elegir
qué rezago probar, no para descartar.

## Nota metodológica

- **La CCF no descarta nada.** Mide solo relación lineal bivariada, tiene poca
  potencia con ~100 meses. La decisión de qué entra la toma el walk-forward
  (SCRUM-29/54).
- **Script y notebook usan la misma transformación.** `scripts/ccf_candidatas.py`
  es la fuente única del CSV; aplica el mismo log-diff sin cruzar huecos, la
  misma desestacionalización sin leakage, el mismo recorte al inicio del
  protocolo y el mismo filtro de rezagos (0-3, 12) que el notebook.
- **Los márgenes tienen señal débil en la CCF.** El margen de biodiésel da
  -0,18 @ rz2 y el de maíz +0,19 @ rz3: se mantienen **por mecanismo** (su
  evidencia es el colapso de nivel de 2020, no la variación mensual), no por la
  CCF.
- **Biodiésel: ninguna variable interna tiene CCF fuerte** (todas |corr| ≤ 0,30).
  Es coherente con la descomposición contable: los *saltos* del biodiésel los
  explican las **exportaciones**, que entran por la vía de INDEC (SCRUM-57,
  ya en la base), no por el mercado interno.

## Candidatas

| Variable | Mecanismo económico | Target | Rezago mín. (disp.) | Rezagos a probar | CCF (mejor · n) | Evidencia |
|---|---|---|---|---|---|---|
| **ventas_nafta** | Volumen de nafta sobre el que se aplica el corte de etanol | bioetanol (maíz, caña, total) | 0 | 0, 1, 2 | +0,77 total / +0,47 maíz / **+0,85 caña** @ rz0 · n≈103-107 | **Fuerte** |
| **ventas_gasoil** | Volumen de gasoil sobre el que se aplica el corte de biodiésel | biodiésel | 0 | 0, 1 | +0,24 @ rz1 · n=138 | Media (rezago con mecanismo) |
| **molienda_soja** | Disponibilidad de aceite (insumo del biodiésel) | biodiésel | 0 | 0, 1 | +0,30 @ rz0 · n=79 | Media |
| **margen_bioetanol_maiz** | Si el precio regulado no cubre el maíz, cae el incentivo a producir | bioetanol maíz | 0 | 0, 1 | +0,19 @ rz3 · n=35 (señal débil) | Por mecanismo |
| **margen_domestico_biodiesel** | Si el precio no cubre el aceite, las plantas no entregan al corte (2020) | biodiésel | 0 | 0, 1 | -0,18 @ rz2 · n=41 (señal débil) | Por mecanismo (evidencia = colapso de nivel 2020) |
| **precio_biodiesel** (regulado) | Precio de venta → rentabilidad | biodiésel | 0 | 0, 1 | +0,30 @ rz0 · n=27 | Débil (n chico) |
| **precio_bioetanol** (regulado) | Ídem para el etanol | bioetanol | 0 | 0, 1 | sin CCF (n<24 pre-2021) | Por mecanismo |
| **corte_efectivo** | Cumplimiento real de la mezcla (varió 3%→7% con norma fija) | ambos (bioetanol: total, maíz y caña) | 1 | 1 | en la base desde SCRUM-48; la prueba va en SCRUM-31 | Por mecanismo. Ojo: muy correlacionado con la producción del mes anterior (ver `docs/corte.md`) |
| **azucar_usd_kg** | Los ingenios reparten la caña entre azúcar y alcohol según cuál paga más: azúcar cara → menos bioetanol de caña. La zafra (may-nov) ya la captura la estacionalidad; el precio explica cuánto alcohol sale | bioetanol caña y total | 0 | 0, 1, 2 | -0,27 caña / -0,21 total @ rz2 · n=103, pero también -0,18 con **maíz** @ rz2, donde no hay mecanismo (posible factor común); en rz0-1 el signo da al revés (+0,11 a +0,18). **La CCF no la respalda** | Por mecanismo; la decide la ablación. Limitaciones: viene con dos decimales (variación mensual escalonada) y es el precio internacional (Banco Mundial, "Sugar, world"); los ingenios venden sobre todo en el mercado interno, así que es una aproximación (SCRUM-58) |

## Variables de régimen (no candidatas principales)

| Variable | Rol |
|---|---|
| **corte_nominal** | Explica **saltos de nivel** por cambio de norma. En el backtest (desde sep-2021) cambia una sola vez en biodiésel (5% → 7,5% el 16/6/2022, más el COTAB de jun-oct 2022) y ninguna en bioetanol (12% desde 2016) → sirve en el entrenamiento como régimen, no como predictor del mes a mes. En la base desde SCRUM-48. |

## Candidatas débiles / que entran por otra vía

| Variable | Decisión |
|---|---|
| **precio_soja_pizarra**, **precio_maiz_pizarra** | Entran al modelo **vía el margen**, no sueltas: son el denominador del cociente. Sueltas, su CCF es débil (|corr| ≤ 0,23). |

## Probables falsos positivos (CCF sin mecanismo directo)

| Variable | Por qué se marca | Decisión |
|---|---|---|
| **tipo_cambio** @ rezago 12 | -0,20 a -0,28 en bioetanol, pero a rezago 12 y con `n`≈31, sin mecanismo directo (el TC influye **a través del margen**, no solo). | No entra suelta; su efecto va por el margen. |
| **margen** contra series que no le corresponden (p. ej. margen de biodiésel contra bioetanol, +0,27/+0,34 @ rz3) | Rezago 3, `n` chico, sin mecanismo cruzado. | Azar; cada margen es candidato solo de su propia serie. |

## Exportaciones

| Variable | Decisión |
|---|---|
| **expo_indec_tn** + **expo_indec_oculto** (rz 0, SCRUM-57) | **Candidata principal del biodiésel.** Las exportaciones explican ~100% de la variación mensual de la producción desde sep-2021 (descomposición contable). INDEC las publica ~día 20 de t+1, antes de la estimación de la BCR; coincide con la Secretaría (99% de los meses en si hubo exportación, correlación 0,996). Los meses con monto oculto (`s`) se imputan en el constructor de features con datos hasta t-1. Sin CCF: la serie tiene muchos ceros y la diferencia del log no está definida. Ver `docs/exportaciones_indec.md`. |
| ~~exportaciones_biodiesel~~ (Secretaría, rz 1) | **Reemplazada por INDEC.** Llega con la producción (2 meses de rezago), así que no sirve como predictor. |

## Pendiente de datos

El **corte** ya está en la base (SCRUM-48, ver `docs/corte.md`); su prueba en el
modelo va en SCRUM-31. Las exportaciones de INDEC, el driver real del biodiésel,
también (SCRUM-57, ver `docs/exportaciones_indec.md`). Falta el azúcar para la
caña, que se suma cuando esté su ticket de datos.
