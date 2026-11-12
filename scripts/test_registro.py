"""Pruebas del registro de estimaciones (SCRUM-44).

No corre X-13: usa un contexto de X-13 inventado. La prueba contra los
resultados de SCRUM-42, con X-13 de verdad, está en
scripts/prueba_registro_holdout.py.

Trabaja sobre archivos temporales: no toca data/registro_estimaciones.csv ni
data/bcr.db.

Uso, desde la raíz del repo:
    python scripts/test_registro.py
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_db  # noqa: E402
import registro  # noqa: E402
from error_iaca import calcular_variacion  # noqa: E402
from replica_x13 import cargar_series  # noqa: E402
from test_build_db import _copiar_repo  # noqa: E402

MES = pd.Period("2025-09", freq="M")
CTX = {"variante": "log", "spc": "IACA-BIODIESEL_L", "pronostico_x13": 110000.0,
       "estacional": 1.05, "filtrado_penultimo": 95000.0, "filtrado_ultimo": 98000.0}


def _produccion(hasta: pd.Period) -> dict[str, pd.Series]:
    return {k: s[s.index <= hasta] for k, s in cargar_series().items()}


def _reales() -> pd.DataFrame:
    filas = [(registro.SERIES[k], p.to_timestamp().strftime("%Y-%m-%d"), float(v), 0, "2026-11-05")
             for k, s in cargar_series().items() for p, v in s.items()]
    return pd.DataFrame(filas, columns=["serie_id", "mes_estimado", "valor", "provisorio", "fecha_descarga"])


def _registrar(ruta: Path, serie="biodiesel", mes=MES, pronostico=100000.0, **kw):
    return registro.registrar(serie, mes, "modelo_final", pronostico, {"modelo_elegido": "suma_contable"},
                              ruta=ruta, ruta_db=None, produccion=_produccion(mes - 1),
                              fecha_descarga_datos="2025-10-20", contexto=CTX,
                              fecha_corrida=kw.pop("fecha_corrida", "2025-10-20 10:00:00"), **kw)


def _falla(funcion, error, texto: str) -> None:
    try:
        funcion()
    except error as e:
        assert texto in str(e), f"mensaje inesperado: {e}"
    else:
        raise AssertionError(f"tenía que fallar con {error.__name__}")


def test_registrar_y_completar(ruta: Path) -> None:
    nuevas = _registrar(ruta)
    # Una fila del modelo y otra de la réplica del X-13, con la variación calculada.
    assert list(nuevas["modelo"]) == ["modelo_final", "x13_bcr"]
    assert list(nuevas["estimacion_id"]) == [1, 2]
    assert nuevas["pronostico"].tolist() == [100000.0, CTX["pronostico_x13"]]
    factor = 100 / cargar_series()["biodiesel"].loc["2013-01":"2013-12"].mean()
    _, esperada = calcular_variacion(100000.0, CTX, factor, "log")
    assert np.isclose(nuevas["variacion_pronosticada_pct"].iloc[0], esperada)
    assert nuevas["valor_real"].isna().all()

    # Maíz no entra al IACA: se registra sin variación ni fila del X-13.
    maiz = _registrar(ruta, serie="bioetanol_maiz", pronostico=50000.0)
    assert len(maiz) == 1 and maiz["variacion_pronosticada_pct"].isna().all()

    # Completar: real, error en producción y error en la variación.
    hechas = registro.completar(ruta=ruta, ruta_db=None, reales=_reales())
    assert len(hechas) == 3
    df = registro.leer_registro(ruta)
    real = float(cargar_series()["biodiesel"].loc[MES])
    fila = df.iloc[0]
    assert fila.valor_real == real and np.isclose(fila.error_produccion, 100000.0 - real)
    _, var_real = calcular_variacion(real, CTX, factor, "log")
    assert np.isclose(fila.variacion_con_real_pct, var_real)
    assert np.isclose(fila.error_variacion_pp, esperada - var_real)
    assert fila.acierto_signo == int(np.sign(esperada) == np.sign(var_real))
    assert pd.isna(df.iloc[2].error_variacion_pp) and pd.notna(df.iloc[2].error_produccion)

    # Una segunda pasada no cambia nada.
    antes = ruta.read_bytes()
    assert len(registro.completar(ruta=ruta, ruta_db=None, reales=_reales())) == 0
    assert ruta.read_bytes() == antes

    # El CSV conserva los números exactos (se lee igual que se escribió).
    assert registro.leer_registro(ruta).equals(df)


def test_controles(ruta: Path) -> None:
    _registrar(ruta)
    # La misma corrida dos veces.
    _falla(lambda: _registrar(ruta), ValueError, "Ya está registrada")
    # Un mes que no es el siguiente al último dato.
    _falla(lambda: registro.registrar("biodiesel", "2025-11", "m", 1.0, ruta=ruta, ruta_db=None,
                                      produccion=_produccion(MES - 1), fecha_descarga_datos="x",
                                      contexto=CTX), ValueError, "tiene que ser el siguiente")
    # Un mes que ya está publicado.
    _falla(lambda: registro.registrar("biodiesel", MES, "m", 1.0, ruta=ruta, ruta_db=None,
                                      produccion=_produccion(MES), fecha_descarga_datos="x",
                                      contexto=CTX), ValueError, "ya está publicado")
    # Solo agregar: cambiar o borrar una fila existente frena la escritura.
    df = registro.leer_registro(ruta)
    cambiada = df.copy()
    cambiada.loc[0, "pronostico"] = 1.0
    _falla(lambda: registro._controlar_solo_agrega(df, cambiada), RuntimeError, "pronostico")
    _falla(lambda: registro._controlar_solo_agrega(df, df.iloc[1:]), RuntimeError, "Se borrarían")
    # Un real ya completado tampoco se puede cambiar.
    registro.completar(ruta=ruta, ruta_db=None, reales=_reales())
    df = registro.leer_registro(ruta)
    cambiada = df.copy()
    cambiada.loc[0, "valor_real"] = 1.0
    _falla(lambda: registro._controlar_solo_agrega(df, cambiada), RuntimeError, "valor_real")


def _contribuciones(ruta: Path, estimacion_id: int, pronostico: float) -> None:
    """Escribe a mano (sin validar) contribuciones de una estimación que suman su pronóstico."""
    pd.DataFrame({"estimacion_id": estimacion_id, "factor": ["constante", "exportaciones"],
                  "aporte": [pronostico - 1000.0, 1000.0], "aporte_variacion_produccion_pp": [0.0, 1.5],
                  "nota": ["", "estimado"]}).to_csv(registro.ruta_contribuciones_de(ruta), index=False)


def test_base_y_excel(tmp: Path) -> None:
    """build_db carga los CSV del registro y de las contribuciones; registro.py mantiene las tablas al día; el Excel sale."""
    raiz = tmp / "repo"
    _copiar_repo(raiz)
    ruta = raiz / "data" / "registro_estimaciones.csv"
    _registrar(ruta)
    _contribuciones(ruta, 1, 100000.0)
    db = raiz / "data" / "bcr.db"
    build_db.actualizar(raiz, db, "2026-11-11")

    def tabla():
        con = sqlite3.connect(db)
        try:
            return pd.read_sql("SELECT * FROM registro_estimaciones ORDER BY estimacion_id", con)
        finally:
            con.close()

    t = tabla()
    assert len(t) == 2 and list(t.columns) == registro.COLUMNAS
    assert t["pronostico"].tolist() == registro.leer_registro(ruta)["pronostico"].tolist()
    con = sqlite3.connect(db)
    try:
        c = pd.read_sql("SELECT * FROM registro_contribuciones ORDER BY factor", con)
    finally:
        con.close()
    assert list(c.columns) == registro.COLUMNAS_CONTRIBUCIONES and c["aporte"].sum() == 100000.0

    # Al completar con la base indicada, la tabla se actualiza sin rearmar.
    registro.completar(ruta=ruta, ruta_db=db, reales=_reales())
    assert tabla()["valor_real"].notna().all()

    # Contribuciones de una estimación que no está en el registro hacen fallar el armado.
    _contribuciones(ruta, 99, 1.0)
    _falla(lambda: build_db.reconstruir(raiz, db), ValueError, "registro_contribuciones")
    _contribuciones(ruta, 1, 100000.0)

    # Un CSV con una serie que no existe hace fallar el armado.
    df = registro.leer_registro(ruta)
    df.loc[1, "serie_id"] = "no_existe"
    df.to_csv(ruta, index=False)
    _falla(lambda: build_db.reconstruir(raiz, db), ValueError, "registro_estimaciones")

    # Excel con las cuatro hojas. El mes se corrió dos veces: en "registro" están
    # las dos corridas y en "ultima_por_mes" solo la última.
    ruta.unlink()
    _registrar(ruta, pronostico=100000.0)
    _registrar(ruta, pronostico=105000.0, fecha_corrida="2025-10-21 09:00:00")
    _contribuciones(ruta, 3, 105000.0)
    salida = registro.exportar_excel(ruta, tmp / "registro.xlsx")
    hojas = pd.read_excel(salida, sheet_name=None)
    assert list(hojas) == ["ultima_por_mes", "registro", "contribuciones", "columnas"]
    assert len(hojas["registro"]) == 4
    ultima = hojas["ultima_por_mes"]
    assert len(ultima) == 2 and (ultima["fecha_corrida"] == "2025-10-21 09:00:00").all()
    assert ultima.loc[ultima["modelo"] == "modelo_final", "pronostico"].tolist() == [105000.0]
    columnas = hojas["columnas"]
    assert set(columnas.loc[columnas["hoja"] != "contribuciones", "columna"]) == set(registro.COLUMNAS)
    # Contribuciones: el aviso de que los puntos son de producción y la tabla abajo.
    aviso = pd.read_excel(salida, sheet_name="contribuciones", header=None, nrows=1).iloc[0, 0]
    assert "PRODUCCIÓN" in aviso and "No son puntos de la variación del IACA" in aviso
    contrib = pd.read_excel(salida, sheet_name="contribuciones", header=registro.FILA_TABLA_CONTRIBUCIONES)
    assert list(contrib.columns) == list(registro.DESCRIPCIONES_CONTRIBUCIONES)
    assert contrib["aporte"].sum() == 105000.0 and (contrib["estimacion_id"] == 3).all()
    assert (contrib["serie_id"] == "produccion_biodiesel_tn").all()


def test_primer_dato_publicado(tmp: Path) -> None:
    """completar usa la primera versión del mes, aunque después la hayan revisado."""
    raiz = tmp / "repo"
    _copiar_repo(raiz)
    db = raiz / "data" / "bcr.db"
    build_db.actualizar(raiz, db, "2026-11-11")
    ruta = raiz / "data" / "registro_estimaciones.csv"
    _registrar(ruta)

    # La Secretaría revisa septiembre 2025 y se vuelve a armar la base.
    csv = raiz / "data" / "produccion_biodiesel.csv"
    datos = pd.read_csv(csv)
    fila = pd.to_datetime(datos["fecha"]).dt.to_period("M") == MES
    original = float(datos.loc[fila, "produccion_tn"].iloc[0])
    datos.loc[fila, "produccion_tn"] = original + 1000
    datos.to_csv(csv, index=False)
    build_db.actualizar(raiz, db, "2026-11-20")

    # La base tiene el dato revisado como última versión...
    produccion, _ = registro.produccion_en_base(db)
    assert produccion["biodiesel"].loc[MES] == original + 1000

    # ...pero el registro se completa con el primero que se publicó.
    registro.completar(ruta=ruta, ruta_db=db)
    df = registro.leer_registro(ruta)
    assert (df["valor_real"] == original).all()
    assert (df["fecha_real"] == "2026-11-11").all()


def test_sin_base(tmp: Path) -> None:
    """Sin base y sin datos a mano, un mensaje claro en lugar de un TypeError."""
    ruta = tmp / "registro.csv"
    _registrar(ruta)
    _falla(lambda: registro.completar(ruta=ruta, ruta_db=None), ValueError, "reales al completar")
    _falla(lambda: registro.registrar("biodiesel", "2025-09", "m", 1.0, ruta=ruta, ruta_db=None),
           ValueError, "produccion y fecha_descarga_datos")
    _falla(lambda: registro.completar(ruta=ruta, ruta_db=tmp / "no_existe.db"),
           FileNotFoundError, "build_db.py")


def main() -> None:
    pruebas = [test_registrar_y_completar, test_controles, test_base_y_excel,
               test_primer_dato_publicado, test_sin_base]
    con_carpeta = {test_base_y_excel, test_primer_dato_publicado, test_sin_base}
    for prueba in pruebas:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            prueba(tmp if prueba in con_carpeta else tmp / "registro.csv")
        print(f"ok  {prueba.__name__}")
    print("Todas las pruebas pasaron.")


if __name__ == "__main__":
    main()
