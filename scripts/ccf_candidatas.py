"""CCF sin leakage y tabla de candidatas (SCRUM-28).

Calcula la correlación cruzada (CCF) de cada variable externa con cada serie de
producción, sobre series diferenciadas (log-diff) y **desestacionalizadas** (resta de
la media de cada mes), usando **solo
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
MIN_OBS = 24  # mínimo de pares para calcular una correlación
# Rezagos con mecanismo: corto plazo (0-3) + ciclo anual (12). No se prueban
# los rezagos 4-11: con ventana corta, un "mejor" ahí suele ser azar (igual que
# en la selección del notebook).
REZAGOS_PERMITIDOS = (0, 1, 2, 3, 12)

TARGETS = {
    "biodiesel": "produccion_biodiesel_tn",
    "bioetanol_total": "produccion_bioetanol_total_m3",
    "bioetanol_maiz": "produccion_bioetanol_maiz_m3",
    "bioetanol_cana": "produccion_bioetanol_cana_m3",
}
# Inicio de entrenamiento por serie (igual que el protocolo): la CCF no mira
# datos anteriores, así usa la misma ventana que el modelo.
INICIO_PROTOCOLO = {
    "biodiesel": "2008-01",
    "bioetanol_total": "2013-01",
    "bioetanol_maiz": "2012-09",
    "bioetanol_cana": "2013-01",
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
    "azucar_usd_kg",  # SCRUM-58, reparto de la caña entre azúcar y alcohol
    # SCRUM-48: cumplimiento real de la mezcla. Ojo, es casi circular (sale de las
    # ventas al corte, que siguen a la producción); ver docs/corte.md.
    "corte_efectivo_biodiesel",
    "corte_efectivo_bioetanol",
    "corte_efectivo_bioetanol_maiz",
    "corte_efectivo_bioetanol_cana",
]
# No entran acá:
#   - corte_*_nominal_pct: es una variable de RÉGIMEN (escalones por norma), no un
#     predictor del mes a mes; su rol está documentado aparte en docs/candidatas_28.md.
#   - expo_indec_tn (SCRUM-57): tiene muchos meses en cero, así que la variación en
#     log queda fragmentada y la CCF no es interpretable. Se mantiene como candidata
#     por mecanismo (es el driver del biodiésel), con la fila en CCF s/d.


def dlog(s: pd.Series) -> pd.Series:
    """Variación mensual en log, SIN diferenciar a través de huecos.

    Reindexa a una grilla mensual continua antes de diferenciar: si falta un
    mes (precios regulados con 28-41 huecos), el diff da NaN en vez de un salto
    espurio que cruza el hueco. Es la misma transformación que ``logdiff`` del
    notebook, para que el script y los heatmaps coincidan.
    """
    s = s.astype(float)
    s = s[s > 0].dropna()
    if s.empty:
        return s
    grilla = pd.date_range(s.index.min(), s.index.max(), freq="MS")
    s = s.reindex(grilla)
    return np.log(s).diff()


def desestacionalizar(s: pd.Series) -> pd.Series:
    """Resta la media de cada mes calendario, calculada SOLO con los datos que
    recibe (acá, el tramo anterior a ``CORTE``). Así la desestacionalización no
    mira el backtest, y el notebook y esta tabla usan la misma transformación.
    """
    return s - s.groupby(s.index.month).transform("mean")


def mejor_rezago(prod: pd.Series, exo: pd.Series) -> tuple | None:
    """Rezago con mecanismo (``REZAGOS_PERMITIDOS``) de mayor |correlación|.

    Returns:
        ``(rezago, corr, n)`` o ``None`` si no hay suficientes pares.
    """
    mejor = None
    for k in REZAGOS_PERMITIDOS:
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
        raw = df[ty]
        raw = raw[raw.index >= pd.Timestamp(INICIO_PROTOCOLO[nombre])]  # ventana del protocolo
        prod = dlog(raw)
        prod = desestacionalizar(prod[prod.index < CORTE])
        for ex in CANDIDATAS:
            if ex not in df.columns:
                continue
            exo = dlog(df[ex])
            exo = desestacionalizar(exo[exo.index < CORTE])
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
