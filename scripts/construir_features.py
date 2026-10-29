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
  una entra con su rezago y, si es un volumen/precio, en logaritmo.
- ``"contables"`` : la descomposición contable del **biodiésel** (ver abajo).
  No hace nada para el bioetanol.
- ``"lags"``      : rezagos propios del objetivo (1, 2, 12). Para modelos de
  regresión (elastic net); el SARIMAX ya modela la inercia con sus términos AR,
  así que por defecto no se incluyen.
- ``"dummies"``   : indicadores de mes calendario (estacionalidad para el
  elastic net; el SARIMAX usa su parte estacional y el calendario de Fourier).

``con_calendario`` agrega ``dias_mes`` y la estacionalidad suave de Fourier
(sin12/cos12). ``exogenas_extra`` suma candidatas puntuales sin tocar
``EXOGENAS`` (lo usa la ablación de SCRUM-62).

Por defecto ``incluir=("exogenas",)``: reproduce lo que consumía el SARIMAX de
SCRUM-29 (calendario + exógenas elegidas). Los grupos nuevos se piden explícito.

Descomposición contable del biodiésel (grupo ``"contables"``)
-------------------------------------------------------------
El biodiésel se mueve por sus destinos (corte interno + exportaciones), no por
el mercado interno "suelto" —que además desestabiliza el SARIMAX (SCRUM-29)—. La
descomposición contable arma, sin leakage:

- ``demanda_interna_est`` = ``ventas_gasoil_total_m3``(t) ×
  (``biodiesel_ventas_corte_tn`` / ``ventas_gasoil_total_m3``)(t-1). Gasoil de t
  (rezago 0) × tasa de corte de t-1 (las ventas al corte vienen del archivo de
  producción, rezago 1).
- ``expo_est`` = ``expo_indec_tn``(t) (INDEC, rezago 0; SCRUM-57). En los meses
  ocultos por secreto estadístico se imputa con la **mediana de
  ``biodiesel_exportaciones_tn`` (Secretaría) de los meses ocultos anteriores**;
  si todavía no hubo ningún oculto (el primero, 2018-09), cae a la mediana de
  *todos* los meses anteriores. Siempre con datos hasta t-1 y nunca el valor real
  del propio mes oculto. Así no quedan NaN en el medio de la serie.
- ``expo_indec_oculto``(t): 1 si el mes de INDEC está oculto (marca que
  ``expo_est`` de ese mes es imputado).
- ``otras_ventas_t1`` = ``biodiesel_otras_ventas_tn``(t-1) (rezago 1).

Su suma reconstruye la mayor parte de la producción (base de la suma contable N4).

Los tres volúmenes salen en **log1p** (``contables_en_log=True``, el default):
el modelo es en log(y) y en toneladas se desestabiliza —un salto de
exportaciones de 28 mil a 170 mil tn se multiplica y el pronóstico explota
(review de SCRUM-62)—. ``log1p`` además tolera los ceros, que las tres tienen.
La suma contable (N4) necesita las toneladas, así que pasa
``contables_en_log=False``.

INDEC arranca en 2012: con contables, el biodiésel entrena desde 2012 y no desde
2008. El constructor lo avisa (``warnings.warn``) y expone el primer mes con
contables en ``X.attrs["contables_desde"]``. **Al comparar con y sin contables
hay que igualar la ventana de entrenamiento**, o la diferencia mide el cambio de
ventana y no el aporte de las variables (review de SCRUM-62).

Anti-leakage
------------
Cada variable se desplaza por su rezago, de modo que la fila del mes a estimar
nunca toma un valor publicado después de la fecha de corte. La decisión de tomar
logaritmo es **fija por variable** (no depende de los datos, ni del futuro). Si
la fila del mes a estimar queda con algún NaN (un insumo que todavía no se
actualizó en la base), el constructor **frena** nombrando la variable, en vez de
devolver la fila incompleta en silencio (``exigir_fila_completa``).

Punto en el tiempo (limitación conocida)
----------------------------------------
El constructor es agnóstico al ``base`` que recibe: el anti-leakage lo dan los
rezagos, no la versión del dato. Hoy se le pasa la **última versión consolidada**
(``leer_dataset``), así que el backtest usa datos **revisados**, no los que se
conocían en cada mes (no solo para INDEC —``docs/exportaciones_indec.md``— sino
para todas las series). Es algo optimista respecto de una corrida en tiempo real.
Reconstruir los vintages a cada fecha requeriría historia de versiones que hoy la
base no tiene para los meses viejos; si se arma, se le pasa esa base a esta misma
función sin cambios. (Queda como ajuste del DoD del ticket.)

Uso:
    from construir_features import construir_features
    X, y = construir_features("biodiesel", "2024-05")                  # exógenas
    X, y = construir_features("biodiesel", "2024-05",
                              incluir=("exogenas", "contables"))         # + contables
    X.attrs["grupos"]   # {grupo: [columnas]}  (para SCRUM-35)
"""

from __future__ import annotations

import sys
import warnings
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
# SCRUM-26). La ablación de SCRUM-62 decide cuáles aportan y las agrega acá.
EXOGENAS: dict[str, list[tuple[str, int]]] = {
    # Biodiésel: sin exógenas de mercado internas (desestabilizan el SARIMAX,
    # SCRUM-29). Sus drivers reales (corte interno + exportaciones de INDEC) van
    # por el grupo "contables".
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
# probó (ver docs/candidatas_28.md). Se listan como menú; se pasan con
# ``exogenas_extra`` en la ablación.
CANDIDATAS_POR_PROBAR: dict[str, list[tuple[str, int]]] = {
    "biodiesel": [("corte_biodiesel_nominal_pct", 0)],
    "bioetanol_maiz": [("corte_efectivo_bioetanol_maiz", 1)],
    "bioetanol_cana": [("azucar_usd_kg", 0), ("corte_efectivo_bioetanol_cana", 1)],
    "bioetanol_total": [("corte_efectivo_bioetanol", 1)],
}

# Insumos de la descomposición contable del biodiésel y el rezago mínimo con que
# los usa (se chequea contra data/disponibilidad_variables.csv en el test).
_CONTABLES_INSUMOS = (
    "ventas_gasoil_total_m3",
    "biodiesel_ventas_corte_tn",
    "biodiesel_otras_ventas_tn",
    "biodiesel_exportaciones_tn",
    "expo_indec_tn",
    "expo_indec_oculto",
)
CONTABLES_REZAGO_USADO = {
    "ventas_gasoil_total_m3": 0,       # demanda_interna_est: gasoil(t)
    "biodiesel_ventas_corte_tn": 1,    # demanda_interna_est: tasa de corte(t-1)
    "expo_indec_tn": 0,                # expo_est(t)
    "expo_indec_oculto": 0,            # indicador(t)
    "biodiesel_otras_ventas_tn": 1,    # otras_ventas_t1(t-1)
    "biodiesel_exportaciones_tn": 1,   # imputación: meses ocultos < t
}

# Rezagos propios del objetivo para el grupo "lags".
LAGS_OBJETIVO = (1, 2, 12)

# Variables que NO se toman en logaritmo: cocientes/porcentajes adimensionales,
# indicadores y cualquier cosa que pueda valer 0. La decisión es FIJA por
# variable (no depende de los datos ni del futuro). Si una variable que no está
# acá tiene un valor ≤0 en el tramo usado, el constructor frena y pide sumarla.
NO_LOG = {
    "margen_domestico_biodiesel", "margen_bioetanol_maiz",
    "corte_biodiesel_nominal_pct", "corte_bioetanol_nominal_pct",
    "corte_biodiesel_cotab_pct",
    "corte_efectivo_biodiesel", "corte_efectivo_bioetanol",
    "corte_efectivo_bioetanol_maiz", "corte_efectivo_bioetanol_cana",
}

GRUPOS_VALIDOS = ("exogenas", "contables", "lags", "dummies")

# Avisos ya emitidos (el walk-forward llama a esta función una vez por mes: el
# aviso de que las contables arrancan más tarde se da una sola vez por corrida).
_AVISADO: set = set()


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


def _exogenas(base: pd.DataFrame, idx: pd.PeriodIndex, fecha_corte: pd.Period,
              pares: list[tuple[str, int]]) -> pd.DataFrame:
    """Exógenas de mercado desplazadas por su rezago (log fijo por variable).

    La decisión de log NO mira los datos: es log salvo que la variable esté en
    ``NO_LOG``. La positividad se valida solo con datos ≤ fecha de corte (si una
    variable que debería ir en log tiene un ≤0 ahí, frena y pide sumarla a
    ``NO_LOG``); nunca se mira el futuro. Una variable ausente de la base frena.
    """
    X = pd.DataFrame(index=idx)
    for sid, rez in pares:
        if sid not in base.columns:
            raise KeyError(
                f"La exógena {sid!r} no está en la base. Revisá db/series.csv / "
                f"db/derivadas.csv y corré build_db, o sacala de EXOGENAS.")
        col = base[sid].astype(float)
        if sid not in NO_LOG:
            usado = col.loc[:fecha_corte].dropna()
            if not usado.empty and (usado <= 0).any():
                raise ValueError(
                    f"La exógena {sid!r} tiene valores ≤0 hasta {fecha_corte} y se "
                    f"intenta tomar en log; sumala a NO_LOG en construir_features.py.")
            col = np.log(col)
        X[sid] = col.shift(rez).reindex(idx)  # x[t-rez]: nada del futuro
    return X


def _lags(y: pd.Series, idx: pd.PeriodIndex, lags=LAGS_OBJETIVO) -> pd.DataFrame:
    """Rezagos propios del objetivo. ``y`` llega hasta el mes anterior al corte;
    se reindexa a ``idx`` ANTES de shiftear para que el rezago 1 de la fila a
    estimar sea el último dato real (y no NaN por el hueco del propio corte)."""
    s = y.reindex(idx)
    X = pd.DataFrame(index=idx)
    for L in lags:
        X[f"lag_{L}"] = s.shift(L)
    return X


def _contables_biodiesel(base: pd.DataFrame, idx: pd.PeriodIndex,
                         en_log: bool = True
                         ) -> tuple[pd.DataFrame, pd.Period | None]:
    """Descomposición contable del biodiésel (ver cabecera del módulo).

    Args:
        en_log: Si devuelve los tres volúmenes en ``log1p`` (lo que necesita un
            modelo en log). ``False`` los deja en toneladas, para la suma
            contable (N4), donde tienen que sumar.

    Returns:
        El DataFrame recortado a ``idx`` y el primer mes con contables completos
        (para avisar desde cuándo entrenan).
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
    # Imputación de ocultos: mediana de la expo de la Secretaría en los ocultos
    # ANTERIORES; si no hubo ninguno (el primero), mediana de TODOS los meses
    # anteriores. Siempre datos < t; nunca el real de t. Sin NaN en el medio.
    expo_est = expo.copy()
    for m in base.index[oculto == 1]:
        ocultos_previos = se_expo[(oculto == 1) & (base.index < m)].dropna()
        if len(ocultos_previos):
            expo_est.loc[m] = ocultos_previos.median()
        else:
            previos = se_expo[base.index < m].dropna()
            expo_est.loc[m] = previos.median() if len(previos) else np.nan

    otras_ventas_t1 = base["biodiesel_otras_ventas_tn"].astype(float).shift(1)

    X = pd.DataFrame(index=base.index)
    X["demanda_interna_est"] = demanda_interna_est
    X["expo_est"] = expo_est
    X["expo_indec_oculto"] = oculto
    X["otras_ventas_t1"] = otras_ventas_t1

    if en_log:
        # El modelo es en log(y): las contables en toneladas lo desestabilizan
        # (un salto de exportaciones de 28 mil a 170 mil tn se multiplica y el
        # pronóstico explota; review de SCRUM-62). Se pasan a log1p, que además
        # tolera los ceros: las tres tienen meses en 0 (sin exportaciones, sin
        # otras ventas, sin ventas al corte). El indicador de oculto queda 0/1.
        for col in ("demanda_interna_est", "expo_est", "otras_ventas_t1"):
            X[col] = np.log1p(X[col])

    X = X.reindex(idx)
    completas = X.dropna()
    desde = completas.index.min() if not completas.empty else None
    return X, desde


def construir_features(
    objetivo: str,
    fecha_corte,
    base: pd.DataFrame | None = None,
    con_calendario: bool = True,
    incluir: tuple[str, ...] = ("exogenas",),
    exogenas_extra: list[tuple[str, int]] | None = None,
    exigir_fila_completa: bool = True,
    contables_en_log: bool = True,
) -> tuple[pd.DataFrame, pd.Series]:
    """Arma ``(X, y)`` para un objetivo hasta ``fecha_corte``, sin leakage.

    Args:
        objetivo: Nombre del protocolo ("biodiesel", "bioetanol_total", ...).
        fecha_corte: Mes a estimar (``Period`` o algo que ``pd.Period`` acepte).
            ``y`` llega hasta ``fecha_corte - 1``; ``X`` incluye la fila de
            ``fecha_corte``.
        base: Dataset ya leído (para no releerlo en cada iteración del
            walk-forward). Si es ``None``, se lee con ``leer_dataset``.
        con_calendario: Si agrega días del mes y la estacionalidad de Fourier.
        incluir: Grupos de features a construir (ver cabecera).
        exogenas_extra: Pares ``(serie_id, rezago)`` extra, además de
            ``EXOGENAS[objetivo]`` (para la ablación de SCRUM-62, sin editar
            ``EXOGENAS``).
        exigir_fila_completa: Si la fila del mes a estimar tiene algún NaN en una
            feature de datos, frena con un error que nombra la(s) variable(s) a
            actualizar en la base. ``True`` por defecto.
        contables_en_log: Si los volúmenes contables del biodiésel van en
            ``log1p`` (lo que necesita un modelo en log). ``False`` los deja en
            toneladas, para la suma contable (N4).

    Returns:
        ``(X, y)``. ``y`` en unidades originales; ``X`` con una fila por mes
        (``PeriodIndex``), cada variable desplazada por su rezago, y
        ``X.attrs["grupos"]`` mapeando cada grupo a sus columnas (para SCRUM-35).
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

    idx = pd.period_range(y.index.min(), fecha_corte, freq="M")
    partes: list[pd.DataFrame] = []
    grupos: dict[str, list[str]] = {}
    contables_desde: pd.Period | None = None

    if con_calendario:
        cal = _calendario(idx)
        partes.append(cal)
        grupos["calendario"] = list(cal.columns)
    if "dummies" in incluir:
        dm = _dummies_mes(idx)
        partes.append(dm)
        grupos["dummies"] = list(dm.columns)

    pares = list(EXOGENAS.get(objetivo, [])) if "exogenas" in incluir else []
    if exogenas_extra:
        pares = pares + list(exogenas_extra)
    if pares:
        ex = _exogenas(base, idx, fecha_corte, pares)
        partes.append(ex)
        grupos["exogenas"] = list(ex.columns)

    if "contables" in incluir and objetivo == "biodiesel":
        co, contables_desde = _contables_biodiesel(base, idx, en_log=contables_en_log)
        partes.append(co)
        grupos["contables"] = list(co.columns)
        if contables_desde is not None and contables_desde > idx[0]:
            clave = ("contables", objetivo, str(contables_desde), str(idx[0]))
            if clave not in _AVISADO:   # una vez por corrida, no por mes del walk-forward
                _AVISADO.add(clave)
                warnings.warn(
                    f"Las contables del biodiésel arrancan en {contables_desde} (INDEC desde "
                    f"2012): el modelo con contables entrena desde ahí, no desde {idx[0]}.",
                    stacklevel=2)
    if "lags" in incluir:
        lg = _lags(y, idx)
        partes.append(lg)
        grupos["lags"] = list(lg.columns)

    X = pd.concat(partes, axis=1) if partes else pd.DataFrame(index=idx)

    if exigir_fila_completa:
        datos = [c for g, cols in grupos.items() if g != "calendario" for c in cols]
        if datos:
            fila = X.loc[fecha_corte, datos]
            faltan = list(fila.index[fila.isna()])
            if faltan:
                raise ValueError(
                    f"No se puede estimar {objetivo} en {fecha_corte}: la fila del mes a "
                    f"estimar tiene NaN en {faltan}. Actualizá esas series en la base "
                    f"(build_db) o esperá a que se publiquen.")

    X.attrs["grupos"] = grupos
    X.attrs["objetivo"] = objetivo
    X.attrs["contables_desde"] = str(contables_desde) if contables_desde is not None else None
    return X, y


# Alias con el nombre que propuso el ticket SCRUM-59 (la implementación quedó en
# construir_features.py, ya consumido por el resto del pipeline).
armar_features = construir_features


def nombres_features(X: pd.DataFrame) -> dict[str, list[str]]:
    """Columnas de ``X`` agrupadas (para las tablas de contribución, SCRUM-35)."""
    return dict(X.attrs.get("grupos", {}))


if __name__ == "__main__":
    for obj in OBJETIVOS:
        incluir = ("exogenas", "contables") if obj == "biodiesel" else ("exogenas",)
        X, y = construir_features(obj, pd.Period("2024-05", freq="M"), incluir=incluir)
        datos = [c for c in X.columns if c not in ("dias_mes", "sin12", "cos12")]
        print(f"{obj:16s}  y hasta {y.index[-1]}  X {X.shape}  "
              f"grupos={ {g: len(c) for g, c in X.attrs['grupos'].items()} }")
        print(f"                  cols={datos}")
