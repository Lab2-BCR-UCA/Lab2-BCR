# Comparación de modelos y elección del final (SCRUM-34)

Código: `scripts/comparacion_final.py`. Pruebas de la regla:
`scripts/test_comparacion_final.py`.

## 1. Regla de elección

Se elige **el modelo más interpretable cuyo error no sea significativamente
peor que el del mejor**.

- El mejor es el de menor MAE en el backtest (2021-09 a 2025-08, 48 meses),
  entre todos los modelos de la grilla de la serie.
- "Significativamente peor": diferencia de error absoluto contra el mejor
  positiva y Diebold-Mariano (varianza HAC, corrección de Harvey, Leybourne y
  Newbold) con p < 0,05 bilateral.
- Orden de interpretabilidad: suma contable, elastic net, SARIMAX, X-13 BCR.
- El naive y el naive estacional son referencias: pueden ser el mejor, pero no
  se eligen.
- La elección usa solo el backtest. El holdout (2025-09 a 2026-09, 13 meses)
  se corrió una sola vez, con los modelos ya elegidos, para confirmar.

Grilla:

- Biodiésel: naive, naive estacional, X-13 BCR, suma contable (SCRUM-60),
  elastic net `con_contables_sin_eventos` (SCRUM-54/31) y SARIMAX (SCRUM-29).
- Bioetanol maíz, caña y total: naive, naive estacional, X-13 BCR, elastic net
  y SARIMAX. En el total, elastic net y SARIMAX son la suma de maíz y caña.

## 2. Resultado

| Serie | Elegido | Motivo | MAE backtest | MAE holdout |
|---|---|---|---:|---:|
| Biodiésel (tn) | suma contable | es el de menor MAE | 21.947 | 11.896 |
| Bioetanol maíz (m³) | elastic net | no es significativamente peor que el X-13 (+357, p = 0,50) | 5.449 | 5.155 |
| Bioetanol caña (m³) | elastic net | no es significativamente peor que el X-13 (+379, p = 0,68) | 5.661 | 4.610 |
| Bioetanol total (m³) | elastic net (maíz + caña) | es el de menor MAE | 7.242 | 8.069 |

Lo que hay que decir con claridad:

- **Ningún modelo elegido le gana al X-13 de la BCR de forma significativa**, ni
  en el backtest ni en el holdout. En biodiésel la suma contable tiene menos
  error en las dos ventanas (−6.318 tn, p = 0,10; −5.464 tn, p = 0,16), pero la
  diferencia no alcanza para afirmarlo. En bioetanol los errores son
  prácticamente iguales.
- Contra el naive, solo el elastic net de caña gana claramente (backtest
  −2.189 m³, p = 0,002; holdout −4.544 m³, p = 0,005).
- La ganancia de los modelos elegidos es la explicación: cada estimación se
  puede descomponer en factores (SCRUM-35, `docs/contribuciones.md`), cosa que
  el X-13 no permite.

## 3. Tablas completas

Diferencia "vs X-13" = MAE del modelo menos MAE del X-13 (negativa: el modelo
tiene menos error), con el p-valor de Diebold-Mariano. El acierto de signo del
naive es 0 % por construcción (predice variación nula).

**Biodiésel (tn)**

| Modelo | MAE backtest | MAE holdout | MAPE backtest | Signo backtest | vs X-13, backtest | vs X-13, holdout |
|---|---:|---:|---:|---:|---:|---:|
| naive | 23.673 | 15.834 | 24,9 % | 0 % | −4.591 (p = 0,05) | −1.526 (p = 0,39) |
| naive estacional | 58.671 | 17.808 | 73,6 % | 56 % | +30.406 (p = 0,00) | +449 (p = 0,92) |
| X-13 BCR | 28.264 | 17.360 | 34,3 % | 50 % | — | — |
| suma contable **(elegido)** | 21.947 | 11.896 | 22,4 % | 67 % | −6.318 (p = 0,10) | −5.464 (p = 0,16) |
| elastic net | 24.407 | 13.658 | 29,7 % | 50 % | −3.858 (p = 0,14) | −3.702 (p = 0,32) |
| SARIMAX | 29.222 | 17.059 | 30,0 % | 38 % | +957 (p = 0,80) | −301 (p = 0,92) |

**Bioetanol maíz (m³)**

| Modelo | MAE backtest | MAE holdout | MAPE backtest | Signo backtest | vs X-13, backtest | vs X-13, holdout |
|---|---:|---:|---:|---:|---:|---:|
| naive | 5.631 | 4.035 | 9,5 % | 0 % | +539 (p = 0,03) | +223 (p = 0,55) |
| naive estacional | 9.381 | 5.465 | 15,7 % | 52 % | +4.289 (p = 0,01) | +1.653 (p = 0,29) |
| X-13 BCR | 5.092 | 3.812 | 8,7 % | 65 % | — | — |
| elastic net **(elegido)** | 5.449 | 5.155 | 8,8 % | 71 % | +357 (p = 0,50) | +1.344 (p = 0,26) |
| SARIMAX | 6.394 | 5.088 | 10,8 % | 67 % | +1.302 (p = 0,13) | +1.276 (p = 0,03) |

**Bioetanol caña (m³)**

| Modelo | MAE backtest | MAE holdout | MAPE backtest | Signo backtest | vs X-13, backtest | vs X-13, holdout |
|---|---:|---:|---:|---:|---:|---:|
| naive | 7.849 | 9.154 | 25,9 % | 0 % | +2.568 (p = 0,01) | +4.866 (p = 0,00) |
| naive estacional | 8.526 | 4.447 | 28,1 % | 67 % | +3.245 (p = 0,01) | +158 (p = 0,87) |
| X-13 BCR | 5.282 | 4.289 | 18,4 % | 73 % | — | — |
| elastic net **(elegido)** | 5.661 | 4.610 | 21,2 % | 65 % | +379 (p = 0,68) | +321 (p = 0,43) |
| SARIMAX | 7.620 | 6.902 | 26,8 % | 56 % | +2.339 (p = 0,01) | +2.614 (p = 0,04) |

**Bioetanol total (m³)**

| Modelo | MAE backtest | MAE holdout | MAPE backtest | Signo backtest | vs X-13, backtest | vs X-13, holdout |
|---|---:|---:|---:|---:|---:|---:|
| naive | 8.167 | 10.756 | 8,5 % | 0 % | +878 (p = 0,28) | +3.384 (p = 0,06) |
| naive estacional | 12.489 | 5.948 | 12,6 % | 58 % | +5.200 (p = 0,00) | −1.424 (p = 0,50) |
| X-13 BCR | 7.289 | 7.372 | 7,8 % | 69 % | — | — |
| elastic net (maíz + caña) **(elegido)** | 7.242 | 8.069 | 7,4 % | 65 % | −47 (p = 0,95) | +697 (p = 0,60) |
| SARIMAX (maíz + caña) | 10.979 | 11.059 | 11,6 % | 62 % | +3.690 (p = 0,00) | +3.687 (p = 0,06) |

## 4. Confirmación en el holdout

En el holdout ningún modelo elegido es significativamente peor que el mejor de
esa ventana:

| Serie | Mejor en el holdout | Elegido contra el mejor |
|---|---|---|
| Biodiésel | suma contable (el elegido) | — |
| Maíz | X-13 BCR (3.812) | +1.344, p = 0,26 |
| Caña | X-13 BCR (4.289) | +321, p = 0,43 |
| Total | naive estacional (5.948) | +2.121, p = 0,26 |

La elección se mantiene. Dos advertencias:

- 12 de los 13 meses del holdout son provisorios (`docs/protocolo_evaluacion.md`):
  estas métricas pueden cambiar cuando se revisen los datos.
- En maíz, desde el cambio de régimen de noviembre de 2025 el elastic net tiene
  más error que el X-13 (MAE 5.536 contra 3.181 m³ en 11 meses). Son pocos meses
  para concluir, pero conviene seguirlo cuando entren datos nuevos.

## 5. Subperíodos (`results/comparacion_final_subperiodos.csv`)

MAE del elegido y del X-13 en cada régimen (cortes de `CORTES_REGIMEN`):

| Serie | Ventana y régimen | Meses | Elegido | X-13 |
|---|---|---:|---:|---:|
| Biodiésel | backtest, desde Ley 27.640 | 48 | 21.947 | 28.264 |
| Biodiésel | holdout, desde Ley 27.640 | 2 | 9.248 | 15.543 |
| Biodiésel | holdout, desde corte nov-2025 | 11 | 12.377 | 17.690 |
| Maíz | backtest, desde Ley 27.640 | 48 | 5.449 | 5.092 |
| Maíz | holdout, desde Ley 27.640 | 2 | 3.060 | 7.280 |
| Maíz | holdout, desde corte nov-2025 | 11 | 5.536 | 3.181 |
| Caña | backtest, desde Ley 27.640 | 48 | 5.661 | 5.282 |
| Caña | holdout, desde Ley 27.640 | 2 | 2.492 | 3.013 |
| Caña | holdout, desde corte nov-2025 | 11 | 4.995 | 4.520 |
| Total | backtest, desde Ley 27.640 | 48 | 7.242 | 7.289 |
| Total | holdout, desde Ley 27.640 | 2 | 5.552 | 9.296 |
| Total | holdout, desde corte nov-2025 | 11 | 8.526 | 7.022 |

## 6. Piso práctico del biodiésel

El piso (`docs/suma_contable.md`) es el error que queda usando las ventas y
exportaciones reales del mes. Backtest: 18.637 tn; la suma contable queda
~3.300 tn arriba. Holdout: 14.750 tn, y la suma contable da 11.896 tn,
**por debajo del piso**. Confirma que el piso es una referencia y no un límite
estricto.

## 7. Error sobre la variación del IACA

Con `scripts/error_iaca.py` (SCRUM-42) se pasó la producción del modelo final
por el mismo cálculo del índice que hace la BCR. Error absoluto medio de la
variación, en puntos porcentuales, y acierto de signo:

| Serie | Ventana | Modelo final | X-13 BCR | Diferencia (p DM) | Signo final | Signo X-13 |
|---|---|---:|---:|---:|---:|---:|
| Biodiésel | backtest (48) | 15,58 | 19,34 | −3,76 (p = 0,15) | 72,9 % | 62,5 % |
| Biodiésel | holdout (13) | 8,96 | 12,26 | −3,31 (p = 0,21) | 53,8 % | 53,8 % |
| Bioetanol total | backtest (48) | 4,97 | 5,10 | −0,14 (p = 0,81) | 72,9 % | 62,5 % |
| Bioetanol total | holdout (13) | 4,95 | 4,50 | +0,45 (p = 0,57) | 53,8 % | 61,5 % |

Mismo resultado que en producción: menos error en biodiésel, sin significancia,
y empate en bioetanol. Las métricas del X-13 en el backtest son las mismas que
ya estaban en `results/iaca_backtest_metricas.csv` antes de agregar el modelo
final. El p-valor sale de `comparar_modelos` con pérdida absoluta sobre
`error_pp` de `results/iaca_<ventana>_detalle.csv`.

## 8. Reproducibilidad entre entornos

- Suma contable y elastic net dan lo mismo en Windows y Linux.
- El X-13 (`x13binary` 1.1.61) da distinto en meses puntuales entre Windows y
  Linux (por ejemplo mayo de 2025 en bioetanol total, ver `docs/error_iaca.md`).
  Los resultados guardados se generaron en Linux.
- El SARIMAX de bioetanol depende de la versión de statsmodels: el MAE de maíz
  en el backtest da 6.394 m³ con statsmodels 0.15.0 y 6.216 m³ en otra máquina
  del equipo (el valor que citan `docs/candidatas_28.md` y
  `docs/aporte_variables.md`). Al correr con el holdout se regeneró
  `results/sarimax.csv` en este entorno, así que su backtest de bioetanol cambia
  respecto de la versión anterior. No cambia la elección (el SARIMAX no queda
  elegido en ninguna serie).
- Entorno de la corrida guardada: Python 3.13, numpy 2.5.3, pandas 3.0.5,
  scikit-learn 1.9.1, scipy 1.18.1, statsmodels 0.15.0.

## 9. Archivos

Entradas (`results/`): `protocolo_predicciones.csv`,
`suma_contable_predicciones.csv`, `elastic_net_predicciones.csv`,
`sarimax_predicciones.csv` (nuevo: `scripts/sarimax.py` ahora guarda las
predicciones de cada mes).

Salidas (`results/`):

- `comparacion_final_metricas.csv`, `_diferencias.csv`, `_subperiodos.csv`,
  `_eleccion.csv` y `comparacion_final_<serie>.png`.
- `modelo_final_predicciones.csv`: la predicción del elegido en cada serie, con
  modelo `modelo_final` y la columna `modelo_elegido`.
- `iaca_backtest_*` (ahora con el modelo final) e `iaca_holdout_*`.

## 10. Ejecución

Desde la raíz del proyecto:

    python scripts/suma_contable.py --con-holdout
    python scripts/elastic_net.py --con-holdout
    python scripts/sarimax.py --con-holdout
    python scripts/comparacion_final.py
    python scripts/test_comparacion_final.py
    python scripts/error_iaca.py --modelo-final modelo_final --predicciones-extra results/modelo_final_predicciones.csv
    python scripts/error_iaca.py --ventana holdout --modelo-final modelo_final --predicciones-extra results/modelo_final_predicciones.csv

Las tres primeras ya se corrieron con el holdout y sus resultados están en
`results/`: el backtest dio igual que antes. `comparacion_final.py` usa las
predicciones guardadas y no reentrena nada.
