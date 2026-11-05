"""Aporte del margen doméstico del biodiésel (SCRUM-31).

La ablación de SCRUM-62 (``experimento_exogenas.py``) no incluyó el margen
doméstico del biodiésel (``margen_domestico_biodiesel``). Acá se prueba en los dos
modelos donde puede entrar, en el backtest, con la diferencia de MAE por bootstrap
de bloques + Diebold-Mariano (``evaluacion.comparar_modelos``). El holdout no se
toca.

Mecanismo: si el precio regulado no cubre el costo del aceite, las plantas no
entregan al corte (2020). El margen tiene rezago 0 (disponible hacia el día 2-4
de t+1; los tres insumos confirmados tras SCRUM-49) y existe desde 2018-01.

1. SARIMAX: base vs base + margen
---------------------------------
La base del biodiésel es SARIMA puro, así que para no mezclar el efecto de la
variable con el de acortar la ventana, base y variante arrancan las dos en
2018-01. Con esa ventana la base queda rota: entre enero y febrero de 2021 la
producción pasó de 28.073 a 164.411 tn (×5,9) y el modelo en log, con diferencia
estacional, repite ese salto un año después (189.217 × 5,9 ≈ 1,1 M tn en
2022-02). Su MAE (~57.000) es más del doble que el del naive (23.673), así que
esta comparación **no es concluyente**: se reporta, pero no decide.

2. Elastic net: margen con valor vs margen aplanado
---------------------------------------------------
El elastic net del biodiésel que SCRUM-54 recomienda para SCRUM-34
(``biodiesel_con_contables_sin_eventos``) ya incluye el margen. Antes de 2018 el
margen es NaN y el imputador agrega un indicador de faltante, que funciona como
una dummy de "antes de 2018". Sacar la variable entera se llevaría también esa
dummy y mezclaría los dos efectos. Por eso se compara contra la misma versión con
el margen **aplanado** (``Config.aplanar``): el valor se vuelve constante donde
hay dato, los NaN quedan, y el indicador se mantiene. La diferencia mide solo el
aporte del valor del margen.

Lectura: ``dif MAE = MAE(con margen) − MAE(sin el valor)``. Negativo = el margen
baja el error. Distinguible si el IC95 no cruza 0.

Uso, desde la raíz del proyecto:
    python scripts/experimento_margen.py

Salida: results/experimento_margen.csv (una fila por modelo).
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))

from elastic_net import MODELOS, ModeloElasticNet, _base, serie_objetivo  # noqa: E402
from evaluacion import comparar_modelos, evaluar_ventanas, ventanas_protocolo  # noqa: E402
from sarimax import ModeloSARIMAX, _serie_base  # noqa: E402

SERIE = "biodiesel"
MARGEN = "margen_domestico_biodiesel"
INICIO_SARIMAX = "2018-01"               # primer mes con margen
CONFIG_EN = "biodiesel_con_contables_sin_eventos"


def _metricas(detalle: pd.DataFrame) -> tuple[float, float, str]:
    """MAE, error absoluto máximo y el mes en que ocurre."""
    ok = detalle.loc[detalle["estado"] == "ok"].copy()
    ok["abs"] = ok["error"].abs()
    peor = ok.loc[ok["abs"].idxmax()]
    return ok["abs"].mean(), float(peor["abs"]), str(pd.Period(peor["fecha"], freq="M"))


def _sarimax(con_margen: bool, ventanas: dict) -> pd.DataFrame:
    extra = [(MARGEN, 0)] if con_margen else None
    detalle, _ = evaluar_ventanas(
        serie=_serie_base(SERIE),
        crear_modelo=lambda: ModeloSARIMAX(SERIE, exogenas_extra=extra),
        inicio_entrenamiento=INICIO_SARIMAX, ventanas=ventanas,
        nombre_serie=SERIE, nombre_modelo="sarimax",
    )
    return detalle


def _elastic_net(aplanar: tuple, ventanas: dict) -> pd.DataFrame:
    base = _base()
    cfg = dataclasses.replace(MODELOS[CONFIG_EN], aplanar=aplanar)
    detalle, _ = evaluar_ventanas(
        serie=serie_objetivo(SERIE, base),
        crear_modelo=lambda: ModeloElasticNet(cfg, base),
        inicio_entrenamiento=cfg.inicio, ventanas=ventanas,
        nombre_serie=SERIE, nombre_modelo="elastic_net",
    )
    return detalle


def _fila(modelo: str, comparacion: str, inicio: str, sin: pd.DataFrame,
          con: pd.DataFrame) -> dict:
    s_mae, s_max, s_mes = _metricas(sin)
    c_mae, c_max, c_mes = _metricas(con)
    c = comparar_modelos(con, sin, perdida="ae")
    distinguible = bool(c["ic_inf"] > 0 or c["ic_sup"] < 0)
    print(f"== {modelo} ({comparacion}, desde {inicio}) ==")
    print(f"  sin: MAE={s_mae:,.0f}  máx={s_max:,.0f} ({s_mes})")
    print(f"  con: MAE={c_mae:,.0f}  máx={c_max:,.0f} ({c_mes})")
    print(f"  dif (con-sin) = {c['diferencia_media']:+,.0f}  "
          f"IC95 [{c['ic_inf']:,.0f}, {c['ic_sup']:,.0f}]  DM p={c['dm_p_valor']:.3f}  "
          f"-> {'distinguible' if distinguible else 'no distinguible'}\n")
    return {
        "modelo": modelo, "comparacion": comparacion, "inicio_entrenamiento": inicio,
        "MAE_sin": round(s_mae, 2), "MAE_con": round(c_mae, 2),
        "dif_MAE": round(c["diferencia_media"], 2),
        "ic95_inf": round(c["ic_inf"], 2), "ic95_sup": round(c["ic_sup"], 2),
        "dm_p_valor": round(c["dm_p_valor"], 4),
        "error_max_sin": round(s_max, 2), "mes_error_max_sin": s_mes,
        "error_max_con": round(c_max, 2), "mes_error_max_con": c_mes,
        "distinguible_95": distinguible,
    }


def main() -> None:
    ventanas = {"backtest": ventanas_protocolo(_serie_base(SERIE).index[-1])["backtest"]}
    print("Aporte del margen doméstico del biodiésel (backtest, MAE principal)\n")
    filas = [
        _fila("sarimax", "base vs base+margen", INICIO_SARIMAX,
              _sarimax(False, ventanas), _sarimax(True, ventanas)),
        _fila("elastic_net_" + CONFIG_EN, "margen aplanado vs margen", MODELOS[CONFIG_EN].inicio,
              _elastic_net((MARGEN,), ventanas), _elastic_net((), ventanas)),
    ]
    out = RAIZ / "results" / "experimento_margen.csv"
    out.parent.mkdir(exist_ok=True)
    pd.DataFrame(filas).to_csv(out, index=False)
    print(f"Guardado en {out}")


if __name__ == "__main__":
    main()
