"""Suma contable del biodiésel (SCRUM-60), enchufada al protocolo (SCRUM-43).

Estima la producción sumando los destinos del biodiésel:

    predicción(t) = demanda_interna_est(t) + expo_est(t) + otras_ventas_t1(t)

Las tres partes salen de ``construir_features`` (SCRUM-59), así que respetan la
disponibilidad temporal y no usan datos publicados después de estimar. Cada
predicción se puede explicar por componente: es lo que pidió la BCR.

Por qué no se estima una regresión
----------------------------------
Producción = ventas + exportaciones + variación de stock, así que los
coeficientes se fijan en 1 por identidad contable. Con pocos datos y
exportaciones a saltos, los coeficientes estimados son inestables: en la prueba
del prototipo el MAE subió de ~22.000 a ~25.000 tn, y agregar una corrección del
error (promedio reciente o AR(1)) tampoco mejoró.

Solo biodiésel: en bioetanol la producción no sigue a las ventas del mes (la
caña se produce en la zafra y se vende todo el año) y el modelo daba peor que
el X-13.

Piso práctico de error
----------------------
Si se conocieran las ventas y exportaciones reales del mes, el único error
restante sería la variación de stock. Ese error no se puede predecir con datos
públicos. Es una referencia, no un límite estricto (ver docs/suma_contable.md).

Uso, desde la raíz del proyecto:

    python scripts/suma_contable.py                # backtest
    python scripts/suma_contable.py --con-holdout  # agrega el holdout (SCRUM-34)

Salidas en results/:
    suma_contable_predicciones.csv   predicción, error y aporte de cada parte, por mes
    suma_contable_metricas.csv       métricas del modelo
    suma_contable_piso.csv           piso práctico de error
    suma_contable_diferencias.csv    contra el naive y el X-13 BCR (Diebold-Mariano)

Requiere haber corrido antes ``protocolo_largo.py`` (usa sus predicciones).
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

from build_db import leer_dataset  # noqa: E402
from construir_features import OBJETIVOS, construir_features  # noqa: E402
from evaluacion import comparar_modelos, evaluar_ventanas, ventanas_protocolo  # noqa: E402

COMPONENTES = ("demanda_interna_est", "expo_est", "otras_ventas_t1")
INICIO_ENTRENAMIENTO = "2012-01"  # INDEC arranca en 2012
REFERENCIAS = ("naive", "x13_bcr")

_BASE: pd.DataFrame | None = None


def _base() -> pd.DataFrame:
    global _BASE
    if _BASE is None:
        _BASE = leer_dataset()
    return _BASE


class ModeloSumaContable:
    """Cumple ``fit(serie)`` / ``predict()``; no estima parámetros.

    ``fit`` solo usa la serie para saber qué mes se estima. Después de ``fit``,
    ``contribuciones()`` devuelve el aporte de cada parte en toneladas.
    """

    def __init__(self, base: pd.DataFrame | None = None) -> None:
        self.base = base
        self._fila: pd.Series | None = None

    def fit(self, serie: pd.Series) -> "ModeloSumaContable":
        indice = serie.index
        if not isinstance(indice, pd.PeriodIndex):
            indice = pd.PeriodIndex(pd.to_datetime(indice), freq="M")
        fecha_corte = indice.max() + 1
        base = _base() if self.base is None else self.base
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # aviso de que INDEC arranca en 2012
            X, _ = construir_features(
                "biodiesel", fecha_corte, base=base, con_calendario=False,
                incluir=("contables",), contables_en_log=False,
            )
        self._fila = X.loc[fecha_corte, list(COMPONENTES)].astype(float)
        return self

    def predict(self) -> float:
        return float(self._fila.sum())

    def contribuciones(self) -> dict[str, float]:
        return {c: float(self._fila[c]) for c in COMPONENTES}


def serie_biodiesel(base: pd.DataFrame) -> pd.Series:
    s = base[OBJETIVOS["biodiesel"]].dropna().astype(float)
    s.index = pd.PeriodIndex(pd.to_datetime(s.index), freq="M")
    return s.sort_index()


def contribuciones_por_mes(serie: pd.Series, meses, base: pd.DataFrame) -> pd.DataFrame:
    """Una fila por mes con el aporte de cada componente, en toneladas."""
    filas = []
    for mes in meses:
        modelo = ModeloSumaContable(base).fit(serie[serie.index < mes])
        filas.append({"fecha": mes.to_timestamp(), **modelo.contribuciones()})
    return pd.DataFrame(filas)


def piso_practico(base: pd.DataFrame, ventanas: dict) -> pd.DataFrame:
    """MAE que quedaría con las ventas y exportaciones reales del mes.

    El residuo es la variación de stock. Se calcula con exportaciones de la
    Secretaría, porque son las que cierran la identidad contable.
    """
    b = base.copy()
    b.index = pd.PeriodIndex(pd.to_datetime(b.index), freq="M")
    ventas = (b["biodiesel_ventas_corte_tn"] + b["biodiesel_exportaciones_tn"]
              + b["biodiesel_otras_ventas_tn"])
    error = ventas - b[OBJETIVOS["biodiesel"]]
    filas = []
    for nombre, (inicio, fin) in ventanas.items():
        e = error.loc[inicio:fin].dropna()
        filas.append({"ventana": nombre, "inicio": inicio, "fin": fin, "meses": len(e),
                      "MAE_piso_tn": e.abs().mean(), "RMSE_piso_tn": np.sqrt((e ** 2).mean())})
    return pd.DataFrame(filas)


def comparar(detalle: pd.DataFrame, predicciones: pd.DataFrame) -> pd.DataFrame:
    """Suma contable contra cada referencia, ventana por ventana."""
    filas = []
    for ventana, propio in detalle.groupby("ventana"):
        for ref in REFERENCIAS:
            otro = predicciones[(predicciones["serie"] == "biodiesel")
                                & (predicciones["modelo"] == ref)
                                & (predicciones["ventana"] == ventana)]
            r = comparar_modelos(propio, otro, perdida="ae")
            filas.append({"ventana": ventana, "contra": ref, **r})
    return pd.DataFrame(filas)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--con-holdout", action="store_true",
                    help="agrega el holdout (correr una sola vez, en SCRUM-34)")
    args = ap.parse_args()

    base = _base()
    serie = serie_biodiesel(base)
    ventanas = ventanas_protocolo(serie.index[-1])
    if not args.con_holdout:
        ventanas = {"backtest": ventanas["backtest"]}

    detalle, metricas = evaluar_ventanas(
        serie, lambda: ModeloSumaContable(base), INICIO_ENTRENAMIENTO, ventanas,
        nombre_serie="biodiesel", nombre_modelo="suma_contable",
    )
    meses = pd.to_datetime(detalle["fecha"]).dt.to_period("M")
    aportes = contribuciones_por_mes(serie, meses, base)
    predicciones = detalle.merge(aportes, on="fecha", how="left")
    suma = predicciones[list(COMPONENTES)].sum(axis=1)
    if not np.allclose(suma, predicciones["prediccion"]):
        raise ValueError("Los componentes no suman la predicción.")

    protocolo = pd.read_csv(RAIZ / "results" / "protocolo_predicciones.csv",
                            parse_dates=["fecha"])
    diferencias = comparar(detalle, protocolo)
    piso = piso_practico(base, ventanas)

    out = RAIZ / "results"
    predicciones.to_csv(out / "suma_contable_predicciones.csv", index=False)
    metricas.to_csv(out / "suma_contable_metricas.csv", index=False)
    piso.to_csv(out / "suma_contable_piso.csv", index=False)
    diferencias.to_csv(out / "suma_contable_diferencias.csv", index=False)

    print(metricas[["ventana", "MAE", "MAPE_pct", "acierto_signo_pct",
                    "meses_evaluados"]].round(2).to_string(index=False))
    print(piso.round(1).to_string(index=False))
    print(diferencias[["ventana", "contra", "diferencia_media", "ic_inf", "ic_sup",
                       "dm", "dm_p_valor"]].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
