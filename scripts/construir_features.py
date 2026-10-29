"""Constructor común de features (SCRUM-59).

Una sola función arma ``(X, y)`` para un objetivo y un mes de corte, respetando
la disponibilidad temporal (SCRUM-26): cada variable entra con su rezago, así
``X.loc[t]`` solo usa datos que la BCR tendría al estimar el mes ``t`` (sin fuga
de información futura). La usan el SARIMAX (SCRUM-29/62), el elastic net
(SCRUM-54) y la suma contable (N4), para que las tres vean exactamente las
mismas variables y las tablas de contribuciones (SCRUM-35) hablen el mismo idioma.

Grupos de features (parámetro ``incluir``)
------------------------------------------
- ``"exogenas"``  : las candidatas de mercado de cada objetivo (``EXOGENAS``),
  elegidas por mecanismo en el EDA (SCRUM-28, ``docs/candidatas_28.md``). Cada
  una entra con su rezago y, si es un volumen/precio positivo, en logaritmo.
- ``"contables"`` : la descomposición contable del **biodiésel** (ver abajo).
  No hace nada para el bioetanol.
- ``"lags"``      : rezagos propios del objetivo (1, 2, 12). Para modelos de
  regresión (elastic net); el SARIMAX ya modela la inercia con sus términos AR,
  así que por defecto no se incluyen.
- ``"dummies"``   : indicadores de mes calendario (estacionalidad para el
  elastic net; el SARIMAX usa su parte estacional y el calendario de Fourier).

``con_calendario`` agrega ``dias_mes`` y la estacionalidad suave de Fourier
(sin12/cos12), que sirven a todos los modelos.

Por defecto ``incluir=("exogenas",)``: reproduce exactamente lo que consumía el
SARIMAX de SCRUM-29 (calendario + exógenas elegidas). Los grupos nuevos se piden
explícitamente (el SARIMAX con exógenas de SCRUM-62 pide ``("exogenas",
"contables")`` para el biodiésel).

Descomposición contable del biodiésel (grupo ``"contables"``)
-------------------------------------------------------------
El biodiésel se mueve por sus destinos (corte interno + exportaciones), no por
el mercado interno "suelto", y las internas desestabilizan el SARIMAX
(SCRUM-29). La descomposición contable arma, sin leakage:

- ``demanda_interna_est`` = ``ventas_gasoil_total_m3``(t) ×
  (``biodiesel_ventas_corte_tn`` / ``ventas_gasoil_total_m3``)(t-1). Estima la
  demanda del corte del mes t con el gasoil de t (rezago 0, confirmado) y la
  tasa de corte efectiva de t-1 (las ventas al corte vienen del archivo de
  producción, rezago 1). Mezcla rezagos 0 y 1, por eso va acá y no como derivada
  de la base (el mecanismo de SCRUM-56 no permite mezclar rezagos).
- ``expo_est`` = ``expo_indec_tn``(t) (INDEC, rezago 0; SCRUM-57). En los meses
  ocultos por secreto estadístico se imputa con la **mediana de
  ``biodiesel_exportaciones_tn`` (Secretaría) de los meses ocultos anteriores**,
  usando solo datos hasta t-1. Nunca usa el valor real de la Secretaría del
  propio mes oculto.
- ``expo_indec_oculto``(t): 1 si el mes de INDEC está oculto (marca que
  ``expo_est`` de ese mes es imputado).
- ``otras_ventas_t1`` = ``biodiesel_otras_ventas_tn``(t-1) (rezago 1).

Su suma reconstruye la mayor parte de la producción (es la base de la suma
contable N4).

Anti-leakage
------------
El dato de cada variable se desplaza por su rezago, de modo que la fila del mes
a estimar nunca toma un valor publicado después de la fecha de corte. Se trabaja
sobre la **última versión consolidada** de cada serie (``leer_dataset``); la
reconstrucción point-in-time de versiones vive en la base (SCRUM-56) y su
limitación para el backtest —el histórico de INDEC es la versión revisada— está
documentada en ``docs/exportaciones_indec.md`` (SCRUM-57).

Uso:
    from construir_features import construir_features
    X, y = construir_features("biodiesel", "2024-05")                 # exógenas
    X, y = construir_features("biodiesel", "2024-05",
                              incluir=("exogenas", "contables"))        # + contables
    # y: producción hasta 2024-04 (entrenamiento)
    # X: una fila por mes hasta 2024-05 inclusive (la última es la del mes a
    #    estimar); X.loc["2024-05"] no contiene datos del futuro.
    # X.attrs["grupos"]: {grupo: [columnas]} para las tablas de contribución.
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

# Exógenas de mercado por objetivo: (serie_id, rezago). Candidatas por mecanismo
# (SCRUM-28). rezago 0 = disponible el mismo mes al estimar (confirmado en
# SCRUM-26). Este es el conjunto que elige el modelo; la ablación de SCRUM-62
# decide cuáles entran y las agrega acá.
EXOGENAS: dict[str, list[tuple[str, int]]] = {
    # Biodiésel: sin exógenas de mercado internas (desestabilizan el SARIMAX,
    # SCRUM-29). Sus drivers reales (corte interno + exportaciones de INDEC) van
    # por el grupo "contables", no como exógenas sueltas.
    "biodiesel": [],
    "bioetanol_total": [
        ("ventas_nafta_total_m3", 0),
    ],
    "bioetanol_maiz": [
        ("ventas_nafta_total_m3", 0),
        ("margen_bioetanol_maiz", 0),
    ],
    "bioetanol_cana": [
        ("ventas_nafta_total_m3", 0),
    ],
}

# Candidatas que SCRUM-48/57/58 dejaron en la base y que la ablación de SCRUM-62
# va a probar (se mueven a EXOGENAS las que aporten). Documentadas acá para que
# el menú esté a la vista:
#   biodiésel:      corte_biodiesel_nominal_pct (0, régimen)
#   bioetanol maíz: corte_efectivo_bioetanol_maiz (1)
#   bioetanol caña: azucar_usd_kg (0), corte_efectivo_bioetanol_cana (1)
CANDIDATAS_POR_PROBAR: dict[str, list[tuple[str, int]]] = {
    "biodiesel": [("corte_biodiesel_nominal_pct", 0)],
    "bioetanol_maiz": [("corte_efectivo_bioetanol_maiz", 1)],
    "bioetanol_cana": [("azucar_usd_kg", 0), ("corte_efectivo_bioetanol_cana", 1)],
}

# Insumos de la descomposición contable del biodiésel (todos en la base).
_CONTABLES_INSUMOS = (
    "ventas_gasoil_total_m3",
    "biodiesel_ventas_corte_tn",
    "biodiesel_otras_ventas_tn",
    "biodiesel_exportaciones_tn",
    "expo_indec_tn",
    "expo_indec_oculto",
)

# Rezagos propios del objetivo para el grupo "lags".
LAGS_OBJETIVO = (1, 2, 12)

# Variables que NO se toman en logaritmo: cocientes/porcentajes adimensionales,
# indicadores y cualquier cosa que pueda valer 0 (log(0) = -inf).
NO_LOG = {
    "margen_domestico_biodiesel", "margen_bioetanol_maiz",
    "corte_biodiesel_nominal_pct", "corte_bioetanol_nominal_pct",
    "corte_biodiesel_cotab_pct",
    "corte_efectivo_biodiesel", "corte_efectivo_bioetanol",
    "corte_efectivo_bioetanol_maiz", "corte_efectivo_bioetanol_cana",
}

GRUPOS_VALIDOS = ("exogenas", "contables", "lags", "dummies")


def _base_mensual(base: pd.DataFrame | None) -> pd.DataFrame:
    """Lee la base (o usa la pasada) y la devuelve con índice mensual Period."""
    base = leer_dataset() if base is None else base
    base = base.copy()
    if not isinstance(base.index, pd.PeriodIndex):
        base.index = pd.PeriodIndex(pd.to_datetime(base.index), freq="M")
    return base.sort_index()


def _calendario(idx: pd.PeriodIndex) -> pd.DataFrame:
    """Features de calendario: días del mes y estacionalidad suave (Fourier)."""
    X = pd.DataFrame(index=idx)
    X["dias_mes"] = idx.to_timestamp(how="start").days_in_month.astype(float)
    m = idx.month
    X["sin12"] = np.sin(2 * np.pi * m / 12)
    X["cos12"] = np.cos(2 * np.pi * m / 12)
    return X


def _dummies_mes(idx: pd.PeriodIndex) -> pd.DataFrame:
    """Indicadores de mes calendario (enero es la base, se omite)."""
    X = pd.DataFrame(index=idx)
    for m in range(2, 13):
        X[f"mes_{m:02d}"] = (idx.month == m).astype(float)
    return X


def _exogenas(base: pd.DataFrame, idx: pd.PeriodIndex,
              pares: list[tuple[str, int]]) -> pd.DataFrame:
    """Exógenas de mercado desplazadas por su rezago (en log si corresponde)."""
    X = pd.DataFrame(index=idx)
    for sid, rez in pares:
        if sid not in base.columns:
            continue  # todavía no está en la base; se suma cuando entre
        col = base[sid].astype(float)
        if sid not in NO_LOG and (col.dropna() > 0).all():
            col = np.log(col)
        X[sid] = col.shift(rez).reindex(idx)  # x[t-rez]: nada del futuro
    return X


def _lags(y: pd.Series, idx: pd.PeriodIndex,
          lags=LAGS_OBJETIVO) -> pd.DataFrame:
    """Rezagos propios del objetivo. ``y`` llega hasta el mes anterior al corte,
    así el rezago 1 de la fila a estimar es el último dato real."""
    X = pd.DataFrame(index=idx)
    for L in lags:
        X[f"lag_{L}"] = y.shift(L).reindex(idx)
    return X


def _contables_biodiesel(base: pd.DataFrame, idx: pd.PeriodIndex) -> pd.DataFrame:
    """Descomposición contable del biodiésel (ver cabecera del módulo).

    Todo sobre la grilla completa de ``base`` y recién al final se recorta a
    ``idx``, para que los rezagos tomen el mes anterior real aunque caiga antes
    del inicio de ``idx``.
    """
    faltan = [c for c in _CONTABLES_INSUMOS if c not in base.columns]
    if faltan:
        raise KeyError(f"Faltan insumos contables del biodiésel en la base: {faltan}")

    gas = base["ventas_gasoil_total_m3"].astype(float)
    ventas_corte = base["biodiesel_ventas_corte_tn"].astype(float)
    tasa_corte = ventas_corte / gas                      # tn de biodiésel por m3 de gasoil
    demanda_interna_est = gas * tasa_corte.shift(1)      # gasoil(t) × tasa(t-1)

    expo = base["expo_indec_tn"].astype(float)
    oculto = base["expo_indec_oculto"].fillna(0).astype(float)
    se_expo = base["biodiesel_exportaciones_tn"].astype(float)
    # Imputación de los meses ocultos: mediana de la expo de la Secretaría en los
    # meses ocultos ANTERIORES (datos hasta t-1). Nunca el valor real de t.
    expo_est = expo.copy()
    meses_ocultos = base.index[oculto == 1]
    for m in meses_ocultos:
        previos = se_expo[(oculto == 1) & (base.index < m)].dropna()
        expo_est.loc[m] = previos.median() if len(previos) else np.nan

    otras_ventas_t1 = base["biodiesel_otras_ventas_tn"].astype(float).shift(1)

    X = pd.DataFrame(index=base.index)
    X["demanda_interna_est"] = demanda_interna_est
    X["expo_est"] = expo_est
    X["expo_indec_oculto"] = oculto
    X["otras_ventas_t1"] = otras_ventas_t1
    return X.reindex(idx)


def construir_features(
    objetivo: str,
    fecha_corte,
    base: pd.DataFrame | None = None,
    con_calendario: bool = True,
    incluir: tuple[str, ...] = ("exogenas",),
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
        incluir: Grupos de features a construir (ver cabecera del módulo).
            Por defecto solo ``"exogenas"``.

    Returns:
        ``(X, y)``. ``y`` es la producción en unidades originales (sin log);
        ``X`` tiene una fila por mes (``PeriodIndex`` mensual), cada variable
        desplazada por su rezago, y ``X.attrs["grupos"]`` mapea cada grupo a sus
        columnas (para SCRUM-35). ``X.loc[t]`` solo usa datos de ``t`` o
        anteriores según la disponibilidad de cada variable.
    """
    if objetivo not in OBJETIVOS:
        raise KeyError(f"Objetivo desconocido: {objetivo!r}")
    malos = [g for g in incluir if g not in GRUPOS_VALIDOS]
    if malos:
        raise ValueError(f"Grupos desconocidos {malos}; válidos: {GRUPOS_VALIDOS}")

    base = _base_mensual(base)
    fecha_corte = pd.Period(fecha_corte, freq="M")

    y = base[OBJETIVOS[objetivo]].dropna().astype(float)
    y = y[y.index < fecha_corte]
    if y.empty:
        raise ValueError(f"Sin datos de {objetivo} antes de {fecha_corte}.")

    # Índice de features: del inicio de la serie objetivo al mes a estimar.
    idx = pd.period_range(y.index.min(), fecha_corte, freq="M")

    partes: list[pd.DataFrame] = []
    grupos: dict[str, list[str]] = {}

    if con_calendario:
        cal = _calendario(idx)
        partes.append(cal)
        grupos["calendario"] = list(cal.columns)
    if "dummies" in incluir:
        dm = _dummies_mes(idx)
        partes.append(dm)
        grupos["dummies"] = list(dm.columns)
    if "exogenas" in incluir:
        ex = _exogenas(base, idx, EXOGENAS.get(objetivo, []))
        partes.append(ex)
        grupos["exogenas"] = list(ex.columns)
    if "contables" in incluir and objetivo == "biodiesel":
        co = _contables_biodiesel(base, idx)
        partes.append(co)
        grupos["contables"] = list(co.columns)
    if "lags" in incluir:
        lg = _lags(y, idx)
        partes.append(lg)
        grupos["lags"] = list(lg.columns)

    X = pd.concat(partes, axis=1) if partes else pd.DataFrame(index=idx)
    X.attrs["grupos"] = grupos
    X.attrs["objetivo"] = objetivo
    return X, y


# Alias con el nombre que propuso el ticket SCRUM-59 (la implementación quedó en
# construir_features.py, ya consumido por el resto del pipeline).
armar_features = construir_features


def nombres_features(X: pd.DataFrame) -> dict[str, list[str]]:
    """Columnas de ``X`` agrupadas (para las tablas de contribución, SCRUM-35)."""
    return dict(X.attrs.get("grupos", {}))


if __name__ == "__main__":
    # Chequeo rápido: qué arma cada objetivo y que la fila del mes a estimar no
    # quede vacía de exógenas por el recorte de rezagos.
    for obj in OBJETIVOS:
        incluir = ("exogenas", "contables") if obj == "biodiesel" else ("exogenas",)
        X, y = construir_features(obj, pd.Period("2024-05", freq="M"), incluir=incluir)
        datos = [c for c in X.columns if c not in ("dias_mes", "sin12", "cos12")]
        print(f"{obj:16s}  y hasta {y.index[-1]}  X {X.shape}  "
              f"grupos={ {g: len(c) for g, c in X.attrs['grupos'].items()} }")
        print(f"                  cols={datos}")
