# Elastic net con variables externas (SCRUM-54)

Código: `scripts/elastic_net.py`. Pruebas: `scripts/test_elastic_net.py`.
Resultados: `results/elastic_net_*.csv`.

## Especificación

- Regresión lineal con penalización L1/L2 sobre todas las candidatas. El target
  va en niveles y lleva dummies de mes, así que cada coeficiente se lee en tn o
  m³.
- Features del constructor común (SCRUM-59), con sus rezagos de
  disponibilidad, más los rezagos propios 1, 2 y 12.
- Todo lo que se ajusta con datos se ajusta solo con el entrenamiento de cada
  iteración del walk-forward:
  - imputación y estandarización de X;
  - estandarización de y;
  - lambda y mezcla L1/L2.
- Lambda y la mezcla salen de `TimeSeriesSplit` (5 folds) dentro del
  entrenamiento. En cada fold se reajustan la imputación y la estandarización.
  La grilla es de 20 lambdas por 4 mezclas (0,1; 0,5; 0,9 y 1), el criterio es
  el MAE de validación, y nunca hay validación aleatoria.
- Las variables con historia más corta que la ventana se imputan con la media
  del entrenamiento y se les agrega un indicador de faltante. Pasa con los
  márgenes (desde 2018) y la molienda (desde 2015). La fila del mes a estimar
  siempre está completa, porque lo exige el constructor.
- Se aplica la máscara de eventos de SCRUM-53. La predicción se recorta en 0.

Ventanas de entrenamiento:
- maíz desde 2012-09 y caña desde 2013-01, iguales al SARIMAX;
- biodiésel desde 2012-01 (arranque de INDEC) en todas sus versiones, para
  que la comparación mida variables y no un cambio de ventana.

## Modelos

| Modelo | Candidatas |
|---|---|
| `bioetanol_maiz` | ventas de nafta, margen de maíz, corte efectivo de maíz (t-1) |
| `bioetanol_cana` | ventas de nafta, azúcar, corte efectivo de caña (t-1) |
| `bioetanol_total` | suma de las predicciones de maíz y caña |
| `biodiesel_sin_contables` | gasoil, molienda, aceite de soja, margen doméstico, corte nominal, COTAB, corte efectivo (t-1) |
| `biodiesel_con_contables` | lo anterior más `demanda_interna_est`, `expo_est`, `expo_indec_oculto` y `otras_ventas_t1` (en toneladas) |

Las variantes de control para SCRUM-53 son biodiésel con contables:
- `_sin_eventos`: sin excluir los meses de eventos;
- `_dummy_evento`: sin excluir los eventos y con el indicador "corte efectivo
  del mes anterior < 2%".

## Resultados del backtest (2021-09 a 2025-08, 48 meses)

| Serie | Modelo | MAE | Naive | X-13 BCR |
|---|---|---|---|---|
| Bioetanol maíz | elastic net | 5.449 m³ | 5.631 | 5.092 |
| Bioetanol caña | elastic net | 5.661 m³ | 7.849 | 5.282 |
| Bioetanol total | suma de elastic nets | 7.242 m³ | 8.167 | 7.289 |
| Biodiésel | sin contables | 34.132 tn | 23.673 | 28.264 |
| Biodiésel | con contables | 27.114 tn | 23.673 | 28.264 |
| Biodiésel | con contables, sin excluir eventos | 24.407 tn | 23.673 | 28.264 |
| Biodiésel | suma contable (SCRUM-60) | 21.947 tn | 23.673 | 28.264 |

Diferencias de MAE con IC 95% por bootstrap y p de Diebold-Mariano
(`results/elastic_net_diferencias.csv`). Un valor negativo significa que el
elastic net tiene menos error.

| Elastic net | Contra | Dif. MAE | IC 95% | p |
|---|---|---|---|---|
| Caña | naive | −2.189 | −3.429 a −887 | 0,002 |
| Caña | X-13 BCR | +379 | −1.383 a +2.157 | 0,68 |
| Maíz | X-13 BCR | +357 | −611 a +1.299 | 0,50 |
| Total | X-13 BCR | −47 | −1.620 a +1.651 | 0,95 |
| Biodiésel con contables | sin contables | −7.018 | −11.288 a −3.025 | 0,002 |
| Biodiésel con contables | suma contable | +5.168 | +852 a +9.484 | 0,026 |
| Biodiésel sin excluir eventos | suma contable | +2.460 | −1.672 a +6.636 | 0,27 |
| Biodiésel sin excluir eventos | con exclusión | −2.708 | −4.251 a −1.434 | 0,001 |

Lectura:

- **Bioetanol.** El elastic net empata con el X-13 BCR en las tres series (ninguna
  diferencia es distinguible) y le gana claro al naive en caña. Su ventaja es
  que es explicable: cada predicción es una suma de aportes.
- **Biodiésel.** Las contables son lo que importa: sin ellas el modelo pierde
  incluso contra el naive. Con ellas, el resto de las candidatas no agrega. La
  mejor versión (sin excluir eventos) queda 2.460 tn por encima de la suma
  contable, sin diferencia distinguible. La versión con exclusión es peor que la
  suma contable de forma distinguible. Para el biodiésel la suma contable sigue
  siendo la referencia: es igual de explicable y no estima nada.

## Variables seleccionadas

En `results/elastic_net_seleccion.csv` está, por variable, la frecuencia con
que entra entre las 48 iteraciones, su coeficiente mediano cuando entra (en tn
o m³ por un desvío de la variable) y el porcentaje de veces con signo positivo.
Las que entran siempre o casi siempre:

- **Maíz:** ventas de nafta (+4.083), corte efectivo de maíz t-1 (+3.661) y
  rezagos 1, 2 y 12. Todas con signo estable.
- **Caña:** rezagos 1 y 12, las dummies de zafra (junio y julio positivas,
  diciembre negativa) y ventas de nafta (62% de las iteraciones, +791). El azúcar
  entra en el 31% y el corte efectivo de caña en el 29%: aporte débil, en línea
  con la ablación de SCRUM-62.
- **Biodiésel con contables:** `expo_est` (+40.171), `demanda_interna_est`,
  rezago 1, diciembre negativo, molienda y corte nominal. Todas con signo
  estable entre iteraciones.

**Ojo con los indicadores de faltante de los márgenes** (doméstico en biodiésel,
de maíz en bioetanol). Valen 1 antes de 2018,
entran casi siempre y funcionan como una dummy de nivel de esos años, no como
efecto del margen (el margen en sí entra solo entre el 4% y el 27% de las
iteraciones). No es leakage: en el backtest valen siempre 0, así que su aporte
es una constante igual en todos los meses y se suma al intercepto. Hay que
leerlos así en las tablas de contribuciones (SCRUM-35).

## Eventos: resultado empírico (SCRUM-53)

La regla de SCRUM-53 es excluir del entrenamiento los meses de eventos
terminados. En el elastic net del biodiésel **la exclusión empeora**: sin excluir,
el MAE baja 2.708 tn (IC −4.251 a −1.434, p 0,001). La razón está en los
coeficientes. Con la exclusión, `demanda_interna_est` pesa menos de la mitad
(+5.312 contra +13.620 por desvío). Los meses de 2020-2021 con corte casi nulo
no son una relación falsa: son justamente los que muestran que, cuando cae el
corte, cae la producción. La demanda interna estimada ya los captura, porque es
gasoil por corte efectivo t-1. Sacarlos le quita al modelo la variación que
identifica ese efecto.

La dummy como predictor tampoco suma. Contra el mismo modelo sin excluir, el MAE
sube 1.004 tn (IC +72 a +2.136, p 0,07). Es consistente con lo que anticipaba
`docs/eventos.md`: es redundante con el corte efectivo.

Recomendación para SCRUM-34: tomar la versión sin excluir eventos del elastic
net del biodiésel. La tabla y la función de exclusión quedan disponibles para
los modelos donde sí sirvan.

## Limitaciones

- El backtest usa datos revisados, no los conocidos en cada mes
  (`docs/features.md`), así que puede ser algo optimista.
- La comparación contra la suma contable lee
  `results/suma_contable_predicciones.csv` de SCRUM-60. Si no está en `results/`,
  el script saltea esa fila con un aviso.
- El holdout se corre una sola vez, en SCRUM-34, con `--con-holdout`.
