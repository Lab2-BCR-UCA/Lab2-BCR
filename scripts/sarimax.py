"""SARIMAX con variables externas (SCRUM-29), enchufado al protocolo (SCRUM-43).

``ModeloSARIMAX`` cumple la interfaz ``fit(serie)`` / ``predict()`` que usa
``evaluacion.evaluar_modelo``. Las exógenas las arma ``construir_features``
(SCRUM-59) respetando la disponibilidad temporal (SCRUM-26), así que son las
mismas que usan el elastic net (SCRUM-54) y la suma contable (N4).

SARIMA captura inercia y estacionalidad (en log); las exógenas explican el
desvío del mes. Se modela en log para las 4 series (caña incluida).

Bioetanol total
---------------
Se evalúan DOS variantes (para ver si conviene): el total modelado **directo**,
y el total como **suma de las predicciones de maíz y caña** (``ModeloSARIMAXSumaTotal``).

Orden
-----
Por defecto ``(1,1,1)(0,1,1,12)`` en log (d=1). El EDA (SCRUM-45) marca con
ADF+KPSS solo biodiésel y caña como estacionarias en log; total y maíz dan
contradictorio → d=1. El experimento controlado (``experimento_d.py``, mismo
p,q,P,Q, solo cambia d; MAE con IC por bootstrap de bloques) está versionado en
``results/experimento_d.csv``: en biodiésel d=1 gana y es distinguible
(DM p=0,025), en caña d=0 y d=1 no se distinguen. Por eso d=1 en las 4. El
orden, con ``--buscar-orden``, se elige UNA vez con datos < sep-2021
(pre-backtest) y se fija: consistente con el protocolo, sin leakage.

Desempeño (backtest, MAE): biodiésel 29.221, total 7.528, maíz 6.216, caña
7.628. El UCM tiene menor error que el SARIMAX en maíz y caña (MAPE 7,9 vs 10,4
y 20,5 vs 26,8); empatan en biodiésel y total. El SARIMAX no es el mejor en
ninguna serie; la mejora real para biodiésel espera las exportaciones (INDEC).

Alcance (SCRUM-29): el biodiésel corre **sin exógenas** (las internas lo
desestabilizan, ver construir_features) y la caña **sin azúcar**, porque esas
variables todavía no están en la base. Sumarlas queda en un follow-up (SCRUM-62)
bloqueado por SCRUM-48 (corte), SCRUM-58 (azúcar) y SCRUM-57 (INDEC).

Diagnóstico e intervalos
------------------------
``--diagnosticos`` reporta Ljung-Box (autocorrelación de residuos) y Jarque-Bera
(normalidad). ``--intervalos`` da el pronóstico puntual con bandas 80% y 95%
para el último mes (anexo; la BCR pidió un número, no rangos). El total **no**
lleva intervalo: no se pueden sumar los de maíz y caña sin su covarianza; se
reportan los de maíz y caña por separado.

Uso, desde la raíz del proyecto:

    python scripts/sarimax.py                 # walk-forward (backtest; default)
    python scripts/sarimax.py --con-holdout   # agrega el holdout (correr al final)
    python scripts/sarimax.py --buscar-orden  # elige orden por AIC/ADF+KPSS (exploración)
    python scripts/sarimax.py --diagnosticos  # Ljung-Box + Jarque-Bera por serie
    python scripts/sarimax.py --intervalos    # bandas 80/95 del último mes (anexo)

Salida: results/sarimax.csv. Requiere: pip install statsmodels scipy pandas numpy
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

from scipy.stats import jarque_bera  # noqa: E402
from statsmodels.stats.diagnostic import acorr_ljungbox  # noqa: E402
from statsmodels.tsa.statespace.sarimax import SARIMAX  # noqa: E402
from statsmodels.tsa.stattools import adfuller, kpss  # noqa: E402

from build_db import leer_dataset  # noqa: E402
from construir_features import OBJETIVOS, construir_features  # noqa: E402
from evaluacion import evaluar_ventanas, ventanas_protocolo  # noqa: E402

ORDER_FIJO = (1, 1, 1)
SEASONAL_FIJO = (0, 1, 1, 12)
MIN_OBS_EXOG = 36
CORTE_ORDEN = pd.Timestamp("2021-09-01")
INICIO_ENTRENAMIENTO = {
    "biodiesel": "2008-01",
    "bioetanol_total": "2013-01",
    "bioetanol_maiz": "2012-09",
    "bioetanol_cana": "2013-01",
}
COMPONENTES_TOTAL = ("bioetanol_maiz", "bioetanol_cana")  # total = suma de estos
GRILLA_PQ = list(itertools.product(range(3), range(3)))
GRILLA_SEASONAL = list(itertools.product((0, 1), (0, 1), (0, 1)))

_BASE: pd.DataFrame | None = None
_ORDENES: dict[str, tuple] = {}


def _base() -> pd.DataFrame:
    global _BASE
    if _BASE is None:
        _BASE = leer_dataset()
    return _BASE


def _serie_base(objetivo: str) -> pd.Series:
    """Serie objetivo de la base, índice mensual (Period)."""
    s = _base()[OBJETIVOS[objetivo]].dropna().astype(float)
    if not isinstance(s.index, pd.PeriodIndex):
        s.index = pd.PeriodIndex(pd.to_datetime(s.index), freq="M")
    return s.sort_index()


def _d_por_tests(y_log: pd.Series, alfa: float = 0.05) -> int:
    """``d`` según ADF + KPSS juntos (regla del EDA, SCRUM-45)."""
    s = y_log.dropna()
    if len(s) < 24:
        return 1
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            adf_estac = adfuller(s, autolag="AIC")[1] < alfa
            kpss_estac = kpss(s, regression="c", nlags="auto")[1] > alfa
        return 0 if (adf_estac and kpss_estac) else 1
    except Exception:
        return 1


def elegir_orden(y_log: pd.Series) -> tuple:
    """Orden ``(order, seasonal_order)``: ``d`` lo fija ADF+KPSS, el resto el AIC."""
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
    return (mejor[1], mejor[2]) if mejor else (ORDER_FIJO, SEASONAL_FIJO)


def _orden_de(objetivo: str) -> tuple:
    """Orden por AIC/ADF+KPSS, elegido UNA vez con datos < CORTE_ORDEN, cacheado."""
    if objetivo not in _ORDENES:
        s = _serie_base(objetivo)
        ini = pd.Period(INICIO_ENTRENAMIENTO[objetivo], freq="M")
        s = s[(s.index >= ini) & (s.index < CORTE_ORDEN.to_period("M"))]
        _ORDENES[objetivo] = elegir_orden(np.log(s.asfreq("M")))
    return _ORDENES[objetivo]


class ModeloSARIMAX:
    """SARIMAX en log con exógenas de ``construir_features``.

    Fábrica: ``lambda: ModeloSARIMAX("biodiesel")``. Orden fijo por defecto.
    """

    def __init__(self, objetivo: str, order=ORDER_FIJO, seasonal_order=SEASONAL_FIJO) -> None:
        self.objetivo = objetivo
        self.order = order
        self.seasonal_order = seasonal_order
        self._res = None
        self._x_pred: pd.DataFrame | None = None

    def fit(self, serie: pd.Series) -> "ModeloSARIMAX":
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
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            f = self._res.forecast(1, exog=self._x_pred)
        return float(np.exp(np.asarray(f)[0]))

    def predict_intervalo(self, niveles=(0.8, 0.95)) -> dict:
        """Pronóstico puntual + bandas por nivel (en unidades originales).

        Devuelve ``{"punto": x, 0.8: (lo, hi), 0.95: (lo, hi)}``. Las bandas
        salen del intervalo en log y se exponencian (asimétrico en nivel).
        """
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fc = self._res.get_forecast(1, exog=self._x_pred)
        out = {"punto": float(np.exp(np.asarray(fc.predicted_mean)[0]))}
        for nv in niveles:
            ci = np.asarray(fc.conf_int(alpha=1 - nv))
            out[nv] = (float(np.exp(ci[0, 0])), float(np.exp(ci[0, 1])))
        return out


class ModeloSARIMAXSumaTotal:
    """Bioetanol total como SUMA de las predicciones de maíz y caña (DoD).

    Cumple fit/predict: ``fit`` recibe la serie total (solo para el mes a
    estimar) y ajusta un ModeloSARIMAX por componente; ``predict`` suma.
    Sin intervalo: no se pueden sumar los de los componentes sin su covarianza.
    """

    def __init__(self) -> None:
        self._sub: dict[str, ModeloSARIMAX] = {}

    def fit(self, serie_total: pd.Series) -> "ModeloSARIMAXSumaTotal":
        y = serie_total.copy()
        if not isinstance(y.index, pd.PeriodIndex):
            y.index = pd.PeriodIndex(pd.to_datetime(y.index), freq="M")
        fecha_corte = y.sort_index().index[-1] + 1
        self._sub = {}
        for comp in COMPONENTES_TOTAL:
            s = _serie_base(comp)
            s = s[s.index < fecha_corte]
            self._sub[comp] = ModeloSARIMAX(comp).fit(s)
        return self

    def predict(self) -> float:
        return float(sum(m.predict() for m in self._sub.values()))


def diagnosticos(objetivos=tuple(OBJETIVOS)) -> pd.DataFrame:
    """Ljung-Box (lag 12) y Jarque-Bera sobre los residuos del modelo final.

    Ajusta cada serie con el orden fijo sobre toda la historia disponible y
    mira los residuos (p>0,05: no se rechaza buena especificación/normalidad).
    """
    filas = []
    for objetivo in objetivos:
        s = _serie_base(objetivo)
        m = ModeloSARIMAX(objetivo).fit(s)
        resid = pd.Series(np.asarray(m._res.resid)).iloc[13:].dropna()  # saca el burn-in
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            lb_p = float(acorr_ljungbox(resid, lags=[12], return_df=True)["lb_pvalue"].iloc[0])
            jb_p = float(jarque_bera(resid)[1])
        filas.append({"serie": objetivo, "ljung_box_p": round(lb_p, 4),
                      "jarque_bera_p": round(jb_p, 4),
                      "resid_ok": lb_p > 0.05, "resid_normal": jb_p > 0.05})
    return pd.DataFrame(filas)


def intervalos_ultimo(niveles=(0.8, 0.95)) -> pd.DataFrame:
    """Bandas 80/95 del pronóstico del próximo mes, por serie (anexo).

    Para el total NO se suman los intervalos de los componentes (falta la
    covarianza): se reportan maíz y caña por separado y se marca el total.
    """
    filas = []
    for objetivo in OBJETIVOS:
        s = _serie_base(objetivo)
        m = ModeloSARIMAX(objetivo).fit(s)
        iv = m.predict_intervalo(niveles)
        fila = {"serie": objetivo, "mes": str(s.index[-1] + 1), "punto": round(iv["punto"], 1)}
        for nv in niveles:
            fila[f"inf_{int(nv*100)}"] = round(iv[nv][0], 1)
            fila[f"sup_{int(nv*100)}"] = round(iv[nv][1], 1)
        filas.append(fila)
    df = pd.DataFrame(filas)
    print("Nota: el total se reporta directo; su suma (maíz+caña) no lleva "
          "intervalo porque faltaría la covarianza entre componentes.")
    return df


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--con-holdout", action="store_true",
                    help="agrega el holdout (por defecto solo backtest)")
    ap.add_argument("--buscar-orden", action="store_true",
                    help="elige el orden por AIC/ADF+KPSS (exploración; no el default)")
    ap.add_argument("--diagnosticos", action="store_true", help="Ljung-Box + Jarque-Bera")
    ap.add_argument("--intervalos", action="store_true", help="bandas 80/95 del último mes")
    args = ap.parse_args()

    if args.diagnosticos:
        print("Diagnóstico de residuos (p>0,05 = no se rechaza):")
        print(diagnosticos().to_string(index=False))
        return
    if args.intervalos:
        print("Intervalos del próximo mes (anexo):")
        print(intervalos_ultimo().to_string(index=False))
        return

    series = {n: _serie_base(n) for n in OBJETIVOS}
    ultimo = min(s.index[-1] for s in series.values())
    ventanas = ventanas_protocolo(ultimo)
    if not args.con_holdout:
        ventanas = {"backtest": ventanas["backtest"]}

    def fabrica(nombre):
        if args.buscar_orden:
            o, so = _orden_de(nombre)
            return lambda: ModeloSARIMAX(nombre, o, so)
        return lambda: ModeloSARIMAX(nombre)

    # (serie_objetivo, variante, fábrica). El total va directo Y como suma.
    configs = [
        ("biodiesel", "directo", fabrica("biodiesel")),
        ("bioetanol_maiz", "directo", fabrica("bioetanol_maiz")),
        ("bioetanol_cana", "directo", fabrica("bioetanol_cana")),
        ("bioetanol_total", "directo", fabrica("bioetanol_total")),
        ("bioetanol_total", "suma_maiz_cana", lambda: ModeloSARIMAXSumaTotal()),
    ]

    resumenes = []
    for objetivo, variante, crear in configs:
        _, resumen = evaluar_ventanas(
            serie=series[objetivo],
            crear_modelo=crear,
            inicio_entrenamiento=INICIO_ENTRENAMIENTO[objetivo],
            ventanas=ventanas,
            nombre_serie=objetivo,
            nombre_modelo=f"sarimax_{variante}",
        )
        resumen["variante"] = variante
        resumenes.append(resumen)

    resumen = pd.concat(resumenes, ignore_index=True)
    out = RAIZ / "results"
    out.mkdir(exist_ok=True)
    resumen.to_csv(out / "sarimax.csv", index=False)

    # MAE es la métrica principal (decisión del 27/10); MAPE como referencia.
    for ventana in ventanas:
        r = resumen[resumen["ventana"] == ventana]
        print(f"\n{ventana} (MAE = métrica principal):")
        print(r[["serie", "variante", "MAE", "MAPE_pct", "meses_evaluados"]]
              .round(2).to_string(index=False))
    print(f"\nGuardado en {out / 'sarimax.csv'}")
    print("Comparación formal (MAE + DM/bootstrap vs naive_estacional): protocolo_largo.py")


if __name__ == "__main__":
    main()
