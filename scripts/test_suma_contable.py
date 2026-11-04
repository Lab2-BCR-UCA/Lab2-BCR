"""Pruebas de la suma contable (SCRUM-60). Uso: python scripts/test_suma_contable.py"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_db import leer_dataset  # noqa: E402
from suma_contable import ModeloSumaContable, piso_practico, serie_biodiesel  # noqa: E402

MES = pd.Period("2024-05", freq="M")


def _prediccion(base):
    serie = serie_biodiesel(leer_dataset())
    return ModeloSumaContable(base).fit(serie[serie.index < MES]).predict()


def test_componentes_suman():
    base = leer_dataset()
    serie = serie_biodiesel(base)
    modelo = ModeloSumaContable(base).fit(serie[serie.index < MES])
    assert np.isclose(sum(modelo.contribuciones().values()), modelo.predict())


def test_sin_leakage():
    """Cambiar lo que todavía no se conoce al estimar no mueve la predicción."""
    base = leer_dataset()
    original = _prediccion(base)
    fecha = MES.to_timestamp()
    sucia = base.copy()
    for col in ("produccion_biodiesel_tn", "biodiesel_ventas_corte_tn",
                "biodiesel_otras_ventas_tn", "biodiesel_exportaciones_tn"):
        sucia.loc[fecha, col] = 9e9
    futuro = base.index > fecha
    columnas = ["ventas_gasoil_total_m3", "expo_indec_tn", "biodiesel_ventas_corte_tn"]
    sucia.loc[futuro, columnas] = 9e9
    assert np.isclose(_prediccion(sucia), original)


def test_piso_es_variacion_de_stock():
    base = pd.DataFrame({
        "produccion_biodiesel_tn": [100.0, 100.0],
        "biodiesel_ventas_corte_tn": [50.0, 60.0],
        "biodiesel_exportaciones_tn": [40.0, 40.0],
        "biodiesel_otras_ventas_tn": [5.0, 10.0],
    }, index=pd.to_datetime(["2022-01-01", "2022-02-01"]))
    piso = piso_practico(base, {"v": ("2022-01", "2022-02")})
    assert piso.loc[0, "MAE_piso_tn"] == 7.5  # |−5| y |+10|


if __name__ == "__main__":
    test_componentes_suman()
    test_sin_leakage()
    test_piso_es_variacion_de_stock()
    print("OK")
