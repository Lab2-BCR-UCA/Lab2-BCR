# Aporte de las variables clave (SCRUM-31)

Cuánto mejora el error cada decisión de modelado que no se había probado con el
protocolo (SCRUM-43), para justificar ante la BCR qué impulsa la producción y
elegir el modelo final (SCRUM-34) con respaldo.

La ablación de las exógenas del SARIMAX (INDEC/contables, corte, azúcar) ya está
en SCRUM-62 (`results/experimento_exogenas.csv`). Este documento cubre lo que
quedó afuera. **Todo se decide con el backtest (sep-2021 a ago-2025); el holdout
no se toca.** Las diferencias de MAE van con intervalo por bootstrap de bloques y
Diebold-Mariano (varianza HAC), con `comparar_modelos` de `evaluacion.py`.
Criterio del proyecto: una variante entra solo si **baja** el MAE y la diferencia
es **distinguible de cero** (IC95 que no cruza 0); si no, gana la parsimonia.

## 1. Transformación: nivel vs log (total y maíz)

El EDA de producción (SCRUM-45, parte B) concluye que el bioetanol total y el de
maíz son más parejos en nivel, pero el SARIMAX los modela en log como a las demás
series. `experimento_transformacion.py` corre el mismo modelo —mismo orden
`(1,1,1)(0,1,1,12)`, mismas exógenas— cambiando **solo** la transformación.

| Serie | MAE log | MAE nivel | dif (nivel−log) | IC95 | p (DM) | Distinguible |
|---|---|---|---|---|---|---|
| bioetanol_total | 7.528 | 8.253 | +726 | [−847, +2.363] | 0,38 | No |
| bioetanol_maíz | 6.216 | 5.937 | −279 | [−1.550, +1.013] | 0,67 | No |

**Decisión: se mantiene log en las cuatro series.** En el total el nivel es peor y
en el maíz es apenas mejor, pero en los dos casos el IC cruza 0: no hay diferencia
distinguible. Ante el empate, se mantiene log por continuidad con biodiésel y caña
(que el EDA sí deja en log) y por parsimonia. El MAE del maíz se corre un poco
según las versiones de statsmodels/numpy (ver nota en `docs/candidatas_28.md`);
no cambia la conclusión, porque la diferencia con log está dentro del ruido.

## 2. Margen doméstico del biodiésel

No entró en la ablación de SCRUM-62. Mecanismo: si el precio regulado no cubre el
costo del aceite, las plantas no entregan al corte (el colapso de 2020). El margen
(`margen_domestico_biodiesel`, rezago 0, disponible hacia el día 2-4 de t+1, los
tres insumos confirmados tras SCRUM-49) resume ese incentivo. `experimento_margen.py`
lo prueba con **ventana igualada**: el margen arranca en 2018 (lo deriva el aceite),
así que la base y la variante arrancan las dos en 2018-01, para no confundir el
efecto de la variable con el de acortar la ventana (misma lección que SCRUM-62).

| Config (desde 2018-01) | MAE | error máx (mes) | dif (con−sin) | IC95 | p (DM) | Distinguible |
|---|---|---|---|---|---|---|
| base (SARIMA puro) | 57.020 | 838.432 (2022-02) | — | — | — | — |
| + margen doméstico | 60.665 | 720.747 (2022-02) | +3.645 | [−2.280, +10.569] | 0,29 | No |

**Decisión: el margen no entra al SARIMAX.** Empeora el MAE y la diferencia no es
distinguible de cero.

Limitación a tener presente: con la ventana recortada a 2018, la propia base se
degrada mucho (MAE 57.020 contra 29.221 con la historia completa desde 2008, y
blow-ups de ~800.000 tn en 2022-02, cuando el salto de exportaciones entra en un
modelo en log con pocos años de entrenamiento). La comparación queda ruidosa, pero
la conclusión cualitativa se sostiene y es coherente con el resto del proyecto: el
biodiésel se mueve por sus **destinos** (exportaciones de INDEC), no por el margen,
y el efecto del margen es de **nivel** —el colapso de 2020—, que el protocolo ya
trata como **evento** y excluye del entrenamiento (SCRUM-53). No es una variable de
variación mensual.

## 3. Frecuencia de selección del elastic net

El resto de las candidatas se evalúa por su frecuencia de selección dentro del
walk-forward del elastic net (SCRUM-54, `results/elastic_net_seleccion.csv`): en
cuántas de las 48 iteraciones del backtest la penalización L1/L2 le dio
coeficiente distinto de cero, y con qué signo. Se listan las variables sustantivas
(sin las dummies de mes ni los indicadores de faltante) con selección ≥ 25 %.

**bioetanol_maíz**

| Variable | Selección | Coef. mediana (tn) | Signo + |
|---|---|---|---|
| ventas_nafta_total_m3 | 100 % | +4.083 | 100 % |
| corte_efectivo_bioetanol_maiz | 100 % | +3.661 | 100 % |
| lag_1 / lag_2 / lag_12 | 100 % | +1.993 a +3.760 | 100 % |
| margen_bioetanol_maiz | 25 % | +30 | 75 % |

**bioetanol_caña**

| Variable | Selección | Coef. mediana (tn) | Signo + |
|---|---|---|---|
| lag_1 / lag_12 | 100 % | +4.639 a +7.932 | 100 % |
| ventas_nafta_total_m3 | 63 % | +791 | 100 % |
| azucar_usd_kg | 31 % | +101 | 67 % |
| corte_efectivo_bioetanol_cana | 29 % | +260 | 100 % |

**biodiésel (con contables)**

| Variable | Selección | Coef. mediana (tn) | Signo + |
|---|---|---|---|
| expo_est (exportaciones INDEC) | 100 % | +40.171 | 100 % |
| demanda_interna_est | 100 % | +5.312 | 100 % |
| lag_1 | 100 % | +8.813 | 100 % |
| corte_biodiesel_nominal_pct | 96 % | +2.610 | 100 % |
| molienda_soja_tn | 96 % | +4.226 | 100 % |
| ventas_gasoil_total_m3 | 44 % | +3.304 | 100 % |

Todos los signos son económicamente correctos (más demanda, exportaciones,
molienda o ventas → más producción). El coeficiente de `expo_est` (+40.171)
confirma que las exportaciones dominan el biodiésel.

## Conclusión: qué mantener (alimenta SCRUM-34)

- **Transformación:** log en las cuatro series. Nivel no se distingue de log en
  total ni en maíz.
- **Margen doméstico del biodiésel:** no entra al SARIMAX. Su valor es de nivel
  (evento 2020), ya cubierto por la exclusión de eventos (SCRUM-53), no de
  precisión mensual.
- **Variables que importan, por serie:**
  - *maíz:* ventas de nafta + corte efectivo + inercia (lags). El margen de maíz
    es marginal (25 %).
  - *caña:* sobre todo inercia estacional (lags) y algo de nafta; azúcar y corte
    efectivo entran poco (la zafra ya la captura la estacionalidad).
  - *biodiésel:* exportaciones (expo_est) por lejos, más demanda interna, corte
    nominal y molienda. Es la descomposición contable, no el mercado interno
    suelto.
- **Lectura para el 34:** la evidencia refuerza el reparto por producto —biodiésel
  por sus destinos (suma contable), bioetanol por nafta + estacionalidad + corte—
  y no agrega transformaciones ni variables nuevas al conjunto ya elegido.

## Reproducir

```
python scripts/experimento_transformacion.py   # tabla 1 -> results/experimento_transformacion.csv
python scripts/experimento_margen.py            # tabla 2 -> results/experimento_margen.csv
# tabla 3: results/elastic_net_seleccion.csv (SCRUM-54)
```
