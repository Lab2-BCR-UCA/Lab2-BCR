
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
| Error medio absoluto (pp) | 19,3364 | 5,0948 |
| Error medio con signo (pp) | +10,8554 | -0,1391 |
| Aciertos del signo | 30 | 31 |
| Acierto del signo (%) | 62,50 | 64,58 |

Resultados provisionales, sujetos a la revisión indicada
en la siguiente sección.

## 6. Discrepancia detectada

En mayo de 2025, para bioetanol total:

- Pronóstico del protocolo: 95.105,69 m³.
- Pronóstico X-13 recalculado: 95.764,48 m³.
- Diferencia: 658,79 m³.

La corrida fue reproducible y no devolvió errores de X-13.

Para mantener la coherencia entre el pronóstico y los
componentes utilizados, el cálculo del IACA utiliza el
pronóstico recalculado y registra la diferencia.

No se modificó el CSV original del protocolo.

La causa de la discrepancia sigue pendiente de investigación.
Las métricas del backtest deben considerarse provisionales
hasta resolverla.

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
- results/iaca_backtest_detalle.csv
- results/iaca_backtest_metricas.csv
- results/iaca_backtest_discrepancias.csv

## 9. Ejecución

Desde la raíz del proyecto:

Validar contra Excel:

    python scripts/validar_iaca_x13.py

Evaluar agosto de 2026:

    python scripts/error_iaca.py --mes 2026-08

Evaluar el backtest completo:

    python scripts/error_iaca.py

Incorporar el modelo final:

    python scripts/error_iaca.py --modelo-final NOMBRE_MODELO

## 10. Pendientes

- Investigar la discrepancia de mayo de 2025.
- Incorporar las predicciones del modelo final seleccionado
  por el equipo en el SCRUM-34.
- Comparar sus métricas del IACA contra X-13 BCR.
- Revisar los resultados antes de cerrar el SCRUM-42.
