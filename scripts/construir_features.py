"""Constructor común de features (SCRUM-59).

Una sola función arma ``(X, y)`` para un objetivo y una fecha de corte,
respetando la disponibilidad temporal (SCRUM-26): cada exógena entra con su
rezago, así ``X.loc[t]`` solo usa datos que la BCR tendría al estimar el mes
``t`` (sin fuga de información futura). La usan el SARIMAX (SCRUM-29), el
elastic net (SCRUM-54) y la suma contable (N4), para que las tres vean
exactamente las mismas variables.

Las exógenas por objetivo salen de las candidatas por mecanismo del EDA
(SCRUM-28, ``docs/candidatas_28.md``). A medida que entren a la base las que
faltan —corte efectivo (SCRUM-48), exportaciones de INDEC (N1) y azúcar
(N2)— se suman acá (hay un hueco marcado para cada una).

Nota sobre el biodiésel: en el walk-forward (SCRUM-29) las exógenas internas
(margen, molienda, ventas, precio) **empeoran** el SARIMAX —de 30% a 50-96% de
MAPE, con pronósticos que se disparan por extrapolación en meses puntuales—.
Es coherente con la descomposición contable: al biodiésel lo mueven las
*exportaciones*, no el mercado interno. Por eso el biodiésel arranca **sin
exógenas** (SARIMA puro) hasta que entre la serie de INDEC (N1), que es su
driver real. Las internas se mantienen documentadas abajo por si se usan en un
modelo que las trate mejor (p. ej. el elastic net regularizado, SCRUM-54).

Uso:
    from construir_features import construir_features
    X, y = construir_features("biodiesel", "2024-05")
    # y: producción hasta 2024-04 (entrenamiento)
    # X: features desde el inicio hasta 2024-05 inclusive (la última fila es la
    #    del mes a estimar); X.loc["2024-05"] no contiene datos del futuro.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))
from build_db import leer_dataset  # noqa: E402

# Serie objetivo (serie_id en la base) de cada nombre del protocolo.
OBJETIVOS = {
    "biodiesel": "produccion_biodiesel_tn",
    "bioetanol_total": "produccion_bioetanol_total_m3",
    "bioetanol_maiz": "produccion_bioetanol_maiz_m3",
    "bioetanol_cana": "produccion_bioetanol_cana_m3",
}

# Exógenas por objetivo: (serie_id, rezago). Candidatas por mecanismo (SCRUM-28).
# rezago 0 = disponible el mismo mes al estimar (confirmado en SCRUM-26).
EXOGENAS: dict[str, list[tuple[str, int]]] = {
    # Biodiésel: SIN exógenas internas (desestabilizan el SARIMAX, ver cabecera).
    # Su driver real son las exportaciones; entran cuando esté N1.
    "biodiesel": [
        # Ya en la base (SCRUM-57): ("expo_indec_tn", 0) + ("expo_indec_oculto", 0).
        #   Falta imputar acá los meses ocultos de expo_indec_tn (vienen vacíos)
        #   con datos hasta t-1 antes de sumarla; ver docs/exportaciones_indec.md.
        # SCRUM-31 (ya en la base, SCRUM-48): ("corte_efectivo_biodiesel", 1),
        #   ("corte_biodiesel_nominal_pct", 0) como régimen
    ],
    "bioetanol_total": [
        ("ventas_nafta_total_m3", 0),
    ],
    "bioetanol_maiz": [
        ("ventas_nafta_total_m3", 0),
        ("margen_bioetanol_maiz", 0),
        # SCRUM-31 (ya en la base, SCRUM-48): ("corte_efectivo_bioetanol_maiz", 1)
    ],
    "bioetanol_cana": [
        ("ventas_nafta_total_m3", 0),
        # TODO N2 (Banco Mundial): ("precio_azucar_usd_tn", 0)
    ],
}

# Exógenas internas del biodiésel que probamos y descartamos para el SARIMAX
# (quedan acá por si un modelo regularizado las aprovecha, p. ej. SCRUM-54):
#   margen_domestico_biodiesel (0), molienda_soja_tn (0),
#   ventas_gasoil_total_m3 (0), precio_biodiesel_ars_tn (0)
EXOGENAS_BIODIESEL_DESCARTADAS = [
    ("margen_domestico_biodiesel", 0),
    ("molienda_soja_tn", 0),
    ("ventas_gasoil_total_m3", 0),
    ("precio_biodiesel_ars_tn", 0),
]

# Exógenas que conviene tomar en logaritmo (precios y volúmenes positivos).
# Los márgenes ya son cocientes adimensionales: se dejan en nivel.
NO_LOG = {"margen_domestico_biodiesel", "margen_bioetanol_maiz"}


def _calendario(idx: pd.PeriodIndex) -> pd.DataFrame:
    """Features de calendario: días del mes y estacionalidad suave (Fourier)."""
    X = pd.DataFrame(index=idx)
    X["dias_mes"] = idx.to_timestamp(how="start").days_in_month.astype(float)
    m = idx.month
    X["sin12"] = np.sin(2 * np.pi * m / 12)
    X["cos12"] = np.cos(2 * np.pi * m / 12)
    return X


def construir_features(
    objetivo: str,
    fecha_corte,
    base: pd.DataFrame | None = None,
    con_calendario: bool = True,
) -> tuple[pd.DataFrame, pd.Series]:
    """Arma ``(X, y)`` para un objetivo hasta ``fecha_corte``, sin leakage.

    Args:
        objetivo: Nombre del protocolo ("biodiesel", "bioetanol_total", ...).
        fecha_corte: Mes a estimar (``Period`` o algo que ``pd.Period`` acepte).
            ``y`` llega hasta ``fecha_corte - 1``; ``X`` incluye la fila de
            ``fecha_corte`` (la del mes a estimar).
        base: Dataset de la base ya leído (para no releerlo en cada iteración
            del walk-forward). Si es ``None``, se lee con ``leer_dataset``.
        con_calendario: Si agrega días del mes y la estacionalidad de Fourier.

    Returns:
        ``(X, y)``. ``y`` es la producción en unidades originales (sin log);
        ``X`` tiene una fila por mes, índice ``PeriodIndex`` mensual, cada
        exógena desplazada por su rezago (``X.loc[t]`` solo usa datos de
        ``t - rezago``).
    """
    if objetivo not in OBJETIVOS:
        raise KeyError(f"Objetivo desconocido: {objetivo!r}")

    base = leer_dataset() if base is None else base
    base = base.copy()
    if not isinstance(base.index, pd.PeriodIndex):
        base.index = pd.PeriodIndex(pd.to_datetime(base.index), freq="M")
    base = base.sort_index()

    fecha_corte = pd.Period(fecha_corte, freq="M")

    y = base[OBJETIVOS[objetivo]].dropna().astype(float)
    y = y[y.index < fecha_corte]
    if y.empty:
        raise ValueError(f"Sin datos de {objetivo} antes de {fecha_corte}.")

    # Índice de features: desde el inicio de la serie objetivo hasta el mes a
    # estimar, inclusive (la última fila es la de la predicción).
    idx = pd.period_range(y.index.min(), fecha_corte, freq="M")

    X = _calendario(idx) if con_calendario else pd.DataFrame(index=idx)

    for sid, rez in EXOGENAS.get(objetivo, []):
        if sid not in base.columns:
            continue  # todavía no entró a la base (ver TODOs); se suma cuando esté
        col = base[sid].astype(float)
        if sid not in NO_LOG and (col.dropna() > 0).all():
            col = np.log(col)
        # el rezago asegura que X.loc[t] use x[t-rez]: nada del futuro.
        X[sid] = col.shift(rez).reindex(idx)

    return X, y


if __name__ == "__main__":
    # Chequeo rápido anti-leakage: la fila del mes a estimar no debe traer
    # ninguna exógena con datos posteriores al corte.
    for obj in OBJETIVOS:
        X, y = construir_features(obj, pd.Period("2024-05", freq="M"))
        print(f"{obj:16s}  y hasta {y.index[-1]}  X {X.shape}  "
              f"cols={[c for c in X.columns if c not in ('dias_mes','sin12','cos12')]}")
