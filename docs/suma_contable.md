# Suma contable del biodiésel (SCRUM-60)

Código: `scripts/suma_contable.py`. Pruebas: `scripts/test_suma_contable.py`.

## Modelo

Predicción(t) = `demanda_interna_est`(t) + `expo_est`(t) + `otras_ventas_t1`(t).
Las tres partes vienen de `construir_features` (ver `docs/features.md`).

No estima parámetros. Los coeficientes valen 1 por la identidad contable
(producción = ventas + exportaciones + variación de stock). Con coeficientes
estimados, en el prototipo el MAE subió de ~22.000 a ~25.000 tn, porque hay
pocos datos y las exportaciones van a saltos. Una corrección del error
(promedio reciente o AR(1)) tampoco mejoró. El modelo es solo para biodiésel:
en bioetanol la producción no sigue a las ventas del mes.

## Resultados del backtest (2021-09 a 2025-08, 48 meses)

| Modelo | MAE (tn) |
|---|---|
| Suma contable | 21.947 |
| Naive | 23.673 |
| X-13 BCR | 28.264 |
| Piso práctico | 18.637 |

MAPE 22,4% y acierto de signo 66,7%. La comparación por error absoluto da:

| Contra | Diferencia de MAE (tn) | IC 95% | p (Diebold-Mariano) |
|---|---|---|---|
| Naive | −1.726 | −8.091 a +4.089 | 0,57 |
| X-13 BCR | −6.318 | −13.595 a +1.668 | 0,10 |

La suma contable tiene menos error, pero la diferencia no es estadísticamente
distinguible: ambos intervalos incluyen el cero. La regla de SCRUM-34 igual la
favorece si no resulta peor que el mejor modelo, porque es la más interpretable.

## Piso práctico

Con las ventas y exportaciones reales del mes, el único error restante es la
variación de stock: 18.637 tn de MAE. Ese error no se puede predecir con datos
públicos, pero el piso es una referencia y no un límite estricto: con las ventas
al corte reales y las exportaciones de INDEC, el MAE del backtest da 17.930 tn,
porque las diferencias entre INDEC y la Secretaría compensan parte del stock. El
modelo queda a ~3.300 tn del piso.

## Limitación

El backtest usa datos ya revisados, no los conocidos en cada mes
(`docs/features.md`), así que puede ser algo optimista.

El holdout se corre una sola vez, en SCRUM-34, con `--con-holdout`.
