"""Experimento controlado: nivel vs log en el SARIMAX de total y maíz (SCRUM-31).

El EDA de producción (SCRUM-45, parte B) concluye que el bioetanol **total** y el
de **maíz** son más parejos en nivel que en log, pero el SARIMAX (SCRUM-29) los
modela en log como a las otras series. Este experimento aísla el efecto de esa
decisión: corre el mismo modelo —mismo orden ``(1,1,1)(0,1,1,12)``, mismas
exógenas— cambiando **solo** la transformación de la serie objetivo.

Lectura: ``dif MAE = MAE(nivel) − MAE(log)``. Negativo = nivel tiene menos error.
Si el IC95 de la diferencia cruza 0, las dos transformaciones no se distinguen y
se mantiene log por continuidad con el resto de las series (parsimonia).

Métrica principal: MAE (decisión del 27/10). Diferencia con IC por bootstrap de
bloques + Diebold-Mariano (``comparar_modelos`` de ``evaluacion``), en el backtest
del protocolo (SCRUM-43). El holdout no se toca.

Uso, desde la raíz del proyecto:
    python scripts/experimento_transformacion.py

Salida: results/experimento_transformacion.csv. Requiere statsmodels, scipy, pandas.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))

from sarimax import ModeloSARIMAX, _serie_base, INICIO_ENTRENAMIENTO, OBJETIVOS  # noqa: E402
from evaluacion import comparar_modelos, evaluar_ventanas, ventanas_protocolo  # noqa: E402

SERIES = ["bioetanol_total", "bioetanol_maiz"]


def _evaluar(nombre: str, transformacion: str, ventanas: dict) -> pd.DataFrame:
    """Backtest del SARIMAX de ``nombre`` con la transformación indicada."""
    detalle, _ = evaluar_ventanas(
        serie=_serie_base(nombre),
        crear_modelo=lambda: ModeloSARIMAX(nombre, transformacion=transformacion),
        inicio_entrenamiento=INICIO_ENTRENAMIENTO[nombre],
        ventanas=ventanas,
        nombre_serie=nombre,
        nombre_modelo=f"sarimax_{transformacion}",
    )
    return detalle


def main() -> None:
    ultimo = min(_serie_base(n).index[-1] for n in OBJETIVOS)
    ventanas = {"backtest": ventanas_protocolo(ultimo)["backtest"]}

    print("Nivel vs log en el SARIMAX (backtest, MAE = métrica principal)")
    print("Mismo orden y mismas exógenas; solo cambia la transformación.\n")
    filas = []
    for nombre in SERIES:
        det_log = _evaluar(nombre, "log", ventanas)
        det_niv = _evaluar(nombre, "nivel", ventanas)
        mae_log = det_log.loc[det_log["estado"] == "ok", "error"].abs().mean()
        mae_niv = det_niv.loc[det_niv["estado"] == "ok", "error"].abs().mean()

        c = comparar_modelos(det_niv, det_log, perdida="ae")
        distinguible = bool(c["ic_inf"] > 0 or c["ic_sup"] < 0)
        mejor = "nivel" if c["diferencia_media"] < 0 else "log"
        print(f"== {nombre} ==")
        print(f"  log:   MAE={mae_log:,.0f}")
        print(f"  nivel: MAE={mae_niv:,.0f}")
        print(f"  dif MAE (nivel-log) = {c['diferencia_media']:+,.0f}  "
              f"IC95 [{c['ic_inf']:,.0f}, {c['ic_sup']:,.0f}]  DM p={c['dm_p_valor']:.3f}  -> "
              f"{mejor} mejor, {'DISTINGUIBLE' if distinguible else 'no distinguible (IC cruza 0)'}\n")
        filas.append({
            "serie": nombre,
            "MAE_log": round(mae_log, 2), "MAE_nivel": round(mae_niv, 2),
            "dif_MAE_nivel_menos_log": round(c["diferencia_media"], 2),
            "ic95_inf": round(c["ic_inf"], 2), "ic95_sup": round(c["ic_sup"], 2),
            "dm_p_valor": round(c["dm_p_valor"], 4),
            "mejor": mejor, "distinguible_95": distinguible,
        })

    out = RAIZ / "results" / "experimento_transformacion.csv"
    out.parent.mkdir(exist_ok=True)
    pd.DataFrame(filas).to_csv(out, index=False)
    print(f"Guardado en {out}")
    print("Criterio: se cambia a nivel solo si baja el MAE de forma distinguible; "
          "si el IC cruza 0, se mantiene log por continuidad con las otras series.")


if __name__ == "__main__":
    main()
