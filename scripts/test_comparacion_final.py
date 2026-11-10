"""Pruebas de la regla de elección del modelo final (SCRUM-34).

Uso: python scripts/test_comparacion_final.py
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comparacion_final as cf  # noqa: E402

SERIE = "bioetanol_maiz"   # grilla: naive, naive_estacional, x13_bcr, elastic net, sarimax
EN, SA = "elastic_net_bioetanol_maiz", "sarimax_directo"


def _met(maes: dict) -> pd.DataFrame:
    return pd.DataFrame([{"serie": SERIE, "ventana": "backtest", "modelo": m, "MAE": v}
                         for m, v in maes.items()])


def _dif(rows: dict) -> pd.DataFrame:
    """rows: {(modelo, contra): (diferencia, p)}"""
    return pd.DataFrame([{"serie": SERIE, "ventana": "backtest", "modelo": m, "contra": c,
                          "diferencia_media": d, "dm_p_valor": p}
                         for (m, c), (d, p) in rows.items()])


def _elegir(maes, rows):
    grilla_original = cf.GRILLA
    cf.GRILLA = {SERIE: grilla_original[SERIE]}
    try:
        return cf.elegir(_met(maes), _dif(rows)).iloc[0]
    finally:
        cf.GRILLA = grilla_original


def _base_rows(peor_en=(300, 0.40), peor_sa=(900, 0.01)):
    rows = {}
    for m in (EN, SA, "naive", "naive_estacional", "x13_bcr"):
        rows[(m, "naive")] = (-100, 0.5)
        rows[(m, "x13_bcr")] = (+100, 0.5)
    rows[(EN, "mejor")] = peor_en
    rows[(SA, "mejor")] = peor_sa
    rows[("naive", "mejor")] = (500, 0.2)
    rows[("naive_estacional", "mejor")] = (4000, 0.001)
    return rows


def test_elige_mas_interpretable_si_no_es_significativamente_peor():
    maes = {"x13_bcr": 5000, EN: 5300, SA: 5900, "naive": 5500, "naive_estacional": 9000}
    e = _elegir(maes, _base_rows(peor_en=(300, 0.40)))
    assert e["elegido"] == EN and e["mejor"] == "x13_bcr", e
    print("ok  elige el elastic net (más interpretable) aunque el X-13 tenga menos MAE, si no es peor de forma significativa")


def test_salta_al_siguiente_si_es_significativamente_peor():
    maes = {"x13_bcr": 5000, EN: 5300, SA: 5900, "naive": 5500, "naive_estacional": 9000}
    e = _elegir(maes, _base_rows(peor_en=(300, 0.01), peor_sa=(900, 0.01)))
    assert e["elegido"] == "x13_bcr", e
    assert EN in e["descartados_por_ser_peores"] and SA in e["descartados_por_ser_peores"]
    print("ok  si el elastic net y el SARIMAX son significativamente peores, queda el X-13")


def test_peor_sin_significancia_no_descarta():
    maes = {"x13_bcr": 5000, EN: 5300, SA: 5900, "naive": 5500, "naive_estacional": 9000}
    e = _elegir(maes, _base_rows(peor_en=(300, 0.051)))
    assert e["elegido"] == EN, e
    print("ok  p = 0,051 no alcanza para descartar (umbral 0,05)")


def test_el_mejor_se_elige_directo():
    maes = {"x13_bcr": 5600, EN: 5000, SA: 5900, "naive": 5500, "naive_estacional": 9000}
    rows = _base_rows()
    rows[("x13_bcr", "mejor")] = (600, 0.3)
    e = _elegir(maes, rows)
    assert e["elegido"] == EN and e["motivo"] == "es el de menor MAE", e
    print("ok  si el más interpretable es también el mejor, se elige con ese motivo")


def test_naive_puede_ser_mejor_pero_no_se_elige():
    maes = {"x13_bcr": 5600, EN: 5300, SA: 5900, "naive": 5000, "naive_estacional": 9000}
    rows = _base_rows(peor_en=(300, 0.40))
    rows[("x13_bcr", "mejor")] = (600, 0.3)
    e = _elegir(maes, rows)
    assert e["mejor"] == "naive" and e["elegido"] == EN, e
    print("ok  el naive puede ser el mejor, pero el elegido sale del orden de interpretabilidad")


if __name__ == "__main__":
    test_elige_mas_interpretable_si_no_es_significativamente_peor()
    test_salta_al_siguiente_si_es_significativamente_peor()
    test_peor_sin_significancia_no_descarta()
    test_el_mejor_se_elige_directo()
    test_naive_puede_ser_mejor_pero_no_se_elige()
    print("\nTodas las pruebas de la regla pasaron.")
