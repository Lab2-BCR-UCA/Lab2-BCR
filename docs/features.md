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
| `exogenas` *(default)* | Candidatas de mercado de cada objetivo (`EXOGENAS`), por mecanismo del EDA (SCRUM-28). En log si es volumen/precio positivo. | Todos |
| `contables` | Descomposición contable del **biodiésel** (ver abajo). No hace nada para el bioetanol. | SARIMAX-62, suma contable N4 |
| `lags` | Rezagos propios del objetivo (1, 2, 12). | Elastic net (SCRUM-54) |
| `dummies` | Indicadores de mes calendario. | Elastic net |

`con_calendario=True` (default) agrega `dias_mes` y la estacionalidad de Fourier
(`sin12`, `cos12`).

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
  `biodiesel_exportaciones_tn` (Secretaría) de los meses ocultos anteriores**,
  usando solo datos hasta t−1. Nunca usa el valor real de la Secretaría del
  propio mes oculto.
- **`expo_indec_oculto`**(t): 1 si el mes de INDEC está oculto (marca que
  `expo_est` de ese mes es imputado).
- **`otras_ventas_t1`** = `biodiesel_otras_ventas_tn`(t−1) (rezago 1).

Su suma reconstruye la mayor parte de la producción: es la base de la suma
contable N4.

## Anti-leakage

Cada variable se desplaza por su rezago, así la fila del mes a estimar nunca
toma un dato publicado después de la fecha de corte. Se trabaja sobre la última
versión consolidada de cada serie (`leer_dataset`); la reconstrucción
point-in-time de versiones vive en la base (SCRUM-56) y su limitación para el
backtest —el histórico de INDEC es la versión revisada— está en
`docs/exportaciones_indec.md`.

## Pruebas

```bash
python scripts/test_construir_features.py
```

Cubre el DoD: anti-leakage de la fila a estimar (envenenando el futuro de la
base), la imputación de los meses ocultos (mediana de ocultos previos, nunca el
real del mes) y que el default reproduce el conjunto de exógenas de SCRUM-29.
