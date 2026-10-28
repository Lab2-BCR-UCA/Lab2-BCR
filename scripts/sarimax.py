"""SARIMAX con variables externas (SCRUM-29), enchufado al protocolo (SCRUM-43).

``ModeloSARIMAX`` cumple la interfaz ``fit(serie)`` / ``predict()`` que usa
``evaluacion.evaluar_modelo``. Las exógenas las arma ``construir_features``
(SCRUM-59) respetando la disponibilidad temporal (SCRUM-26), así que son las
mismas que van a usar el elastic net (SCRUM-54) y la suma contable (N4).

Idea del modelo: SARIMA captura inercia y estacionalidad (en log); las
exógenas explican el desvío del mes.

Orden
-----
Por defecto ``(1,1,1)(0,1,1,12)`` en log (d=1). El EDA (SCRUM-45) marca con
**ADF + KPSS** solo biodiésel y caña como estacionarias en log (candidatas a
d=0); total y maíz dan contradictorio → d=1.

Experimento controlado (``experimento_d.py``: mismo p,q,P,Q, solo cambia d,
pérdida MAE con IC por bootstrap de bloques, backtest):

    biodiésel: d=1 MAE 29.221  vs d=0 31.555 → dif(d0-d1)=+2.333,
               IC95 [294, 4.208], DM p=0,025  → d=1 MEJOR y distinguible.
    caña:      d=1 MAE  7.628  vs d=0  7.039 → dif=-588,
               IC95 [-1.631, 475], p=0,286   → d=0 apenas mejor, NO distinguible.

Conclusión: se usa **d=1** en las 4 (biodiésel por significancia; caña porque da
igual; total/maíz por el EDA). La búsqueda por AIC (``--buscar-orden``) queda
como exploración: no aísla d y el AIC optimiza ajuste in-sample, no el error a
1 mes. El orden se elige **una sola vez con datos anteriores a sep-2021**
(pre-backtest) y se fija para todo el walk-forward: es consistente con el
protocolo y no es leakage (confirmado en review).

Desempeño (backtest): **UCM gana en maíz (MAPE 7,9 vs 10,4) y caña (20,5 vs
26,8)**; SARIMAX empata al UCM en biodiésel (~30) y total (~8). El SARIMAX no es
el mejor en ninguna serie; la mejora real para biodiésel espera las
exportaciones de INDEC (N1), que todavía no están en la base.

Nota: las exógenas internas del biodiésel desestabilizan el SARIMAX (ver
construir_features), así que el biodiésel corre sin exógenas por ahora.

Uso, desde la raíz del proyecto:

    python scripts/sarimax.py                 # walk-forward, orden fijo (default)
    python scripts/sarimax.py --sin-holdout   # solo backtest
    python scripts/sarimax.py --buscar-orden  # elige orden por AIC/ADF+KPSS (exploración)

Salida: results/sarimax.csv (métricas por serie y ventana).
Requiere: pip install statsmodels pandas numpy
"""

from __future__ import annotations

import argparse
import itertools
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))

from statsmodels.tsa.statespace.sarimax import SARIMAX  # noqa: E402
from statsmodels.tsa.stattools import adfuller, kpss  # noqa: E402

from build_db import leer_dataset  # noqa: E402
from construir_features import OBJETIVOS, construir_features  # noqa: E402
from evaluacion import evaluar_ventanas, ventanas_protocolo  # noqa: E402

ORDER_FIJO = (1, 1, 1)
SEASONAL_FIJO = (0, 1, 1, 12)
MIN_OBS_EXOG = 36                       # mínimo de meses para animarse a usar exógenas
CORTE_ORDEN = pd.Timestamp("2021-09-01")  # el orden se elige con datos < backtest
INICIO_ENTRENAMIENTO = {                # igual que el protocolo (baselines.py)
    "biodiesel": "2008-01",
    "bioetanol_total": "2013-01",
    "bioetanol_maiz": "2012-09",
    "bioetanol_cana": "2013-01",
}
# Grilla de búsqueda (opción --buscar-orden): d lo fija ADF+KPSS, el AIC el resto.
GRILLA_PQ = list(itertools.product(range(3), range(3)))            # p, q
GRILLA_SEASONAL = list(itertools.product((0, 1), (0, 1), (0, 1)))  # P, D, Q (m=12)

_BASE: pd.DataFrame | None = None
_ORDENES: dict[str, tuple] = {}


def _base() -> pd.DataFrame:
    global _BASE
    if _BASE is None:
        _BASE = leer_dataset()
    return _BASE


def _d_por_tests(y_log: pd.Series, alfa: float = 0.05) -> int:
    """``d`` según ADF + KPSS juntos (regla del EDA, SCRUM-45).

    d=0 solo si **ambos** coinciden en estacionariedad (ADF rechaza raíz
    unitaria y KPSS no rechaza estacionariedad). Si se contradicen o ambos dan
    no estacionaria, d=1 (conservador). Da biodiésel/caña → d=0, total/maíz → 1.
    """
    s = y_log.dropna()
    if len(s) < 24:
        return 1
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            adf_estac = adfuller(s, autolag="AIC")[1] < alfa      # rechaza raíz unitaria
            kpss_estac = kpss(s, regression="c", nlags="auto")[1] > alfa  # no rechaza estac.
        return 0 if (adf_estac and kpss_estac) else 1
    except Exception:
        return 1


def elegir_orden(y_log: pd.Series) -> tuple:
    """Orden ``(order, seasonal_order)``: ``d`` lo fija ADF+KPSS, el resto el AIC.

    Exploración (``--buscar-orden``), no el default: el experimento controlado
    muestra que d=1 iguala o gana, y el AIC no optimiza el error a 1 mes.
    """
    d = _d_por_tests(y_log)
    mejor = None
    for (p, q) in GRILLA_PQ:
        for (P, D, Q) in GRILLA_SEASONAL:
            if p == q == P == D == Q == 0 and d == 0:
                continue
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    res = SARIMAX(
                        y_log, order=(p, d, q), seasonal_order=(P, D, Q, 12),
                        enforce_stationarity=False, enforce_invertibility=False,
                    ).fit(disp=False, maxiter=50)
                if np.isfinite(res.aic) and (mejor is None or res.aic < mejor[0]):
                    mejor = (res.aic, (p, d, q), (P, D, Q, 12))
            except Exception:
                continue
    if mejor is None:
        return ORDER_FIJO, SEASONAL_FIJO
    return mejor[1], mejor[2]


def _orden_de(objetivo: str) -> tuple:
    """Orden por AIC/ADF+KPSS para ``objetivo``, elegido UNA vez con datos
    < CORTE_ORDEN (pre-backtest) y cacheado: consistente con el protocolo, no
    leakage. Solo se usa con ``--buscar-orden``."""
    if objetivo not in _ORDENES:
        base = _base()
        y = base[OBJETIVOS[objetivo]].dropna().astype(float)
        if not isinstance(y.index, pd.PeriodIndex):
            y.index = pd.PeriodIndex(pd.to_datetime(y.index), freq="M")
        ini = pd.Period(INICIO_ENTRENAMIENTO[objetivo], freq="M")
        y = y[(y.index >= ini) & (y.index < CORTE_ORDEN.to_period("M"))]
        _ORDENES[objetivo] = elegir_orden(np.log(y.asfreq("M")))
    return _ORDENES[objetivo]


class ModeloSARIMAX:
    """SARIMAX en log con exógenas de ``construir_features``.

    La fábrica le pasa el nombre de la serie: ``lambda: ModeloSARIMAX("biodiesel")``.
    Por defecto usa el orden fijo ``(1,1,1)(0,1,1,12)``.
    """

    def __init__(self, objetivo: str, order=ORDER_FIJO, seasonal_order=SEASONAL_FIJO) -> None:
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

        cols = [c for c in X.columns
                if x_pred[c].notna().all() and x_train[c].notna().sum() >= MIN_OBS_EXOG]

        exog_tr = exog_pr = None
        if cols:
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
    ap.add_argument("--buscar-orden", action="store_true",
                    help="elige el orden por AIC/ADF+KPSS (exploración; no el default)")
    args = ap.parse_args()

    series = _objetivos_desde_base()
    ultimo = min(s.index[-1] for s in series.values())
    ventanas = ventanas_protocolo(ultimo)
    if args.sin_holdout:
        ventanas = {"backtest": ventanas["backtest"]}

    if args.buscar_orden:
        print("Orden elegido por AIC/ADF+KPSS (datos < 2021-09):")
        for nombre in series:
            o, so = _orden_de(nombre)
            print(f"  {nombre:16s} order={o} seasonal={so}")

    def fabrica(nombre):
        if args.buscar_orden:
            o, so = _orden_de(nombre)
            return lambda: ModeloSARIMAX(nombre, o, so)
        return lambda: ModeloSARIMAX(nombre)  # orden fijo (default)

    resumenes = []
    for nombre, serie in series.items():
        _, resumen = evaluar_ventanas(
            serie=serie,
            crear_modelo=fabrica(nombre),
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

    # MAE es la métrica principal (decisión del 27/10); MAPE como referencia.
    for ventana in ventanas:
        r = resumen[resumen["ventana"] == ventana]
        print(f"\n{ventana} (MAE = métrica principal):")
        print(r[["serie", "MAE", "MAPE_pct", "meses_evaluados", "cobertura_pct"]]
              .round(2).to_string(index=False))
    print(f"\nGuardado en {out / 'sarimax.csv'}")
    print("Comparación formal (MAE + DM/bootstrap vs naive_estacional): protocolo_largo.py")


if __name__ == "__main__":
    main()
