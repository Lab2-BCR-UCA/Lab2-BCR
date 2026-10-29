"""Réplica del modelo X-13ARIMA-SEATS que usa BCR (SCRUM-23 / ajuste a config BCR).

Corre X-13 sobre las series de producción con validación walk-forward a un
mes, usando el **protocolo de evaluación del equipo** (`evaluacion.py`,
SCRUM-21) para que las métricas sean idénticas a las de los baselines y los
modelos propios.

Hay dos réplicas, que se guardan juntas pero con nombres de modelo distintos:

``x13_bcr`` — configuración exacta de BCR
    Usa los cuatro ``.spc`` que envió BCR (``spc/IACA-*_L.spc`` y ``*_N.spc``)
    tal cual: solo se reemplaza la línea ``file = "...prn"`` por los datos
    inline. En cada iteración corre la versión en log (``_L``) y en nivel
    (``_N``) y aplica el **criterio de selección de BCR**: se queda con la que
    tiene menor desvío estándar de la variación logarítmica mensual de la
    serie filtrada por estacionalidad e irregular (tendencia-ciclo, tabla D12),
    calculado sobre los últimos 12 meses, que es la ventana que reproduce la
    elección de BCR (log en biodiesel, nivel en bioetanol).
    También se guardan la selección con el criterio calculado sobre toda la
    serie (``x13_bcr_selcompleta``) y las dos variantes fijas
    (``x13_bcr_log`` y ``x13_bcr_nivel``) para ver cuánto aporta la selección.

``x13_auto`` — réplica automática anterior (referencia)
    El spec mínimo que usábamos antes de tener los ``.spc``: ventana desde
    2013, ``aictest=(td easter)`` y ``automdl`` con órdenes (4 2), sin
    ``seasonalma`` ni el resto de la config. Se mantiene para separar cuánto
    se gana ajustando el X-13 de cuánto se gana cambiando de modelo.

Outliers: los ``.spc`` de BCR **no traen outliers fijos** (no hay
``regression{ variables = (AO... LS... TC...) }``) ni un bloque ``outlier{}``,
así que X-13 tampoco los identifica automáticamente. No hay outliers
detectados con la muestra completa que puedan filtrar información futura al
walk-forward. Ver ``docs/x13_config_bcr.md``.

Salidas:
    results/x13.csv                       resumen por serie y modelo
    results/predicciones_x13.csv          detalle mensual (protocolo)
    results/seleccion_x13_bcr.csv         log vs nivel elegido en cada mes
    results/pronostico_x13_bcr_2026-07.csv   12 pronósticos con datos a jul-2026

Tiempo de corrida: cada corrida con la config BCR tarda ~10-40 s (X-11 con
slidingspans, spectrum y check). Las corridas se reparten entre los
núcleos disponibles (``--procesos N``). Con 2 núcleos, el total es de
unos 15-20 minutos.

Uso:
    python scripts/replica_x13.py                # todo
    python scripts/replica_x13.py --procesos 4
    python scripts/replica_x13.py --solo-julio   # solo el pronóstico a jul-2026

Requiere: pip install x13binary pandas numpy
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
from x13binary import find_x13_bin

sys.path.append(str(Path(__file__).resolve().parent))
from evaluacion import evaluar_modelo  # protocolo del equipo (SCRUM-21)

X13 = find_x13_bin()
RAIZ = Path(__file__).resolve().parent.parent
SPC_DIR = RAIZ / "spc"

# Ventana de test acordada con el equipo (últimos 12 meses).
INICIO_TEST = "2025-09"
FIN_TEST = "2026-08"

# Corte del DoD: pronósticos que BCR publicó con datos hasta julio 2026.
CORTE_DOD = "2026-07"

# .spc de BCR por serie: (log, nivel). BCR solo modela biodiesel y bioetanol
# total; a maíz y caña se les aplica la config de bioetanol como extensión.
SPC_BCR = {
    "biodiesel":       ("IACA-BIODIESEL_L", "IACA-BIODIESEL_N"),
    "bioetanol_total": ("IACA-BIOETANOL_L", "IACA-BIOETANOL_N"),
    "bioetanol_maiz":  ("IACA-BIOETANOL_L", "IACA-BIOETANOL_N"),
    "bioetanol_cana":  ("IACA-BIOETANOL_L", "IACA-BIOETANOL_N"),
}

# Inicio de la serie que recibe cada réplica.
#  - x13_bcr: el `span` de los .spc (biodiesel 2008.01, bioetanol 2010.01).
#    En maíz se arranca en 2012-09 porque antes hay ceros (log imposible).
#  - x13_auto: los inicios del protocolo (docs/protocolo_evaluacion.md §4).
INICIO_BCR = {
    "biodiesel": "2008-01",
    "bioetanol_total": "2010-01",
    "bioetanol_maiz": "2012-09",
    "bioetanol_cana": "2010-01",
}
INICIO_PROTOCOLO = {
    "biodiesel": "2008-01",
    "bioetanol_total": "2013-01",
    "bioetanol_maiz": "2012-09",
    "bioetanol_cana": "2013-01",
}
# Transformación de la réplica automática (la que usaba antes el equipo).
LOG_AUTO = {"biodiesel": True, "bioetanol_total": False,
            "bioetanol_maiz": False, "bioetanol_cana": False}


# ---------------------------------------------------------------------------
# Utilidades comunes
# ---------------------------------------------------------------------------

def _a_periodos(serie: pd.Series) -> pd.Series:
    """Devuelve la serie con índice mensual (PeriodIndex), ordenada."""
    s = serie.copy()
    if not isinstance(s.index, pd.PeriodIndex):
        s.index = pd.to_datetime(s.index).to_period("M")
    return s.sort_index().astype(float)


def _bloque_datos(vals: np.ndarray) -> str:
    filas = [vals[i:i + 6] for i in range(0, len(vals), 6)]  # X-13 corta líneas largas
    cuerpo = "\n".join("        " + " ".join(f"{v:.4f}" for v in f) for f in filas)
    return f"data = (\n{cuerpo}\n    )"


def _correr(spec: str) -> dict[str, str]:
    """Corre X-13 sobre un spec y devuelve el texto de los archivos de salida."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "run"
        base.with_suffix(".spc").write_text(spec, encoding="ascii")
        subprocess.run([X13, base.name], cwd=tmp, capture_output=True,
                       text=True, timeout=600)
        salida = {}
        for p in Path(tmp).iterdir():
            if p.stem == "run" and p.suffix in (".fct", ".d12", ".html"):
                salida[p.suffix[1:]] = p.read_text(encoding="latin-1")
        err = Path(tmp) / "run_err.html"
        if err.exists():
            salida["err"] = err.read_text(encoding="latin-1")
        return salida


def _leer_tabla(texto: str | None) -> pd.Series:
    """Lee una tabla guardada por X-13 (fecha yyyymm \\t valor ...)."""
    if not texto:
        return pd.Series(dtype=float)
    fechas, vals = [], []
    for linea in texto.splitlines():
        partes = linea.split("\t")
        if partes and partes[0].strip().isdigit() and len(partes) > 1:
            f = partes[0].strip()
            fechas.append(pd.Period(f"{f[:4]}-{f[4:]}", freq="M"))
            vals.append(float(partes[1].strip().replace("E", "e")))
    return pd.Series(vals, index=pd.PeriodIndex(fechas, freq="M"), dtype=float)


def _modelo_elegido(html: str | None) -> str:
    if not html:
        return ""
    m = re.search(r"Final automatic model choice\s*:\s*([()\d ]+)",
                  re.sub("<[^>]*>", "", html))
    return m.group(1).strip() if m else ""


# ---------------------------------------------------------------------------
# Configuración BCR (.spc reales)
# ---------------------------------------------------------------------------

def _anio_mes(texto: str) -> tuple[int, int]:
    a, m = texto.split(".")
    return int(a), int(m)


def spec_desde_spc(nombre_spc: str, serie: pd.Series) -> str:
    """Arma el spec de una corrida a partir del .spc de BCR.

    Solo se cambia lo imprescindible para correrlo fuera de la PC de BCR:
    la línea ``file = "...prn"`` (y ``format = free``) se reemplaza por los
    datos inline. Si la serie arranca después del ``start`` del .spc (caso
    maíz), se corren ``start``, ``span`` y ``modelspan`` a ese mes. Todo el
    resto (transform, regression, automdl, forecast, estimate, check, x11,
    slidingspans, spectrum) queda idéntico.

    Args:
        nombre_spc: Nombre del archivo en ``spc/`` sin extensión.
        serie: Serie mensual con índice de períodos, sin huecos.
    """
    texto = (SPC_DIR / f"{nombre_spc}.spc").read_text(encoding="latin-1")
    s = _a_periodos(serie)

    inicio_spc = _anio_mes(re.search(r"\bstart\s*=\s*([\d.]+)", texto).group(1))
    if (s.index[0].year, s.index[0].month) < inicio_spc:
        s = s[s.index >= pd.Period(f"{inicio_spc[0]}-{inicio_spc[1]:02d}", freq="M")]
    p0 = s.index[0]
    inicio = (p0.year, p0.month)

    texto = re.sub(r'file\s*=\s*"[^"]*"', lambda _: _bloque_datos(s.to_numpy()), texto)
    texto = re.sub(r"\n[ \t]*format\s*=\s*free[^\n]*", "", texto)
    texto = re.sub(r"\bstart\s*=\s*[\d.]+", f"start = {p0.year}.{p0.month:02d}", texto)

    def _correr_a_inicio(m: re.Match) -> str:
        a, mm = _anio_mes(m.group(2))
        a, mm = max((a, mm), inicio)
        return f"{m.group(1)}({a}.{mm:02d},)"

    texto = re.sub(r"\b(span\s*=\s*)\(\s*([\d.]+)\s*,\s*\)", _correr_a_inicio, texto)
    texto = re.sub(r"\b(modelspan\s*=\s*)\(\s*([\d.]+)\s*,\s*\)", _correr_a_inicio, texto)
    return texto


def criterio_bcr(d12: pd.Series, ultimo: pd.Period, ultimos_meses: int | None = None) -> float:
    """Criterio de selección de BCR.

    Desvío estándar de la variación logarítmica mensual de la serie filtrada
    por estacionalidad e irregular (tendencia-ciclo, D12). Se usa solo el
    tramo observado: con ``appendfcst = YES`` la D12 trae además los 12 meses
    pronosticados, que se descartarían.

    Args:
        d12: Tendencia-ciclo guardada por X-13.
        ultimo: Último mes observado.
        ultimos_meses: Si se indica, el desvío se calcula solo sobre las
            últimas ``n`` variaciones (ver docs/x13_config_bcr.md: con 12
            meses se reproduce la elección de BCR a julio 2026).
    """
    t = d12[d12.index <= ultimo]
    t = t[t > 0]
    var = np.log(t).diff().dropna()
    if ultimos_meses:
        var = var.iloc[-ultimos_meses:]
    return float(var.std(ddof=1)) if len(var) > 1 else np.nan


def corrida_bcr(nombre_spc: str, serie: pd.Series) -> dict:
    """Corre un .spc de BCR y devuelve pronósticos, criterio y modelo."""
    s = _a_periodos(serie)
    salida = _correr(spec_desde_spc(nombre_spc, s))
    fct = _leer_tabla(salida.get("fct"))
    d12 = _leer_tabla(salida.get("d12"))
    return {
        "spc": nombre_spc,
        "fct": fct,
        "criterio": criterio_bcr(d12, s.index[-1]),
        "criterio_12m": criterio_bcr(d12, s.index[-1], ultimos_meses=12),
        "modelo_arima": _modelo_elegido(salida.get("html")),
        "error": "" if len(fct) else re.sub("<[^>]*>", " ", salida.get("err", ""))[:300],
    }


def pronostico_bcr(serie: pd.Series, nombre_serie: str) -> dict:
    """Corre log y nivel y aplica el criterio de selección de BCR."""
    spc_log, spc_niv = SPC_BCR[nombre_serie]
    r_log, r_niv = corrida_bcr(spc_log, serie), corrida_bcr(spc_niv, serie)

    def elegir(clave: str) -> str:
        c_log, c_niv = r_log[clave], r_niv[clave]
        if np.isnan(c_niv) or (not np.isnan(c_log) and c_log <= c_niv):
            return "log"
        return "nivel"

    return {"log": r_log, "nivel": r_niv,
            "elegido": elegir("criterio"), "elegido_12m": elegir("criterio_12m")}


# ---------------------------------------------------------------------------
# Réplica automática (spec mínimo anterior, se mantiene como referencia)
# ---------------------------------------------------------------------------

def spec_auto(serie: pd.Series, log: bool) -> str:
    """Spec mínimo que usaba el equipo antes de tener los .spc de BCR."""
    s = _a_periodos(serie)
    p0 = s.index[0]
    modelspan = "  modelspan=(2013.1, )\n" if (p0.year, p0.month) <= (2013, 1) else ""
    transform = "transform{ function=log }" if log else "transform{ function=none }"
    return (
        f"series{{\n  start={p0.year}.{p0.month}\n  period=12\n{modelspan}"
        f"  {_bloque_datos(s.to_numpy())}\n}}\n"
        f"{transform}\n"
        "regression{ aictest=(td easter) }\n"
        "automdl{ maxdiff=(2 1) maxorder=(4 2) }\n"
        "forecast{ maxlead=1 save=(fct) }\n"
    )


def pronostico_auto(serie: pd.Series, log: bool) -> float:
    fct = _leer_tabla(_correr(spec_auto(serie, log)).get("fct"))
    return float(fct.iloc[0]) if len(fct) else np.nan


# ---------------------------------------------------------------------------
# Walk-forward: se precalculan las corridas en paralelo y el protocolo las lee
# ---------------------------------------------------------------------------

def _tarea(args: tuple) -> tuple:
    """Una iteración del walk-forward (se ejecuta en un proceso aparte)."""
    tipo, nombre, entrenamiento = args
    clave = (tipo, nombre, str(entrenamiento.index[-1]))
    try:
        if tipo == "bcr":
            return clave, pronostico_bcr(entrenamiento, nombre)
        return clave, pronostico_auto(entrenamiento, LOG_AUTO[nombre])
    except Exception as exc:  # se registra como fallo en el protocolo
        return clave, exc


class ModeloPrecalculado:
    """Adaptador fit/predict que lee una corrida de X-13 ya hecha.

    ``fit`` toma el último mes de entrenamiento como clave; ``predict``
    devuelve el pronóstico a un mes de esa corrida. Así el walk-forward pasa
    por ``evaluar_modelo`` igual que los baselines, pero las corridas
    (lentas) se hacen antes y en paralelo.

    Args:
        cache: Resultados de ``_tarea``.
        tipo: ``"bcr"`` o ``"auto"``.
        nombre: Serie.
        variante: Para ``bcr``: ``"seleccion"``, ``"seleccion_12m"``, ``"log"``
            o ``"nivel"``.
    """

    def __init__(self, cache: dict, tipo: str, nombre: str, variante: str = "") -> None:
        self.cache, self.tipo, self.nombre, self.variante = cache, tipo, nombre, variante
        self._clave = None

    def fit(self, serie: pd.Series) -> "ModeloPrecalculado":
        self._clave = (self.tipo, self.nombre, str(_a_periodos(serie).index[-1]))
        return self

    def predict(self) -> float:
        r = self.cache[self._clave]
        if isinstance(r, Exception):
            raise r
        if self.tipo == "auto":
            return r
        v = {"seleccion": r["elegido"], "seleccion_12m": r["elegido_12m"]}.get(self.variante, self.variante)
        fct = r[v]["fct"]
        if not len(fct):
            raise RuntimeError(f"X-13 sin pronóstico ({r[v]['spc']}): {r[v]['error']}")
        return float(fct.iloc[0])


def cargar_series() -> dict[str, pd.Series]:
    bd = pd.read_csv(RAIZ / "data/produccion_biodiesel.csv", parse_dates=["fecha"]).set_index("fecha")
    be = pd.read_csv(RAIZ / "data/produccion_bioetanol.csv", parse_dates=["fecha"]).set_index("fecha")
    return {
        "biodiesel": _a_periodos(bd["produccion_tn"]),
        "bioetanol_total": _a_periodos(be["produccion_total_m3"]),
        "bioetanol_maiz": _a_periodos(be["produccion_maiz_m3"]),
        "bioetanol_cana": _a_periodos(be["produccion_cana_m3"]),
    }


def _iteraciones(serie: pd.Series, inicio: str) -> list[pd.Series]:
    s = serie[serie.index >= pd.Period(inicio, freq="M")]
    return [s[s.index < mes] for mes in pd.period_range(INICIO_TEST, FIN_TEST, freq="M")]


def walk_forward(series: dict[str, pd.Series], procesos: int) -> None:
    tareas = []
    for nombre, serie in series.items():
        tareas += [("bcr", nombre, e) for e in _iteraciones(serie, INICIO_BCR[nombre])]
        tareas += [("auto", nombre, e) for e in _iteraciones(serie, INICIO_PROTOCOLO[nombre])]
    # las corridas BCR (lentas) primero, para repartir mejor la carga
    tareas.sort(key=lambda t: t[0] != "bcr")

    print(f"Corriendo {len(tareas)} iteraciones de X-13 en {procesos} procesos...")
    cache = {}
    with ProcessPoolExecutor(max_workers=procesos) as ex:
        for i, (clave, r) in enumerate(ex.map(_tarea, tareas), 1):
            cache[clave] = r
            if i % 10 == 0 or i == len(tareas):
                print(f"  {i}/{len(tareas)}", flush=True)

    modelos = [("x13_bcr", "bcr", "seleccion_12m"), ("x13_bcr_selcompleta", "bcr", "seleccion"),
               ("x13_bcr_log", "bcr", "log"),
               ("x13_bcr_nivel", "bcr", "nivel"), ("x13_auto", "auto", "")]
    detalles, resumenes, seleccion = [], [], []
    for nombre, serie in series.items():
        for modelo, tipo, variante in modelos:
            inicio = INICIO_BCR[nombre] if tipo == "bcr" else INICIO_PROTOCOLO[nombre]
            detalle, resumen = evaluar_modelo(
                serie=serie,
                crear_modelo=lambda t=tipo, n=nombre, v=variante: ModeloPrecalculado(cache, t, n, v),
                inicio_entrenamiento=inicio,
                inicio_test=INICIO_TEST,
                fin_test=FIN_TEST,
                nombre_serie=nombre,
                nombre_modelo=modelo,
            )
            resumen["inicio_entrenamiento"] = inicio
            detalles.append(detalle)
            resumenes.append(resumen)

        for (tipo, n, ultimo), r in cache.items():
            if tipo == "bcr" and n == nombre and not isinstance(r, Exception):
                seleccion.append({
                    "serie": nombre,
                    "fecha_pronostico": (pd.Period(ultimo, freq="M") + 1).to_timestamp(),
                    "datos_hasta": ultimo,
                    "elegido": r["elegido"],
                    "criterio_log": r["log"]["criterio"],
                    "criterio_nivel": r["nivel"]["criterio"],
                    "elegido_12m": r["elegido_12m"],
                    "criterio_12m_log": r["log"]["criterio_12m"],
                    "criterio_12m_nivel": r["nivel"]["criterio_12m"],
                    "modelo_log": r["log"]["modelo_arima"],
                    "modelo_nivel": r["nivel"]["modelo_arima"],
                    "pronostico_log": r["log"]["fct"].iloc[0] if len(r["log"]["fct"]) else np.nan,
                    "pronostico_nivel": r["nivel"]["fct"].iloc[0] if len(r["nivel"]["fct"]) else np.nan,
                })

    out = RAIZ / "results"
    out.mkdir(exist_ok=True)
    resumen = pd.concat(resumenes, ignore_index=True)
    resumen.to_csv(out / "x13.csv", index=False)
    pd.concat(detalles, ignore_index=True).to_csv(out / "predicciones_x13.csv", index=False)
    (pd.DataFrame(seleccion).sort_values(["serie", "fecha_pronostico"])
       .to_csv(out / "seleccion_x13_bcr.csv", index=False))

    print("\nMAE (test {} → {}; tn biodiésel, m³ bioetanol):".format(INICIO_TEST, FIN_TEST))
    print(resumen.pivot_table(index="serie", columns="modelo", values="MAE").round(0).to_string())
    print("\nMAPE % (referencia):")
    print(resumen.pivot_table(index="serie", columns="modelo", values="MAPE_pct").round(2).to_string())
    print(f"\nGuardado en {out}/x13.csv, predicciones_x13.csv y seleccion_x13_bcr.csv")


def pronostico_corte(series: dict[str, pd.Series], corte: str = CORTE_DOD) -> pd.DataFrame:
    """12 pronósticos con datos hasta ``corte``, como los publica BCR (DoD)."""
    filas = []
    for nombre in ("biodiesel", "bioetanol_total"):
        s = series[nombre]
        s = s[(s.index >= pd.Period(INICIO_BCR[nombre], freq="M")) & (s.index <= pd.Period(corte, freq="M"))]
        r = pronostico_bcr(s, nombre)
        for v in ("log", "nivel"):
            for h, (fecha, valor) in enumerate(r[v]["fct"].items(), 1):
                filas.append({
                    "serie": nombre, "datos_hasta": corte, "variante": v,
                    "elegida_por_criterio": v == r["elegido"],
                    "elegida_criterio_12m": v == r["elegido_12m"],
                    "criterio": r[v]["criterio"], "criterio_12m": r[v]["criterio_12m"],
                    "modelo_arima": r[v]["modelo_arima"],
                    "horizonte": h, "fecha": fecha.to_timestamp(), "pronostico": valor,
                })
    df = pd.DataFrame(filas)
    out = RAIZ / "results" / f"pronostico_x13_bcr_{corte}.csv"
    df.to_csv(out, index=False)
    resumen = (df[df.horizonte == 1]
               [["serie", "variante", "elegida_por_criterio", "criterio",
                "elegida_criterio_12m", "criterio_12m", "modelo_arima", "pronostico"]])
    print(f"Pronósticos con datos a {corte} (horizonte 1):")
    print(resumen.to_string(index=False))
    print(f"Guardado en {out}")
    return df


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--procesos", type=int, default=max(1, os.cpu_count() or 1))
    ap.add_argument("--solo-julio", action="store_true",
                    help="solo el pronóstico con datos a julio 2026 (DoD)")
    args = ap.parse_args()

    series = cargar_series()
    pronostico_corte(series)
    if not args.solo_julio:
        walk_forward(series, args.procesos)


if __name__ == "__main__":  # necesario en Windows para ProcessPoolExecutor
    main()
