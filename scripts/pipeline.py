"""Pipeline de estimación mensual (SCRUM-38).

Un solo comando que deja la estimación del mes, su explicación y el registro:

1. Descarga los datos públicos (si una fuente falla, avisa y sigue).
2. Procesa las exportaciones de INDEC del mes a estimar (el CSV anual se baja
   a mano, ver ``docs/exportaciones_indec.md``).
3. Arma la base (``build_db.py``).
4. Completa en el registro el real de los meses que ya se publicaron.
5. Estima el mes siguiente al último dato de producción con el modelo final
   de cada serie (``results/comparacion_final_eleccion.csv``, SCRUM-34).
6. Calcula las contribuciones de cada estimación (SCRUM-35).
7. Agrega la estimación al registro con la variación del IACA que se
   publicaría (SCRUM-44) y las contribuciones a
   ``data/registro_contribuciones.csv`` (solo las del modelo final, sin la
   fila ``total``). Antes de escribir valida todo, incluido que los aportes
   sumen el pronóstico del registro; si algo no cierra no escribe ninguno de
   los dos archivos.

Salida: el registro (``data/registro_estimaciones.csv``), las contribuciones
(``data/registro_contribuciones.csv``) y un resumen en pantalla. Los informes
para la BCR (Excel y HTML) se arman a partir de lo que devuelve ``correr``.

El modelo se reentrena en cada corrida con todos los datos hasta el mes
anterior, igual que en la evaluación (walk-forward): el pronóstico de un mes
pasado coincide con ``results/modelo_final_predicciones.csv``.

Uso, desde la raíz del repo:

    python scripts/pipeline.py                      # corrida mensual completa
    python scripts/pipeline.py --sin-descargas      # con los datos que ya están
    python scripts/pipeline.py --simular 2026-09    # demo: estima un mes ya publicado

``--simular`` hace como si el mes todavía no se hubiera publicado: borra en
memoria la producción de ese mes en adelante, estima, y compara con el real.
No descarga nada ni toca el registro real: escribe en ``results/simulacion/``.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import warnings
from datetime import datetime
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))

import registro  # noqa: E402
from build_db import leer_dataset  # noqa: E402
from construir_features import OBJETIVOS  # noqa: E402
from contribuciones import explicar  # noqa: E402

RUTA_CONTRIBUCIONES = registro.RUTA_CONTRIBUCIONES
RUTA_ELECCION = RAIZ / "results" / "comparacion_final_eleccion.csv"
CARPETA_SIMULACION = RAIZ / "results" / "simulacion"
CARPETA_INDEC = RAIZ / "variables_externas" / "data" / "indec_biodiesel"

# Orden en que se estiman y se muestran.
SERIES = ("biodiesel", "bioetanol_total", "bioetanol_maiz", "bioetanol_cana")
UNIDAD = {"biodiesel": "tn", "bioetanol_total": "m³", "bioetanol_maiz": "m³", "bioetanol_cana": "m³"}
NOMBRE = {"biodiesel": "Biodiésel", "bioetanol_total": "Bioetanol total",
          "bioetanol_maiz": "Bioetanol maíz", "bioetanol_cana": "Bioetanol caña"}

# Variables del mes a estimar sin las que la suma contable no puede estimar.
INSUMOS_BIODIESEL = {
    "ventas_gasoil_total_m3": "ventas de gasoil (Secretaría de Energía, salen los días 25-27)",
    "expo_indec_oculto": "exportaciones de INDEC (salen alrededor del día 20)",
}

DESCARGAS = [
    ("producción (Secretaría de Energía)", ["scripts/scrape_produccion_se.py"]),
    ("soja y maíz (CAC)", ["scripts/scrape_cac_soja_maiz.py"]),
    ("tipo de cambio (BCRA)", ["scripts/scrape_tipo_cambio.py"]),
    ("precios regulados", ["scripts/scrape_biocombustibles.py"]),
    ("molienda de soja", ["variables_externas/descargar_variables.py", "--output", "variables_externas/data"]),
    ("ventas de gasoil y nafta", ["variables_externas/descargar_combustibles.py", "--output", "variables_externas/data"]),
    ("aceite de soja y azúcar", ["variables_externas/descargar_aceite_soja.py"]),
]


# ------------------------------------------------------------------ pasos

def _correr(script: list[str]) -> tuple[bool, str]:
    # UTF-8 explícito: en Windows la consola usa otra codificación y los
    # mensajes con tildes de los scripts romperían la lectura.
    entorno = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([sys.executable, *script], cwd=RAIZ, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=entorno)
    salida = (r.stdout + r.stderr).strip().splitlines()
    return r.returncode == 0, (salida[-1] if salida else "")


def descargar() -> list[str]:
    """Corre las descargas automáticas. Devuelve las que fallaron (no frena)."""
    fallas = []
    for nombre, script in DESCARGAS:
        ok, ultima = _correr(script)
        print(f"  {'ok   ' if ok else 'FALLÓ'} {nombre}" + ("" if ok else f": {ultima}"), flush=True)
        if not ok:
            fallas.append(nombre)
    return fallas


def ultimo_mes_produccion() -> pd.Period:
    """Último mes publicado de biodiesel, leído del CSV que deja la descarga."""
    df = pd.read_csv(RAIZ / "data" / "produccion_biodiesel.csv", parse_dates=["fecha"])
    return pd.Period(df.loc[df["produccion_tn"].notna(), "fecha"].max(), freq="M")


def procesar_indec(mes: pd.Period) -> bool:
    """Procesa el CSV anual de INDEC hasta ``mes``. Avisa si falta el archivo del año."""
    if not any(CARPETA_INDEC.glob(f"*_{mes.year}_*.csv")):
        print(f"  FALTA el CSV de INDEC de {mes.year} en {CARPETA_INDEC.relative_to(RAIZ)} "
              "(ver docs/exportaciones_indec.md)")
        return False
    ok, ultima = _correr(["variables_externas/procesar_indec_biodiesel.py", "--hasta", str(mes)])
    print(f"  {'ok   ' if ok else 'FALLÓ'} exportaciones de INDEC hasta {mes}" + ("" if ok else f": {ultima}"))
    return ok


def armar_base() -> None:
    ok, ultima = _correr(["scripts/build_db.py"])
    if not ok:
        raise RuntimeError(f"No se pudo armar la base: {ultima}")
    print("  ok    base armada")


def modelos_elegidos() -> dict[str, str]:
    e = pd.read_csv(RUTA_ELECCION)
    return dict(zip(e["serie"], e["elegido"]))


def faltantes_del_mes(base: pd.DataFrame, mes: pd.Period) -> list[str]:
    """Insumos del biodiesel que todavía no están para ``mes``."""
    b = base.copy()
    b.index = pd.PeriodIndex(pd.to_datetime(b.index), freq="M")
    return [desc for col, desc in INSUMOS_BIODIESEL.items()
            if mes not in b.index or pd.isna(b.loc[mes, col])]


def ocultar_desde(base: pd.DataFrame, mes: pd.Period) -> pd.DataFrame:
    """Copia de la base sin la producción de ``mes`` en adelante (para simular)."""
    b = base.copy()
    periodos = pd.PeriodIndex(pd.to_datetime(b.index), freq="M")
    b.loc[periodos >= mes, list(OBJETIVOS.values())] = float("nan")
    return b


def _serie(base: pd.DataFrame, serie: str, hasta: pd.Period | None = None) -> pd.Series:
    """Producción de ``serie`` desde el dataset, con índice mensual."""
    s = base[OBJETIVOS[serie]].dropna().astype(float)
    s.index = pd.PeriodIndex(pd.to_datetime(s.index), freq="M")
    return s[s.index <= hasta] if hasta is not None else s


def estimar(mes: pd.Period, base: pd.DataFrame, elegidos: dict[str, str]) -> dict[str, pd.DataFrame]:
    """Estimación y contribuciones de cada serie. La predicción está en ``.attrs``."""
    salida = {}
    for serie in SERIES:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            salida[serie] = explicar(elegidos[serie], mes, base)
        print(f"  ok    {NOMBRE[serie]}: {salida[serie].attrs['prediccion']:,.0f} {UNIDAD[serie]} "
              f"({elegidos[serie]})", flush=True)
    return salida


def armar_contribuciones(tablas: dict[str, pd.DataFrame], ids: dict[str, int]) -> pd.DataFrame:
    """Contribuciones a guardar, unidas al registro por ``estimacion_id``.

    Una fila por factor de la estimación del modelo final de cada serie. La
    fila ``total`` no se guarda: es la suma de las demás. No escribe nada; la
    validación y la escritura las hace ``registro.agregar``.
    """
    partes = []
    for serie, t in tablas.items():
        cuerpo = t[t["factor"] != "total"]
        partes.append(pd.DataFrame({
            "estimacion_id": ids[serie],
            "factor": cuerpo["factor"].to_numpy(),
            "aporte": cuerpo["aporte"].to_numpy(dtype=float),
            "aporte_variacion_produccion_pp": cuerpo["aporte_variacion_produccion_pp"].to_numpy(dtype=float),
            "nota": cuerpo["nota"].fillna("").to_numpy() if "nota" in cuerpo else "",
        }))
    return pd.concat(partes, ignore_index=True)[registro.COLUMNAS_CONTRIBUCIONES]


# ------------------------------------------------------------------ corrida

def correr(sin_descargas: bool = False, simular: str | None = None) -> dict:
    """Corre el pipeline. Devuelve el mes, las tablas de contribuciones, las filas
    agregadas al registro y, si es una simulación, los reales del mes."""
    print(f"Pipeline de estimación — {datetime.now():%d/%m/%Y %H:%M}\n", flush=True)
    elegidos = modelos_elegidos()

    if simular:
        mes = pd.Period(simular, freq="M")
        print(f"SIMULACIÓN de {mes}: se oculta la producción desde ese mes. No se descarga nada "
              "ni se toca el registro real.\n")
        base_completa = leer_dataset()
        base = ocultar_desde(base_completa, mes)
        CARPETA_SIMULACION.mkdir(parents=True, exist_ok=True)
        ruta_registro = CARPETA_SIMULACION / f"registro_{mes}.csv"
        ruta_contrib = CARPETA_SIMULACION / f"contribuciones_{mes}.csv"
        for r in (ruta_registro, ruta_contrib):
            r.unlink(missing_ok=True)
        ruta_db = None
        produccion = {s: _serie(base_completa, s, hasta=mes - 1) for s in SERIES}
        fecha_datos = f"simulación (datos hasta {mes - 1})"
        reales = {s: float(_serie(base_completa, s).loc[mes]) for s in SERIES}
    else:
        if not sin_descargas:
            print("1. Descargas")
            fallas = descargar()
            if DESCARGAS[0][0] in fallas:
                raise RuntimeError("No se pudo descargar la producción: sin ella no se sabe qué mes "
                                   "estimar. Reintentar más tarde o pasar el .xlsx a mano "
                                   "(python scripts/scrape_produccion_se.py ruta.xlsx) y correr con "
                                   "--sin-descargas.")
            if fallas:
                print(f"  Aviso: fallaron {len(fallas)} descargas; se sigue con los datos anteriores.")
        mes = ultimo_mes_produccion() + 1
        print(f"\nMes a estimar: {mes}\n\n2. Exportaciones de INDEC")
        procesar_indec(mes)
        print("\n3. Base")
        armar_base()
        base = leer_dataset()
        faltan = faltantes_del_mes(base, mes)
        if faltan:
            raise RuntimeError(f"Todavía no están los datos de {mes} de: " + "; ".join(faltan)
                               + ". Volver a correr cuando salgan.")
        print("\n4. Registro: reales publicados")
        hechas = registro.completar()
        print(f"  ok    {len(hechas)} estimaciones anteriores completadas con el real")
        ruta_registro, ruta_contrib = registro.RUTA_REGISTRO, RUTA_CONTRIBUCIONES
        ruta_db, produccion, fecha_datos, reales = registro.RUTA_DB, None, None, None

    print(f"\n5. Estimación de {mes}")
    tablas = estimar(mes, base, elegidos)

    print("\n6. Registro y variación del IACA (corre X-13, ~30 s por serie)")
    # Primero se arman todas las filas (registro y contribuciones) sin escribir;
    # registro.agregar valida todo junto y recién después escribe los dos CSV.
    filas, ids = [], {}
    acumulado = registro.leer_registro(ruta_registro)
    for serie in SERIES:
        nuevas = registro.preparar(
            serie, mes, "modelo_final", tablas[serie].attrs["prediccion"],
            {"modelo_elegido": elegidos[serie]},
            anterior=acumulado, ruta_db=ruta_db,
            produccion=None if produccion is None else {serie: produccion[serie]},
            fecha_descarga_datos=fecha_datos,
        )
        ids[serie] = int(nuevas.loc[nuevas["modelo"] == "modelo_final", "estimacion_id"].iloc[0])
        filas.append(nuevas)
        acumulado = pd.concat([acumulado, nuevas], ignore_index=True) if len(acumulado) else nuevas
    filas = pd.concat(filas, ignore_index=True)
    contribuciones = armar_contribuciones(tablas, ids)
    registro.agregar(filas, contribuciones, ruta=ruta_registro, ruta_contribuciones=ruta_contrib,
                     ruta_db=ruta_db)
    print(f"  ok    {len(filas)} filas en el registro y {len(contribuciones)} contribuciones guardadas "
          "(los aportes suman el pronóstico)")

    print()
    _imprimir_resumen(tablas, filas, reales)
    return {
        "mes": mes, "tablas": tablas, "filas": filas, "reales": reales, "simulacion": bool(simular),
        "elegidos": elegidos, "contribuciones": contribuciones,
        "ruta_registro": ruta_registro, "ruta_contribuciones": ruta_contrib,
        "base": base_completa if simular else base,
    }


def _imprimir_resumen(tablas, filas, reales) -> None:
    for serie, t in tablas.items():
        reg = filas[(filas["serie_id"] == OBJETIVOS[serie]) & (filas["modelo"] == "modelo_final")].iloc[0]
        linea = (f"{NOMBRE[serie]:16s} {t.attrs['prediccion']:>10,.0f} {UNIDAD[serie]:2s}  "
                 f"producción {t.attrs['variacion_produccion_estimada_pct']:+6.1f} %")
        if pd.notna(reg["variacion_pronosticada_pct"]):
            linea += f"  IACA {reg['variacion_pronosticada_pct']:+6.2f} %"
        if reales is not None:
            linea += f"  | real {reales[serie]:,.0f}, error {t.attrs['prediccion'] - reales[serie]:+,.0f}"
        print(linea)
        cuerpo = t[~t["factor"].isin(["total", "constante"])].copy()
        cuerpo = cuerpo.reindex(cuerpo["aporte_variacion_produccion_pp"].abs().sort_values(ascending=False).index)
        for _, f in cuerpo.head(3).iterrows():
            print(f"    {f['factor']:38s} {f['aporte_variacion_produccion_pp']:+6.1f} puntos")
        if t.attrs["exportaciones_estimadas"]:
            print("    Aviso: INDEC ocultó la exportación del mes; se usa un estimado.")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--sin-descargas", action="store_true", help="usar los datos que ya están")
    p.add_argument("--simular", metavar="AAAA-MM", help="estimar un mes ya publicado, sin tocar el registro real")
    a = p.parse_args(argv)
    try:
        correr(a.sin_descargas, a.simular)
    except (RuntimeError, ValueError, FileNotFoundError) as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
