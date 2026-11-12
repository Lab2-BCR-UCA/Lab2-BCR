"""Pruebas del pipeline de estimación (SCRUM-38).

- Simula la corrida en meses del holdout y compara contra lo que guardó la
  evaluación: el pronóstico contra ``results/modelo_final_predicciones.csv`` y
  la variación del IACA contra ``results/iaca_holdout_detalle.csv``. Si
  coinciden, el pipeline estima igual que el modelo que se evaluó.

  Para que no dependa de lo que se haya descargado después, la simulación arma
  aparte, en ``results/simulacion/base_evaluacion/``, una base solo con las
  copias de ``data/snapshots/`` hasta ``FECHA_DATOS_EVALUACION`` (la versión de
  los datos con que se corrió la evaluación). No toca ``data/bcr.db``.
- Controla que frene si faltan las ventas de gasoil o las exportaciones del mes,
  y antes del día 28 del mes siguiente, completando igual los reales.
- Controla los reintentos de las descargas y los avisos de INDEC (sin red).
- Controla las contribuciones: solo las del modelo final, sin la fila
  ``total``, que sumen el pronóstico del registro, que solo se agreguen y que
  si algo no cierra no se escriba ninguno de los dos archivos.

Corre X-13 (dos series por mes): tarda alrededor de un minuto y medio.

Uso, desde la raíz del repo (sirve cualquier clon; no hace falta que la base
esté al día):
    python scripts/test_pipeline.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_db  # noqa: E402
import pipeline  # noqa: E402
import registro  # noqa: E402
from build_db import leer_dataset  # noqa: E402
from construir_features import OBJETIVOS  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
RESULTS = RAIZ / "results"
# Versión de los datos con que se corrió la evaluación (SCRUM-34, 42 y 63): la
# última descarga que usaron results/modelo_final_predicciones.csv y
# results/iaca_holdout_detalle.csv. Si se rehace la evaluación con datos más
# nuevos, actualizar esta fecha.
FECHA_DATOS_EVALUACION = "2026-11-05"
# Un mes común, uno con la exportación oculta por INDEC y el último del holdout.
MESES = ["2025-11", "2026-07", "2026-09"]
NOMBRE_DE_ID = {v: k for k, v in OBJETIVOS.items()}


_BASE_EVALUACION: Path | None = None


def base_de_la_evaluacion() -> Path:
    """Base con los datos de la evaluación, armada una sola vez por corrida de las pruebas.

    Queda en ``results/simulacion/base_evaluacion/`` (no se versiona) y no se
    borra al terminar: en Windows, SQLite puede tener el archivo abierto todavía.
    """
    global _BASE_EVALUACION
    if _BASE_EVALUACION is None:
        _BASE_EVALUACION = armar_base_de_la_evaluacion(pipeline.CARPETA_SIMULACION / "base_evaluacion")
    return _BASE_EVALUACION


def armar_base_de_la_evaluacion(destino: Path, fecha: str = FECHA_DATOS_EVALUACION) -> Path:
    """Arma en ``destino`` una base solo con las copias de ``data/snapshots/`` hasta ``fecha``.

    Es la base que tenía la evaluación: lo que se haya descargado después no
    cambia la simulación. Borra antes lo que hubiera en ``destino``. Devuelve
    la ruta de la base.
    """
    shutil.rmtree(destino, ignore_errors=True)
    raiz = Path(destino) / "repo"
    shutil.copytree(RAIZ / "db", raiz / "db")
    (raiz / "data" / "snapshots").mkdir(parents=True)
    shutil.copy(RAIZ / "data" / "disponibilidad_variables.csv", raiz / "data")
    manifiesto = pd.read_csv(RAIZ / "data" / "snapshots" / "manifiesto.csv", dtype=str, keep_default_na=False)
    hasta = manifiesto[manifiesto["fecha_descarga"] <= fecha]
    faltan = [a for a in hasta["archivo_snapshot"] if not (RAIZ / "data" / "snapshots" / a).exists()]
    if faltan:
        raise AssertionError(f"Faltan copias de los datos de la evaluación en data/snapshots/: {faltan}. "
                             "Correr la prueba en un clon del repo con data/snapshots/ completo.")
    for a in hasta["archivo_snapshot"]:
        (raiz / "data" / "snapshots" / a).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(RAIZ / "data" / "snapshots" / a, raiz / "data" / "snapshots" / a)
    hasta.to_csv(raiz / "data" / "snapshots" / "manifiesto.csv", index=False)
    db = raiz / "data" / "bcr.db"
    build_db.reconstruir(raiz, db)
    return db


def _coincide(obtenido: float, esperado: float, que: str, tol: dict) -> None:
    """Igual que la evaluación, o un mensaje que explica la causa más probable."""
    if not np.isclose(obtenido, esperado, **tol):
        raise AssertionError(
            f"{que}: el pipeline da {obtenido:,.4f} y la evaluación guardó {esperado:,.4f}. "
            f"La simulación usa los datos hasta el {FECHA_DATOS_EVALUACION}; si cambió el código de un "
            "modelo, o se rehizo la evaluación con datos más nuevos sin actualizar FECHA_DATOS_EVALUACION, "
            "esta prueba tiene que fallar. Ver docs/pipeline.md, sección 4.")


def test_simulacion_coincide_con_la_evaluacion():
    pred = pd.read_csv(RESULTS / "modelo_final_predicciones.csv")
    iaca = pd.read_csv(RESULTS / "iaca_holdout_detalle.csv")
    db = base_de_la_evaluacion()
    with _reemplazos(pipeline, leer_dataset=lambda: leer_dataset(db)):
        for mes in MESES:
            _simular_y_comparar(mes, pred, iaca)
    print(f"ok  la simulación da el mismo pronóstico y la misma variación del IACA que la evaluación "
          f"({', '.join(MESES)}; datos hasta el {FECHA_DATOS_EVALUACION})")


def _simular_y_comparar(mes: str, pred: pd.DataFrame, iaca: pd.DataFrame) -> None:
    pipeline.correr(simular=mes)
    reg = pd.read_csv(pipeline.CARPETA_SIMULACION / f"registro_{mes}.csv")
    for _, fila in reg.iterrows():
        serie = NOMBRE_DE_ID[fila["serie_id"]]
        if fila["modelo"] == "modelo_final":
            esperado = pred[(pred["serie"] == serie) & pred["fecha"].str.startswith(mes)]["prediccion"]
            _coincide(fila["pronostico"], esperado.iloc[0], f"Pronóstico de {serie} {mes}", {"rtol": 1e-9})
        if pd.notna(fila["variacion_pronosticada_pct"]):
            e = iaca[(iaca["serie"] == serie) & (iaca["modelo"] == fila["modelo"]) & (iaca["fecha"] == mes)]
            assert len(e) == 1, (mes, serie, fila["modelo"])
            _coincide(fila["pronostico"], e["produccion_pronosticada"].iloc[0],
                      f"Pronóstico de {fila['modelo']} para {serie} {mes}", {"rtol": 1e-9})
            _coincide(fila["variacion_pronosticada_pct"], e["variacion_pronosticada_pct"].iloc[0],
                      f"Variación del IACA de {fila['modelo']} para {serie} {mes}", {"atol": 1e-9})
    contrib = registro.leer_contribuciones(pipeline.CARPETA_SIMULACION / f"contribuciones_{mes}.csv")
    assert list(contrib.columns) == registro.COLUMNAS_CONTRIBUCIONES
    assert "total" not in set(contrib["factor"]), mes
    final = reg[reg["modelo"] == "modelo_final"].set_index("estimacion_id")["pronostico"]
    suma = contrib.groupby(contrib["estimacion_id"].astype(int))["aporte"].sum()
    assert sorted(suma.index) == sorted(final.index), (mes, "solo y todas las del modelo final")
    assert np.allclose(suma.loc[final.index], final, rtol=1e-9), mes
    oculto = contrib[(contrib["factor"] == "exportaciones") & (contrib["nota"] != "")]
    assert (len(oculto) > 0) == (mes == "2026-07"), (mes, "aviso de exportaciones estimadas")


def test_frena_si_faltan_datos_del_mes():
    base = leer_dataset(base_de_la_evaluacion())
    mes = pd.Period("2026-09", freq="M")
    assert pipeline.faltantes_del_mes(base, mes) == []
    sin_gasoil = base.copy()
    sin_gasoil.loc[pd.Timestamp("2026-09-01"), "ventas_gasoil_total_m3"] = np.nan
    faltan = pipeline.faltantes_del_mes(sin_gasoil, mes)
    assert len(faltan) == 1 and "gasoil" in faltan[0]
    assert len(pipeline.faltantes_del_mes(base, mes + 1)) == 2
    print("ok  frena si todavía no están las ventas de gasoil o las exportaciones del mes")


@contextmanager
def _reemplazos(modulo, **nuevos):
    """Reemplaza atributos de un módulo mientras dura el bloque."""
    viejos = {k: getattr(modulo, k) for k in nuevos}
    for k, v in nuevos.items():
        setattr(modulo, k, v)
    try:
        yield
    finally:
        for k, v in viejos.items():
            setattr(modulo, k, v)


def test_frena_antes_del_28_y_completa_igual():
    """Antes del 28 frena sin procesar INDEC ni estimar, pero arma la base y completa los reales."""
    llamadas = []
    falsos = dict(
        ultimo_mes_produccion=lambda: pd.Period("2026-09", freq="M"),
        procesar_indec=lambda *a, **k: llamadas.append("indec"),
        armar_base=lambda: llamadas.append("base"),
        leer_dataset=lambda: llamadas.append("leer") or leer_dataset(),
        estimar=lambda *a, **k: llamadas.append("estimar"),
    )
    completar = lambda: llamadas.append("completar") or pd.DataFrame()  # noqa: E731
    assert pipeline.fecha_para_correr(pd.Period("2026-10", freq="M")) == date(2026, 11, 28)
    with _reemplazos(pipeline, **falsos), _reemplazos(registro, completar=completar):
        # 27/11: todavía no se puede estimar octubre.
        _falla(lambda: pipeline.correr(sin_descargas=True, hoy=date(2026, 11, 27)), "desde el 28/11/2026")
        assert llamadas == ["base", "leer", "completar"], llamadas
        assert isinstance(_error(lambda: pipeline.correr(sin_descargas=True, hoy=date(2026, 11, 27))),
                          pipeline.TodaviaNoSePuedeEstimar)
        # 28/11 en adelante: procesa INDEC; si faltan datos, completa antes de frenar.
        llamadas.clear()
        with _reemplazos(pipeline, faltantes_del_mes=lambda *a: ["ventas de gasoil"]):
            _falla(lambda: pipeline.correr(sin_descargas=True, hoy=date(2026, 11, 28)), "ventas de gasoil")
        assert llamadas == ["indec", "base", "leer", "completar"], llamadas
    print("ok  antes del 28 frena con la fecha para volver a correr y completa igual los reales")


def test_descargas_reintenta():
    intentos = []

    def correr_falso(respuestas):
        def f(script):
            intentos.append(script[0])
            return respuestas.pop(0) if respuestas else (True, "")
        return f

    conexion = (False, "requests.exceptions.ConnectionError: Max retries exceeded")
    with _reemplazos(pipeline.time, sleep=lambda s: None):
        # Falla dos veces y a la tercera anda.
        with _reemplazos(pipeline, _correr=correr_falso([conexion, conexion])):
            assert pipeline.descargar() == []
        assert intentos.count(pipeline.DESCARGAS[0][1][0]) == 3
        # La producción no responde: tres intentos, mensaje claro y no sigue con las demás.
        intentos.clear()
        with _reemplazos(pipeline, _correr=correr_falso([conexion] * 3)):
            assert pipeline.descargar() == [pipeline.DESCARGAS[0][0]]
        assert len(intentos) == 3
        ok, mensaje = None, None
        with _reemplazos(pipeline, _correr=correr_falso([conexion] * 3)):
            ok, mensaje = pipeline._descargar_una("x", ["x.py"])
        assert not ok and "no responde" in mensaje and "No es un error del programa" in mensaje
        # Un error del programa no se disfraza de sitio caído.
        error = (False, "KeyError: 'produccion_tn'")
        with _reemplazos(pipeline, _correr=correr_falso([error] * 3)):
            ok, mensaje = pipeline._descargar_una("x", ["x.py"])
        assert not ok and mensaje == "KeyError: 'produccion_tn'"
        # Si la producción no se puede bajar porque el sitio no responde, no es un error:
        # NO SE ESTIMÓ (TodaviaNoSePuedeEstimar). Si es otra cosa, ERROR (RuntimeError).
        with _reemplazos(pipeline, _correr=correr_falso([conexion] * 3)):
            e = _error(lambda: pipeline.correr())
        assert type(e) is pipeline.TodaviaNoSePuedeEstimar and "no responde" in str(e), e
        with _reemplazos(pipeline, _correr=correr_falso([error] * 3)):
            e = _error(lambda: pipeline.correr())
        assert type(e) is RuntimeError and "produccion_tn" in str(e), e
    print("ok  las descargas se reintentan y, si el sitio no responde, lo dice")


def test_avisos_de_indec():
    mes = pd.Period("2026-10", freq="M")
    corridas = []
    with tempfile.TemporaryDirectory() as tmp, \
            _reemplazos(pipeline, CARPETA_INDEC=Path(tmp), RAIZ=Path(tmp).parent,
                        _correr=lambda s: corridas.append(s) or (True, "")):
        # Antes del 20 de noviembre INDEC no publicó octubre: aviso, no FALLÓ.
        assert pipeline.procesar_indec(mes, date(2026, 11, 15)) is False
        # Sin archivo del año.
        assert pipeline.procesar_indec(mes, date(2026, 11, 28)) is False
        # Archivo bajado el 10/11, antes de que se publicara octubre: viejo.
        def archivo(dia):
            ms = int(pd.Timestamp(f"2026-11-{dia} 12:00", tz="America/Argentina/Buenos_Aires").timestamp() * 1000)
            ruta = Path(tmp) / f"indec_38260000_2026_{ms}.csv"
            ruta.write_text("x")
            return ruta
        viejo = archivo("10")
        assert pipeline.procesar_indec(mes, date(2026, 11, 28)) is False
        assert corridas == []
        viejo.unlink()
        archivo("21")
        assert pipeline.procesar_indec(mes, date(2026, 11, 28)) is True
        assert len(corridas) == 1 and corridas[0][-1] == "2026-10"
    print("ok  INDEC: distingue 'todavía no publicó' de 'el CSV es viejo'")


def _error(funcion):
    try:
        funcion()
    except Exception as e:  # noqa: BLE001
        return e
    raise AssertionError("tenía que fallar")


def _falla(funcion, texto: str) -> None:
    try:
        funcion()
    except (ValueError, RuntimeError) as e:
        assert texto in str(e), f"mensaje inesperado: {e}"
    else:
        raise AssertionError(f"tenía que fallar ({texto})")


def test_contribuciones():
    """registro.agregar: valida todo antes de escribir y solo agrega. Sin X-13 (maíz no va al IACA)."""
    serie = "bioetanol_maiz"
    produccion = {serie: pd.Series([10.0, 11.0], index=pd.period_range("2026-07", periods=2, freq="M"))}

    def preparar(mes, pronostico, anterior, modelo="modelo_final"):
        corrida = f"2026-11-11 10:00:{len(anterior) if anterior is not None else 0:02d}"
        return registro.preparar(serie, mes, modelo, pronostico, anterior=anterior, ruta_db=None,
                                 produccion=produccion, fecha_descarga_datos="2026-11-11",
                                 fecha_corrida=corrida)

    def tabla(i, aportes, factores=None):
        factores = factores or [f"f{k}" for k in range(len(aportes))]
        return pd.DataFrame({"estimacion_id": i, "factor": factores, "aporte": aportes,
                             "aporte_variacion_produccion_pp": [1.0] * len(aportes),
                             "nota": [""] * len(aportes)})

    with tempfile.TemporaryDirectory() as tmp:
        ruta = Path(tmp) / "registro_estimaciones.csv"
        ruta_c = Path(tmp) / "registro_contribuciones.csv"
        nuevas = preparar("2026-09", 100.0, None)
        registro.agregar(nuevas, tabla(1, [60.0, 40.0]), ruta=ruta, ruta_db=None)
        assert ruta_c.exists(), "las contribuciones van al lado del registro"
        assert list(registro.leer_contribuciones(ruta_c)["aporte"]) == [60.0, 40.0]
        antes = (ruta.read_bytes(), ruta_c.read_bytes())

        def sin_cambios():
            assert (ruta.read_bytes(), ruta_c.read_bytes()) == antes, "no tenía que escribir nada"
            assert not ruta.with_suffix(".tmp").exists() and not ruta_c.with_suffix(".tmp").exists()

        anterior = registro.leer_registro(ruta)
        otra = preparar("2026-09", 200.0, anterior)  # segunda corrida del mismo mes: id 2
        casos = [
            ("no suman el pronóstico", tabla(2, [150.0, 40.0])),
            ("'total'", tabla(2, [150.0, 50.0, 200.0], ["a", "b", "total"])),
            ("repetidos", tabla(2, [150.0, 50.0], ["a", "a"])),
            ("no están en el registro", tabla(3, [200.0])),
            ("Faltan o sobran", pd.concat([tabla(2, [200.0]), tabla(1, [100.0])], ignore_index=True)),
            ("vacíos", tabla(2, [200.0, float("nan")])),
        ]
        for texto, contrib in casos:
            _falla(lambda: registro.agregar(otra, contrib, ruta=ruta, ruta_db=None), texto)
            sin_cambios()
        # Una fila que no es del modelo final no lleva contribuciones.
        x13 = preparar("2026-09", 300.0, anterior, modelo="x13_bcr")
        _falla(lambda: registro.agregar(x13, tabla(2, [300.0]), ruta=ruta, ruta_db=None), "modelo final")
        sin_cambios()
        # La misma estimación dos veces.
        _falla(lambda: registro.agregar(nuevas, tabla(1, [100.0]), ruta=ruta, ruta_db=None), "ya están")
        sin_cambios()

        # La corrida válida se agrega sin tocar lo anterior.
        registro.agregar(otra, tabla(2, [150.0, 50.0]), ruta=ruta, ruta_db=None)
        assert ruta.read_bytes().startswith(antes[0])
        c = registro.leer_contribuciones(ruta_c)
        assert list(c["estimacion_id"]) == [1, 1, 2, 2] and list(c["aporte"]) == [60.0, 40.0, 150.0, 50.0]
        assert ruta_c.read_bytes().startswith(antes[1])
    print("ok  contribuciones: solo modelo final, sin 'total', suman el pronóstico, solo se agregan "
          "y si algo falla no se escribe ningún archivo")


if __name__ == "__main__":
    test_frena_si_faltan_datos_del_mes()
    test_frena_antes_del_28_y_completa_igual()
    test_descargas_reintenta()
    test_avisos_de_indec()
    test_contribuciones()
    test_simulacion_coincide_con_la_evaluacion()
    print("\nTodas las pruebas del pipeline pasaron.")
