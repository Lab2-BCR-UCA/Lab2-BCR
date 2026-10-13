"""Pruebas de la base unificada (SCRUM-27).

Corre sobre una copia temporal del repo, así no toca data/snapshots ni la base
real. Verifica los criterios del DoD:

    1. La base se genera desde cero con un script.
    2. Una segunda descarga agrega versiones sin pisar las anteriores.
    3. Los controles de calidad frenan datos inválidos y no rompen la base anterior.

Uso, desde la raíz del repo:
    python scripts/test_build_db.py
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_db  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]


def _copiar_repo(destino: Path) -> None:
    """Copia solo lo que la base necesita: catálogo y CSV de las fuentes."""
    shutil.copytree(RAIZ / "db", destino / "db")
    (destino / "data").mkdir()
    shutil.copy(RAIZ / "data" / "disponibilidad_variables.csv", destino / "data")
    for archivo in pd.read_csv(RAIZ / "db" / "fuentes.csv")["archivo_origen"]:
        (destino / archivo).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(RAIZ / archivo, destino / archivo)


def _construir(raiz: Path, fecha: str) -> dict:
    _, resumen = build_db.actualizar(raiz, raiz / "data" / "bcr.db", fecha)
    return resumen


def _consulta(raiz: Path, sql: str, params=()) -> list:
    with sqlite3.connect(raiz / "data" / "bcr.db") as con:
        return con.execute(sql, params).fetchall()


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        raiz = Path(tmp)
        _copiar_repo(raiz)
        csv_bd = raiz / "data" / "produccion_biodiesel.csv"

        # 1. Primera carga desde cero.
        r1 = _construir(raiz, "2026-10-01")
        assert r1["series"] == 26 and r1["descargas"] == 8, r1
        print(f"ok  primera carga: {r1['series']} series, {r1['observaciones']} observaciones")

        # Sin cambios en los CSV no se crea ninguna versión nueva.
        r1b = _construir(raiz, "2026-10-02")
        assert r1b["descargas"] == 8, r1b
        print("ok  sin cambios no se agregan versiones")

        # Un CSV con saltos de línea de Windows no cuenta como versión nueva.
        csv_bd.write_bytes(csv_bd.read_bytes().replace(b"\n", b"\r\n"))
        assert _construir(raiz, "2026-10-02")["descargas"] == 8
        print("ok  CRLF no genera una versión falsa")

        # 2. Segunda descarga: la Secretaría revisa julio y publica septiembre.
        df = pd.read_csv(csv_bd)
        original_jul = float(df.loc[df["fecha"] == "2026-07-01", "produccion_tn"].iloc[0])
        df.loc[df["fecha"] == "2026-07-01", "produccion_tn"] = original_jul + 1000
        nueva = df.iloc[[-1]].assign(fecha="2026-09-01", produccion_tn=150000.0)
        pd.concat([df, nueva]).to_csv(csv_bd, index=False)

        r2 = _construir(raiz, "2026-11-05")
        assert r2["descargas"] == 9, r2
        versiones = _consulta(raiz,
            "SELECT d.fecha_descarga, o.valor FROM observaciones o JOIN descargas d USING (descarga_id) "
            "WHERE o.serie_id = 'produccion_biodiesel_tn' AND o.fecha = '2026-07-01' ORDER BY 1")
        assert versiones == [("2026-10-01", original_jul), ("2026-11-05", original_jul + 1000)], versiones
        ultima = _consulta(raiz,
            "SELECT valor, fecha_descarga FROM v_ultima_version "
            "WHERE serie_id = 'produccion_biodiesel_tn' AND fecha = '2026-07-01'")
        assert ultima == [(original_jul + 1000, "2026-11-05")], ultima
        sep = _consulta(raiz, "SELECT produccion_biodiesel_tn FROM v_dataset_mensual WHERE fecha = '2026-09-01'")
        assert sep == [(150000.0,)], sep
        print("ok  segunda descarga: julio conserva las dos versiones, la vista toma la nueva y suma septiembre")

        # Reconstruir desde cero da el mismo resultado (la historia vive en las copias).
        (raiz / "data" / "bcr.db").unlink()
        r3 = build_db.reconstruir(raiz, raiz / "data" / "bcr.db")
        assert (r3["descargas"], r3["observaciones"]) == (r2["descargas"], r2["observaciones"])
        print("ok  borrar y reconstruir conserva todas las versiones")

        # 3. Un valor negativo frena la carga; la base y las copias quedan como estaban.
        manifiesto = raiz / "data" / "snapshots" / "manifiesto.csv"
        manifiesto_antes = manifiesto.read_bytes()
        copias_antes = sorted((raiz / "data" / "snapshots").rglob("*.csv"))
        csv_valido = csv_bd.read_bytes()
        df = pd.read_csv(csv_bd)
        df.loc[df["fecha"] == "2026-08-01", "produccion_tn"] = -5
        df.to_csv(csv_bd, index=False)
        try:
            _construir(raiz, "2026-12-01")
            raise AssertionError("debería haber fallado por el valor negativo")
        except ValueError as e:
            assert "negativos" in str(e), e
        assert _consulta(raiz, "SELECT COUNT(*) FROM descargas") == [(9,)]
        assert manifiesto.read_bytes() == manifiesto_antes
        assert sorted((raiz / "data" / "snapshots").rglob("*.csv")) == copias_antes
        print("ok  un negativo frena la carga; la base, el manifiesto y las copias no cambian")

        # Corregido el dato, la carga siguiente funciona normalmente.
        csv_bd.write_bytes(csv_valido)
        assert _construir(raiz, "2026-12-01")["descargas"] == 9
        print("ok  después de una carga fallida la siguiente funciona")

        # Un mes faltante en una serie sin huecos esperados también frena la carga.
        df = df[df["fecha"] != "2026-08-01"]
        df = df[df["fecha"] != "2015-06-01"]
        df.to_csv(csv_bd, index=False)
        try:
            _construir(raiz, "2026-12-02")
            raise AssertionError("debería haber fallado por el mes faltante")
        except ValueError as e:
            assert "meses faltantes" in str(e), e
        print("ok  un mes faltante frena la carga")

        # Una copia editada a mano se detecta por el hash.
        copia = next((raiz / "data" / "snapshots" / "tipo_cambio").glob("*.csv"))
        copia.write_text(copia.read_text() + "2099-01-01,1,1\n")
        try:
            build_db.reconstruir(raiz, raiz / "data" / "bcr.db")
            raise AssertionError("debería haber detectado la copia modificada")
        except ValueError as e:
            assert "hash" in str(e), e
        print("ok  una copia modificada a mano se detecta")

    print("\nTodas las pruebas pasaron.")


if __name__ == "__main__":
    main()
