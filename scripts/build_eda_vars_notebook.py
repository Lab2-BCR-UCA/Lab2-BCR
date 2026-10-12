"""Genera el notebook de EDA de variables externas y su relación con la
producción (SCRUM-28).

El notebook:
  1. Carga las series objetivo (producción) y todas las variables externas
     candidatas (precios, tipo de cambio, pizarra, molienda de soja y ventas de
     combustibles).
  2. Estadística descriptiva y gráficos de cada variable.
  3. Justifica el diferenciado con ADF (nivel vs. variación mensual en log).
  4. Correlación cruzada (CCF) con la producción para rezagos 0 a 12 meses,
     sobre las series **diferenciadas y desestacionalizadas**, con bandas de
     significancia.
  5. Filtra por la tabla de disponibilidad temporal (SCRUM-26) y por un conjunto
     de rezagos con mecanismo, y arma la lista de candidatas con su rezago
     recomendado.

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
   meses**, sobre series **diferenciadas y desestacionalizadas**: la variación
   mensual en log quita la tendencia, y restar la media de cada mes calendario
   quita la estacionalidad. Las dos cosas juntas evitan correlaciones espurias
   (varias series —caña, bioetanol total, pizarra— son estacionales, y sin
   sacar la estacionalidad la CCF queda inflada).
3. Respetamos la **tabla de disponibilidad temporal** (SCRUM-26,
   `data/disponibilidad_variables.csv`) al elegir el rezago: de nada sirve una
   correlación en un rezago al que no vamos a tener acceso al pronosticar.
4. Limitamos la elección a **rezagos con mecanismo** (0–3 meses y 12), para no
   quedarnos con un cruce de la banda por azar entre los 13 rezagos probados.

> **Nota de alcance.** Las series de precio están en **pesos nominales**
> (arrastran inflación). Al diferenciar en log se saca la tendencia, y como la
> producción es física (tn / m³, no pesos), la comovimiento inflacionario no
> genera correlación espuria directa. Aun así, para modelar conviene evaluar
> versiones deflactadas.
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
total, de maíz y de caña (m³). **Recortamos cada serie a su inicio de
entrenamiento del protocolo** (`evaluacion.py`): bioetanol total y caña arrancan
en 2013, no antes, para que la CCF se calcule sobre el mismo tramo que después
usan los modelos (no sobre el arranque ruidoso 2009–2012).
""")

code("""
def serie_mensual(df, col):
    s = (df.assign(fecha=pd.to_datetime(df["fecha"]))
           .set_index("fecha")[col].sort_index().astype(float))
    return s[~s.index.duplicated()]

# Inicio de entrenamiento por serie (igual que el protocolo de evaluación).
inicio_protocolo = {
    "biodiesel":       "2008-01",
    "bioetanol_total": "2013-01",
    "bioetanol_maiz":  "2012-09",
    "bioetanol_cana":  "2013-01",
}

bd = pd.read_csv(DATA / "produccion_biodiesel.csv")
be = pd.read_csv(DATA / "produccion_bioetanol.csv")

crudos = {
    "biodiesel":       serie_mensual(bd, "produccion_tn"),
    "bioetanol_total": serie_mensual(be, "produccion_total_m3"),
    "bioetanol_maiz":  serie_mensual(be, "produccion_maiz_m3"),
    "bioetanol_cana":  serie_mensual(be, "produccion_cana_m3"),
}
objetivos = {n: s[s.index >= pd.Timestamp(inicio_protocolo[n])] for n, s in crudos.items()}
for n, s in objetivos.items():
    print(f"{n:16s}: {s.index.min():%Y-%m} → {s.index.max():%Y-%m}  ({len(s)} meses, desde {inicio_protocolo[n]})")
""")

md("""
### Variables externas candidatas

Las cargamos de los **dos relevamientos**:

- **Ya estaban en el repo** (precio, TC, pizarra), en `data/` — documentadas en
  `docs/fuentes_series.md` (Flor).
- **Nuevas de SCRUM-25** (molienda de soja, ventas de gasoil/nafta), en
  `variables_externas/data/` — documentadas en `variables_externas/README.md`
  (Victoria).

Los dos CSV de SCRUM-25 están **versionados** en el repo (son chicos), así que
el notebook es reproducible en un clon limpio. Si por algún motivo faltan, el
notebook **corta con error** en vez de seguir con una lista incompleta (así no
se pisa `variables_candidatas.csv` con menos filas sin que nadie se entere).
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
        faltantes.append(f"{nombre} ({archivo}, {org})")

if faltantes:
    raise FileNotFoundError(
        "Faltan fuentes de variables externas; no sigo para no generar una "
        "lista incompleta. Deberían estar versionadas en el repo. Faltan:\\n  - "
        + "\\n  - ".join(faltantes)
    )

print("Variables externas cargadas:")
for n, s in externas.items():
    print(f"  [{origen[n]:8s}] {n:22s}: {s.index.min():%Y-%m} → {s.index.max():%Y-%m}  ({len(s)} meses)")
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
## 3. Preparación: diferenciar y desestacionalizar

Dos problemas a sacar antes de correlacionar:

1. **Tendencia.** Casi todas las series suben (los precios, por inflación).
   Correlacionar series con tendencia da correlaciones **espurias**. Se saca con
   la **variación mensual en log** (`Δ log x = log(x_t) − log(x_{t-1})`). El ADF
   lo confirma: en nivel no se rechaza la raíz unitaria, diferenciada sí.
2. **Estacionalidad.** El `Δlog` saca la tendencia pero **no** la
   estacionalidad, y caña, bioetanol total, ventas y pizarra son estacionales.
   Dos series con el mismo patrón estacional "correlacionan" aunque no tengan
   relación. Se saca **restando la media de cada mes calendario** a la serie ya
   diferenciada.

Trabajamos entonces sobre la **variación mensual desestacionalizada** de cada
serie (producción y externas).

> **Huecos en los precios regulados.** Según `docs/fuentes_series.md`, los
> precios regulados tienen meses sin dato (biodiesel 28, bioetanol 41). Una
> `Δlog` que cruza un hueco no es una variación mensual, así que **no
> diferenciamos a través de los huecos**: reindexamos a la grilla mensual y la
> diferencia que toca un faltante queda `NaN`. Esas dos series quedan con `n`
> chico y su CCF se lee con **confianza menor**.
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
print("p<0.05 ⇒ estacionaria. Esperamos: nivel NO, log-diff SÍ.")
pd.DataFrame(filas).set_index("variable").round(3)
""")

code("""
def logdiff(s):
    \"\"\"Variación mensual en log, SIN diferenciar a través de huecos.\"\"\"
    s = s[s > 0].dropna()
    if s.empty:
        return s
    grilla = pd.date_range(s.index.min(), s.index.max(), freq="MS")
    s = s.reindex(grilla)
    return np.log(s).diff().dropna()

def prep(s):
    \"\"\"Variación mensual en log desestacionalizada (resta la media de cada mes).\"\"\"
    d = logdiff(s)
    if d.empty:
        return d
    return d - d.groupby(d.index.month).transform("mean")

obj_d = {n: prep(s) for n, s in objetivos.items()}
ext_d = {n: prep(s) for n, s in externas.items()}

print("Observaciones (variación mensual desestacionalizada) por variable externa:")
for n, s in ext_d.items():
    print(f"  {n:22s}: {len(s):>3} obs")
""")

md(r"""
## 4. Correlación cruzada (CCF) con la producción

Para cada par (variable externa, producción) calculamos la correlación entre
`x` rezagada `k` meses y la producción, para `k = 0 … 12`:

$$\rho_k = \mathrm{corr}\big(x_{t-k},\; y_t\big)$$

Un `k` positivo significa que la variable externa **adelanta** a la producción
en `k` meses (indicador líder). Las dos series ya vienen diferenciadas y
desestacionalizadas.

**Significancia:** bandas aproximadas de ±1,96/√n (95%). Una correlación dentro
de la banda no se distingue de ruido.
""")

code("""
MAX_LAG = 12

def ccf_series(x, y, max_lag=MAX_LAG):
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

Una grilla por producción: filas = variables, columnas = rezago (0 a 12). Rojo =
positiva, azul = negativa. Punto negro = **significativa** (fuera de ±1,96/√n).
Se muestran los 13 rezagos, pero la **selección** de más abajo solo considera
los rezagos con mecanismo (0–3 y 12).
""")

code("""
REZAGOS_PERMITIDOS = [0, 1, 2, 3, 12]  # corto plazo + ciclo anual

def heatmap_ccf(nombre_target, target_d):
    corr, n = tabla_ccf(target_d, ext_d)
    banda = 1.96 / np.sqrt(n.replace(0, np.nan))
    sig = corr.abs() > banda
    fig, ax = plt.subplots(figsize=(11, 0.55 * len(corr) + 1.5))
    im = ax.imshow(corr.values, cmap="RdBu_r", vmin=-0.6, vmax=0.6, aspect="auto")
    ax.set_xticks(range(MAX_LAG + 1)); ax.set_xticklabels(range(MAX_LAG + 1))
    ax.set_yticks(range(len(corr))); ax.set_yticklabels(corr.index, fontsize=9)
    ax.set_xlabel("rezago (meses)")
    for j in REZAGOS_PERMITIDOS:      # resalta las columnas que la selección usa
        ax.axvline(j, color="k", lw=0.4, ls=":", alpha=0.4)
    for i in range(len(corr)):
        for j in range(MAX_LAG + 1):
            if bool(sig.values[i, j]):
                ax.plot(j, i, "o", ms=3, color="black")
    ax.set_title(f"CCF — {nombre_target}  (• significativa 95%; línea = rezago considerado)", fontsize=10)
    fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02)
    fig.tight_layout(); plt.show()
    return corr, n

ccf_tablas = {}
for nombre, td in obj_d.items():
    ccf_tablas[nombre] = heatmap_ccf(nombre, td)
""")

md("""
## 5. Selección de candidatas

El rezago recomendado tiene que cumplir **dos** condiciones:

1. **Disponible** cuando pronostiquemos — rezago `≥ rezago_min` de la tabla de
   disponibilidad temporal (SCRUM-26, `data/disponibilidad_variables.csv`).
2. **Con mecanismo** — entre los rezagos `0–3` (efecto de corto plazo) o `12`
   (ciclo anual). Esto evita quedarnos con un cruce de la banda por azar: con 13
   rezagos probados, ~1 de cada 20 cruza solo por ruido, y los rezagos sueltos
   de 4 a 11 meses no tienen una explicación clara.

El rezago recomendado es el de **mayor |correlación|** entre los que cumplen las
dos condiciones; es candidata si además es **significativo** (95%).
""")

code("""
disp = pd.read_csv(DATA / "disponibilidad_variables.csv")
disp_ext = disp[disp["tipo"] == "externa"]
rezago_min = dict(zip(disp_ext["variable"], disp_ext["rezago_min"].astype(int)))
print("rezago_min (SCRUM-26):")
print(disp_ext[["variable", "rezago_min", "estado"]].to_string(index=False))
DEFAULT_MIN = 1

# Precios regulados: muchos huecos → confianza menor (docs/fuentes_series.md).
baja_confianza = {"precio_biodiesel", "precio_bioetanol_cana", "precio_bioetanol_maiz"}

def seleccionar(nombre_target):
    corr, n = ccf_tablas[nombre_target]
    banda = 1.96 / np.sqrt(n.replace(0, np.nan))
    filas = []
    for var in corr.index:
        fila = corr.loc[var]
        kmin = rezago_min.get(var, DEFAULT_MIN)
        validos = [k for k in REZAGOS_PERMITIDOS if k >= kmin and pd.notna(fila[k])]
        if not validos:
            continue
        kd = max(validos, key=lambda k: abs(fila[k]))   # mejor rezago válido
        sig = abs(fila[kd]) > banda.loc[var, kd]
        filas.append({
            "target": nombre_target, "variable": var, "origen": origen[var],
            "rezago_min_disp": kmin, "rezago_recomendado": int(kd),
            "corr": round(float(fila[kd]), 3), "n_obs": int(n.loc[var, kd]),
            "significativa": bool(sig),
            "confianza": "baja (huecos)" if var in baja_confianza else "normal",
            "candidata": bool(sig),
        })
    return pd.DataFrame(filas)

candidatas = pd.concat([seleccionar(t) for t in obj_d], ignore_index=True)
candidatas = candidatas.sort_values(["target", "candidata", "corr"],
                                    ascending=[True, False, False],
                                    key=lambda c: c.abs() if c.name == "corr" else c)
candidatas.to_csv(OUT / "variables_candidatas.csv", index=False)
print("\\nGuardado:", OUT / "variables_candidatas.csv")
candidatas
""")

md("""
### Lista final de candidatas por serie

Las que quedan **significativas** en un rezago disponible y con mecanismo, tras
sacar tendencia y estacionalidad. Las de precio regulado van marcadas *baja
confianza* por los huecos.
""")

code("""
for t in obj_d:
    sub = candidatas[(candidatas.target == t) & candidatas.candidata]
    print(f"\\n### {t}")
    if sub.empty:
        print("  (sin candidatas significativas con mecanismo)")
        continue
    for _, r in sub.iterrows():
        c = r["corr"]
        signo = "+" if c > 0 else "−"
        flag = "  ⚠ baja confianza" if r["confianza"].startswith("baja") else ""
        print(f"  {r['variable']:22s}  rezago {r['rezago_recomendado']:>2}  "
              f"corr {signo}{abs(c):.2f}  (n={int(r['n_obs'])}){flag}")
""")

md("""
## 6. Conclusiones y próximos pasos

- La **lista de candidatas con rezago recomendado** queda en
  `results/variables_candidatas.csv` (una fila por par variable–serie), con
  columnas de origen (repo / SCRUM-25), confianza y significancia.
- Criterio: correlación cruzada **significativa** (95%) sobre series
  diferenciadas y **desestacionalizadas**, en un rezago **disponible**
  (SCRUM-26) y **con mecanismo** (0–3 o 12).
- Tras sacar la estacionalidad, **varias correlaciones de pizarra se caen**
  (eran estacionalidad común, no relación real). Las de precio de bioetanol se
  sostienen más, pero son de **baja confianza** por los huecos. En general las
  correlaciones son **débiles**: estas variables no son predictores lineales
  fuertes de la producción en variación mensual.
- La tabla de disponibilidad se lee de `data/disponibilidad_variables.csv`
  (SCRUM-26); si cambia un `rezago_min`, la selección se recalcula sola.

**Para el modelado (SCRUM-29 en adelante):**

1. Entran las candidatas de cada serie, cada una en **su** rezago recomendado
   (nunca en un rezago no disponible → evita fuga de información futura).
2. Las variables de **precio** están en pesos nominales y con huecos; probar
   versiones deflactadas y un criterio de relleno (ver `docs/fuentes_series.md`)
   antes de descartarlas.
3. Correlación ≠ causalidad ≠ mejora predictiva: la preselección reduce el
   espacio de búsqueda, pero el aporte real se mide con el **mismo protocolo**
   (`evaluacion.py`) comparando el modelo con y sin cada variable.
""")

nb["cells"] = cells
destino = Path(__file__).resolve().parent.parent / "notebooks" / "eda_variables_externas.ipynb"
destino.parent.mkdir(exist_ok=True)
nbf.write(nb, destino)
print(f"Notebook escrita: {destino}  ({len(cells)} celdas)")
