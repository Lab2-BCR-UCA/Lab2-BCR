# Protocolo de evaluación de modelos

Estado: protocolo largo (SCRUM-43) con backtest de selección y holdout
final. Pendientes de confirmación con la BCR en la sección 13.

## 1. Objetivo

Establecer un procedimiento común para comparar los modelos de predicción
de producción mensual de biocombustibles en igualdad de condiciones.

## 2. Variables objetivo

- Producción de biodiesel, en toneladas.
- Producción de bioetanol total, en metros cúbicos.
- Producción de bioetanol de maíz, en metros cúbicos.
- Producción de bioetanol de caña de azúcar, en metros cúbicos.

Las métricas se calcularán por separado para cada serie.

## 3. Ventanas de evaluación

Con 12 meses de test no se puede distinguir ningún modelo: en las cuatro
series el intervalo de la diferencia de error entre X-13 y naive estacional
incluye el cero. Por eso la evaluación se divide en dos ventanas:

| Ventana | Meses (datos a agosto 2026) | Para qué se usa |
|---|---|---|
| Backtest de selección | septiembre 2021 a agosto 2025 (48 meses) | Todas las decisiones: variables, rezagos, hiperparámetros y modelo final. |
| Holdout final | septiembre 2025 a agosto 2026 (12 meses) | Confirmar al final. No se usa para decidir nada. |

Reglas:

- El backtest empieza siempre en septiembre 2021 y termina 12 meses antes
  del último dato. El holdout son los últimos 12 meses. Cuando llega un mes
  nuevo, las dos ventanas se corren un mes. Lo calcula
  `ventanas_protocolo()` en `scripts/evaluacion.py`.
- El holdout se corre una sola vez, con el modelo ya elegido. Si se mira el
  holdout para cambiar algo, deja de ser holdout. Para trabajar se usa
  `python scripts/protocolo_largo.py --sin-holdout`.
- Los baselines y el X-13 de BCR sí se reportan en el holdout porque no se
  eligen: son las referencias contra las que se compara el modelo final.
- La ventana anterior de 12 meses (septiembre 2025 a agosto 2026) coincide
  con el holdout, así que los resultados viejos de `results/x13.csv` y
  `results/baselines.csv` siguen siendo comparables.

Los 12 meses del holdout están marcados como provisorios en los CSV, como
confirmó la BCR. Se mantienen y se informan siempre como provisorios: las
métricas pueden cambiar cuando se revisen los datos reales.

Todos los modelos deben evaluarse sobre los mismos meses y la misma
versión de los datos. Una actualización de las fuentes requerirá volver
a evaluar todos los modelos incluidos en la comparación.

## 4. Inicio del entrenamiento

Se adoptan provisionalmente los inicios propuestos en
notebooks/eda_produccion.ipynb:

| Serie | Inicio |
|---|---|
| Biodiesel | Enero de 2008 |
| Bioetanol total | Enero de 2013 |
| Bioetanol de maíz | Septiembre de 2012 |
| Bioetanol de caña | Enero de 2013 |

Los cortes del bioetanol buscan excluir la etapa de arranque.
Para maíz, también se excluyen los ceros anteriores al inicio de producción.

Para la comparación final se verificará que todos los modelos de una
misma serie, incluido X-13, utilicen el mismo inicio de entrenamiento.
Cualquier diferencia deberá acordarse y documentarse.

## 5. Validación walk-forward

Se utiliza una ventana de entrenamiento expansiva y un horizonte
de predicción de un mes.

Para cada mes del test:

1. Crear y ajustar el modelo con observaciones hasta el mes anterior.
2. Predecir la producción del mes evaluado.
3. Guardar la predicción y el valor real.
4. Incorporar el valor real al entrenamiento de la siguiente iteración.

Se aplica igual en las dos ventanas, con el mismo código de modelo
(`evaluar_ventanas()` llama a `evaluar_modelo()` en cada una):

- Backtest: primera predicción septiembre 2021, entrenando hasta agosto 2021;
  última, agosto 2025.
- Holdout: primera predicción septiembre 2025, entrenando hasta agosto 2025;
  última, agosto 2026, entrenando hasta julio 2026.

El equipo confirmó que su evaluación de X-13 también realiza
12 predicciones a un mes, reajustando el modelo en cada iteración
con forecast maxlead=1.

Este backtest supone que el dato del mes anterior está disponible.
Se debe confirmar si este supuesto reproduce el retraso de publicación
de la Secretaría de Energía y el momento de predicción de la BCR.

## 6. Prevención del uso de información futura

**Regla anti-leakage:** toda decisión que alimenta al modelo (selección de
variables, estandarización, tratamiento de outliers, hiperparámetros,
transformación log o nivel) se toma dentro de cada iteración con datos hasta
t-1. Nada se ajusta una vez con toda la serie y se reutiliza.

En la práctica:

- Las transformaciones y el preprocesamiento se ajustan solo con
  los datos de entrenamiento de cada iteración.
- La selección de parámetros se realiza con datos anteriores al test
  o con validación temporal dentro del entrenamiento de cada iteración.
- No se utiliza el test completo para elegir parámetros.
- Al incorporar variables externas, se respetarán sus fechas de disponibilidad.
- No se utilizarán automáticamente valores del mes que se está prediciendo.

La evaluación utiliza la historia contenida en los CSV actuales.
No reproduce necesariamente las versiones de los datos disponibles
en cada fecha histórica.

## 6 bis. Comparaciones con incertidumbre y subperíodos

Además del promedio, cada modelo se compara contra el naive estacional con
la diferencia de pérdida mes a mes, d_t = pérdida(modelo) - pérdida(naive
estacional). Negativa significa que el modelo tiene menos error. Se
reportan dos pérdidas: error absoluto porcentual (la del MAPE) y error
absoluto (la del MAE).

Para cada diferencia se informan:

- **Intervalo de confianza del 95 % por bootstrap circular por bloques.**
  Los errores están autocorrelacionados, así que no se remuestrea mes por
  mes sino en bloques de largo n^(1/3) (4 meses en el backtest, 2 en el
  holdout), con 5000 réplicas y semilla fija.
- **Diebold-Mariano** con varianza HAC de Newey-West (rezagos n^(1/3)) y
  la corrección de muestra chica de Harvey, Leybourne y Newbold (1997),
  con p-valor sobre una t con n-1 grados de libertad.

Si el intervalo incluye el cero, la diferencia no es concluyente. Aun con
48 meses es posible que varios intervalos lo incluyan: "ningún modelo le
gana claramente al naive estacional" es un resultado válido y así se
comunica al equipo y a la BCR.

**Error por subperíodo.** Las métricas también se reportan separadas por
régimen, con los cortes de `CORTES_REGIMEN` en `scripts/evaluacion.py`:

| Corte | Primer mes del régimen nuevo |
|---|---|
| Ley 27.640 (biocombustibles) | agosto 2021 |
| Corte de nivel observado en el EDA | noviembre 2025 |

Como el backtest empieza en septiembre 2021, todo el backtest queda en el
régimen de la Ley 27.640. El corte de noviembre 2025 cae dentro del
holdout: lo divide en septiembre a octubre 2025 y noviembre 2025 a agosto
2026. Con 2 y 10 meses, esos subperíodos son descriptivos, no inferenciales.

### Resultados con datos a agosto 2026

`python scripts/protocolo_largo.py`. MAPE (%):

| Serie | Ventana | naive | naive estacional | x13_auto | x13_bcr | x13_bcr_sel12m |
|---|---|---|---|---|---|---|
| Biodiesel | backtest | **24,9** | 73,6 | 32,2 | 39,0 | 34,3 |
| Biodiesel | holdout | 18,2 | **15,8** | 21,0 | 19,7 | 21,0 |
| Bioetanol total | backtest | 8,5 | 12,6 | **7,8** | **7,8** | **7,8** |
| Bioetanol total | holdout | 10,3 | **5,0** | 7,5 | 7,5 | 7,5 |
| Bioetanol maíz | backtest | 9,5 | 15,7 | **8,6** | **8,6** | 8,7 |
| Bioetanol maíz | holdout | 6,6 | 6,6 | 6,0 | 6,0 | **5,9** |
| Bioetanol caña | backtest | 25,9 | 28,1 | 20,8 | 20,8 | **18,4** |
| Bioetanol caña | holdout | 28,4 | 15,5 | 16,4 | 16,4 | **15,0** |

Lectura:

- **En el backtest, el X-13 de BCR le gana al naive estacional en las
  cuatro series y el intervalo no incluye el cero** en ninguna variante.
  Diebold-Mariano da p ≤ 0,04 en biodiesel, bioetanol total y maíz, y entre
  0,02 y 0,07 en caña según la variante.
- **En el holdout, ningún intervalo excluye el cero** salvo dos casos en
  contra del modelo: X-13 en log en bioetanol total y el naive en caña son
  peores que el naive estacional. Con 12 meses no se puede distinguir
  ningún modelo, que es justamente lo que motivó este protocolo.
- El naive estacional de biodiesel da 73,6 % en el backtest por la caída de
  producción de 2023: predice cada mes con el mismo mes de 2022, que tenía
  más de 160 mil toneladas, y la producción real bajó a entre 20 y 60 mil.
  No es un error de cálculo. Por eso en biodiesel el naive (mes anterior)
  queda como el mejor modelo del backtest.
- Ordenar modelos por el holdout lleva a conclusiones distintas que el
  backtest. La comparación para decidir es la del backtest.

Detalle completo: `results/protocolo_metricas.csv` y
`results/protocolo_diferencias.csv`.

## 7. Escala de evaluación

Las predicciones se evalúan en las unidades originales de producción.

Si un modelo utiliza logaritmos o diferencias, debe reconstruir el nivel
antes de calcular las métricas.

La comparación con X-13 debe utilizar pronósticos de producción original
en las mismas unidades, no índices ni valores desestacionalizados.

## 8. Métricas

### MAE

Promedio de los errores absolutos.
Se expresa en toneladas o metros cúbicos. Menor es mejor.

### RMSE

Raíz del promedio de los errores al cuadrado.
Penaliza especialmente los errores grandes.
Se expresa en toneladas o metros cúbicos. Menor es mejor.

### MAPE

Promedio del error absoluto porcentual respecto del valor real.
Se informa en porcentaje. Menor es mejor.

Los meses con producción real igual a cero se excluyen únicamente
del MAPE. Se informa la cantidad de meses excluidos.

Si todos los valores reales evaluados son cero, el MAPE se informa
como no definido. Los valores cercanos a cero pueden producir
porcentajes muy elevados.

### Acierto de signo

Porcentaje de meses en que coincide la dirección de la variación
predicha y la real.

Ambas variaciones se calculan respecto del mismo valor real del
mes anterior:

- Variación real: real del mes menos real del mes anterior.
- Variación predicha: predicción del mes menos real del mes anterior.

Se utilizan tres categorías: sube, baja y sin cambio.
Solo la coincidencia de categorías cuenta como acierto.

El modelo último valor siempre predice sin cambio. Por eso su acierto
es cero cuando todos los meses reales presentan subas o bajas.
Puede acertar en meses cuya producción real no cambia.

Inicialmente se evalúa sobre producción original.
Queda pendiente confirmar si la BCR requiere también una evaluación
sobre producción desestacionalizada.

## 9. Datos faltantes y fallos

- Los datos faltantes no se reemplazan automáticamente por cero.
- Se comprueba que haya una observación por mes, sin fechas duplicadas.
- Si falta un dato necesario, la evaluación señala el problema.
- Las predicciones deben ser finitas y no negativas.
- Si un modelo falla, se registra el mes y el motivo.
- Se informa la cobertura: meses predichos sobre los 12 meses previstos.
- Las métricas de una evaluación incompleta se calculan sobre los meses
  exitosos y se identifican como parciales.
- No se compara directamente una evaluación parcial con otra completa.

## 10. Modelos simples para comprobar la función

- Último valor: predice el mismo valor que el mes anterior.
- Estacional: predice el mismo valor que el mismo mes del año anterior.

La interfaz actual requiere:

- fit(serie): recibe la producción histórica de entrenamiento.
- predict(): devuelve una única predicción en unidades originales.
- Una función o clase que cree un modelo nuevo para cada iteración.

Otros modelos podrán conectarse mediante adaptadores.

## 11. Archivos y resultados

- docs/protocolo_evaluacion.md: reglas de evaluación.
- scripts/evaluacion.py: función reutilizable, modelos simples, ventanas,
  subperíodos y comparación de modelos.
- scripts/prueba_evaluacion.py: ejecución y comprobaciones.
- scripts/prueba_protocolo_largo.py: pruebas de ventanas, subperíodos,
  bootstrap y Diebold-Mariano.
- scripts/protocolo_largo.py: corre baselines y X-13 BCR en las dos ventanas.
- results/predicciones_baselines.csv: resultados mensuales.
- results/metricas_baselines.csv: métricas por serie y modelo.
- results/protocolo_predicciones.csv: predicciones por serie, modelo,
  ventana y mes.
- results/protocolo_metricas.csv: métricas por serie, modelo y ventana.
- results/protocolo_subperiodos.csv: métricas por subperíodo.
- results/protocolo_diferencias.csv: diferencias contra el naive
  estacional con intervalo y Diebold-Mariano.

Las corridas de X-13 se cachean en `data/cache_x13.db` (no se versiona).
La clave incluye un hash de los datos de entrenamiento y de los `.spc`: si
cambia un dato o una configuración, esa corrida se rehace sola. La primera
corrida completa tarda alrededor de una hora y media con 2 núcleos; las
siguientes, segundos.

Se utiliza results/ como carpeta común de resultados del equipo.

La tabla mensual incluye:

- Serie y modelo.
- Mes evaluado.
- Valor real y valor real del mes anterior.
- Predicción.
- Error, definido como predicción menos valor real.
- Acierto de signo.
- Estado de la predicción y motivo de fallo, si corresponde.
- Marca provisorio tomada de la fuente.

La tabla resumen incluye:

- Serie y modelo.
- Inicio y final del test.
- Meses previstos y evaluados.
- Cobertura y condición de evaluación completa.
- MAE y RMSE.
- MAPE, meses válidos y ceros excluidos.
- Acierto de signo.
- Cantidad de meses provisorios.

## 12. Pruebas realizadas

Se ejecutaron los dos modelos simples sobre las cuatro series,
con 12 meses por evaluación y cobertura del 100 %.

Se comprobaron:

- La cantidad de meses y la ausencia de fallos.
- Las predicciones contra los valores históricos correspondientes.
- Las cuatro métricas con un ejemplo pequeño calculable a mano.
- La presencia de la marca provisorio en cada mes evaluado.

Los 12 meses de cada evaluación están marcados como provisorios.
No hubo valores reales iguales a cero en el período evaluado.

## 13. Pendientes de confirmación

- Alinear con X-13 los inicios de entrenamiento y la versión de los datos.
- Confirmar el origen y significado de la columna provisorio.
- Confirmar la fecha de emisión de la predicción y el retraso de publicación.
- Confirmar la serie sobre la que la BCR requiere medir el acierto de signo.
- Obtener la configuración de X-13 de la BCR y su archivo .spc,
  si se requiere reproducir exactamente su procedimiento.

La ventana de test y el procedimiento walk-forward a un mes
ya fueron acordados con el equipo.

## 14. Integración futura de variables externas

La primera versión utiliza únicamente producción histórica.

Más adelante se incorporarán variables externas mediante una interfaz común:

- fit(y_train, X_train=None).
- predict(X_next=None).

Antes de incorporarlas se acordarán nombres, unidades, fechas de
disponibilidad, rezagos y tratamiento de faltantes.

Cada predicción utilizará únicamente información disponible al
momento de emitirla.

## 15. Criterios de finalización

- Protocolo documentado.
- Función reutilizable en el repositorio.
- Función probada con un modelo simple.