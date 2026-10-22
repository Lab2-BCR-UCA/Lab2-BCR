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

    probar_derivadas()
    print("\nTodas las pruebas pasaron.")


# ---------------------------------------------------------- derivadas (SCRUM-56)

PRECIO = "precio_bioetanol_maiz_ars_l"
MAIZ = "precio_maiz_pizarra_ars_tn"
DERIVADA = "derivada_prueba"


def _ratio_prueba(insumos: pd.DataFrame) -> pd.Series:
    """Fórmula de prueba: un cociente entre un precio regulado y la pizarra."""
    return insumos[PRECIO] / insumos[MAIZ]


def _escribir_derivadas(raiz: Path, filas: list[str]) -> None:
    encabezado = "serie_id,funcion,insumos,unidad,tipo,variable_disponibilidad,huecos_esperados,descripcion"
    (raiz / "db" / "derivadas.csv").write_text("\n".join([encabezado, *filas]) + "\n", encoding="utf-8")


def _fila(serie_id=DERIVADA, funcion="_ratio_prueba", insumos=f"{PRECIO}|{MAIZ}",
          variable="margen_bioetanol_maiz") -> str:
    return f"{serie_id},{funcion},{insumos},ratio,externa,{variable},no,Derivada de prueba"


def _espera_error(raiz: Path, texto: str) -> None:
    try:
        build_db.reconstruir(raiz, raiz / "data" / "bcr.db")
    except ValueError as e:
        assert texto in str(e), e
        return
    raise AssertionError(f"debería haber fallado con: {texto}")


def probar_derivadas() -> None:
    build_db.modulo_derivadas._ratio_prueba = _ratio_prueba
    with tempfile.TemporaryDirectory() as tmp:
        raiz = Path(tmp)
        _copiar_repo(raiz)
        _escribir_derivadas(raiz, [_fila()])
        csv_maiz = raiz / "data" / "soja_maiz_cac_mensual.csv"
        csv_precio = raiz / "data" / "bioetanol_precios.csv"
        precios = pd.read_csv(csv_precio, parse_dates=["fecha"]).set_index("fecha")[["precio_maiz_ars_l"]]
        maiz = pd.read_csv(csv_maiz, parse_dates=["fecha"]).set_index("fecha")["maiz_ars_tn"]

        # 1. La derivada aparece en la base y en la vista, calculada con el relleno.
        r1 = _construir(raiz, "2026-10-01")
        assert r1["series"] == 27 and r1["versiones_derivadas"] == 1, r1
        grilla = pd.date_range(precios.index.min(), precios.index.max(), freq="MS")
        hueco = grilla.difference(precios.index)[0]
        esperado = precios["precio_maiz_ars_l"].reindex(grilla).ffill()[hueco] / maiz[hueco]
        valor = _consulta(raiz, f"SELECT {DERIVADA} FROM v_dataset_mensual WHERE fecha = ?",
                          (hueco.strftime("%Y-%m-%d"),))[0][0]
        assert abs(valor - esperado) < 1e-12, (valor, esperado)
        print(f"ok  la derivada está en la vista; {hueco:%Y-%m} (sin resolución) usa el precio vigente")

        # El relleno no toca las observaciones crudas: el hueco sigue sin dato.
        crudo = _consulta(raiz, "SELECT COUNT(*) FROM observaciones WHERE serie_id = ? AND fecha = ?",
                          (PRECIO, hueco.strftime("%Y-%m-%d")))
        assert crudo == [(0,)], crudo
        print("ok  el relleno no modifica las observaciones crudas")

        # 2. Un cambio que no afecta a los insumos (soja) no genera una versión nueva.
        df = pd.read_csv(csv_maiz)
        df.loc[df.index[-1], "soja_ars_tn"] += 1
        df.to_csv(csv_maiz, index=False)
        r2 = _construir(raiz, "2026-10-15")
        assert r2["versiones_derivadas"] == 1, r2
        print("ok  un cambio en una columna que no es insumo no genera versión nueva")

        # 3. La CAC revisa agosto: versión nueva de la derivada, la anterior queda.
        agosto = "2026-08-01"
        df = pd.read_csv(csv_maiz)
        df.loc[df["fecha"] == agosto, "maiz_ars_tn"] *= 1.10
        df.to_csv(csv_maiz, index=False)
        r3 = _construir(raiz, "2026-11-05")
        assert r3["versiones_derivadas"] == 2, r3
        versiones = _consulta(raiz,
            "SELECT d.fecha_descarga, o.valor FROM observaciones o JOIN descargas d USING (descarga_id) "
            "WHERE o.serie_id = ? AND o.fecha = ? ORDER BY 1", (DERIVADA, agosto))
        assert [v[0] for v in versiones] == ["2026-10-01", "2026-11-05"], versiones
        assert abs(versiones[1][1] - versiones[0][1] / 1.10) < 1e-9, versiones
        print("ok  revisión de un insumo: versión nueva de la derivada sin pisar la anterior")

        # Qué se sabía el 20/10: la derivada vieja, coherente con la pizarra vieja.
        def al(fecha, serie):
            return _consulta(raiz,
                "SELECT o.valor FROM observaciones o JOIN descargas d USING (descarga_id) "
                "WHERE o.serie_id = ? AND o.fecha = ? AND d.fecha_descarga <= ? "
                "ORDER BY d.fecha_descarga DESC, o.descarga_id DESC LIMIT 1", (serie, agosto, fecha))[0][0]
        precio_ago = precios.loc[agosto, "precio_maiz_ars_l"]
        assert abs(al("2026-10-20", DERIVADA) - precio_ago / al("2026-10-20", MAIZ)) < 1e-12
        assert abs(al("2026-11-10", DERIVADA) - precio_ago / al("2026-11-10", MAIZ)) < 1e-12
        print("ok  consulta a una fecha: la derivada coincide con sus insumos a esa fecha")

        # 4. Linaje: cada versión registra las descargas de insumos que usó.
        linaje = _consulta(raiz,
            "SELECT d.fecha_descarga, i.fuente, i.fecha_descarga FROM descargas d "
            "JOIN descargas_insumos l ON l.descarga_id = d.descarga_id "
            "JOIN descargas i ON i.descarga_id = l.insumo_descarga_id "
            "WHERE d.serie_derivada = ? ORDER BY 1, 2, 3", (DERIVADA,))
        ultima = sorted((f, s) for v, f, s in linaje if v == "2026-11-05")
        assert ("pizarra_cac", "2026-11-05") in ultima and ("precios_bioetanol", "2026-10-01") in ultima, linaje
        assert ("pizarra_cac", "2026-10-01") not in ultima, linaje  # la descarga nueva trae el archivo entero
        assert all(v != "2026-10-01" or s == "2026-10-01" for v, f, s in linaje), linaje
        print("ok  linaje completo: cada versión apunta a las descargas de insumos que usó")

        # Reconstruir desde cero da exactamente lo mismo (las derivadas no se guardan).
        (raiz / "data" / "bcr.db").unlink()
        r4 = build_db.reconstruir(raiz, raiz / "data" / "bcr.db")
        assert (r4["versiones_derivadas"], r4["observaciones"]) == (2, r3["observaciones"]), r4
        assert not any((raiz / "data" / "snapshots").glob(f"*{DERIVADA}*"))
        print("ok  borrar y reconstruir recalcula las mismas versiones")

        # 5. El precio regulado deja de llegar mientras la pizarra sigue: se
        #    rellena con el último vigente, pero pasados 3 meses avisa.
        df = pd.read_csv(csv_maiz)
        nuevos = pd.date_range("2026-10-01", periods=4, freq="MS").strftime("%Y-%m-%d")
        extra = pd.DataFrame({"fecha": nuevos, "maiz_ars_tn": 300000.0, "soja_ars_tn": 560000.0})
        pd.concat([df, extra]).to_csv(csv_maiz, index=False)
        r5 = _construir(raiz, "2026-11-10")
        assert any(DERIVADA in a and "se rellenó 4 meses" in a for a in r5["avisos"]), r5["avisos"]
        print("ok  un relleno de más de 3 meses al final genera un aviso")
        df.to_csv(csv_maiz, index=False)

        # 6. Errores de catálogo.
        _escribir_derivadas(raiz, [_fila(insumos="produccion_bioetanol_maiz_m3|" + MAIZ)])
        _espera_error(raiz, "el rezago de una derivada no puede ser menor")
        print("ok  un rezago menor que el de sus insumos frena el armado")

        _escribir_derivadas(raiz, [_fila(), _fila(serie_id="otra", insumos=f"{DERIVADA}|{MAIZ}")])
        _espera_error(raiz, "no se permiten derivadas de derivadas")
        print("ok  una derivada de una derivada frena el armado")

        _escribir_derivadas(raiz, [_fila(funcion="no_existe")])
        _espera_error(raiz, "no existe la función")
        _escribir_derivadas(raiz, [_fila(insumos=f"{PRECIO}|serie_inventada")])
        _espera_error(raiz, "no está en db/series.csv")
        print("ok  una función o un insumo inexistentes frenan el armado")

        # 7. Una división por cero frena el armado y la base anterior queda intacta.
        _escribir_derivadas(raiz, [_fila()])
        _construir(raiz, "2026-11-11")
        antes = _consulta(raiz, "SELECT COUNT(*) FROM observaciones")
        df = pd.read_csv(csv_maiz)
        df.loc[df["fecha"] == agosto, "maiz_ars_tn"] = 0
        df.to_csv(csv_maiz, index=False)
        try:
            _construir(raiz, "2026-12-01")
            raise AssertionError("debería haber fallado por la división por cero")
        except ValueError as e:
            assert "infinitos" in str(e), e
        assert _consulta(raiz, "SELECT COUNT(*) FROM observaciones") == antes
        print("ok  una división por cero frena el armado sin romper la base anterior")
    del build_db.modulo_derivadas._ratio_prueba


if __name__ == "__main__":
    main()
