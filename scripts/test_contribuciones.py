"""Pruebas de las contribuciones (SCRUM-35).

Las contribuciones tienen que reconstruir exactamente la predicción que guardó
el protocolo, y los puntos de variación tienen que sumar la variación estimada.

Uso: python scripts/test_contribuciones.py
"""

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from contribuciones import MODELOS_EN, TOTAL, explicar, grupo_de  # noqa: E402
from elastic_net import MODELOS, _base, armar_X  # noqa: E402

RESULTS = Path(__file__).resolve().parent.parent / "results"
MESES = ["2022-10", "2024-03", "2026-08"]   # dos del backtest y uno del holdout
ARCHIVO = {"suma_contable": "suma_contable_predicciones.csv"}
BASE = _base()


def _guardada(modelo: str, mes: str) -> float:
    archivo = ARCHIVO.get(modelo, "elastic_net_predicciones.csv")
    p = pd.read_csv(RESULTS / archivo)
    fila = p[(p["modelo"] == modelo) & (p["fecha"].str.startswith(mes))]
    assert len(fila) == 1, (modelo, mes, len(fila))
    return float(fila["prediccion"].iloc[0])


def test_reconstruye_prediccion_del_protocolo():
    for modelo in ["suma_contable", *MODELOS_EN, TOTAL]:
        for mes in MESES:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                t = explicar(modelo, mes, BASE)
            cuerpo = t[t["factor"] != "total"]
            guardada = _guardada(modelo, mes)
            assert np.isclose(cuerpo["aporte"].sum(), guardada, rtol=1e-9, atol=1e-4), \
                (modelo, mes, cuerpo["aporte"].sum(), guardada)
            assert np.isclose(cuerpo["aporte_variacion_produccion_pp"].sum(),
                              100 * (guardada / t.attrs["real_anterior"] - 1), atol=1e-9)
            assert np.isclose(t.attrs["prediccion"], guardada, rtol=1e-9, atol=1e-4)
    print("ok  aportes = predicción guardada y puntos = variación estimada "
          f"(5 modelos x {len(MESES)} meses, incluido el holdout)")


def test_todas_las_variables_tienen_factor():
    mes = pd.Period("2025-06", "M")
    for nombre in ("biodiesel_con_contables_sin_eventos", "bioetanol_maiz", "bioetanol_cana"):
        X, _ = armar_X(MODELOS[nombre], mes, BASE)
        for var in list(X.columns) + [f"missingindicator_{c}" for c in X.columns]:
            grupo_de(var, MODELOS[nombre].objetivo)
    try:
        grupo_de("variable_inventada", "biodiesel")
    except KeyError:
        pass
    else:
        raise AssertionError("una variable sin factor debió frenar")
    print("ok  todas las variables de los modelos elegidos tienen factor; una desconocida frena")


def test_suma_contable_otras_ventas_no_mueve_la_variacion():
    t = explicar("suma_contable", "2026-08", BASE)
    otras = t.loc[t["factor"] == "otras ventas", "aporte_variacion_produccion_pp"].iloc[0]
    assert abs(otras) < 1e-9
    print("ok  otras ventas entra con rezago 1: aporte nulo a la variación")


def test_avisa_exportaciones_estimadas():
    # 2026-07: INDEC ocultó el dato; 2026-08 no.
    oculto = explicar("suma_contable", "2026-07", BASE)
    assert oculto.attrs["exportaciones_estimadas"]
    assert oculto.loc[oculto["factor"] == "exportaciones", "nota"].iloc[0] != ""
    assert (oculto.loc[oculto["factor"] != "exportaciones", "nota"] == "").all()
    assert not explicar("suma_contable", "2026-08", BASE).attrs["exportaciones_estimadas"]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cana = explicar("elastic_net_bioetanol_cana", "2026-07", BASE)
    assert not cana.attrs["exportaciones_estimadas"]   # bioetanol no usa exportaciones
    print("ok  avisa cuando las exportaciones son un estimado (INDEC oculto)")


def test_estacionalidad_con_nombre_por_serie():
    assert grupo_de("lag_12", "bioetanol_maiz") == "estacionalidad (maíz)"
    assert grupo_de("mes_6", "bioetanol_cana") == "estacionalidad (zafra)"
    assert grupo_de("mes_6", "biodiesel") == "estacionalidad"
    print("ok  la estacionalidad de maíz y la de caña salen con nombres distintos")


if __name__ == "__main__":
    test_todas_las_variables_tienen_factor()
    test_suma_contable_otras_ventas_no_mueve_la_variacion()
    test_avisa_exportaciones_estimadas()
    test_estacionalidad_con_nombre_por_serie()
    test_reconstruye_prediccion_del_protocolo()
    print("\nTodas las pruebas de contribuciones pasaron.")
