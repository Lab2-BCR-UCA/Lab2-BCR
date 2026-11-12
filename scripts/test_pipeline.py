"""Pruebas del pipeline de estimación (SCRUM-38).

- Simula la corrida en meses del holdout y compara contra lo que guardó la
  evaluación: el pronóstico contra ``results/modelo_final_predicciones.csv`` y
  la variación del IACA contra ``results/iaca_holdout_detalle.csv``. Si
  coinciden, el pipeline estima igual que el modelo que se evaluó.
- Controla que frene si faltan las ventas de gasoil o las exportaciones del mes.
- Controla las contribuciones: solo las del modelo final, sin la fila
  ``total``, que sumen el pronóstico del registro, que solo se agreguen y que
  si algo no cierra no se escriba ninguno de los dos archivos.

Corre X-13 (dos series por mes): tarda alrededor de un minuto y medio.

Uso, desde la raíz del repo, con la base armada:
    python scripts/test_pipeline.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pipeline  # noqa: E402
import registro  # noqa: E402
from build_db import leer_dataset  # noqa: E402
from construir_features import OBJETIVOS  # noqa: E402

RESULTS = Path(__file__).resolve().parents[1] / "results"
# Un mes común, uno con la exportación oculta por INDEC y el último del holdout.
MESES = ["2025-11", "2026-07", "2026-09"]
NOMBRE_DE_ID = {v: k for k, v in OBJETIVOS.items()}


def test_simulacion_coincide_con_la_evaluacion():
    pred = pd.read_csv(RESULTS / "modelo_final_predicciones.csv")
    iaca = pd.read_csv(RESULTS / "iaca_holdout_detalle.csv")
    for mes in MESES:
        pipeline.correr(simular=mes)
        reg = pd.read_csv(pipeline.CARPETA_SIMULACION / f"registro_{mes}.csv")
        for _, fila in reg.iterrows():
            serie = NOMBRE_DE_ID[fila["serie_id"]]
            if fila["modelo"] == "modelo_final":
                esperado = pred[(pred["serie"] == serie) & pred["fecha"].str.startswith(mes)]["prediccion"]
                assert np.isclose(fila["pronostico"], esperado.iloc[0], rtol=1e-9), (mes, serie)
            if pd.notna(fila["variacion_pronosticada_pct"]):
                e = iaca[(iaca["serie"] == serie) & (iaca["modelo"] == fila["modelo"]) & (iaca["fecha"] == mes)]
                assert len(e) == 1, (mes, serie, fila["modelo"])
                assert np.isclose(fila["pronostico"], e["produccion_pronosticada"].iloc[0], rtol=1e-9)
                assert np.isclose(fila["variacion_pronosticada_pct"], e["variacion_pronosticada_pct"].iloc[0],
                                  atol=1e-9), (mes, serie, fila["modelo"])
        contrib = registro.leer_contribuciones(pipeline.CARPETA_SIMULACION / f"contribuciones_{mes}.csv")
        assert list(contrib.columns) == registro.COLUMNAS_CONTRIBUCIONES
        assert "total" not in set(contrib["factor"]), mes
        final = reg[reg["modelo"] == "modelo_final"].set_index("estimacion_id")["pronostico"]
        suma = contrib.groupby(contrib["estimacion_id"].astype(int))["aporte"].sum()
        assert sorted(suma.index) == sorted(final.index), (mes, "solo y todas las del modelo final")
        assert np.allclose(suma.loc[final.index], final, rtol=1e-9), mes
        oculto = contrib[(contrib["factor"] == "exportaciones") & (contrib["nota"] != "")]
        assert (len(oculto) > 0) == (mes == "2026-07"), (mes, "aviso de exportaciones estimadas")
    print(f"ok  la simulación da el mismo pronóstico y la misma variación del IACA que la evaluación "
          f"({', '.join(MESES)})")


def test_frena_si_faltan_datos_del_mes():
    base = leer_dataset()
    mes = pd.Period("2026-09", freq="M")
    assert pipeline.faltantes_del_mes(base, mes) == []
    sin_gasoil = base.copy()
    sin_gasoil.loc[pd.Timestamp("2026-09-01"), "ventas_gasoil_total_m3"] = np.nan
    faltan = pipeline.faltantes_del_mes(sin_gasoil, mes)
    assert len(faltan) == 1 and "gasoil" in faltan[0]
    assert len(pipeline.faltantes_del_mes(base, mes + 1)) == 2
    print("ok  frena si todavía no están las ventas de gasoil o las exportaciones del mes")


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
    test_contribuciones()
    test_simulacion_coincide_con_la_evaluacion()
    print("\nTodas las pruebas del pipeline pasaron.")
