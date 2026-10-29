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
| **corte_efectivo** | Cumplimiento real de la mezcla (varió 3%→7% con norma fija) | ambos (bioetanol: total, maíz y caña) | 1 | 1 | en la base desde SCRUM-48; probado en la ablación de SCRUM-62 | Por mecanismo. Ojo: muy correlacionado con la producción del mes anterior (ver `docs/corte.md`). Ablación: no distinguible en maíz/caña; **empeora** el total (ver abajo) |
| **azucar_usd_kg** | Los ingenios reparten la caña entre azúcar y alcohol según cuál paga más: azúcar cara → menos bioetanol de caña. La zafra (may-nov) ya la captura la estacionalidad; el precio explica cuánto alcohol sale | bioetanol caña y total | 0 | 0, 1, 2 | -0,27 caña / -0,21 total @ rz2 · n=103, pero también -0,18 con **maíz** @ rz2, donde no hay mecanismo (posible factor común); en rz0-1 el signo da al revés (+0,11 a +0,18). **La CCF no la respalda** | Por mecanismo; la decidió la ablación (SCRUM-62): baja el MAE de la caña pero no de forma distinguible (ver abajo). Limitaciones: viene con dos decimales (variación mensual escalonada) y es el precio internacional (Banco Mundial, "Sugar, world"); los ingenios venden sobre todo en el mercado interno, así que es una aproximación (SCRUM-58) |

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

## Resultado de la ablación en el SARIMAX (SCRUM-62)

Con el corte (SCRUM-48), INDEC (SCRUM-57) y el azúcar (SCRUM-58) ya en la base,
SCRUM-62 corrió la ablación en el backtest (`scripts/experimento_exogenas.py`,
`results/experimento_exogenas.csv`): modelo base de SCRUM-29 vs base + cada
candidata, MAE con IC por bootstrap de bloques + Diebold-Mariano. **La ventana de
entrenamiento se iguala** entre base y variante (ver más abajo) y las contables
del biodiésel entran en log1p.

| Serie | Candidata | dif MAE (var − base) | IC95 | p | error máx (base → var) | Veredicto |
|---|---|---|---|---|---|---|
| biodiésel | + contables | **+3.239** | [−3.105, 9.665] | 0,31 | 113k → 103k | empeora, no distinguible |
| biodiésel | + contables + corte nominal | **+3.522** | [−2.778, 10.171] | 0,26 | 113k → 114k | empeora, no distinguible |
| maíz | + corte efectivo | −439 | [−1.483, 539] | 0,39 | 18,5k → **24,6k** | mejora MAE, peor cola, no distinguible |
| caña | + azúcar | −297 | [−914, 322] | 0,37 | 29,1k → 25,8k | mejora, no distinguible |
| caña | + corte efectivo | −151 | [−779, 473] | 0,66 | 29,1k → 27,2k | mejora, no distinguible |
| caña | + azúcar + corte efectivo | −268 | [−1.023, 467] | 0,51 | 29,1k → 24,8k | mejora, no distinguible |
| total | + corte efectivo | +537 | [81, 1.011] | 0,03 | 23,9k → 27,5k | **empeora, distinguible** |

MAE del modelo base (backtest, `results/sarimax.csv`): biodiésel 29.221 (desde
2012, para comparar con las contables: 28.556), total 7.528, maíz 6.216, caña
7.628.

> **Nota de reproducibilidad.** Estos números dependen de las versiones de
> statsmodels / numpy / pandas: en otro entorno el biodiésel da igual (+3,2k) pero
> el bioetanol se corre un poco (p. ej. maíz −617 / p=0,18 en vez de −439 / 0,39).
> El `requirements.txt` no fija versiones todavía; hay un ticket aparte para eso.
> Las conclusiones no cambian entre entornos.

**Conclusión. Ninguna candidata justifica entrar al modelo.**

- **Biodiésel: las contables NO aportan precisión.** Entran recién en 2012 (con
  INDEC), así que hay que compararlas contra una base que arranque también en
  2012. Con esa base (MAE 28.556), las contables **empeoran** a 31.794 (+3.239) y
  con el corte nominal a 32.078 (+3.522). La "mejora" de −385 que aparecía sin
  igualar la ventana era el efecto de entrenar con menos años (acortar la base a
  2012 ya baja el MAE unos 666), no el de las variables.
- **Maíz + corte efectivo**: baja el MAE pero **empeora el peor mes** (error
  máximo 18,5k → 24,6k) y no es distinguible (p=0,39).
- **Caña + azúcar / corte**: bajan el MAE pero no de forma distinguible (p≥0,37).
- **Total + corte efectivo**: empeora y es distinguible (p=0,03), aunque es una
  comparación al borde entre siete.

Por parsimonia, el SARIMAX de pronóstico queda con el conjunto de SCRUM-29. Esto
es coherente con el criterio del propio SCRUM-28: la CCF era el filtro para
decidir **qué probar**, la ablación es la **prueba**, y la prueba no respalda
sumar ninguna.

El valor de las contables es **explicativo**, no de precisión: descomponen la
producción de biodiésel en demanda del corte + exportaciones (lo que la BCR pidió
explicar) y alimentan la suma contable (N4) y las tablas de contribución
(SCRUM-35).

### Límites de la ablación

- **Blow-up controlado (DoD).** Con las contables en toneladas, el mes 2022-02 se
  iba a ~355 mil tn contra 177 mil reales: el salto de exportaciones (28 mil
  imputado → 150-175 mil) entra multiplicando en un modelo en log. Pasándolas a
  log1p (SCRUM-59) el error máximo del biodiésel con contables baja a ~103 mil,
  en línea con la base (~113 mil). Por eso el experimento reporta el error máximo
  por variante.
- **El corte efectivo es casi circular**: sale de ventas al corte / ventas del
  combustible y las ventas al corte siguen a la producción (`docs/corte.md`). Su
  CCF de +0,86 con la caña es el síntoma, no evidencia. Entra con rezago 1, así
  que no hay leakage.
- **Varias comparaciones sin corrección por comparaciones múltiples**: con 7
  tests al 95% se esperan ~0,35 rechazos falsos, así que el único resultado
  distinguible (total, p=0,03) se lee como "no hay evidencia de que ayude".
- **Cada candidata se prueba sola** contra una base fija: no hay selección
  conjunta ni hacia adelante.
