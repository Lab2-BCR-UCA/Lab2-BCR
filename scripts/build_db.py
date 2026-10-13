"""Construye la base unificada del proyecto (SCRUM-27).

La base (SQLite) es un derivado: se arma desde cero cada vez, leyendo las
versiones fechadas de cada fuente guardadas en data/snapshots/. Así la base
se puede borrar y regenerar sin perder historia.

Pasos:
    1. Copias fechadas: para cada fuente de db/fuentes.csv, si el CSV actual
       cambió respecto de la última copia guardada, se guarda una copia nueva
       en data/snapshots/<fuente>/<fecha>.csv y se anota en el manifiesto.
    2. Reconstrucción: se crea la base con db/schema.sql y se cargan todas las
       copias del manifiesto, de la más vieja a la más nueva.
    3. Controles de calidad: duplicados, meses faltantes, negativos y nulos.
       Si algo falla, la base anterior queda intacta.

Uso, desde la raíz del repo:
    python scripts/build_db.py                       # copia lo que cambió y reconstruye
    python scripts/build_db.py --solo-reconstruir    # reconstruye sin mirar los CSV actuales
    python scripts/build_db.py --fecha-descarga 2026-11-05   # fecha para las copias nuevas

La primera copia de cada fuente toma la fecha del último commit que modificó
el CSV; las siguientes, la fecha del día (o la de --fecha-descarga).

Requiere: pandas.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import sqlite3
import subprocess
import sys
from datetime import date
from pathlib import Path

import pandas as pd

RAIZ_DEFECTO = Path(__file__).resolve().parents[1]
CAMPOS_MANIFIESTO = ["archivo_snapshot", "fuente", "fecha_descarga", "hash_sha256", "filas", "origen"]


# ---------------------------------------------------------------- utilidades

def _contenido_normalizado(ruta: Path) -> bytes:
    """Lee un archivo con saltos de línea unificados a LF.

    Evita que un clon en Windows (CRLF) parezca una versión nueva del dato.
    """
    return ruta.read_bytes().replace(b"\r\n", b"\n")


def _hash(contenido: bytes) -> str:
    return hashlib.sha256(contenido).hexdigest()


def _fecha_commit(raiz: Path, archivo: str) -> str | None:
    """Fecha (YYYY-MM-DD) del último commit que tocó el archivo, si hay git."""
    try:
        r = subprocess.run(
            ["git", "log", "-1", "--format=%cs", "--", archivo],
            cwd=raiz, capture_output=True, text=True, timeout=30,
        )
        return r.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _leer_manifiesto(ruta: Path) -> list[dict]:
    if not ruta.exists():
        return []
    with ruta.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _escribir_manifiesto(ruta: Path, filas: list[dict]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS_MANIFIESTO, lineterminator="\n")
        w.writeheader()
        w.writerows(filas)


# ---------------------------------------------------------- 1. copias fechadas

def guardar_copias(raiz: Path, fuentes: pd.DataFrame, fecha_forzada: str | None) -> list[Path]:
    """Guarda una copia fechada de cada fuente cuyo contenido cambió.

    Returns:
        Rutas de las copias nuevas.
    """
    dir_snap = raiz / "data" / "snapshots"
    ruta_manifiesto = dir_snap / "manifiesto.csv"
    manifiesto = _leer_manifiesto(ruta_manifiesto)
    mensajes = []

    for fila in fuentes.itertuples():
        origen_csv = raiz / fila.archivo_origen
        if not origen_csv.exists():
            raise FileNotFoundError(f"No existe el archivo de la fuente {fila.fuente}: {fila.archivo_origen}")

        contenido = _contenido_normalizado(origen_csv)
        h = _hash(contenido)
        previas = [m for m in manifiesto if m["fuente"] == fila.fuente]
        if any(m["hash_sha256"] == h for m in previas):
            continue  # ya está guardada esta versión

        if fecha_forzada:
            fecha, origen = fecha_forzada, "carga"
        elif not previas:
            fecha = _fecha_commit(raiz, fila.archivo_origen) or date.today().isoformat()
            origen = "commit"
        else:
            fecha, origen = date.today().isoformat(), "carga"

        destino = dir_snap / fila.fuente / f"{fecha}.csv"
        n = 2
        while destino.exists():  # dos versiones distintas el mismo día
            destino = dir_snap / fila.fuente / f"{fecha}_{n}.csv"
            n += 1
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(contenido)

        filas_datos = max(contenido.count(b"\n") - 1, 0)
        manifiesto.append({
            "archivo_snapshot": destino.relative_to(dir_snap).as_posix(),
            "fuente": fila.fuente,
            "fecha_descarga": fecha,
            "hash_sha256": h,
            "filas": filas_datos,
            "origen": origen,
        })
        mensajes.append(destino)

    _escribir_manifiesto(ruta_manifiesto, manifiesto)
    return mensajes


def actualizar(raiz: Path, ruta_db: Path, fecha_forzada: str | None = None) -> tuple[list[Path], dict]:
    """Guarda las copias nuevas y reconstruye la base, todo o nada.

    Si la reconstrucción falla los controles, borra las copias recién creadas
    y restaura el manifiesto: una descarga inválida no queda en la historia.

    Returns:
        Copias nuevas y resumen de la reconstrucción.
    """
    fuentes, _ = _cargar_catalogo(raiz)
    ruta_manifiesto = raiz / "data" / "snapshots" / "manifiesto.csv"
    previo = ruta_manifiesto.read_bytes() if ruta_manifiesto.exists() else None
    nuevas = guardar_copias(raiz, fuentes, fecha_forzada)
    try:
        resumen = reconstruir(raiz, ruta_db)
    except Exception:
        for ruta in nuevas:
            ruta.unlink(missing_ok=True)
        if previo is None:
            ruta_manifiesto.unlink(missing_ok=True)
        else:
            ruta_manifiesto.write_bytes(previo)
        raise
    return nuevas, resumen


# ------------------------------------------------------------ 2. reconstrucción

def _cargar_catalogo(raiz: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    fuentes = pd.read_csv(raiz / "db" / "fuentes.csv")
    series = pd.read_csv(raiz / "db" / "series.csv")
    disp = pd.read_csv(raiz / "data" / "disponibilidad_variables.csv")

    errores = []
    if fuentes["fuente"].duplicated().any():
        errores.append("db/fuentes.csv tiene fuentes repetidas")
    if series["serie_id"].duplicated().any():
        errores.append("db/series.csv tiene serie_id repetidos")
    sin_fuente = set(series["fuente"]) - set(fuentes["fuente"])
    if sin_fuente:
        errores.append(f"series con fuente desconocida: {sorted(sin_fuente)}")
    rezagos = dict(zip(disp["variable"], disp["rezago_min"]))
    sin_disp = sorted(set(series["variable_disponibilidad"]) - set(rezagos))
    if sin_disp:
        errores.append(f"variables sin fila en data/disponibilidad_variables.csv: {sin_disp}")
    if errores:
        raise ValueError("Catálogo inválido:\n  " + "\n  ".join(errores))

    series = series.assign(
        rezago_min=series["variable_disponibilidad"].map(rezagos).astype(int),
        huecos_esperados=series["huecos_esperados"].str.strip().str.lower().map({"si": 1, "no": 0}),
    )
    if series["huecos_esperados"].isna().any():
        raise ValueError("huecos_esperados debe ser 'si' o 'no' en db/series.csv")
    return fuentes, series


def _controlar(serie_id: str, s: pd.Series, huecos_ok: bool, snapshot: str,
               errores: list[str], avisos: list[str]) -> None:
    """Controles de calidad de una serie en una versión."""
    nulos = s[s.isna()].index
    if len(nulos):
        errores.append(f"{serie_id} ({snapshot}): {len(nulos)} valores nulos, por ejemplo {nulos[0]:%Y-%m}")
    s = s.dropna()
    negativos = s[s < 0].index
    if len(negativos):
        errores.append(f"{serie_id} ({snapshot}): {len(negativos)} valores negativos, por ejemplo {negativos[0]:%Y-%m}")
    if s.empty:
        errores.append(f"{serie_id} ({snapshot}): no tiene datos")
        return
    grilla = pd.date_range(s.index.min(), s.index.max(), freq="MS")
    faltan = grilla.difference(s.index)
    if len(faltan):
        msg = f"{serie_id} ({snapshot}): {len(faltan)} meses faltantes, por ejemplo {faltan[0]:%Y-%m}"
        (avisos if huecos_ok else errores).append(msg)


def reconstruir(raiz: Path, ruta_db: Path) -> dict:
    """Arma la base desde cero a partir del manifiesto de copias.

    Escribe primero en un archivo temporal y solo reemplaza la base si todos
    los controles pasan.

    Returns:
        Resumen con conteos y avisos.
    """
    fuentes, series = _cargar_catalogo(raiz)
    dir_snap = raiz / "data" / "snapshots"
    manifiesto = _leer_manifiesto(dir_snap / "manifiesto.csv")
    errores, avisos = [], []

    faltan_copias = set(fuentes["fuente"]) - {m["fuente"] for m in manifiesto}
    if faltan_copias:
        raise ValueError(f"Fuentes sin ninguna copia en data/snapshots: {sorted(faltan_copias)}")

    tmp = ruta_db.with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(tmp)
    try:
        con.executescript((raiz / "db" / "schema.sql").read_text(encoding="utf-8"))
        con.executemany("INSERT INTO fuentes VALUES (?, ?, ?)",
                        fuentes[["fuente", "archivo_origen", "descripcion"]].itertuples(index=False))
        cols = ["serie_id", "fuente", "columna_origen", "unidad", "tipo",
                "variable_disponibilidad", "rezago_min", "huecos_esperados", "descripcion"]
        con.executemany(f"INSERT INTO series ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                        series[cols].itertuples(index=False))

        orden = sorted(manifiesto, key=lambda m: (m["fecha_descarga"], m["archivo_snapshot"]))
        for m in orden:
            ruta = dir_snap / m["archivo_snapshot"]
            if not ruta.exists():
                errores.append(f"falta la copia {m['archivo_snapshot']} listada en el manifiesto")
                continue
            if _hash(_contenido_normalizado(ruta)) != m["hash_sha256"]:
                errores.append(f"la copia {m['archivo_snapshot']} fue modificada (no coincide el hash)")
                continue

            cur = con.execute(
                "INSERT INTO descargas (fuente, fecha_descarga, archivo_snapshot, hash_sha256, filas, origen) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (m["fuente"], m["fecha_descarga"], m["archivo_snapshot"], m["hash_sha256"],
                 int(m["filas"]), m["origen"]),
            )
            descarga_id = cur.lastrowid

            df = pd.read_csv(ruta)
            df["fecha"] = pd.to_datetime(df["fecha"]).dt.to_period("M").dt.to_timestamp()
            if df["fecha"].duplicated().any():
                dup = df.loc[df["fecha"].duplicated(), "fecha"].iloc[0]
                errores.append(f"{m['archivo_snapshot']}: mes duplicado {dup:%Y-%m}")
                continue
            df = df.set_index("fecha").sort_index()
            provisorio = None
            if "provisorio" in df.columns:
                provisorio = df["provisorio"].astype(str).str.strip().str.lower().map({"true": 1, "false": 0})

            for s in series[series["fuente"] == m["fuente"]].itertuples():
                if s.columna_origen not in df.columns:
                    errores.append(f"{m['archivo_snapshot']}: falta la columna {s.columna_origen} ({s.serie_id})")
                    continue
                valores = pd.to_numeric(df[s.columna_origen], errors="coerce")
                _controlar(s.serie_id, valores, bool(s.huecos_esperados), m["archivo_snapshot"], errores, avisos)
                ok = valores.dropna()
                filas = [
                    (s.serie_id, f.strftime("%Y-%m-%d"), float(v),
                     None if provisorio is None or pd.isna(provisorio.get(f)) else int(provisorio[f]),
                     descarga_id)
                    for f, v in ok.items()
                ]
                con.executemany(
                    "INSERT INTO observaciones (serie_id, fecha, valor, provisorio, descarga_id) "
                    "VALUES (?, ?, ?, ?, ?)", filas)

        # Vista ancha generada desde el catálogo.
        columnas = ",\n    ".join(
            f"MAX(CASE WHEN serie_id = '{sid}' THEN valor END) AS {sid}" for sid in series["serie_id"])
        con.execute(f"CREATE VIEW v_dataset_mensual AS\nSELECT fecha,\n    {columnas}\n"
                    f"FROM v_ultima_version\nGROUP BY fecha\nORDER BY fecha")
        con.commit()

        resumen = {
            "fuentes": con.execute("SELECT COUNT(*) FROM fuentes").fetchone()[0],
            "series": con.execute("SELECT COUNT(*) FROM series").fetchone()[0],
            "descargas": con.execute("SELECT COUNT(*) FROM descargas").fetchone()[0],
            "observaciones": con.execute("SELECT COUNT(*) FROM observaciones").fetchone()[0],
            "meses_dataset": con.execute("SELECT COUNT(*) FROM v_dataset_mensual").fetchone()[0],
            "avisos": avisos,
        }
    finally:
        con.close()

    if errores:
        tmp.unlink(missing_ok=True)
        raise ValueError("Controles de calidad fallidos; la base anterior no se modificó:\n  "
                         + "\n  ".join(errores))
    os.replace(tmp, ruta_db)
    return resumen


# ----------------------------------------------------------------- lectura

def leer_dataset(ruta_db: Path | str | None = None) -> pd.DataFrame:
    """Devuelve el dataset mensual (última versión de cada dato), indexado por fecha."""
    ruta_db = Path(ruta_db) if ruta_db else RAIZ_DEFECTO / "data" / "bcr.db"
    with sqlite3.connect(ruta_db) as con:
        df = pd.read_sql("SELECT * FROM v_dataset_mensual", con, parse_dates=["fecha"])
    return df.set_index("fecha")


# ---------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--raiz", type=Path, default=RAIZ_DEFECTO, help="raíz del repositorio")
    p.add_argument("--db", type=Path, default=None, help="ruta de la base (por defecto data/bcr.db)")
    p.add_argument("--solo-reconstruir", action="store_true",
                   help="no guarda copias nuevas; solo arma la base con las existentes")
    p.add_argument("--fecha-descarga", default=None,
                   help="fecha YYYY-MM-DD para las copias nuevas (por defecto, hoy)")
    a = p.parse_args(argv)

    raiz = a.raiz.resolve()
    ruta_db = (a.db or raiz / "data" / "bcr.db").resolve()
    if a.fecha_descarga:
        date.fromisoformat(a.fecha_descarga)  # valida el formato

    try:
        if a.solo_reconstruir:
            r = reconstruir(raiz, ruta_db)
        else:
            nuevas, r = actualizar(raiz, ruta_db, a.fecha_descarga)
            for ruta in nuevas:
                print(f"copia nueva: {ruta.relative_to(raiz).as_posix()}")
    except (ValueError, FileNotFoundError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(f"Base generada en {ruta_db}")
    print(f"  {r['fuentes']} fuentes, {r['series']} series, {r['descargas']} versiones, "
          f"{r['observaciones']} observaciones, {r['meses_dataset']} meses en el dataset")
    if r["avisos"]:
        print(f"  {len(r['avisos'])} avisos (huecos esperados):")
        for msg in r["avisos"]:
            print(f"    {msg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
