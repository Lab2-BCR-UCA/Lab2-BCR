"""Protocolo largo de evaluación (SCRUM-43): backtest de selección + holdout final.

Corre los baselines (SCRUM-22) y el X-13 con la configuración de BCR
(SCRUM-41) sobre las dos ventanas de docs/protocolo_evaluacion.md:

- backtest: walk-forward a un mes desde 2021-09 hasta 12 meses antes del
  último dato. Es la ventana para tomar decisiones.
- holdout: los últimos 12 meses. No se usa para decidir nada.

Además del resumen de métricas, reporta el error por subperíodo (cambios de
régimen) y la diferencia de error de cada modelo contra el naive estacional
con intervalo de confianza (bootstrap por bloques) y Diebold-Mariano.

Las corridas de X-13 son lentas (10-40 s cada una con la config de BCR), así
que se cachean en ``data/cache_x13.db`` (SQLite, no se versiona). La clave
de cada corrida incluye un hash de los datos de entrenamiento y de los .spc:
si cambia un dato o una config, esa corrida se rehace sola.

Uso, desde la raíz del proyecto:

    python scripts/protocolo_largo.py               # todo
    python scripts/protocolo_largo.py --procesos 4
    python scripts/protocolo_largo.py --sin-holdout # solo el backtest

Salidas en results/:
    protocolo_predicciones.csv  una fila por serie, modelo, ventana y mes
    protocolo_metricas.csv      métricas por serie, modelo y ventana
    protocolo_subperiodos.csv   métricas por subperíodo de régimen
    protocolo_diferencias.csv   cada modelo contra el naive estacional

Requiere: pip install x13binary pandas numpy scipy
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent))
from evaluacion import (  # noqa: E402
    Estacional,
    UltimoValor,
    comparar_modelos,
    error_por_subperiodo,
    evaluar_ventanas,
    ventanas_protocolo,
)
from replica_x13 import (  # noqa: E402
    INICIO_BCR,
    INICIO_PROTOCOLO,
    LOG_AUTO,
    SPC_BCR,
    SPC_DIR,
    cargar_series,
    pronostico_auto,
    pronostico_bcr,
)

RAIZ = Path(__file__).resolve().parent.parent
CACHE = RAIZ / "data" / "cache_x13.db"
REFERENCIA = "naive_estacional"
PERDIDAS = ("ape", "ae")

# modelo: (tipo, variante). tipo "base" no usa X-13.
MODELOS = {
    "naive": ("base", UltimoValor),
    "naive_estacional": ("base", Estacional),
    "x13_auto": ("auto", None),
    "x13_bcr_log": ("bcr", "log"),
    "x13_bcr_nivel": ("bcr", "nivel"),
    "x13_bcr_selcompleta": ("bcr", "elegido"),
    "x13_bcr": ("bcr", "elegido_12m"),  # el criterio que reproduce a BCR
}


# ---------------------------------------------------------------------------
# Caché de corridas de X-13
# ---------------------------------------------------------------------------

def _hash_config(tipo: str, nombre: str) -> str:
    """Hash de la configuración: los .spc para BCR, la transformación para auto."""
    h = hashlib.sha256(tipo.encode())
    if tipo == "bcr":
        for spc in SPC_BCR[nombre]:
            h.update((SPC_DIR / f"{spc}.spc").read_bytes())
    else:
        h.update(str(LOG_AUTO[nombre]).encode())
    return h.hexdigest()[:16]


def _hash_datos(entrenamiento: pd.Series) -> str:
    h = hashlib.sha256(str(entrenamiento.index[0]).encode())
    h.update(np.round(entrenamiento.to_numpy(dtype=float), 6).tobytes())
    return h.hexdigest()[:16]


def _clave(tipo: str, nombre: str, entrenamiento: pd.Series) -> tuple:
    return (tipo, nombre, str(entrenamiento.index[-1]),
            _hash_datos(entrenamiento), _hash_config(tipo, nombre))


def _abrir_cache() -> sqlite3.Connection:
    con = sqlite3.connect(CACHE)
    con.execute(
        "CREATE TABLE IF NOT EXISTS corridas ("
        " tipo TEXT, serie TEXT, datos_hasta TEXT, hash_datos TEXT,"
        " hash_config TEXT, resultado TEXT NOT NULL,"
        " PRIMARY KEY (tipo, serie, datos_hasta, hash_datos, hash_config))"
    )
    return con


def _leer_cache(con: sqlite3.Connection) -> dict:
    return {tuple(f[:5]): json.loads(f[5]) for f in con.execute("SELECT * FROM corridas")}


def _primero(fct: pd.Series) -> float | None:
    return float(fct.iloc[0]) if len(fct) else None


def _correr(args: tuple) -> tuple:
    """Una corrida de X-13 (proceso aparte). Devuelve un resultado serializable."""
    clave, entrenamiento = args
    tipo, nombre = clave[0], clave[1]
    try:
        if tipo == "bcr":
            r = pronostico_bcr(entrenamiento, nombre)
            res = {"elegido": r["elegido"], "elegido_12m": r["elegido_12m"]}
            for v in ("log", "nivel"):
                res[v] = _primero(r[v]["fct"])
                res[f"error_{v}"] = r[v]["error"]
                res[f"modelo_{v}"] = r[v]["modelo_arima"]
        else:
            f = pronostico_auto(entrenamiento, LOG_AUTO[nombre])
            res = {"pronostico": None if np.isnan(f) else f}
    except Exception as exc:  # queda como fallo en el protocolo
        res = {"excepcion": f"{type(exc).__name__}: {exc}"}
    return clave, res


def _entrenamientos(serie: pd.Series, inicio: str, ventanas: dict) -> list[pd.Series]:
    """Lo mismo que recibe cada iteración de evaluar_modelo."""
    s = serie[serie.index >= pd.Period(inicio, freq="M")].astype(float)
    salida = []
    for desde, hasta in ventanas.values():
        for mes in pd.period_range(desde, hasta, freq="M"):
            salida.append(s[s.index < mes])
    return salida


def precalcular(series: dict, ventanas: dict, procesos: int) -> dict:
    """Corre las iteraciones de X-13 que no estén en caché y devuelve todas."""
    con = _abrir_cache()
    cache = _leer_cache(con)
    pendientes = []
    for nombre, serie in series.items():
        for tipo, inicios in (("bcr", INICIO_BCR), ("auto", INICIO_PROTOCOLO)):
            for ent in _entrenamientos(serie, inicios[nombre], ventanas):
                clave = _clave(tipo, nombre, ent)
                if clave not in cache:
                    pendientes.append((clave, ent))
    # las de BCR (lentas) primero, para repartir mejor la carga
    pendientes.sort(key=lambda t: t[0][0] != "bcr")

    total = len(pendientes)
    print(f"Corridas de X-13: {total} pendientes, {len(cache)} en caché.", flush=True)
    if total:
        with ProcessPoolExecutor(max_workers=procesos) as ex:
            futuros = [ex.submit(_correr, p) for p in pendientes]
            for i, fut in enumerate(as_completed(futuros), 1):
                clave, res = fut.result()
                con.execute("INSERT OR REPLACE INTO corridas VALUES (?,?,?,?,?,?)",
                            (*clave, json.dumps(res)))
                con.commit()  # se guarda cada una: si se corta, no se pierde nada
                cache[clave] = res
                if i % 20 == 0 or i == total:
                    print(f"  {i}/{total}", flush=True)
    con.close()
    return cache


class ModeloX13Cacheado:
    """Adaptador fit/predict que lee la corrida de X-13 desde la caché.

    ``fit`` arma la clave con los mismos datos que recibe la iteración, así
    que nunca puede leer una corrida hecha con otros datos.
    """

    def __init__(self, cache: dict, tipo: str, nombre: str, variante: str | None) -> None:
        self.cache, self.tipo, self.nombre, self.variante = cache, tipo, nombre, variante

    def fit(self, serie: pd.Series) -> "ModeloX13Cacheado":
        clave = _clave(self.tipo, self.nombre, serie.astype(float))
        if clave not in self.cache:
            raise KeyError(f"Corrida sin precalcular: {clave[:3]}")
        self.res = self.cache[clave]
        return self

    def predict(self) -> float:
        r = self.res
        if "excepcion" in r:
            raise RuntimeError(r["excepcion"])
        if self.tipo == "auto":
            valor = r["pronostico"]
        else:
            v = r[self.variante] if self.variante.startswith("elegido") else self.variante
            valor = r[v]
            if valor is None:
                raise RuntimeError(f"X-13 sin pronóstico ({v}): {r[f'error_{v}']}")
        if valor is None:
            raise RuntimeError("X-13 sin pronóstico.")
        return valor


# ---------------------------------------------------------------------------
# Evaluación
# ---------------------------------------------------------------------------

def _crear(cache: dict, tipo: str, variante, nombre: str):
    if tipo == "base":
        return variante
    return lambda: ModeloX13Cacheado(cache, tipo, nombre, variante)


def diferencias(detalle: pd.DataFrame) -> pd.DataFrame:
    filas = []
    for (serie, ventana), grupo in detalle.groupby(["serie", "ventana"], sort=False):
        ref = grupo[grupo["modelo"] == REFERENCIA]
        for modelo, g in grupo.groupby("modelo", sort=False):
            if modelo == REFERENCIA:
                continue
            for perdida in PERDIDAS:
                r = comparar_modelos(g, ref, perdida=perdida)
                filas.append({"serie": serie, "ventana": ventana, "modelo": modelo,
                              "referencia": REFERENCIA, **r})
    return pd.DataFrame(filas)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--procesos", type=int, default=max(1, os.cpu_count() or 1))
    ap.add_argument("--sin-holdout", action="store_true",
                    help="evalúa solo el backtest (para tomar decisiones)")
    args = ap.parse_args()

    series = cargar_series()
    ultimo = min(s.index[-1] for s in series.values())
    ventanas = ventanas_protocolo(ultimo)
    if args.sin_holdout:
        ventanas = {"backtest": ventanas["backtest"]}
    for nombre, (desde, hasta) in ventanas.items():
        print(f"{nombre}: {desde} a {hasta}")

    cache = precalcular(series, ventanas, args.procesos)

    detalles, resumenes = [], []
    for nombre, serie in series.items():
        for modelo, (tipo, variante) in MODELOS.items():
            inicio = INICIO_BCR[nombre] if tipo == "bcr" else INICIO_PROTOCOLO[nombre]
            detalle, resumen = evaluar_ventanas(
                serie=serie,
                crear_modelo=_crear(cache, tipo, variante, nombre),
                inicio_entrenamiento=inicio,
                ventanas=ventanas,
                nombre_serie=nombre,
                nombre_modelo=modelo,
            )
            resumen["inicio_entrenamiento"] = inicio
            detalles.append(detalle)
            resumenes.append(resumen)

    detalle = pd.concat(detalles, ignore_index=True)
    resumen = pd.concat(resumenes, ignore_index=True)
    sub = error_por_subperiodo(detalle)
    dif = diferencias(detalle)

    out = RAIZ / "results"
    out.mkdir(exist_ok=True)
    detalle.to_csv(out / "protocolo_predicciones.csv", index=False)
    resumen.to_csv(out / "protocolo_metricas.csv", index=False)
    sub.to_csv(out / "protocolo_subperiodos.csv", index=False)
    dif.to_csv(out / "protocolo_diferencias.csv", index=False)

    incompletas = resumen[~resumen["evaluacion_completa"]]
    if len(incompletas):
        print("\nEvaluaciones incompletas:")
        print(incompletas[["serie", "modelo", "ventana", "cobertura_pct"]].to_string(index=False))

    for ventana in ventanas:
        r = resumen[resumen["ventana"] == ventana]
        print(f"\nMAPE % ({ventana}):")
        print(r.pivot_table(index="serie", columns="modelo", values="MAPE_pct",
                            sort=False).round(1).to_string())
        d = dif[(dif["ventana"] == ventana) & (dif["perdida"] == "ape")]
        print(f"\nDiferencia de APE contra {REFERENCIA} ({ventana}), IC 95 %:")
        print(d[["serie", "modelo", "diferencia_media", "ic_inf", "ic_sup",
                 "dm", "dm_p_valor"]].round(2).to_string(index=False))
    print(f"\nGuardado en {out}/protocolo_*.csv")


if __name__ == "__main__":  # necesario en Windows para ProcessPoolExecutor
    main()
