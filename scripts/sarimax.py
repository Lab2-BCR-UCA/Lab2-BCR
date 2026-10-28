"""SARIMAX con variables externas (SCRUM-29), enchufado al protocolo (SCRUM-43).

``ModeloSARIMAX`` cumple la interfaz ``fit(serie)`` / ``predict()`` que usa
``evaluacion.evaluar_modelo``. Las exógenas las arma ``construir_features``
(SCRUM-59) respetando la disponibilidad temporal (SCRUM-26), así que son las
mismas que van a usar el elastic net (SCRUM-54) y la suma contable (N4).

Idea del modelo: SARIMA captura inercia y estacionalidad (en log); las
exógenas (margen, ventas, etc.) explican el desvío del mes. Pocas variables, a
su rezago disponible, para no sobreajustar con ~100-200 meses.

Nota sobre la muestra: algunas exógenas arrancan en 2018 (margen, precios
regulados). SARIMAX no admite huecos en las exógenas, así que el entrenamiento
con exógenas empieza donde todas están disponibles. Si esa ventana queda muy
corta, el modelo cae a un SARIMA sin exógenas (queda registrado en el motivo).

Uso, desde la raíz del proyecto:

    python scripts/sarimax.py                 # walk-forward (backtest + holdout)
    python scripts/sarimax.py --sin-holdout   # solo backtest

Salida: results/sarimax.csv (métricas por serie y ventana).
Requiere: pip install statsmodels pandas numpy
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))

from statsmodels.tsa.statespace.sarimax import SARIMAX  # noqa: E402

from build_db import leer_dataset  # noqa: E402
from construir_features import OBJETIVOS, construir_features  # noqa: E402
from evaluacion import evaluar_ventanas, ventanas_protocolo  # noqa: E402

# Órdenes por defecto (en log). Puntos de partida razonables; se afinan por
# serie en el walk-forward (TODO: búsqueda de orden por AIC con datos < corte).
ORDER = (1, 1, 1)
SEASONAL_ORDER = (0, 1, 1, 12)
MIN_OBS_EXOG = 36          # mínimo de meses para animarse a usar exógenas
INICIO_ENTRENAMIENTO = {   # igual que el protocolo (baselines.py)
    "biodiesel": "2008-01",
    "bioetanol_total": "2013-01",
    "bioetanol_maiz": "2012-09",
    "bioetanol_cana": "2013-01",
}

# Base cacheada a nivel módulo: se lee una sola vez, no en cada iteración.
_BASE: pd.DataFrame | None = None


def _base() -> pd.DataFrame:
    global _BASE
    if _BASE is None:
        _BASE = leer_dataset()
    return _BASE


class ModeloSARIMAX:
    """SARIMAX en log con exógenas de ``construir_features``.

    La fábrica le pasa el nombre de la serie para que sepa qué exógenas cargar:
    ``lambda: ModeloSARIMAX("biodiesel")``.
    """

    def __init__(self, objetivo: str, order=ORDER, seasonal_order=SEASONAL_ORDER) -> None:
        self.objetivo = objetivo
        self.order = order
        self.seasonal_order = seasonal_order
        self._res = None
        self._x_pred: pd.DataFrame | None = None

    def fit(self, serie: pd.Series) -> "ModeloSARIMAX":
        """Ajusta el SARIMAX con las exógenas disponibles hasta el mes a estimar."""
        y = serie.copy()
        if not isinstance(y.index, pd.PeriodIndex):
            y.index = pd.PeriodIndex(pd.to_datetime(y.index), freq="M")
        y = y.sort_index().astype(float)
        fecha_corte = y.index[-1] + 1
        y_log = np.log(y.asfreq("M"))

        X, _ = construir_features(self.objetivo, fecha_corte, base=_base())
        x_train = X.reindex(y_log.index)
        x_pred = X.reindex([fecha_corte])

        # Exógenas usables: sin NaN ni en el entrenamiento común ni en la fila
        # de predicción. (El calendario nunca tiene NaN.)
        cols = [c for c in X.columns
                if x_pred[c].notna().all() and x_train[c].notna().sum() >= MIN_OBS_EXOG]

        exog_tr = exog_pr = None
        if cols:
            # Muestra común: los meses donde y y TODAS las exógenas existen.
            marco = pd.concat([y_log.rename("y"), x_train[cols]], axis=1).dropna()
            if len(marco) >= MIN_OBS_EXOG:
                y_log = marco["y"]
                exog_tr = marco[cols]
                exog_pr = x_pred[cols]

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self._res = SARIMAX(
                y_log, exog=exog_tr, order=self.order,
                seasonal_order=self.seasonal_order,
                enforce_stationarity=False, enforce_invertibility=False,
            ).fit(disp=False, maxiter=200)
        self._x_pred = exog_pr
        return self

    def predict(self) -> float:
        """Pronóstico a un mes, de vuelta en unidades originales."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            f = self._res.forecast(1, exog=self._x_pred)
        return float(np.exp(np.asarray(f)[0]))


def _objetivos_desde_base() -> dict[str, pd.Series]:
    """Series objetivo tomadas de la base (mismas que ve construir_features)."""
    base = _base()
    out = {}
    for nombre, sid in OBJETIVOS.items():
        s = base[sid].dropna().astype(float)
        if not isinstance(s.index, pd.PeriodIndex):
            s.index = pd.PeriodIndex(pd.to_datetime(s.index), freq="M")
        out[nombre] = s.sort_index()
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sin-holdout", action="store_true", help="solo el backtest")
    args = ap.parse_args()

    series = _objetivos_desde_base()
    ultimo = min(s.index[-1] for s in series.values())
    ventanas = ventanas_protocolo(ultimo)
    if args.sin_holdout:
        ventanas = {"backtest": ventanas["backtest"]}

    resumenes = []
    for nombre, serie in series.items():
        _, resumen = evaluar_ventanas(
            serie=serie,
            crear_modelo=lambda n=nombre: ModeloSARIMAX(n),
            inicio_entrenamiento=INICIO_ENTRENAMIENTO[nombre],
            ventanas=ventanas,
            nombre_serie=nombre,
            nombre_modelo="sarimax",
        )
        resumenes.append(resumen)

    resumen = pd.concat(resumenes, ignore_index=True)
    out = RAIZ / "results"
    out.mkdir(exist_ok=True)
    resumen.to_csv(out / "sarimax.csv", index=False)

    for ventana in ventanas:
        r = resumen[resumen["ventana"] == ventana]
        print(f"\nMAPE % ({ventana}):")
        print(r[["serie", "MAPE_pct", "meses_evaluados", "cobertura_pct"]]
              .round(2).to_string(index=False))
    print(f"\nGuardado en {out / 'sarimax.csv'}")


if __name__ == "__main__":
    main()
