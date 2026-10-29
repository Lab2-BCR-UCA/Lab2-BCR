# Protocolo de evaluación de modelos

Estado: protocolo largo (SCRUM-43) con backtest de selección y holdout
final. Las respuestas recibidas de la BCR se resumen en
[`respuestas_bcr.md`](respuestas_bcr.md); solo los puntos realmente abiertos
siguen en la sección 13.

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

La BCR confirmó que su evaluación de X-13 también realiza
12 predicciones a un mes, reajustando el modelo en cada iteración
con forecast maxlead=1.

Este backtest supone que el dato del mes anterior está disponible. Está
confirmado: al estimar el mes t, el último dato de producción que tiene la
BCR es t-1 (mail de la BCR del 9/10; ver `docs/disponibilidad_temporal.md`,
SCRUM-26).

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
reportan dos pérdidas: **error absoluto en toneladas o m³ (MAE, métrica
principal)** y error absoluto porcentual (MAPE, de referencia). El cálculo
del MAPE no cambia; solo cambia el criterio de priorización porque un mismo
error en toneladas pesa mucho más porcentualmente en meses de baja producción.

Estos intervalos son de la **diferencia de error entre dos modelos**, para
saber si uno le gana al otro. No son intervalos de predicción: los
intervalos 80/95 de cada pronóstico los produce cada modelo (SCRUM-29 y
SCRUM-54).

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

`python scripts/protocolo_largo.py`. **MAE** (toneladas para biodiésel,
m³ para bioetanol; menor es mejor). `x13_bcr` es la
variante que reproduce a BCR (criterio log/nivel sobre los últimos 12
meses: log en biodiesel, nivel en bioetanol); `x13_bcr_selcompleta` aplica
el criterio sobre toda la serie y en biodiesel termina eligiendo nivel.
Los MAPE siguen disponibles en `results/protocolo_metricas.csv`.

| Serie | Ventana | naive | naive estacional | x13_auto | x13_bcr_selcompleta | x13_bcr |
|---|---|---|---|---|---|---|
| Biodiesel | backtest | **23.673** | 58.671 | 27.188 | 30.089 | 28.264 |
| Biodiesel | holdout | 16.963 | **15.708** | 18.648 | 16.602 | 18.648 |
| Bioetanol total | backtest | 8.167 | 12.489 | 7.303 | 7.303 | **7.289** |
| Bioetanol total | holdout | 10.882 | **5.327** | 7.911 | 7.911 | 7.911 |
| Bioetanol maíz | backtest | 5.631 | 9.381 | **5.062** | **5.062** | 5.092 |
| Bioetanol maíz | holdout | 4.271 | 4.391 | 3.878 | 3.878 | **3.839** |
| Bioetanol caña | backtest | 7.849 | 8.526 | 5.812 | 5.812 | **5.282** |
| Bioetanol caña | holdout | 9.046 | 4.405 | 4.653 | 4.653 | **4.161** |

Lectura:

- **En el backtest, el X-13 de BCR le gana al naive estacional en las
  cuatro series:** con pérdida absoluta (MAE), las diferencias tienen
  intervalos del 95 % que excluyen el cero y Diebold-Mariano da p ≤ 0,014.
  Pero en **biodiésel el naive del mes anterior gana al X-13 BCR**:
  MAE de 23.673 contra 28.264 tn.
- **En el holdout de 12 meses casi todas las diferencias de MAE son
  inconcluyentes:** la excepción frente al naive estacional es el naive
  de caña, que resulta peor. Se reserva el holdout para confirmar y no
  para cambiar decisiones del modelo.
- El naive estacional de biodiésel tiene MAE de 58.671 tn (MAPE 73,6 %)
  en el backtest por la caída de producción de 2023: predice cada mes
  con el mismo mes de 2022, cuando se producían más de 160 mil toneladas,
  frente a 20-60 mil en 2023. No es un error de cálculo.
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

**Métrica principal: MAE** en la unidad original de cada serie. MAPE,
RMSE y acierto de signo se siguen calculando como referencias y diagnósticos;
no se modificó la fórmula de ninguna métrica.

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
- results/baselines.csv: **única fuente de métricas de los baselines**
  para el test corto (SCRUM-22); contiene también cobertura y provisorios.
  La genera `scripts/baselines.py` y la leen `scripts/comparacion.py` y
  `notebooks/replica_x13.ipynb`.
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

En la validación original de la ventana corta se ejecutaron los dos modelos
simples sobre las cuatro series, con 12 meses por evaluación y cobertura del
100 %. El protocolo largo posterior se valida con
`scripts/prueba_protocolo_largo.py`.

Se comprobaron:

- La cantidad de meses y la ausencia de fallos.
- Las predicciones contra los valores históricos correspondientes.
- Las cuatro métricas con un ejemplo pequeño calculable a mano.
- La presencia de la marca provisorio en cada mes evaluado.

Los 12 meses de esa ventana corta están marcados como provisorios.
No hubo valores reales iguales a cero en el período evaluado.

## 13. Pendientes de confirmación

Ya confirmados (registro y fuentes en [`respuestas_bcr.md`](respuestas_bcr.md)):

- Retraso de publicación: al estimar t, el último dato de producción es t-1
  (mail de la BCR del 9/10, SCRUM-26).
- Configuración de X-13 de la BCR: se usan sus cuatro `.spc` y la réplica
  coincide con los 12 pronósticos de su Excel (SCRUM-41). El criterio
  elige la transformación de menor dispersión de la variación logarítmica
  mensual de D12; **la longitud exacta de su ventana no fue confirmada**.
- Los últimos 12 meses figuran siempre como provisorios, según confirmó la
  BCR. Por eso el holdout se informa como provisorio.
- Reunión con la BCR del 20/10: la BCR quiere **un número concreto, sin
  rangos**, y lo que más pesa no es el valor del índice sino el **poder
  explicativo** de las variables. El pronóstico puntual es el entregable;
  los intervalos de predicción quedan como apoyo interno.
- La BCR no tiene un día fijo de cierre previo al 25-27: puede esperar
  datos de molienda y ventas del mes estimado o estimarlos cuando faltan.
  Esto quedó registrado en SCRUM-26.

Pendientes:

- Alinear con X-13 los inicios de entrenamiento: hoy `x13_bcr` usa el
  inicio de sus `.spc` (2010 en bioetanol total y caña) y los demás modelos
  el de la sección 4. La diferencia está documentada en
  `docs/x13_config_bcr.md`.
- Confirmar con la BCR la ventana del criterio de selección log/nivel.
  `x13_bcr` usa los últimos 12 meses porque reproduce su elección;
  `x13_bcr_selcompleta` usa toda la serie.
- Confirmar la serie sobre la que la BCR requiere medir el acierto de signo.

La ventana de test y el procedimiento walk-forward a un mes
ya fueron acordados con el equipo.

## 14. Integración de variables externas

Los baselines y el X-13 usan solo la producción histórica. El constructor
común `scripts/construir_features.py` (SCRUM-59) ya permite preparar
variables externas para los modelos que las requieran; SARIMAX inicial
(SCRUM-29) está implementado y sus exógenas adicionales se siguen
integrando en SCRUM-62. La suma contable (SCRUM-60) y elastic net
(SCRUM-54) reutilizarán el constructor.

La interfaz de evaluación para esos modelos debe adaptar el equivalente a
`fit(y_train, X_train)` y `predict(X_next)` respetando la fecha de corte.
Los nombres, unidades, rezagos y disponibilidad se documentan en
`docs/features.md` y `docs/disponibilidad_temporal.md`. Cada predicción
debe utilizar únicamente información disponible al momento de emitirla;
las limitaciones por revisiones de datos están descritas en la sección 6.

## 15. Criterios de finalización

- Protocolo documentado.
- Función reutilizable en el repositorio.
- Función probada con un modelo simple.
