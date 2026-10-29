# Constructor común de features (SCRUM-59)

`scripts/construir_features.py` arma la matriz de predictores `X` y el target
`y` para un objetivo y un mes de corte. Lo usan el SARIMAX (SCRUM-29/62), el
elastic net (SCRUM-54) y la suma contable (N4), así todos ven **las mismas
variables con los mismos rezagos** y las tablas de contribución (SCRUM-35)
hablan el mismo idioma.

## Qué hace

```python
import sys; sys.path.insert(0, "scripts")
from construir_features import construir_features

# Exógenas de mercado (lo que consumía el SARIMAX de SCRUM-29)
X, y = construir_features("bioetanol_maiz", "2024-05")

# Biodiésel con su descomposición contable
X, y = construir_features("biodiesel", "2024-05",
                          incluir=("exogenas", "contables"))

X.attrs["grupos"]   # {'calendario': [...], 'contables': [...]}  -> para SCRUM-35
```

- `y`: producción en unidades originales hasta `fecha_corte − 1` (lo que se sabe
  al estimar).
- `X`: una fila por mes, desde el inicio de la serie hasta `fecha_corte`
  **inclusive** (la última fila es la del mes a estimar). Cada variable entra
  desplazada por su rezago (`data/disponibilidad_variables.csv`, SCRUM-26), de
  modo que `X.loc[t]` nunca usa un dato que se publica después de que la BCR
  estima el mes `t`.

## Grupos de features (`incluir`)

| Grupo | Qué agrega | Para quién |
|---|---|---|
| `exogenas` *(default)* | Candidatas de mercado de cada objetivo (`EXOGENAS`), por mecanismo del EDA (SCRUM-28). En log salvo `NO_LOG` (decisión **fija por variable**). | Todos |
| `contables` | Descomposición contable del **biodiésel** (ver abajo). No hace nada para el bioetanol. | SARIMAX-62, suma contable N4 |
| `lags` | Rezagos propios del objetivo (1, 2, 12). | Elastic net (SCRUM-54) |
| `dummies` | Indicadores de mes calendario. | Elastic net |

`con_calendario=True` (default) agrega `dias_mes` y la estacionalidad de Fourier
(`sin12`, `cos12`). `exogenas_extra=[(serie_id, rezago), ...]` suma candidatas
puntuales sin tocar `EXOGENAS` (lo usa la ablación de SCRUM-62).

El default `incluir=("exogenas",)` reproduce exactamente lo que consumía el
SARIMAX de SCRUM-29; los grupos nuevos se piden explícitamente.

## Descomposición contable del biodiésel

El biodiésel se mueve por sus **destinos** (corte interno + exportaciones), no
por el mercado interno suelto —que además desestabiliza el SARIMAX (SCRUM-29)—.
El grupo `contables` arma, sin leakage:

- **`demanda_interna_est`** = `ventas_gasoil_total_m3`(t) ×
  (`biodiesel_ventas_corte_tn` / `ventas_gasoil_total_m3`)(t−1). Estima la
  demanda del corte de t con el gasoil de t (rezago 0) y la tasa de corte de t−1
  (las ventas al corte vienen del archivo de producción, rezago 1). Mezcla
  rezagos 0 y 1, por eso no puede ser una derivada de la base (SCRUM-56 no
  permite mezclar rezagos).
- **`expo_est`** = `expo_indec_tn`(t) (INDEC, rezago 0; SCRUM-57). En los meses
  ocultos por secreto estadístico se imputa con la **mediana de
  `biodiesel_exportaciones_tn` (Secretaría) de los meses ocultos anteriores**; si
  todavía no hubo ningún oculto (el primero, 2018-09), cae a la mediana de
  *todos* los meses anteriores. Siempre con datos hasta t−1 y nunca el valor real
  del propio mes oculto. Así no quedan NaN en el medio de la serie.
- **`expo_indec_oculto`**(t): 1 si el mes de INDEC está oculto (marca que
  `expo_est` de ese mes es imputado).
- **`otras_ventas_t1`** = `biodiesel_otras_ventas_tn`(t−1) (rezago 1).

Su suma reconstruye la mayor parte de la producción: es la base de la suma
contable N4. INDEC arranca en 2012, así que con contables el biodiésel entrena
desde 2012 (no desde 2008): el constructor lo avisa (`warnings.warn`) y expone el
primer mes con contables en `X.attrs["contables_desde"]`.

## Anti-leakage y robustez

- **Rezagos.** Cada variable se desplaza por su rezago, así la fila del mes a
  estimar nunca toma un dato publicado después de la fecha de corte.
- **Log fijo por variable.** La decisión de tomar logaritmo no mira los datos
  (es log salvo `NO_LOG`), para que un 0 en un mes *posterior* al corte no cambie
  la fila del corte. La positividad se valida solo con datos ≤ corte.
- **Fila del mes a estimar.** Si esa fila queda con algún NaN (un insumo sin
  actualizar en la base), el constructor **frena** nombrando la variable
  (`exigir_fila_completa=True`, default). Los anexos del SARIMAX
  (`--diagnosticos`, `--intervalos`) lo ponen en `False` para mostrar el último
  mes estimable best-effort.
- **Variable ausente.** Una exógena que no está en la base **frena** nombrándola
  (no se saltea en silencio).

## Punto en el tiempo (limitación conocida)

El constructor es agnóstico al `base` que recibe: el anti-leakage lo dan los
rezagos, no la versión del dato. Hoy se le pasa la última versión consolidada
(`leer_dataset`), así que el backtest usa datos **revisados**, no los que se
conocían en cada mes — y esto vale para todas las series, no solo INDEC
(`docs/exportaciones_indec.md`). Es algo optimista respecto de una corrida en
tiempo real. Reconstruir los vintages a cada fecha requeriría historia de
versiones que la base hoy no tiene para los meses viejos; si se arma, se le pasa
esa base a esta misma función sin cambios. Queda como ajuste del DoD del ticket.

## Pruebas

```bash
python scripts/test_construir_features.py
```

Cubre: anti-leakage de la fila a estimar (envenenando el futuro **y** el propio
mes de corte en las variables de rezago 1), que el log no mira el futuro, la
imputación de los ocultos (mediana de ocultos previos, con fallback al primero,
nunca el real del mes), que la fila incompleta y la variable ausente frenan, que
los rezagos no son menores que `disponibilidad_variables.csv`, y que el default
reproduce el conjunto de SCRUM-29.
