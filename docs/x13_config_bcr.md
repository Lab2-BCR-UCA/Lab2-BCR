# X-13 con la configuración exacta de BCR

Documenta cómo se replica el X-13 de BCR con sus archivos `.spc`, el
criterio de selección log/nivel, el tratamiento de outliers en el
walk-forward y los resultados. Código: `scripts/replica_x13.py`.

## 1. Archivos `.spc`

BCR envió cuatro archivos, en `spc/`:

| Archivo | Serie | Transformación | `span` | `modelspan` | `maxdiff` | `maxorder` |
|---|---|---|---|---|---|---|
| `IACA-BIODIESEL_L.spc` | Biodiesel | log | 2008.01 | 2013.01 | (2 1) | (4 2) |
| `IACA-BIODIESEL_N.spc` | Biodiesel | nivel | 2008.01 | 2013.01 | (2 1) | (4 2) |
| `IACA-BIOETANOL_L.spc` | Bioetanol | log | 2010.01 | **2010.01** | **(1 1)** | **(2 1)** |
| `IACA-BIOETANOL_N.spc` | Bioetanol | nivel | 2010.01 | 2013.01 | (2 1) | (4 2) |

En los cuatro se repiten estos bloques:

- `regression{ aictest = (TD EASTER) }`
- `forecast{ maxlead = 12 maxback = 12 }`
- `estimate{ maxiter = 6000 }`
- `check{ maxlag = 36 }`
- `x11{ seasonalma = MSR save = (C17 D11 D12 D16) }`
- `slidingspans{}`
- `spectrum{}`

La ventana desde 2013 no se aplica en todos los casos. **El `.spc` de bioetanol en log ajusta el modelo desde 2010 y con órdenes más chicos.** Se respeta tal cual.

### Cómo se usan

`spec_desde_spc()` lee el `.spc` y cambia solo lo mínimo para correrlo fuera de la PC de BCR:

- la línea `file = "...IACA-BIODIESEL.prn"` y `format = free` se reemplazan por los datos inline (`data = (...)`);
- si la serie empieza después del `start` del `.spc`, se corren `start`, `span` y `modelspan` a ese mes. Solo pasa en bioetanol de maíz, que tiene ceros hasta 2012-08.

Todo lo demás queda idéntico.

### Inicio de la serie

La réplica BCR recibe la serie desde el `span` del `.spc`:

- biodiesel: 2008-01;
- bioetanol total y caña: 2010-01;
- maíz: 2012-09.

Para bioetanol total y caña, ese inicio difiere del inicio del protocolo (2013-01). Esto es **intencional**: es lo que usa BCR. Como el `modelspan` del `.spc` en nivel empieza en 2013, el regARIMA se ajusta igual desde 2013. Lo que cambia es el X-11 y, en log, también el modelo.

## 2. Verificación contra BCR (datos a julio 2026)

| Serie | Variante | Réplica | BCR (Win X-13) | Diferencia |
|---|---|---|---|---|
| Biodiesel | log | 103.922,6 tn | 103.922 tn | 0,0 % |
| Bioetanol total | nivel | 140.393,7 m³ | 140.394 m³ | 0,0 % |

Los 12 pronósticos (agosto 2026 a julio 2027) de las dos variantes de cada serie están en `results/pronostico_x13_bcr_2026-07.csv`.

**Verificado contra el Excel de BCR** (`data/modelo_bcr_biocombustibles.xlsx`): los 12 pronósticos coinciden en las dos series (biodiesel en log y bioetanol total en nivel), con una diferencia máxima menor a 0,00001 %. El Excel trae las predicciones como índice base 2013 = 100; se pasan a toneladas y m³ con el factor de la fila 2 de cada bloque (celdas C2 y P2).

## 3. Criterio de selección log / nivel

En el criterio de BCR gana la transformación con menor desvío estándar de la variación logarítmica mensual de la serie filtrada por estacionalidad e irregular. Esa serie es la tendencia-ciclo, tabla D12. Se implementa en `criterio_bcr()`, con la D12 de cada corrida y solo el tramo observado.

No sabemos sobre qué ventana calcula BCR el desvío, así que se prueban dos.

**Con datos a julio 2026:**

| Serie | Ventana | Desvío log | Desvío nivel | Elige |
|---|---|---|---|---|
| Biodiesel | serie completa | 0,0699 | 0,0653 | nivel ✗ |
| Biodiesel | últimos 12 meses | 0,0251 | 0,0316 | **log ✓** |
| Bioetanol | serie completa | 0,0527 | 0,0284 | nivel ✓ |
| Bioetanol | últimos 12 meses | 0,0114 | 0,0105 | **nivel ✓** |

Con la serie completa, el criterio elige nivel en biodiesel, al revés que BCR. Con los últimos 12 meses reproduce las dos elecciones de BCR. En el walk-forward pasa lo mismo: con la ventana de 12 meses, biodiesel elige log en los 12 meses del test.

No damos por confirmado que BCR use 12 meses: es la ventana que reproduce su elección, no algo que sepamos. Por eso se guardan las dos versiones:

- `x13_bcr`: criterio sobre los últimos 12 meses. Es la variante de
  referencia, porque reproduce la elección de BCR (log en biodiesel, nivel en
  bioetanol);
- `x13_bcr_selcompleta`: criterio sobre la serie completa.

**Pendiente:** confirmar con BCR (o con el Excel) la ventana exacta.

El detalle por mes está en `results/seleccion_x13_bcr.csv`: desvíos, elección y modelo ARIMA elegido en cada variante.

## 4. Outliers

Se revisaron los cuatro `.spc`:

- **No hay outliers fijos.** No existe ninguna `regression{ variables = (AO... LS... TC...) }`.
- **No hay bloque `outlier{}`**, así que X-13 tampoco identifica outliers automáticamente.

Se verificó en la salida HTML: el modelo de regresión de la corrida de biodiesel a julio 2026 tiene solo la constante. Días hábiles y Pascua entran o no según el `aictest`, que se reestima en cada corrida.

**Consecuencia para el walk-forward:** no hay outliers detectados con la muestra completa que filtren información futura. No hizo falta reidentificar ni quitar nada.

En cada iteración, X-13 corre solo con datos hasta t-1. Con esos datos reestima todo:

- la selección del modelo ARIMA (`automdl`);
- el test de calendario;
- el reemplazo de valores extremos interno del X-11.

Si en algún momento BCR agrega outliers a mano al `.spc`, habrá que tratarlos así en el walk-forward: reidentificarlos en cada iteración, o descartar los fechados después de t.

## 5. Resultados del walk-forward (ventana corta / holdout)

Protocolo de `docs/protocolo_evaluacion.md`: test de septiembre 2025 a agosto 2026, a un mes, ventana expansiva, 12 de 12 meses evaluados en todos los casos.

**Nota de actualización (SCRUM-43/46):** esta ventana se conserva como
holdout histórico. La comparación para elegir modelo ahora usa el backtest
sep-2021 a ago-2025 y la métrica principal es **MAE**. Los resultados
actualizados están en [`../README.md`](../README.md) y
`results/protocolo_metricas.csv`; el MAPE siguiente queda como referencia
de la validación original del X-13.

MAPE (%):

| Serie | naive estacional | x13_auto | x13_bcr_log | x13_bcr_nivel | x13_bcr_selcompleta | x13_bcr |
|---|---|---|---|---|---|---|
| Biodiesel | **15,8** | 21,0 | 21,0 | 19,7 | 19,7 | 21,0 |
| Bioetanol total | **5,0** | 7,5 | 9,7 | 7,5 | 7,5 | 7,5 |
| Bioetanol maíz | 6,6 | 6,0 | 6,1 | 6,0 | 6,0 | **5,9** |
| Bioetanol caña | 15,5 | 16,4 | 15,4 | 16,4 | 16,4 | **15,0** |

Tabla completa (MAE, RMSE, MAPE, acierto de signo): `results/x13.csv` y `results/comparacion.csv`.

### Lectura

**La réplica automática ya daba los mismos pronósticos que la config BCR en la misma transformación.**

- `x13_auto` coincide exactamente con `x13_bcr_log` en biodiesel y con `x13_bcr_nivel` en bioetanol.
- Lo que agrega el `.spc` y no tenía el spec mínimo no cambia el pronóstico del regARIMA: `seasonalma = MSR`, `maxiter`, `check`, `slidingspans`, `spectrum` y el `span` desde 2010.
- La diferencia que importa viene de la **elección log/nivel**.

**Aplicando el procedimiento exacto de BCR (`x13_bcr`), el X-13 sigue perdiendo contra el naive estacional** en biodiesel y bioetanol total. En maíz y caña queda apenas por delante.

Con el criterio sobre la serie completa (`x13_bcr_selcompleta`), biodiesel pasa a nivel y mejora a 19,7 %, pero sigue peor que el naive estacional.

**Conclusión:** casi todo el margen de mejora está en cambiar de modelo, no en ajustar el X-13. Esa es la comparación que permite distinguir las dos fuentes de ganancia.

### Inicio de entrenamiento distinto entre modelos

Para comparar contra BCR, `x13_bcr*` usa el inicio de sus `.spc`. Eso deja dos diferencias respecto del protocolo y de `x13_auto`:

- en bioetanol total y caña, 2010 en lugar de 2013;
- el walk-forward es idéntico en todo lo demás: mismos meses de test y mismos datos.

Queda registrado en la columna `inicio_entrenamiento` de `results/x13.csv`.

## 6. Tiempo de corrida

Cada corrida con la config BCR tarda entre 10 y 40 segundos según la máquina. El costo viene sobre todo de X-11 con `slidingspans` y `spectrum`.

El walk-forward completo hace 144 corridas:

| Corridas | Cálculo |
|---|---|
| 96 con config BCR | 4 series × 12 meses × log y nivel |
| 48 automáticas | 4 series × 12 meses |

Las corridas se reparten en paralelo con `ProcessPoolExecutor`, usando `--procesos N` (por defecto, todos los núcleos). Con 2 núcleos tardó unos 15 minutos.

Las dos variantes fijas y las dos selecciones salen de las mismas corridas. No se corre X-13 de más.

```bash
python scripts/replica_x13.py                 # pronóstico a jul-2026 + walk-forward
python scripts/replica_x13.py --solo-julio    # solo el pronóstico del DoD (~1 min)
python scripts/comparacion.py                 # regenera results/comparacion.csv
```

## 7. Pendientes

- Confirmar la ventana del criterio de selección.
- La evaluación en el backtest y el holdout se realizó en SCRUM-43;
  el resumen está en `results/protocolo_metricas.csv`.
