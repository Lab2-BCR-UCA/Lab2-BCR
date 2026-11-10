"""Regresión regularizada (elastic net) con variables externas (SCRUM-54).

Una regresión lineal con todas las candidatas, donde la penalización L1/L2
elige las variables. Es el modelo más explicable para la BCR: cada predicción
es una suma de aportes en toneladas o m³.

Modelos (``MODELOS``)
---------------------
- ``bioetanol_maiz`` y ``bioetanol_cana``: modelo principal del bioetanol.
- ``bioetanol_total``: suma de las predicciones de maíz y caña.
- ``biodiesel`` en dos versiones, para comparar contra la suma contable
  (SCRUM-60):
    * ``sin_contables``: sin ``demanda_interna_est`` ni ``expo_est``; solo el
      resto de las candidatas.
    * ``con_contables``: las contables (en toneladas) más el resto, para ver si
      el resto agrega algo.
- Dos variantes de control del biodiésel con contables, para SCRUM-53:
    * ``sin_eventos``: sin excluir los meses de eventos (mide el aporte de la
      limpieza del entrenamiento).
    * ``dummy_evento``: sin excluir eventos y con un indicador "corte efectivo
      del mes anterior < 2%" como predictor (la dummy como alternativa a la
      limpieza; la prueba que pide SCRUM-53).

Especificación
--------------
- Target en niveles con dummies de mes: los coeficientes se leen en tn o m³.
- Features del constructor común (``construir_features``, SCRUM-59) con sus
  rezagos de disponibilidad, más los rezagos propios 1, 2 y 12.
- Todo lo que se ajusta con datos (imputación, estandarización de X e y,
  lambda y mezcla L1/L2) se ajusta **solo con el entrenamiento de cada
  iteración**. Lambda y la mezcla salen de ``TimeSeriesSplit`` dentro del
  entrenamiento, reajustando imputación y estandarización en cada fold
  (``elegir_hiperparametros``). Nunca hay validación aleatoria.
- Las variables con historia más corta que la ventana (márgenes, molienda) se
  imputan con la media del entrenamiento más un indicador de faltante. La fila
  del mes a estimar siempre está completa (lo exige el constructor).
- Los meses de eventos terminados se excluyen del ajuste (SCRUM-53).
- La predicción se recorta en 0 (la producción no puede ser negativa).

Uso, desde la raíz del proyecto:

    python scripts/elastic_net.py                 # backtest
    python scripts/elastic_net.py --con-holdout   # agrega el holdout (SCRUM-34)
    python scripts/elastic_net.py --solo biodiesel_con_contables

Salidas en results/:
    elastic_net_predicciones.csv   predicción y error por modelo y mes
    elastic_net_metricas.csv       métricas por modelo y ventana
    elastic_net_coeficientes.csv   coeficiente de cada variable en cada iteración
    elastic_net_seleccion.csv      frecuencia de selección y signo por variable (solo backtest)
    elastic_net_diferencias.csv    Diebold-Mariano contra las referencias

Requiere haber corrido ``protocolo_largo.py`` (naive y X-13 BCR). La comparación
contra la suma contable usa ``results/suma_contable_predicciones.csv``
(SCRUM-60); si no está, se saltea con un aviso.
"""

from __future__ import annotations

import argparse
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import TransformedTargetRegressor
from sklearn.exceptions import ConvergenceWarning
from sklearn.impute import SimpleImputer
from sklearn.linear_model import ElasticNet, enet_path
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))

from build_db import leer_dataset  # noqa: E402
from construir_features import OBJETIVOS, construir_features  # noqa: E402
from evaluacion import FIN_BACKTEST, comparar_modelos, evaluar_ventanas, ventanas_protocolo  # noqa: E402
from eventos import excluir_eventos  # noqa: E402

ALPHAS = np.logspace(-3, 1, 20)          # sobre y estandarizada
L1_RATIOS = (0.1, 0.5, 0.9, 1.0)
N_FOLDS = 5
MAX_ITER = 10_000
TOL = 1e-4
REFERENCIAS = ("naive", "x13_bcr")

# Candidatas del biodiésel fuera de la descomposición contable (SCRUM-28/48/49).
_BIODIESEL_RESTO = [
    ("ventas_gasoil_total_m3", 0),
    ("molienda_soja_tn", 0),
    ("aceite_soja_usd_tn", 0),
    ("margen_domestico_biodiesel", 0),
    ("corte_biodiesel_nominal_pct", 0),
    ("corte_biodiesel_cotab_pct", 0),
    ("corte_efectivo_biodiesel", 1),
]


@dataclass(frozen=True)
class Config:
    """Qué ve cada modelo. ``inicio`` es el primer mes de entrenamiento."""
    objetivo: str
    inicio: str
    exogenas: list = field(default_factory=list)
    contables: bool = False
    eventos: bool = True
    dummy_evento: bool = False
    # Variables cuyo VALOR se neutraliza (constante donde hay dato) pero que
    # conservan sus NaN, así el indicador de faltante del imputador se mantiene.
    # Sirve para medir el aporte del valor sin perder la dummy de "antes de que
    # exista la serie" (SCRUM-31, margen doméstico desde 2018).
    aplanar: tuple = ()


MODELOS: dict[str, Config] = {
    "bioetanol_maiz": Config("bioetanol_maiz", "2012-09", [
        ("ventas_nafta_total_m3", 0), ("margen_bioetanol_maiz", 0),
        ("corte_efectivo_bioetanol_maiz", 1)]),
    "bioetanol_cana": Config("bioetanol_cana", "2013-01", [
        ("ventas_nafta_total_m3", 0), ("azucar_usd_kg", 0),
        ("corte_efectivo_bioetanol_cana", 1)]),
    # Mismo inicio (2012-01, por INDEC) en todas las versiones del biodiésel: así
    # la comparación mide las variables y no el cambio de ventana (review SCRUM-62).
    "biodiesel_sin_contables": Config("biodiesel", "2012-01", _BIODIESEL_RESTO),
    "biodiesel_con_contables": Config("biodiesel", "2012-01", _BIODIESEL_RESTO, contables=True),
    "biodiesel_con_contables_sin_eventos": Config(
        "biodiesel", "2012-01", _BIODIESEL_RESTO, contables=True, eventos=False),
    # La dummy se prueba como alternativa a limpiar el entrenamiento: sin excluir
    # eventos (con la exclusión, casi todos sus meses en 1 quedan fuera del ajuste).
    "biodiesel_con_contables_dummy_evento": Config(
        "biodiesel", "2012-01", _BIODIESEL_RESTO, contables=True, eventos=False,
        dummy_evento=True),
}
COMPONENTES_TOTAL = ("bioetanol_maiz", "bioetanol_cana")

_BASE: pd.DataFrame | None = None


def _base() -> pd.DataFrame:
    global _BASE
    if _BASE is None:
        _BASE = leer_dataset()
    return _BASE


def _a_periodos(indice) -> pd.PeriodIndex:
    if isinstance(indice, pd.PeriodIndex):
        return indice.asfreq("M")
    return pd.PeriodIndex(pd.to_datetime(indice), freq="M")


def serie_objetivo(objetivo: str, base: pd.DataFrame | None = None) -> pd.Series:
    base = _base() if base is None else base
    s = base[OBJETIVOS[objetivo]].dropna().astype(float)
    s.index = _a_periodos(s.index)
    return s.sort_index()


def armar_X(config: Config, fecha_corte: pd.Period, base: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Features hasta ``fecha_corte`` (la última fila es el mes a estimar)."""
    incluir = ("dummies", "lags") + (("contables",) if config.contables else ())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # aviso de que INDEC arranca en 2012
        X, y = construir_features(
            config.objetivo, fecha_corte, base=base, con_calendario=False,
            incluir=incluir, exogenas_extra=list(config.exogenas),
            contables_en_log=False,
        )
    if config.dummy_evento:
        # Calculable en el momento: corte efectivo de t-1 (rezago 1, SCRUM-26).
        ce = base["corte_efectivo_biodiesel"].astype(float)
        ce.index = _a_periodos(ce.index)
        X["dummy_corte_bajo_t1"] = (ce.shift(1) < 2).astype(float).reindex(X.index)
        X.loc[ce.shift(1).reindex(X.index).isna(), "dummy_corte_bajo_t1"] = np.nan
    for col in config.aplanar:
        if col not in X.columns:
            raise KeyError(f"No se puede aplanar '{col}': no está entre las features.")
        X.loc[X[col].notna(), col] = 0.0
    X = X.loc[pd.Period(config.inicio, freq="M"):]
    return X, y


def _pipeline(alpha: float = 1.0, l1_ratio: float = 0.5) -> TransformedTargetRegressor:
    """Imputación + estandarización de X e y + elastic net, en un solo estimador."""
    regresion = Pipeline([
        ("imputar", SimpleImputer(strategy="mean", add_indicator=True, keep_empty_features=True)),
        ("estandarizar", StandardScaler()),
        ("en", ElasticNet(alpha=alpha, l1_ratio=l1_ratio, max_iter=MAX_ITER, tol=TOL)),
    ])
    return TransformedTargetRegressor(regressor=regresion, transformer=StandardScaler())


def elegir_hiperparametros(X_tr: pd.DataFrame, y_tr: np.ndarray) -> tuple[float, float]:
    """Lambda y mezcla L1/L2 por ``TimeSeriesSplit`` dentro del entrenamiento.

    En cada fold la imputación y la estandarización (de X y de y) se ajustan
    solo con la parte de entrenamiento del fold. Para cada mezcla se recorre la
    grilla de lambdas con ``enet_path`` (arranque en caliente: mucho más rápido
    que un ajuste por punto). Criterio: MAE promedio en los folds de validación.
    """
    folds = TimeSeriesSplit(n_splits=min(N_FOLDS, max(2, len(X_tr) // 24)))
    alphas = np.sort(ALPHAS)[::-1]                     # enet_path va de mayor a menor
    error = np.zeros((len(L1_RATIOS), len(alphas)))
    Xv = X_tr.to_numpy(dtype=float)
    for tr, va in folds.split(Xv):
        imp = SimpleImputer(strategy="mean", add_indicator=True,
                            keep_empty_features=True).fit(Xv[tr])
        esc = StandardScaler().fit(imp.transform(Xv[tr]))
        z_tr, z_va = esc.transform(imp.transform(Xv[tr])), esc.transform(imp.transform(Xv[va]))
        media, desvio = y_tr[tr].mean(), y_tr[tr].std() or 1.0
        for i, l1 in enumerate(L1_RATIOS):
            # Con X e y centradas el intercepto es 0, así que enet_path no lo necesita.
            _, coefs, _ = enet_path(z_tr, (y_tr[tr] - media) / desvio, l1_ratio=l1,
                                    alphas=alphas, max_iter=MAX_ITER, tol=TOL)
            pred = (z_va @ coefs) * desvio + media
            error[i] += np.abs(pred - y_tr[va][:, None]).mean(axis=0)
    i, j = np.unravel_index(np.argmin(error), error.shape)
    return float(alphas[j]), float(L1_RATIOS[i])


class ModeloElasticNet:
    """Cumple ``fit(serie, excluir=None)`` / ``predict()`` del protocolo.

    ``fit`` solo usa la serie para saber qué mes se estima y qué meses excluir;
    las features salen del constructor con la misma base.
    """

    def __init__(self, config: Config, base: pd.DataFrame | None = None) -> None:
        self.config = config
        self.base = _base() if base is None else base

    def fit(self, serie: pd.Series, excluir=None) -> "ModeloElasticNet":
        idx = _a_periodos(serie.index)
        fecha = idx.max() + 1
        X, y = armar_X(self.config, fecha, self.base)

        entrenamiento = X.index[X.index < fecha]
        if excluir is not None:
            fuera = set(idx[np.asarray(excluir, dtype=bool)])
            entrenamiento = entrenamiento[[m not in fuera for m in entrenamiento]]
        y_tr = y.reindex(entrenamiento)
        entrenamiento = entrenamiento[y_tr.notna().to_numpy()]
        X_tr = X.loc[entrenamiento]
        y_tr = y.loc[entrenamiento]
        if len(X_tr) < 36:
            raise ValueError(f"Muy pocos meses de entrenamiento ({len(X_tr)}).")

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ConvergenceWarning)
            self.alpha_, self.l1_ratio_ = elegir_hiperparametros(X_tr, y_tr.to_numpy())
            self.mejor_ = _pipeline(self.alpha_, self.l1_ratio_).fit(X_tr, y_tr.to_numpy())

        self.fila_ = X.loc[[fecha]]
        self.fecha_ = fecha
        self.n_train_ = len(X_tr)
        return self

    def predict(self) -> float:
        return max(0.0, float(self.mejor_.predict(self.fila_)[0]))

    def coeficientes(self) -> pd.DataFrame:
        """Coeficiente por variable: estandarizado y en unidades del target.

        ``coef_unidades`` = cambio en tn (o m³) por un desvío estándar de la
        variable en el entrenamiento.
        """
        reg = self.mejor_.regressor_
        nombres = reg.named_steps["imputar"].get_feature_names_out()
        coef = reg.named_steps["en"].coef_
        escala_y = float(self.mejor_.transformer_.scale_[0])
        return pd.DataFrame({
            "fecha": self.fecha_.to_timestamp(),
            "variable": nombres,
            "coef_estandarizado": coef,
            "coef_unidades": coef * escala_y,
            "seleccionada": coef != 0,
            "alpha": self.alpha_,
            "l1_ratio": self.l1_ratio_,
            "n_train": self.n_train_,
        })


class ModeloSumaBioetanol:
    """Total de bioetanol = predicción de maíz + predicción de caña."""

    def __init__(self, base: pd.DataFrame | None = None) -> None:
        self.base = _base() if base is None else base

    def fit(self, serie: pd.Series, excluir=None) -> "ModeloSumaBioetanol":
        fecha = _a_periodos(serie.index).max() + 1
        self.partes_ = {}
        for nombre in COMPONENTES_TOTAL:
            s = serie_objetivo(nombre, self.base)
            s = s[s.index < fecha]
            mascara = excluir_eventos(nombre)(s.index, fecha)
            self.partes_[nombre] = ModeloElasticNet(MODELOS[nombre], self.base).fit(s, excluir=mascara)
        return self

    def predict(self) -> float:
        return sum(m.predict() for m in self.partes_.values())


class _Registro:
    """Envuelve un modelo para guardar los coeficientes de cada iteración."""

    def __init__(self, modelo, destino: list) -> None:
        self.modelo, self.destino = modelo, destino

    def fit(self, serie, excluir=None):
        self.modelo.fit(serie, excluir=excluir)
        self.destino.append(self.modelo.coeficientes())
        return self

    def predict(self):
        return self.modelo.predict()


def correr(nombre: str, ventanas: dict, base: pd.DataFrame):
    """Evalúa un modelo con el protocolo. Devuelve detalle, métricas y coeficientes."""
    coefs: list[pd.DataFrame] = []
    if nombre == "bioetanol_total":
        objetivo, inicio, excl = "bioetanol_total", "2013-01", excluir_eventos("bioetanol_total")
        crear = lambda: ModeloSumaBioetanol(base)  # noqa: E731
    else:
        cfg = MODELOS[nombre]
        objetivo, inicio = cfg.objetivo, cfg.inicio
        excl = excluir_eventos(cfg.objetivo) if cfg.eventos else (lambda idx, mes: np.zeros(len(idx), bool))
        crear = lambda: _Registro(ModeloElasticNet(cfg, base), coefs)  # noqa: E731
    detalle, metricas = evaluar_ventanas(
        serie_objetivo(objetivo, base), crear, inicio, ventanas,
        nombre_serie=objetivo, nombre_modelo=f"elastic_net_{nombre}", excluir=excl,
    )
    coef = pd.concat(coefs, ignore_index=True) if coefs else pd.DataFrame()
    if not coef.empty:
        coef.insert(0, "modelo", f"elastic_net_{nombre}")
    return detalle, metricas, coef


def resumen_seleccion(coef: pd.DataFrame) -> pd.DataFrame:
    """Frecuencia de selección y signo de cada variable entre iteraciones."""
    if coef.empty:
        return coef
    g = coef.groupby(["modelo", "variable"])
    out = pd.DataFrame({
        "iteraciones": g.size(),
        "frecuencia_seleccion": g["seleccionada"].mean(),
        "coef_unidades_mediana": g["coef_unidades"].median(),
        "coef_unidades_mediana_si_elegida": g.apply(
            lambda d: d.loc[d["seleccionada"], "coef_unidades"].median(), include_groups=False),
        "pct_signo_positivo_si_elegida": g.apply(
            lambda d: 100 * (d.loc[d["seleccionada"], "coef_unidades"] > 0).mean()
            if d["seleccionada"].any() else np.nan, include_groups=False),
    }).reset_index()
    return out.sort_values(["modelo", "frecuencia_seleccion"], ascending=[True, False])


def comparar(detalle: pd.DataFrame, referencias: pd.DataFrame) -> pd.DataFrame:
    """Cada elastic net contra las referencias de su serie, por ventana (MAE)."""
    filas = []
    for (serie, modelo, ventana), propio in detalle.groupby(["serie", "modelo", "ventana"]):
        candidatos = referencias[(referencias["serie"] == serie) & (referencias["ventana"] == ventana)]
        if modelo.endswith("_sin_eventos"):
            otros = ["elastic_net_biodiesel_con_contables", *REFERENCIAS, "suma_contable"]
        elif modelo.endswith("_dummy_evento"):
            otros = ["elastic_net_biodiesel_con_contables",
                     "elastic_net_biodiesel_con_contables_sin_eventos"]
        else:
            otros = list(REFERENCIAS) + (["suma_contable", "elastic_net_biodiesel_sin_contables"]
                                         if modelo == "elastic_net_biodiesel_con_contables" else [])
        for ref in otros:
            otro = candidatos[candidatos["modelo"] == ref]
            if otro.empty:
                continue
            r = comparar_modelos(propio, otro, perdida="ae")
            filas.append({"serie": serie, "modelo": modelo, "ventana": ventana, "contra": ref, **r})
    return pd.DataFrame(filas)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--con-holdout", action="store_true",
                    help="agrega el holdout (correr una sola vez, en SCRUM-34)")
    ap.add_argument("--solo", nargs="*", default=None, help="correr solo estos modelos")
    args = ap.parse_args()

    base = _base()
    ventanas = ventanas_protocolo(serie_objetivo("biodiesel", base).index[-1])
    if not args.con_holdout:
        ventanas = {"backtest": ventanas["backtest"]}

    nombres = list(MODELOS) + ["bioetanol_total"]
    if args.solo:
        nombres = [n for n in nombres if n in args.solo]

    detalles, metricas, coefs = [], [], []
    for nombre in nombres:
        print(f"... {nombre}", flush=True)
        d, m, c = correr(nombre, ventanas, base)
        detalles.append(d)
        metricas.append(m)
        coefs.append(c)
    detalle = pd.concat(detalles, ignore_index=True)
    metrica = pd.concat(metricas, ignore_index=True)
    coef = pd.concat(coefs, ignore_index=True)

    out = RAIZ / "results"
    referencias = [pd.read_csv(out / "protocolo_predicciones.csv", parse_dates=["fecha"])]
    suma = out / "suma_contable_predicciones.csv"
    if suma.exists():
        referencias.append(pd.read_csv(suma, parse_dates=["fecha"]))
    else:
        print("Aviso: falta results/suma_contable_predicciones.csv (SCRUM-60); "
              "se saltea esa comparación.")
    referencias.append(detalle)
    diferencias = comparar(detalle, pd.concat(referencias, ignore_index=True))

    detalle.to_csv(out / "elastic_net_predicciones.csv", index=False)
    metrica.to_csv(out / "elastic_net_metricas.csv", index=False)
    coef.to_csv(out / "elastic_net_coeficientes.csv", index=False)
    # La selección se resume solo con el backtest: el holdout no se usa para
    # describir ni decidir nada (protocolo, SCRUM-43).
    fin = pd.Period(FIN_BACKTEST, freq="M").to_timestamp(how="end")
    resumen_seleccion(coef[pd.to_datetime(coef["fecha"]) <= fin]).to_csv(
        out / "elastic_net_seleccion.csv", index=False)
    diferencias.to_csv(out / "elastic_net_diferencias.csv", index=False)

    print(metrica[["serie", "modelo", "ventana", "MAE", "MAPE_pct", "acierto_signo_pct",
                   "meses_evaluados"]].round(1).to_string(index=False))
    if not diferencias.empty:
        print(diferencias[["serie", "modelo", "ventana", "contra", "diferencia_media",
                           "ic_inf", "ic_sup", "dm_p_valor"]].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
