
# SCRUM-42 — Error sobre la variación del IACA

## 1. Objetivo

Medir si las mejoras en la predicción de producción de
biocombustibles también mejoran la predicción de la variación
del índice utilizado por la BCR.

Se evalúan biodiésel y bioetanol total.

## 2. Metodología

Se replica el procedimiento utilizado por la BCR:

1. Pronóstico mensual de producción con X-13.
2. Utilización de los archivos .spc originales.
3. Conversión de producción a índice base 2013 = 100.
4. Ajuste estacional y filtrado de irregularidad.
5. Aplicación de la media móvil y la fórmula del mes estimado.
6. Cálculo de la variación logarítmica mensual.

Para cada mes se utilizan solamente los datos disponibles
hasta el mes anterior.

La producción real del mes pronosticado se incorpora únicamente
para calcular las métricas de evaluación.

## 3. Métricas

Se utilizan dos métricas principales:

- Error absoluto en puntos porcentuales:
  diferencia absoluta entre la variación pronosticada y
  la variación calculada con la producción real.

- Acierto del signo:
  indica si el modelo predijo correctamente la dirección
  de la variación mensual.

La variación con el dato real se calcula manteniendo los
ajustes estacionales estimados antes del mes evaluado.
Por lo tanto, no representa necesariamente una publicación
posterior de la BCR con ajustes revisados.

Limitaciones:

- El acierto del signo es frágil cuando la variación real
  está cerca de cero: un cambio chico en los componentes de
  X-13 puede darlo vuelta (ver mayo de 2025, sección 6).
- El factor de la base 2013 multiplica a los dos índices y se
  cancela en la variación logarítmica: afecta el nivel del
  índice, no la métrica. Por eso la validación puede usar el
  factor del Excel y el backtest el calculado con los datos.

## 4. Validación — Agosto de 2026

Se utilizaron datos hasta julio de 2026.

### Biodiésel

- Producción pronosticada: 103.922,61 tn.
- Producción real: 146.603,63 tn.
- Variación pronosticada: +3,047257 %.
- Variación con dato real: +28,283998 %.
- Error absoluto: 25,236742 pp.
- Acierto del signo: 1.

### Bioetanol total

- Producción pronosticada: 140.393,72 m³.
- Producción real: 139.521,00 m³.
- Variación pronosticada: +2,303722 %.
- Variación con dato real: +1,803891 %.
- Error absoluto: 0,499831 pp.
- Acierto del signo: 1.

Las fórmulas del índice se reprodujeron correctamente
contra el Excel original de la BCR, dentro de la tolerancia
establecida de 0,001.

## 5. Backtest histórico

Período: septiembre de 2021 a agosto de 2025.

Se evaluaron 48 meses mediante walk-forward mensual
para cada serie.

### X-13 BCR

| Métrica | Biodiésel | Bioetanol total |
|---|---:|---:|
| Meses | 48 | 48 |
| Error medio absoluto (pp) | 19,3364 | 5,1024 |
| Error medio con signo (pp) | +10,8554 | -0,1466 |
| Aciertos del signo | 30 | 30 |
| Acierto del signo (%) | 62,50 | 62,50 |

Los 96 pronósticos de X-13 coinciden con los de
`results/protocolo_predicciones.csv` (ver la sección 6).

## 6. Discrepancia de mayo de 2025 (resuelta)

En la primera corrida, mayo de 2025 de bioetanol total dio
un pronóstico distinto al del protocolo:

- Pronóstico del protocolo: 95.105,69 m³.
- Pronóstico recalculado en la primera corrida: 95.764,48 m³.
- Diferencia: 658,79 m³.

Al volver a correr el backtest completo en otra máquina
(Linux, mismo `x13binary` 1.1.61), los 96 pronósticos
coinciden con el protocolo, incluido mayo de 2025, y no hay
discrepancias. La diferencia sale de la máquina donde corre
X-13, no del cálculo del índice: con los mismos datos y la
misma versión, X-13 puede dar un resultado distinto en algún
mes según la plataforma. Es consistente con lo que pasó al
correr el protocolo largo en Windows (SCRUM-63), donde el MAE
del X-13 de bioetanol total cambió unos 14 m³, lo que equivale
a una diferencia de ese orden en un solo mes.

Los resultados de `results/` son los que coinciden con el
protocolo. En mayo de 2025 cambia también la variación con el
dato real (+0,21 % en lugar de −0,02 %), porque sale de los
mismos componentes, y el signo deja de acertarse.

El script sigue usando el pronóstico de la misma corrida que
genera los componentes y registra en
`iaca_*_discrepancias.csv` cualquier diferencia con el
protocolo, para detectar si vuelve a pasar.

## 7. Caché

Los componentes se guardan en:

data/cache_x13.db

Se utiliza la tabla iaca_componentes, separada de las
tablas que utiliza el protocolo original.

Las claves incluyen hashes de los datos y de la
configuración para evitar reutilizar corridas incompatibles.

El archivo SQLite es local y no se versiona.

## 8. Archivos

- scripts/error_iaca.py
- scripts/validar_iaca_x13.py
- scripts/replica_x13.py
- results/validacion_iaca_agosto_2026.csv
- results/iaca_2026-08_detalle.csv
- results/iaca_2026-08_metricas.csv
- results/iaca_2026-08_discrepancias.csv
- results/iaca_backtest_detalle.csv
- results/iaca_backtest_metricas.csv
- results/iaca_backtest_discrepancias.csv
- results/iaca_holdout_detalle.csv
- results/iaca_holdout_metricas.csv
- results/iaca_holdout_discrepancias.csv

## 9. Ejecución

Desde la raíz del proyecto:

Validar contra Excel:

    python scripts/validar_iaca_x13.py

Evaluar agosto de 2026:

    python scripts/error_iaca.py --mes 2026-08

Evaluar el backtest completo:

    python scripts/error_iaca.py

Evaluar otro modelo del protocolo:

    python scripts/error_iaca.py --modelo-final NOMBRE_MODELO

El modelo tiene que tener sus predicciones en
`results/protocolo_predicciones.csv` o en un CSV con el mismo
formato que se pasa con `--predicciones-extra`. Si un nombre de
modelo está en los dos archivos, el script frena.

Modelo final (SCRUM-34), backtest y holdout:

    python scripts/error_iaca.py --modelo-final modelo_final --predicciones-extra results/modelo_final_predicciones.csv
    python scripts/error_iaca.py --ventana holdout --modelo-final modelo_final --predicciones-extra results/modelo_final_predicciones.csv

## 10. Pendientes

No quedan pendientes dentro de SCRUM-42. La métrica del modelo
final está en `docs/comparacion_final.md` (sección 7).
