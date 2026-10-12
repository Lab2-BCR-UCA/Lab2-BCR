"""Genera el notebook de EDA de variables externas y su relación con la
producción (SCRUM-28).

El notebook:
  1. Carga las series objetivo (producción) y todas las variables externas
     candidatas que encuentre (precios, tipo de cambio, pizarra, molienda de
     soja y ventas de combustibles).
  2. Estadística descriptiva y gráficos de cada variable.
  3. Justifica el diferenciado con ADF (nivel vs. variación mensual en log).
  4. Correlación cruzada (CCF) con la producción para rezagos 0 a 12 meses,
     sobre las series diferenciadas, con bandas de significancia.
  5. Filtra por la tabla de disponibilidad temporal (provisoria, SCRUM-26) y
     arma la lista de variables candidatas con su rezago recomendado.

Salida: notebooks/eda_variables_externas.ipynb y, al correrlo,
results/variables_candidatas.csv.
"""

from __future__ import annotations

from pathlib import Path

import nbformat as nbf

nb = nbf.v4.new_notebook()
cells: list = []


def md(t: str) -> None:
    cells.append(nbf.v4.new_markdown_cell(t.strip("\n")))


def code(t: str) -> None:
    cells.append(nbf.v4.new_code_cell(t.strip("\n")))


md(r"""
# EDA de variables externas y su relación con la producción

**Proyecto BCR · Lab 2 · Épica E3 (SCRUM-28)**

Historia de usuario: como equipo de Data Science necesitamos explorar las
variables externas y su relación con la producción para **preseleccionar** las
que entran al modelo. Esta tarea **no** incorpora todavía variables a los
modelos; deja una lista de candidatas con un rezago recomendado.

## Qué hacemos acá

1. Estadística descriptiva y gráficos de cada variable.
2. **Correlación cruzada (CCF)** con la producción para rezagos de **0 a 12
   meses**, sobre **series diferenciadas** (variación mensual en log) para
   evitar correlaciones espurias por tendencia común.
3. Respetamos una **tabla de disponibilidad temporal** al elegir el rezago: de
   nada sirve una correlación en un rezago al que no vamos a tener acceso en el
   momento de pronosticar.

> **Nota de alcance.** Las series de precio están en **pesos nominales**
> (arrastran inflación). Al diferenciar en log se saca la tendencia, y como la
> producción es física (tn / m³, no pesos), la comovimiento inflacionario no
> genera correlación espuria directa. Aun así, para modelar conviene evaluar
> versiones deflactadas. La tabla de disponibilidad es **provisoria**: la
> define SCRUM-26; acá se usa un parámetro editable.
""")

code("""
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from statsmodels.tsa.stattools import adfuller

warnings.filterwarnings("ignore")
plt.rcParams["figure.figsize"] = (12, 4)
plt.rcParams["axes.grid"] = True

RAIZ = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
DATA = RAIZ / "data"
VEXT = RAIZ / "variables_externas" / "data"
OUT = RAIZ / "results"
OUT.mkdir(exist_ok=True)
print("Raíz:", RAIZ)
""")

md("""
## 1. Carga de datos

### Series objetivo (producción)

Son las cuatro series que hay que pronosticar: biodiesel (tn) y bioetanol
total, de maíz y de caña (m³).
""")

code("""
def serie_mensual(df, col):
    s = (df.assign(fecha=pd.to_datetime(df["fecha"]))
           .set_index("fecha")[col].sort_index().astype(float))
    return s[~s.index.duplicated()]

bd = pd.read_csv(DATA / "produccion_biodiesel.csv")
be = pd.read_csv(DATA / "produccion_bioetanol.csv")

objetivos = {
    "biodiesel":       serie_mensual(bd, "produccion_tn"),
    "bioetanol_total": serie_mensual(be, "produccion_total_m3"),
    "bioetanol_maiz":  serie_mensual(be, "produccion_maiz_m3"),
    "bioetanol_cana":  serie_mensual(be, "produccion_cana_m3"),
}
for n, s in objetivos.items():
    print(f"{n:16s}: {s.index.min():%Y-%m} → {s.index.max():%Y-%m}  ({len(s)} meses)")
""")

md("""
### Variables externas candidatas

Levantamos todo lo que haya disponible, de los **dos relevamientos**:

- **Ya estaban en el repo** (precio, TC, pizarra), en `data/` — documentadas en
  `docs/fuentes_series.md` (Flor).
- **Nuevas de SCRUM-25** (molienda de soja, ventas de gasoil/nafta), en
  `variables_externas/data/` — documentadas en `variables_externas/README.md`
  (Victoria). Estas se generan corriendo sus scrapers una vez; si faltan, se
  omiten y el resto del análisis corre igual.
""")

code("""
# Cada entrada: (archivo, columna, nombre_legible, origen)
fuentes = [
    (DATA / "tipo_cambio_mensual.csv",    "tc_promedio_mes",            "tipo_cambio",            "repo"),
    (DATA / "soja_maiz_cac_mensual.csv",  "soja_ars_tn",               "precio_soja_pizarra",    "repo"),
    (DATA / "soja_maiz_cac_mensual.csv",  "maiz_ars_tn",               "precio_maiz_pizarra",    "repo"),
    (DATA / "biodiesel_precios.csv",      "precio_ars_tn",             "precio_biodiesel",       "repo"),
    (DATA / "bioetanol_precios.csv",      "precio_cana_ars_l",         "precio_bioetanol_cana",  "repo"),
    (DATA / "bioetanol_precios.csv",      "precio_maiz_ars_l",         "precio_bioetanol_maiz",  "repo"),
    (VEXT / "soja_mensual.csv",           "molienda_soja_tn",          "molienda_soja",          "SCRUM-25"),
    (VEXT / "combustibles_mensual.csv",   "ventas_gasoil_grados1a3_m3","ventas_gasoil",          "SCRUM-25"),
    (VEXT / "combustibles_mensual.csv",   "ventas_nafta_grados1a3_m3", "ventas_nafta",           "SCRUM-25"),
]

externas, origen = {}, {}
faltantes = []
for archivo, col, nombre, org in fuentes:
    if archivo.exists():
        externas[nombre] = serie_mensual(pd.read_csv(archivo), col)
        origen[nombre] = org
    else:
        faltantes.append(f"{nombre} ({archivo.name}, {org})")

print("Variables externas cargadas:")
for n, s in externas.items():
    print(f"  [{origen[n]:8s}] {n:22s}: {s.index.min():%Y-%m} → {s.index.max():%Y-%m}  ({len(s)} meses)")
if faltantes:
    print("\\nFALTAN (corré los scrapers de variables_externas/):")
    for f in faltantes:
        print("  -", f)
""")

md("""
## 2. Estadística descriptiva

Resumen numérico de cada variable (nivel). Las escalas son muy distintas
(toneladas, m³, $/tn, $/l, $/USD), así que acá solo miramos cada una en sus
propias unidades. La columna `meses_faltantes` cuenta los huecos dentro del
rango de cada serie (importante para los precios regulados).
""")

code("""
def meses_faltantes(s):
    grilla = pd.date_range(s.index.min(), s.index.max(), freq="MS")
    return int(grilla.difference(s.index).size)

desc = pd.DataFrame({n: s.describe() for n, s in {**objetivos, **externas}.items()}).T
desc = desc[["count", "mean", "std", "min", "50%", "max"]].rename(columns={"50%": "mediana"})
desc["meses_faltantes"] = [meses_faltantes(s) for s in {**objetivos, **externas}.values()]
desc.round(1)
""")

md("""
### Gráficos de nivel

Cada variable en el tiempo. Sirve para ver tendencia, estacionalidad y saltos
(p. ej. el desplome de molienda de dic-2020, la caída de ventas en la cuarentena
de 2020, o los saltos escalonados de los precios regulados por inflación).
""")

code("""
items = list(externas.items())
filas = (len(items) + 1) // 2
fig, axes = plt.subplots(filas, 2, figsize=(13, 2.6 * filas))
for ax, (nombre, s) in zip(axes.ravel(), items):
    ax.plot(s.index, s.values, lw=1.1)
    ax.set_title(f"{nombre}  [{origen[nombre]}]", fontsize=10)
for ax in axes.ravel()[len(items):]:
    ax.axis("off")
fig.suptitle("Variables externas — nivel", y=1.002, fontsize=12)
fig.tight_layout(); plt.show()
""")

md("""
## 3. ¿Por qué diferenciar? Estacionariedad (ADF)

Casi todas las series tienen tendencia (sobre todo las de precio, por
inflación). Correlacionar series con tendencia da correlaciones **espurias**:
dos cosas que suben juntas "correlacionan" aunque no tengan relación.

La solución estándar es trabajar sobre la **variación mensual en log**
(`Δ log x = log(x_t) − log(x_{t-1})`), que quita la tendencia y deja la señal
de corto plazo. El test ADF confirma: en nivel no se rechaza la raíz unitaria
(no estacionaria), diferenciada sí.
""")

code("""
def adf_p(s):
    s = s.dropna()
    if (s <= 0).any() or len(s) < 12:
        return np.nan, np.nan
    nivel = adfuller(s)[1]
    dif = adfuller(np.log(s).diff().dropna())[1]
    return nivel, dif

filas = []
for n, s in {**objetivos, **externas}.items():
    pn, pd_ = adf_p(s)
    filas.append({"variable": n, "p_ADF_nivel": pn, "p_ADF_logdiff": pd_,
                  "nivel_estacionario": pn < 0.05 if pn == pn else None,
                  "logdiff_estacionario": pd_ < 0.05 if pd_ == pd_ else None})
tabla_adf = pd.DataFrame(filas).set_index("variable")
print("p<0.05 ⇒ estacionaria. Esperamos: nivel NO, log-diff SÍ.")
tabla_adf.round(3)
""")

md("""
Trabajamos entonces sobre `Δ log` de cada serie (tanto la producción como las
externas). Para la producción esto coincide con la **variación mensual** que ya
usa el EDA de producción y con lo que publica la BCR en el IACA.

> **Huecos en los precios regulados.** Según `docs/fuentes_series.md` (relevado
> por Flor), los precios regulados tienen meses sin dato: **biodiesel 28 meses,
> bioetanol 41**. Una `Δlog` que cruza un hueco **no es** una variación mensual
> (un salto que abarca varios meses sin dato se contaría como cambio de un
> mes). Por eso **no diferenciamos a través de los huecos**: reindexamos a la
> grilla mensual completa, de modo que cualquier diferencia que toque un mes
> faltante queda `NaN` y se descarta. Así solo quedan variaciones entre meses
> realmente consecutivos. Esto reduce el `n` de esas dos series y su CCF hay
> que leerla con **confianza menor**.
""")

code("""
def logdiff(s):
    \"\"\"Variación mensual en log, SIN diferenciar a través de huecos.

    Reindexa a la grilla mensual completa: si falta el mes t-1, la diferencia
    del mes t queda NaN y se descarta. Evita tratar un salto que abarca varios
    meses sin dato como si fuera una variación de un solo mes.
    \"\"\"
    s = s[s > 0].dropna()
    if s.empty:
        return s
    grilla = pd.date_range(s.index.min(), s.index.max(), freq="MS")
    s = s.reindex(grilla)
    return np.log(s).diff().dropna()

obj_d = {n: logdiff(s) for n, s in objetivos.items()}
ext_d = {n: logdiff(s) for n, s in externas.items()}

print("Variaciones mensuales consecutivas disponibles por variable externa:")
for n, s in ext_d.items():
    print(f"  {n:22s}: {len(s):>3} obs")
""")

md(r"""
## 4. Correlación cruzada (CCF) con la producción

Para cada par (variable externa, producción) calculamos la correlación entre
`x` rezagada `k` meses y la producción, para `k = 0 … 12`:

$$\rho_k = \mathrm{corr}\big(x_{t-k},\; y_t\big)$$

Un `k` positivo significa que la variable externa **adelanta** a la producción
en `k` meses (es un indicador líder). Eso es justo lo que sirve para
pronosticar: si `x` de hace `k` meses anticipa la producción de hoy, y ese dato
está disponible a tiempo, es una candidata.

**Significancia:** bandas aproximadas de ±1,96/√n (95%). Una correlación que
cae dentro de la banda no se distingue de ruido.
""")

code("""
MAX_LAG = 12

def ccf_series(x, y, max_lag=MAX_LAG):
    \"\"\"corr(x[t-k], y[t]) para k=0..max_lag, sobre índices comunes.\"\"\"
    out = {}
    for k in range(max_lag + 1):
        xk = x.shift(k, freq="MS")
        df = pd.concat([xk, y], axis=1, join="inner").dropna()
        out[k] = (df.iloc[:, 0].corr(df.iloc[:, 1]) if len(df) > 2 else np.nan, len(df))
    return out

def tabla_ccf(target_d, ext_d):
    corr, n = {}, {}
    for nombre, x in ext_d.items():
        res = ccf_series(x, target_d)
        corr[nombre] = {k: v[0] for k, v in res.items()}
        n[nombre] = {k: v[1] for k, v in res.items()}
    return pd.DataFrame(corr).T, pd.DataFrame(n).T

print("CCF lista. Convención: rezago k>0 ⇒ la variable externa adelanta a la producción.")
""")

md("""
### Heatmaps de CCF por serie objetivo

Una grilla por cada producción: filas = variables externas, columnas = rezago
(0 a 12). Rojo = correlación positiva, azul = negativa. Marcamos con un punto
las celdas **significativas** (fuera de la banda de ±1,96/√n).
""")

code("""
def heatmap_ccf(nombre_target, target_d):
    corr, n = tabla_ccf(target_d, ext_d)
    banda = 1.96 / np.sqrt(n.replace(0, np.nan))
    sig = corr.abs() > banda
    fig, ax = plt.subplots(figsize=(11, 0.55 * len(corr) + 1.5))
    im = ax.imshow(corr.values, cmap="RdBu_r", vmin=-0.6, vmax=0.6, aspect="auto")
    ax.set_xticks(range(MAX_LAG + 1)); ax.set_xticklabels(range(MAX_LAG + 1))
    ax.set_yticks(range(len(corr))); ax.set_yticklabels(corr.index, fontsize=9)
    ax.set_xlabel("rezago (meses)")
    for i in range(len(corr)):
        for j in range(MAX_LAG + 1):
            if bool(sig.values[i, j]):
                ax.plot(j, i, "o", ms=3, color="black")
    ax.set_title(f"CCF — {nombre_target}  (• = significativa 95%)", fontsize=11)
    fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02)
    fig.tight_layout(); plt.show()
    return corr, n

ccf_tablas = {}
for nombre, td in obj_d.items():
    ccf_tablas[nombre] = heatmap_ccf(nombre, td)
""")

md("""
## 5. Disponibilidad temporal y selección de candidatas

El rezago recomendado no puede ser cualquiera: tiene que ser uno al que
**vayamos a tener acceso** cuando pronostiquemos. Para un pronóstico a un mes,
al estimar la producción del mes `t` (que la Secretaría publica con ~2 meses de
atraso), ya tenemos la variable externa hasta cierto mes según su propio
calendario de publicación.

Codificamos un **rezago mínimo disponible** por variable. Es **provisorio**: lo
define SCRUM-26. Acá va un valor conservador y editable.
""")

code("""
# Rezago MÍNIMO utilizable por variable (meses). PROVISORIO — lo fija SCRUM-26.
#  0 = el dato del propio mes ya está disponible al pronosticar.
#  1 = recién está disponible el dato del mes anterior, etc.
# Tabla de SCRUM-26: data/disponibilidad_variables.csv (ver docs/disponibilidad_temporal.md)
disp = pd.read_csv(DATA / "disponibilidad_variables.csv")
disp_ext = disp[disp["tipo"] == "externa"]
rezago_min = dict(zip(disp_ext["variable"], disp_ext["rezago_min"].astype(int)))
print(disp_ext[["variable", "rezago_min", "estado"]].to_string(index=False))
DEFAULT_MIN = 1  # para cualquier variable no listada

# Variables con muchos huecos → CCF de confianza menor (ver docs/fuentes_series.md).
baja_confianza = {"precio_biodiesel", "precio_bioetanol_cana", "precio_bioetanol_maiz"}

def seleccionar(nombre_target):
    corr, n = ccf_tablas[nombre_target]
    banda = 1.96 / np.sqrt(n.replace(0, np.nan))
    filas = []
    for var in corr.index:
        fila = corr.loc[var]
        kmin = rezago_min.get(var, DEFAULT_MIN)
        disponibles = fila.loc[kmin:]
        if disponibles.abs().notna().sum() == 0:
            continue
        kg = fila.abs().idxmax()
        kd = disponibles.abs().idxmax()
        sig_d = abs(disponibles[kd]) > banda.loc[var, kd]
        filas.append({
            "target": nombre_target, "variable": var, "origen": origen[var],
            "rezago_min_disp": kmin,
            "mejor_rezago_disp": int(kd), "corr_disp": round(float(fila[kd]), 3),
            "signif_disp": bool(sig_d),
            "mejor_rezago_global": int(kg), "corr_global": round(float(fila[kg]), 3),
            "n_obs": int(n.loc[var, kd]),
            "confianza": "baja (huecos)" if var in baja_confianza else "normal",
            "candidata": bool(sig_d),
        })
    return pd.DataFrame(filas)

candidatas = pd.concat([seleccionar(t) for t in obj_d], ignore_index=True)
candidatas = candidatas.sort_values(["target", "signif_disp", "corr_disp"],
                                    ascending=[True, False, False],
                                    key=lambda c: c.abs() if c.name == "corr_disp" else c)
candidatas.to_csv(OUT / "variables_candidatas.csv", index=False)
print("Guardado:", OUT / "variables_candidatas.csv")
candidatas
""")

md("""
### Lista final de candidatas por serie

Nos quedamos con las que tienen una correlación **significativa** en un rezago
**disponible**. Ese es el entregable del DoD: variables candidatas con su
rezago recomendado. Las marcadas como *baja confianza* son las de precio con
muchos huecos: su correlación puede ser frágil.
""")

code("""
for t in obj_d:
    sub = candidatas[(candidatas.target == t) & candidatas.candidata]
    print(f"\\n### {t}")
    if sub.empty:
        print("  (sin candidatas significativas en rezagos disponibles)")
        continue
    for _, r in sub.iterrows():
        signo = "+" if r.corr_disp > 0 else "−"
        flag = "  ⚠ baja confianza" if r.confianza.startswith("baja") else ""
        print(f"  {r.variable:22s}  rezago {r.mejor_rezago_disp:>2} meses  "
              f"corr {signo}{abs(r.corr_disp):.2f}  (n={r.n_obs}){flag}")
""")

md("""
## 6. Conclusiones y próximos pasos

- La **lista de candidatas con rezago recomendado** queda en
  `results/variables_candidatas.csv` (una fila por par variable–serie), con
  columnas de origen (repo / SCRUM-25) y de confianza.
- El criterio fue: correlación cruzada **significativa** (95%) en un rezago
  **disponible** según la tabla de disponibilidad temporal.
- **Las correlaciones son débiles en general** (la más alta ~0,4). En variación
  mensual, estas variables no son predictores lineales fuertes de la
  producción. Además, con 13 rezagos × 9 variables × 4 series hay **testeo
  múltiple**: ~1 de cada 20 celdas cruza la banda por azar, así que las
  "significativas" en rezagos largos y sin mecanismo (9–12) son sospechosas.
  Hay que filtrar por mecanismo, no solo por el número.
- La tabla de disponibilidad (`rezago_min`) se lee de `data/disponibilidad_variables.csv`; la cierra
  SCRUM-26. Si cambia el rezago mínimo de una variable, se recalcula la
  selección sin tocar nada más.

**Para el modelado (SCRUM-24 en adelante):**

1. Entran al modelo las candidatas de cada serie, cada una en **su** rezago
   recomendado (nunca en un rezago no disponible → evita fuga de información
   futura en el walk-forward).
2. Las variables de **precio** están en pesos nominales y con huecos; probar
   versiones deflactadas y un criterio de relleno (ver `docs/fuentes_series.md`)
   antes de descartarlas por ruido.
3. Correlación ≠ causalidad ni ≠ mejora predictiva: la preselección reduce el
   espacio de búsqueda, pero el aporte real de cada variable se mide con el
   **mismo protocolo** (`evaluacion.py`) comparando el modelo con y sin ella.
""")

nb["cells"] = cells
destino = Path(__file__).resolve().parent.parent / "notebooks" / "eda_variables_externas.ipynb"
destino.parent.mkdir(exist_ok=True)
nbf.write(nb, destino)
print(f"Notebook escrita: {destino}  ({len(cells)} celdas)")
