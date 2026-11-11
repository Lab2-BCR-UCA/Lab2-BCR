"""Pruebas del pipeline de estimación (SCRUM-38).

- Simula la corrida en meses del holdout y compara contra lo que guardó la
  evaluación: el pronóstico contra ``results/modelo_final_predicciones.csv`` y
  la variación del IACA contra ``results/iaca_holdout_detalle.csv``. Si
  coinciden, el pipeline estima igual que el modelo que se evaluó.
- Controla que frene si faltan las ventas de gasoil o las exportaciones del mes.
- Controla que las contribuciones solo se agreguen.

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
        contrib = pd.read_csv(pipeline.CARPETA_SIMULACION / f"contribuciones_{mes}.csv", keep_default_na=False)
        total = contrib[contrib["factor"] == "total"].set_index("estimacion_id")["aporte"]
        final = reg[reg["modelo"] == "modelo_final"].set_index("estimacion_id")["pronostico"]
        assert np.allclose(total.loc[final.index], final, rtol=1e-9), mes
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


def test_contribuciones_solo_se_agregan():
    tabla = pd.DataFrame({"fecha": "2026-09", "modelo": "suma_contable", "factor": ["a", "total"],
                          "aporte": [1.0, 1.0], "aporte_variacion_produccion_pp": [0.5, 0.5],
                          "nota": ["", ""]})
    with tempfile.TemporaryDirectory() as tmp:
        ruta = Path(tmp) / "c.csv"
        pipeline.guardar_contribuciones({"biodiesel": tabla}, {"biodiesel": 1},
                                        {"biodiesel": "suma_contable"}, ruta)
        pipeline.guardar_contribuciones({"biodiesel": tabla}, {"biodiesel": 2},
                                        {"biodiesel": "suma_contable"}, ruta)
        assert list(pd.read_csv(ruta)["estimacion_id"]) == [1, 1, 2, 2]
        antes = ruta.read_bytes()
        try:
            pipeline.guardar_contribuciones({"biodiesel": tabla}, {"biodiesel": 2},
                                            {"biodiesel": "suma_contable"}, ruta)
        except RuntimeError:
            pass
        else:
            raise AssertionError("debió frenar por estimación repetida")
        assert ruta.read_bytes() == antes
    print("ok  las contribuciones solo se agregan y no se repiten")


if __name__ == "__main__":
    test_frena_si_faltan_datos_del_mes()
    test_contribuciones_solo_se_agregan()
    test_simulacion_coincide_con_la_evaluacion()
    print("\nTodas las pruebas del pipeline pasaron.")
