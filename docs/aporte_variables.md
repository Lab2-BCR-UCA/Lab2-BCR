# Aporte de las variables clave (SCRUM-31)

Cuánto mejora el error cada decisión de modelado que no se había probado con el
protocolo (SCRUM-43), para justificar ante la BCR qué impulsa la producción y
elegir el modelo final (SCRUM-34) con respaldo.

La ablación de las exógenas del SARIMAX (INDEC/contables, corte, azúcar) ya está
en SCRUM-62 (`results/experimento_exogenas.csv`). Este documento cubre lo que
quedó afuera. **Todo se decide con el backtest (sep-2021 a ago-2025); el holdout
no se toca.** Las diferencias de MAE van con intervalo por bootstrap de bloques y
Diebold-Mariano (varianza HAC), con `comparar_modelos` de `evaluacion.py`.
Criterio del proyecto: una variante entra si **baja** el MAE y la diferencia es
**distinguible de cero** (IC95 que no cruza 0); si no, gana la parsimonia.

Unidades: biodiésel en toneladas (tn); bioetanol en metros cúbicos (m³).

## 1. Transformación: nivel vs log (total y maíz)

El EDA de producción (SCRUM-45, parte B) concluye que el bioetanol total y el de
maíz son más parejos en nivel, pero el SARIMAX los modela en log como a las demás
series. `experimento_transformacion.py` corre el mismo modelo —mismo orden
`(1,1,1)(0,1,1,12)`, mismas exógenas— cambiando **solo** la transformación.

| Serie | MAE log (m³) | MAE nivel (m³) | dif (nivel−log) | IC95 | p (DM) | Distinguible |
|---|---|---|---|---|---|---|
| bioetanol_total | 7.528 | 8.253 | +726 | [−847, +2.363] | 0,38 | No |
| bioetanol_maíz | 6.216 | 5.937 | −279 | [−1.550, +1.013] | 0,67 | No |

**Decisión: se mantiene log en las cuatro series.** En el total el nivel es peor y
en el maíz es apenas mejor, pero en los dos casos el IC cruza 0. Ante el empate se
mantiene log, por continuidad con biodiésel y caña y por parsimonia. El MAE del
maíz se corre un poco según las versiones de statsmodels/numpy (ver nota en
`docs/candidatas_28.md`); no cambia la conclusión.

## 2. Margen doméstico del biodiésel

No entró en la ablación de SCRUM-62. Mecanismo: si el precio regulado no cubre el
costo del aceite, las plantas no entregan al corte (2020). El margen
(`margen_domestico_biodiesel`, rezago 0, disponible hacia el día 2-4 de t+1, los
tres insumos confirmados tras SCRUM-49) existe desde 2018-01.
`experimento_margen.py` lo prueba en los dos modelos donde puede entrar.

| Modelo | Comparación | MAE sin | MAE con | dif (con−sin) | IC95 | p (DM) |
|---|---|---|---|---|---|---|
| SARIMAX (desde 2018-01) | base vs base + margen | 57.020 | 60.665 | +3.645 | [−2.280, +10.569] | 0,29 |
| Elastic net `sin_eventos` | margen aplanado vs margen | 25.313 | 24.407 | −906 | [−2.105, −79] | 0,10 |

**SARIMAX: no concluyente.** Base y variante arrancan en 2018-01 para igualar la
ventana, y con esa ventana la base queda rota. La base es SARIMA puro (no tiene
exportaciones ni ninguna exógena): el problema es la salida del colapso de
2020-2021. Entre enero y febrero de 2021 la producción pasó de 28.073 a 164.411 tn
(×5,9), y el modelo en log, con diferencia estacional, repite ese salto un año
después: 189.217 × 5,9 ≈ 1,1 millones de tn para 2022-02 (predijo 1,02 M, contra
177.386 reales). Esa base
tiene MAE 57.020, más del doble que el naive (23.673), así que no sirve para medir
el margen. La fila se reporta, pero no decide.

**Elastic net: evidencia débil a favor.** El elastic net del biodiésel que SCRUM-54
recomienda para SCRUM-34 (`biodiesel_con_contables_sin_eventos`) ya incluye el
margen. Antes de 2018 el margen es NaN y el imputador agrega un indicador de
faltante, que funciona como una dummy de "antes de 2018". Si se saca la variable
entera también se va esa dummy, y se mezclan los dos efectos. Por eso se compara
contra la misma versión con el margen **aplanado** (`Config.aplanar` en
`elastic_net.py`): el valor queda constante donde hay dato, los NaN se mantienen y
el indicador también. Así la diferencia mide solo el aporte del valor del margen.
El margen baja el MAE en 906 tn y el IC no cruza 0, pero Diebold-Mariano no llega
al 5 % (p = 0,10): es evidencia débil, no concluyente.

**Decisión: el margen queda fuera del SARIMAX y se mantiene en el elastic net.**

## 3. Frecuencia de selección del elastic net

El resto de las candidatas se evalúa por su frecuencia de selección dentro del
walk-forward del elastic net (SCRUM-54, `results/elastic_net_seleccion.csv`): en
cuántas de las 48 iteraciones del backtest la penalización L1/L2 le dio
coeficiente distinto de cero, y con qué signo. Se listan las variables sustantivas
(sin las dummies de mes ni los indicadores de faltante) con selección ≥ 25 %.

El coeficiente es el cambio en la producción (m³ o tn) **por un desvío estándar de
la variable** en el entrenamiento, y se reporta la mediana entre las iteraciones
en que la variable fue elegida. "Signo +" es el porcentaje de esas iteraciones con
coeficiente positivo.

Para el biodiésel se usa la versión `con_contables_sin_eventos`, la que SCRUM-54
recomienda para SCRUM-34 (excluir los eventos empeoraba el MAE).

**bioetanol_maíz** (m³)

| Variable | Selección | Coef. mediana (m³ por 1 desvío) | Signo + |
|---|---|---|---|
| ventas_nafta_total_m3 | 100 % | +4.083 | 100 % |
| corte_efectivo_bioetanol_maiz | 100 % | +3.661 | 100 % |
| lag_1 / lag_2 / lag_12 | 100 % | +1.993 a +3.760 | 100 % |
| margen_bioetanol_maiz | 25 % | +30 | 75 % |

**bioetanol_caña** (m³)

| Variable | Selección | Coef. mediana (m³ por 1 desvío) | Signo + |
|---|---|---|---|
| lag_1 / lag_12 | 100 % | +4.639 a +7.932 | 100 % |
| ventas_nafta_total_m3 | 63 % | +791 | 100 % |
| azucar_usd_kg | 31 % | +101 | 67 % |
| corte_efectivo_bioetanol_cana | 29 % | +260 | 100 % |

**biodiésel, `con_contables_sin_eventos`** (tn)

| Variable | Selección | Coef. mediana (tn por 1 desvío) | Signo + |
|---|---|---|---|
| expo_est (exportaciones INDEC) | 100 % | +41.694 | 100 % |
| demanda_interna_est | 100 % | +13.620 | 100 % |
| lag_1 | 100 % | +7.162 | 100 % |
| molienda_soja_tn | 96 % | +2.826 | 100 % |
| ventas_gasoil_total_m3 | 35 % | +2.087 | 100 % |
| lag_2 | 33 % | +910 | 100 % |
| margen_domestico_biodiesel | 25 % | +558 | 100 % |

El corte nominal del biodiésel entra solo en el 12,5 % de las iteraciones.

**Signos.** No todos coinciden con lo esperado:

- **Azúcar (caña):** por mecanismo se espera signo **negativo** (azúcar cara → los
  ingenios destinan más caña a azúcar y sale menos bioetanol; ver
  `docs/candidatas_28.md`), pero cuando entra sale **positivo** en el 67 % de las
  iteraciones. El elastic net no recupera el mecanismo, así que el azúcar no sirve
  para explicar la caña.
- **Margen del maíz:** entra poco (25 %) y su signo no es estable (positivo en el
  75 %).
- **Corte efectivo (maíz y caña):** el signo es el esperado, pero la variable es
  casi circular. Sale de ventas al corte / ventas de nafta, y las ventas al corte
  siguen a la producción (SCRUM-62, `docs/corte.md`): antes del backtest, su
  correlación con la producción de maíz del mismo mes es 0,97 en niveles. Entra
  con rezago 1, así que no hay leakage, pero lo que aporta es **inercia** (la
  producción del mes anterior por otra vía), no un impulsor.

**Fuera de alcance.** `docs/corte.md` proponía probar la brecha efectivo − nominal
para el tramo de cupos de bioetanol (2012 a ago-2014). No se probó: ese tramo
queda antes del backtest y solo pesa en el entrenamiento.

## Conclusión: qué mantener (alimenta SCRUM-34)

- **Transformación:** log en las cuatro series. Nivel no se distingue de log en
  total ni en maíz.
- **Margen doméstico del biodiésel:** fuera del SARIMAX (la comparación no es
  concluyente porque la base con ventana desde 2018 está rota) y se mantiene en el
  elastic net, donde hay evidencia débil a favor (−906 tn, IC [−2.105, −79],
  p = 0,10).
- **Variables por serie:**
  - *Biodiésel:* las exportaciones de INDEC (`expo_est`) dominan, seguidas por la
    demanda interna estimada y la molienda. Ventas de gasoil, `lag_2` y el margen
    entran en una de cada tres o cuatro iteraciones. Es la descomposición
    contable: el biodiésel se mueve por sus destinos.
  - *Maíz:* ventas de nafta e inercia. El corte efectivo entra siempre, pero como
    inercia (casi circular), no como causa. El margen del maíz es marginal e
    inestable.
  - *Caña:* sobre todo inercia estacional (lags) y algo de nafta. El azúcar entra
    poco y con el signo contrario al del mecanismo, así que no se usa para
    explicar.
- **Lectura para el 34:** la evidencia respalda el reparto por producto —biodiésel
  por sus destinos (suma contable o elastic net con contables), bioetanol por
  nafta y estacionalidad— y no agrega transformaciones nuevas. En las
  explicaciones para la BCR, el corte efectivo se presenta como inercia y el
  azúcar no se presenta como impulsor de la caña.

## Reproducir

```
python scripts/experimento_transformacion.py   # tabla 1 -> results/experimento_transformacion.csv
python scripts/experimento_margen.py            # tabla 2 -> results/experimento_margen.csv
# tabla 3: results/elastic_net_seleccion.csv (SCRUM-54)
```
