"""CCF sin leakage y tabla de candidatas (SCRUM-28).

Calcula la correlación cruzada (CCF) de cada variable externa con cada serie de
producción, sobre series diferenciadas (diferencia del logaritmo), usando **solo
datos anteriores a septiembre 2021** (inicio del backtest de SCRUM-43). Así
ninguna decisión que alimenta al modelo mira meses del backtest o del holdout.

La CCF es **exploratoria**: sirve para elegir qué rezagos probar, no para
descartar variables. Una variable se mantiene como candidata si tiene mecanismo
económico y está disponible a tiempo (tabla de SCRUM-26), aunque su CCF sea
débil — sobre todo las que arrancan en 2018 (precios regulados, margen), donde
la ventana pre-2021 es corta y la correlación es poco confiable.

Lee la base unificada (``build_db.leer_dataset``) y escribe
``results/ccf_candidatas.csv`` con el mejor rezago por par (variable, target).

Uso:
    python scripts/ccf_candidatas.py
"""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from build_db import leer_dataset

RAIZ = Path(__file__).resolve().parent.parent
CORTE = pd.Timestamp("2021-09-01")  # anti-leakage: nada del backtest/holdout
MAX_LAG = 12
MIN_OBS = 24  # mínimo de pares para calcular una correlación

TARGETS = {
    "biodiesel": "produccion_biodiesel_tn",
    "bioetanol_total": "produccion_bioetanol_total_m3",
    "bioetanol_maiz": "produccion_bioetanol_maiz_m3",
    "bioetanol_cana": "produccion_bioetanol_cana_m3",
}
# Candidatas con mecanismo económico (agregadas, no por grado de combustible).
CANDIDATAS = [
    "precio_biodiesel_ars_tn",
    "precio_bioetanol_cana_ars_l",
    "precio_bioetanol_maiz_ars_l",
    "precio_soja_pizarra_ars_tn",
    "precio_maiz_pizarra_ars_tn",
    "tipo_cambio_promedio",
    "ventas_gasoil_total_m3",
    "ventas_nafta_total_m3",
    "molienda_soja_tn",
    "margen_bioetanol_maiz",
    "margen_domestico_biodiesel",  # SCRUM-51, candidata estrella del biodiésel
]


def dlog(s: pd.Series) -> pd.Series:
    """Diferencia del logaritmo (tasa de variación mensual), solo valores > 0."""
    s = s.astype(float)
    s = s[s > 0]
    return np.log(s).diff()


def mejor_rezago(prod: pd.Series, exo: pd.Series) -> tuple | None:
    """Rezago 0..MAX_LAG con mayor |correlación| entre prod[t] y exo[t-k].

    Returns:
        ``(rezago, corr, n)`` o ``None`` si no hay suficientes pares.
    """
    mejor = None
    for k in range(MAX_LAG + 1):
        j = pd.concat([prod, exo.shift(k)], axis=1).dropna()
        if len(j) >= MIN_OBS:
            c = j.iloc[:, 0].corr(j.iloc[:, 1])
            if mejor is None or (not np.isnan(c) and abs(c) > abs(mejor[1])):
                mejor = (k, c, len(j))
    return mejor


def main() -> None:
    """Calcula la CCF sin leakage y la guarda en results/ccf_candidatas.csv."""
    warnings.filterwarnings("ignore")
    df = leer_dataset().sort_index()
    filas = []
    for nombre, ty in TARGETS.items():
        prod = dlog(df[ty])
        prod = prod[prod.index < CORTE]
        for ex in CANDIDATAS:
            if ex not in df.columns:
                continue
            exo = dlog(df[ex])
            exo = exo[exo.index < CORTE]
            r = mejor_rezago(prod, exo)
            if r:
                filas.append([nombre, ex, r[0], round(r[1], 3), r[2]])
    out = pd.DataFrame(filas, columns=["target", "variable", "mejor_rezago", "corr", "n"])
    (RAIZ / "results").mkdir(exist_ok=True)
    out.to_csv(RAIZ / "results" / "ccf_candidatas.csv", index=False)
    print(f"Escrito results/ccf_candidatas.csv ({len(out)} filas, CCF con datos < {CORTE:%Y-%m})")
    print(out.sort_values(["target", "corr"], key=lambda s: s.abs() if s.name == "corr" else s,
                          ascending=[True, False]).to_string(index=False))


if __name__ == "__main__":
    main()
