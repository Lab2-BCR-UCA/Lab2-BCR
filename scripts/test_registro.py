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


def test_base_y_excel(tmp: Path) -> None:
    """build_db carga el CSV del registro; registro.py mantiene la tabla al día; el Excel sale."""
    raiz = tmp / "repo"
    _copiar_repo(raiz)
    ruta = raiz / "data" / "registro_estimaciones.csv"
    _registrar(ruta)
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

    # Al completar con la base indicada, la tabla se actualiza sin rearmar.
    registro.completar(ruta=ruta, ruta_db=db, reales=_reales())
    assert tabla()["valor_real"].notna().all()

    # Un CSV con una serie que no existe hace fallar el armado.
    df = registro.leer_registro(ruta)
    df.loc[1, "serie_id"] = "no_existe"
    df.to_csv(ruta, index=False)
    _falla(lambda: build_db.reconstruir(raiz, db), ValueError, "registro_estimaciones")

    # Excel con las dos hojas.
    ruta.unlink()
    _registrar(ruta)
    salida = registro.exportar_excel(ruta, tmp / "registro.xlsx")
    hojas = pd.read_excel(salida, sheet_name=None)
    assert set(hojas) == {"registro", "columnas"}
    assert len(hojas["registro"]) == 2
    assert set(hojas["columnas"]["columna"]) == set(registro.COLUMNAS)


def main() -> None:
    pruebas = [test_registrar_y_completar, test_controles, test_base_y_excel]
    for prueba in pruebas:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            prueba(tmp if prueba is test_base_y_excel else tmp / "registro.csv")
        print(f"ok  {prueba.__name__}")
    print("Todas las pruebas pasaron.")


if __name__ == "__main__":
    main()
