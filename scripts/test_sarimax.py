"""Pruebas del parámetro de transformación del SARIMAX (SCRUM-31).

Uso: python scripts/test_sarimax.py
"""

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sarimax import ModeloSARIMAX, _serie_base  # noqa: E402

MES = pd.Period("2021-09", freq="M")


def _serie_hasta_corte(nombre: str = "bioetanol_maiz") -> pd.Series:
    s = _serie_base(nombre)
    return s[s.index < MES]


def test_transformacion_invalida_frena():
    try:
        ModeloSARIMAX("bioetanol_maiz", transformacion="raiz")
    except ValueError:
        print("ok  una transformación desconocida frena")
    else:
        raise AssertionError("debió frenar con transformacion inválida")


def test_default_es_log():
    assert ModeloSARIMAX("bioetanol_maiz").transformacion == "log"
    print("ok  la transformación por defecto es log (no cambia el comportamiento previo)")


def test_log_y_nivel_predicen_y_difieren():
    """Las dos transformaciones dan una predicción válida y distinta entre sí."""
    serie = _serie_hasta_corte()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        p_log = ModeloSARIMAX("bioetanol_maiz", transformacion="log").fit(serie).predict()
        p_niv = ModeloSARIMAX("bioetanol_maiz", transformacion="nivel").fit(serie).predict()
    for p in (p_log, p_niv):
        assert np.isfinite(p) and p > 0
    # Las dos quedan en el orden de magnitud de la serie (el nivel no se exponencia).
    techo = serie.max() * 3
    assert p_log < techo and p_niv < techo, (p_log, p_niv, techo)
    assert not np.isclose(p_log, p_niv), "log y nivel no deberían coincidir"
    print(f"ok  log={p_log:,.0f} y nivel={p_niv:,.0f}: válidas, distintas y en escala")


if __name__ == "__main__":
    test_transformacion_invalida_frena()
    test_default_es_log()
    test_log_y_nivel_predicen_y_difieren()
    print("\nTodas las pruebas del SARIMAX pasaron.")
