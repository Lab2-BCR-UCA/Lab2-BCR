"""Ablación del margen doméstico del biodiésel en el SARIMAX (SCRUM-31).

La ablación de SCRUM-62 (``experimento_exogenas.py``) no incluyó el margen
doméstico del biodiésel (``margen_domestico_biodiesel``). Este experimento lo
prueba con el mismo criterio: base vs base + margen, en el backtest, con la
diferencia de MAE por bootstrap de bloques + Diebold-Mariano (``evaluacion``).

Mecanismo: si el precio regulado no cubre el costo del aceite, las plantas no
entregan al corte (el colapso de 2020). El margen (rezago 0; disponible hacia el
día 2-4 de t+1, los tres insumos confirmados tras SCRUM-49) resume ese
incentivo.

Ventana de entrenamiento igualada
---------------------------------
El margen arranca en 2018-01 (lo deriva el aceite de soja), mientras que la serie
de biodiésel arranca en 2008. Comparar "base desde 2008" contra "margen desde
2018" mezclaría el efecto de la variable con el de acortar la ventana (misma
lección que la review de SCRUM-62). Por eso la base y la variante **arrancan las
dos en 2018-01**.

Lectura: ``dif MAE = MAE(con margen) − MAE(base)``. Negativo = el margen baja el
error. Si el IC95 cruza 0, no se distingue de no tenerlo y no justifica sumarlo
(parsimonia). El holdout no se toca.

Uso, desde la raíz del proyecto:
    python scripts/experimento_margen.py

Salida: results/experimento_margen.csv. Requiere statsmodels, scipy, pandas.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))

from sarimax import ModeloSARIMAX, _serie_base  # noqa: E402
from evaluacion import comparar_modelos, evaluar_ventanas, ventanas_protocolo  # noqa: E402

SERIE = "biodiesel"
INICIO_IGUALADO = "2018-01"              # primer mes con margen (lo deriva el aceite)
MARGEN = ("margen_domestico_biodiesel", 0)


def _evaluar(extra: list | None, ventanas: dict) -> pd.DataFrame:
    """Backtest del SARIMAX de biodiésel, con o sin el margen, desde 2018."""
    detalle, _ = evaluar_ventanas(
        serie=_serie_base(SERIE),
        crear_modelo=lambda: ModeloSARIMAX(SERIE, exogenas_extra=extra),
        inicio_entrenamiento=INICIO_IGUALADO,
        ventanas=ventanas,
        nombre_serie=SERIE,
        nombre_modelo="x",
    )
    return detalle


def _metricas(detalle: pd.DataFrame) -> tuple[float, float, str]:
    """MAE, error absoluto máximo y el mes en que ocurre."""
    ok = detalle.loc[detalle["estado"] == "ok"].copy()
    ok["abs"] = ok["error"].abs()
    peor = ok.loc[ok["abs"].idxmax()]
    return ok["abs"].mean(), float(peor["abs"]), str(pd.Period(peor["fecha"], freq="M"))


def main() -> None:
    ultimo = _serie_base(SERIE).index[-1]
    ventanas = {"backtest": ventanas_protocolo(ultimo)["backtest"]}

    print("Ablación del margen doméstico del biodiésel (backtest, MAE principal)")
    print(f"Base y variante arrancan en {INICIO_IGUALADO} (ventana igualada).\n")

    base = _evaluar(None, ventanas)
    var = _evaluar([MARGEN], ventanas)
    b_mae, b_max, b_mes = _metricas(base)
    v_mae, v_max, v_mes = _metricas(var)

    c = comparar_modelos(var, base, perdida="ae")
    distinguible = bool(c["ic_inf"] > 0 or c["ic_sup"] < 0)
    mejora = c["diferencia_media"] < 0
    print(f"  base (desde {INICIO_IGUALADO}): MAE={b_mae:,.0f}  error máx={b_max:,.0f} ({b_mes})")
    print(f"  +margen_domestico          : MAE={v_mae:,.0f}  error máx={v_max:,.0f} ({v_mes})")
    print(f"  dif MAE (con-sin) = {c['diferencia_media']:+,.0f}  "
          f"IC95 [{c['ic_inf']:,.0f}, {c['ic_sup']:,.0f}]  DM p={c['dm_p_valor']:.3f}  -> "
          f"{'MEJORA' if mejora else 'empeora'}, "
          f"{'distinguible' if distinguible else 'no distinguible (IC cruza 0)'}")

    fila = {
        "serie": SERIE, "variante": "+margen_domestico",
        "inicio_entrenamiento": INICIO_IGUALADO,
        "MAE_base": round(b_mae, 2), "MAE_variante": round(v_mae, 2),
        "dif_MAE": round(c["diferencia_media"], 2),
        "ic95_inf": round(c["ic_inf"], 2), "ic95_sup": round(c["ic_sup"], 2),
        "dm_p_valor": round(c["dm_p_valor"], 4),
        "error_max_base": round(b_max, 2), "mes_error_max_base": b_mes,
        "error_max_variante": round(v_max, 2), "mes_error_max_variante": v_mes,
        "mejora": mejora, "distinguible_95": distinguible,
    }
    out = RAIZ / "results" / "experimento_margen.csv"
    out.parent.mkdir(exist_ok=True)
    pd.DataFrame([fila]).to_csv(out, index=False)
    print(f"\nGuardado en {out}")


if __name__ == "__main__":
    main()
