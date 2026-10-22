## Integración futura de variables externas

#La primera versión evalúa modelos usando únicamente producción histórica.

#Más adelante se incorporarán variables externas mediante una interfaz común: fit(y_train, X_train=None) y predict(X_next=None).

#Antes de incorporarlas se acordarán nombres, unidades, fechas de disponibilidad, rezagos y tratamiento de faltantes. Cada predicción utilizará únicamente información disponible al momento de emitirla.

import numpy as np
import pandas as pd


class UltimoValor:
    """Predice el mismo valor que el mes anterior."""

    def fit(self, serie):
        self.valor = float(serie.iloc[-1])
        return self

    def predict(self):
        return self.valor


class Estacional:
    """Predice el mismo valor que el mismo mes del año anterior."""

    def fit(self, serie):
        if len(serie) < 12:
            raise ValueError("Se necesitan al menos 12 meses.")
        self.valor = float(serie.iloc[-12])
        return self

    def predict(self):
        return self.valor


def evaluar_modelo(
    serie,
    crear_modelo,
    inicio_entrenamiento,
    inicio_test="2025-09",
    fin_test="2026-08",
    nombre_serie="serie",
    nombre_modelo="modelo",
):
    """
    Evalúa un modelo mediante walk-forward a un mes.

    Parámetros
    ----------
    serie : pd.Series
        Producción mensual con fechas como índice.
    crear_modelo : callable
        Devuelve un modelo nuevo que implementa fit(serie) y predict().
    inicio_entrenamiento : str
        Primer mes de entrenamiento, por ejemplo "2008-01".
    inicio_test, fin_test : str
        Primer y último mes del período de evaluación.

    Devuelve
    --------
    detalle : pd.DataFrame
        Predicciones, valores reales y fallos por mes.
    resumen : pd.DataFrame
        Métricas y cobertura de la evaluación.

    Las predicciones deben estar en las unidades originales.
    """
    if not isinstance(serie, pd.Series):
        raise TypeError("serie debe ser una Series de pandas.")

    serie = serie.copy()

    if isinstance(serie.index, pd.PeriodIndex):
        serie.index = serie.index.asfreq("M")
    else:
        serie.index = pd.to_datetime(serie.index).to_period("M")

    if serie.index.isna().any():
        raise ValueError("Hay fechas faltantes.")

    if serie.index.has_duplicates:
        raise ValueError("Hay meses duplicados.")

    serie = serie.sort_index()

    inicio = pd.Period(inicio_entrenamiento, freq="M")
    primero = pd.Period(inicio_test, freq="M")
    ultimo = pd.Period(fin_test, freq="M")

    if not inicio < primero <= ultimo:
        raise ValueError(
            "El entrenamiento debe empezar antes del test "
            "y el final del test no puede preceder a su inicio."
        )

    meses = pd.period_range(inicio, ultimo, freq="M")
    faltantes = meses.difference(serie.index)

    if len(faltantes):
        raise ValueError(f"Faltan meses: {list(faltantes)}")

    serie = pd.to_numeric(
        serie.reindex(meses), errors="raise"
    ).astype(float)

    if not np.isfinite(serie.to_numpy()).all():
        raise ValueError("Hay valores faltantes o infinitos.")

    if (serie < 0).any():
        raise ValueError("La producción real no puede ser negativa.")

    registros = []

    for mes in pd.period_range(primero, ultimo, freq="M"):
        entrenamiento = serie.loc[serie.index < mes].copy()
        real = float(serie.loc[mes])
        anterior = float(entrenamiento.iloc[-1])

        registro = {
            "serie": nombre_serie,
            "modelo": nombre_modelo,
            "fecha": mes.to_timestamp(),
            "real": real,
            "real_anterior": anterior,
            "prediccion": np.nan,
            "error": np.nan,
            "acierto_signo": np.nan,
            "estado": "fallo",
            "motivo": "",
        }

        try:
            modelo = crear_modelo()
            modelo.fit(entrenamiento)

            salida = np.asarray(modelo.predict(), dtype=float)

            if salida.size != 1:
                raise ValueError(
                    "El modelo debe devolver una sola predicción."
                )

            prediccion = float(salida.reshape(-1)[0])

            if not np.isfinite(prediccion) or prediccion < 0:
                raise ValueError(
                    "La predicción debe ser finita y no negativa."
                )

            signo_predicho = np.sign(prediccion - anterior)
            signo_real = np.sign(real - anterior)

            registro.update({
                "prediccion": prediccion,
                "error": prediccion - real,
                "acierto_signo": int(signo_predicho == signo_real),
                "estado": "ok",
            })

        except Exception as exc:
            registro["motivo"] = f"{type(exc).__name__}: {exc}"

        registros.append(registro)

    detalle = pd.DataFrame(registros)

    validos = detalle.loc[detalle["estado"] == "ok"]
    para_mape = validos.loc[validos["real"] != 0]

    resumen = {
        "serie": nombre_serie,
        "modelo": nombre_modelo,
        "inicio_test": str(primero),
        "fin_test": str(ultimo),
        "meses_previstos": len(detalle),
        "meses_evaluados": len(validos),
        "cobertura_pct": 100 * len(validos) / len(detalle),
        "evaluacion_completa": len(validos) == len(detalle),
        "MAE": validos["error"].abs().mean(),
        "RMSE": np.sqrt((validos["error"] ** 2).mean()),
        "MAPE_pct": 100 * (
            para_mape["error"].abs() / para_mape["real"].abs()
        ).mean(),
        "meses_validos_MAPE": len(para_mape),
        "ceros_excluidos_MAPE": int((validos["real"] == 0).sum()),
        "acierto_signo_pct": 100 * validos["acierto_signo"].mean(),
    }

    return detalle, pd.DataFrame([resumen])

# ---------------------------------------------------------------------------
# Protocolo largo (SCRUM-43): backtest de selección + holdout final
# ---------------------------------------------------------------------------

# Ventanas con los datos a agosto 2026. Se recalculan con ventanas_protocolo()
# si llegan meses nuevos.
INICIO_BACKTEST = "2021-09"
LARGO_HOLDOUT = 12

# Cambios de régimen para reportar el error por subperíodo. Cada fecha es el
# primer mes del régimen nuevo.
CORTES_REGIMEN = {
    "Ley 27.640": "2021-08",
    "corte nov-2025": "2025-11",
}


def ventanas_protocolo(ultimo_dato, inicio_backtest=INICIO_BACKTEST,
                       largo_holdout=LARGO_HOLDOUT):
    """Devuelve las dos ventanas del protocolo.

    - backtest: desde ``inicio_backtest`` hasta ``largo_holdout`` meses antes
      del último dato. Todas las decisiones se toman acá.
    - holdout: los últimos ``largo_holdout`` meses. No se usa para decidir.

    Devuelve un dict {nombre: (inicio, fin)} con meses "YYYY-MM".
    """
    ultimo = pd.Period(ultimo_dato, freq="M")
    inicio_holdout = ultimo - (largo_holdout - 1)
    fin_backtest = inicio_holdout - 1
    if pd.Period(inicio_backtest, freq="M") > fin_backtest:
        raise ValueError("El backtest queda vacío con esos parámetros.")
    return {
        "backtest": (str(pd.Period(inicio_backtest, freq="M")), str(fin_backtest)),
        "holdout": (str(inicio_holdout), str(ultimo)),
    }


def evaluar_ventanas(serie, crear_modelo, inicio_entrenamiento, ventanas,
                     nombre_serie="serie", nombre_modelo="modelo"):
    """Corre evaluar_modelo en cada ventana y agrega la columna ``ventana``.

    El modelo no cambia entre ventanas: es el mismo ``crear_modelo``.
    """
    detalles, resumenes = [], []
    for nombre, (inicio, fin) in ventanas.items():
        detalle, resumen = evaluar_modelo(
            serie=serie,
            crear_modelo=crear_modelo,
            inicio_entrenamiento=inicio_entrenamiento,
            inicio_test=inicio,
            fin_test=fin,
            nombre_serie=nombre_serie,
            nombre_modelo=nombre_modelo,
        )
        detalle.insert(2, "ventana", nombre)
        resumen.insert(2, "ventana", nombre)
        detalles.append(detalle)
        resumenes.append(resumen)
    return pd.concat(detalles, ignore_index=True), pd.concat(resumenes, ignore_index=True)


def _metricas_basicas(detalle):
    validos = detalle.loc[detalle["estado"] == "ok"]
    para_mape = validos.loc[validos["real"] != 0]
    return {
        "meses": len(detalle),
        "meses_evaluados": len(validos),
        "MAE": validos["error"].abs().mean(),
        "RMSE": np.sqrt((validos["error"] ** 2).mean()),
        "MAPE_pct": 100 * (para_mape["error"].abs() / para_mape["real"].abs()).mean(),
        "acierto_signo_pct": 100 * validos["acierto_signo"].mean(),
    }


def error_por_subperiodo(detalle, cortes=None):
    """Métricas separadas por régimen, según las fechas de ``cortes``.

    ``detalle`` es la salida de evaluar_modelo o evaluar_ventanas. Cada mes
    queda en el régimen del último corte anterior o igual a él; los meses
    previos al primer corte quedan como "antes de <primer corte>". Los
    subperíodos sin meses en la ventana no aparecen.
    """
    cortes = CORTES_REGIMEN if cortes is None else cortes
    orden = sorted(cortes.items(), key=lambda kv: pd.Period(kv[1], freq="M"))
    detalle = detalle.reset_index(drop=True).copy()
    meses = pd.to_datetime(detalle["fecha"]).dt.to_period("M")

    detalle["subperiodo"] = f"antes de {orden[0][0]}"
    for nombre, desde in orden:
        detalle.loc[meses >= pd.Period(desde, freq="M"), "subperiodo"] = f"desde {nombre}"

    claves = [c for c in ("serie", "modelo", "ventana") if c in detalle.columns] + ["subperiodo"]
    filas = []
    for valores, grupo in detalle.groupby(claves, sort=False):
        fila = dict(zip(claves, valores))
        m = meses[grupo.index]
        fila.update({"desde": str(m.min()), "hasta": str(m.max())})
        fila.update(_metricas_basicas(grupo))
        filas.append(fila)
    return pd.DataFrame(filas)


def _perdida(detalle, perdida):
    ok = detalle.loc[detalle["estado"] == "ok"].set_index("fecha")
    if perdida == "ae":
        return ok["error"].abs()
    if perdida == "ape":
        ok = ok.loc[ok["real"] != 0]
        return 100 * ok["error"].abs() / ok["real"].abs()
    if perdida == "se":
        return ok["error"] ** 2
    raise ValueError("perdida debe ser 'ae', 'ape' o 'se'.")


def _varianza_hac(d, rezagos):
    """Varianza de largo plazo de Newey-West (kernel de Bartlett)."""
    d = d - d.mean()
    n = len(d)
    var = d @ d / n
    for k in range(1, rezagos + 1):
        peso = 1 - k / (rezagos + 1)
        var += 2 * peso * (d[k:] @ d[:-k]) / n
    return var


def _p_valor_t(t, gl):
    """p-valor bilateral de una t de Student (aproximación normal si no hay scipy)."""
    try:
        from scipy import stats
        return float(2 * stats.t.sf(abs(t), gl))
    except ImportError:  # aproximación normal
        from math import erfc, sqrt
        return float(erfc(abs(t) / sqrt(2)))


def comparar_modelos(detalle_a, detalle_b, perdida="ape", horizonte=1,
                     rezagos=None, n_boot=5000, largo_bloque=None,
                     nivel=0.95, semilla=0):
    """Compara dos modelos sobre los mismos meses.

    Se calcula la diferencia de pérdida d_t = L(a)_t - L(b)_t. Negativa
    significa que ``a`` tiene menos error.

    Devuelve un dict con:
    - diferencia media e intervalo de confianza por bootstrap circular por
      bloques (los errores están autocorrelacionados);
    - estadístico de Diebold-Mariano con varianza HAC de Newey-West y la
      corrección de muestra chica de Harvey, Leybourne y Newbold (1997),
      con su p-valor sobre una t con n-1 grados de libertad.

    ``perdida``: "ape" (error absoluto %, el del MAPE), "ae" (absoluto, el
    del MAE) o "se" (cuadrático, el del RMSE).
    """
    la, lb = _perdida(detalle_a, perdida), _perdida(detalle_b, perdida)
    comunes = la.index.intersection(lb.index)
    d = (la.loc[comunes] - lb.loc[comunes]).sort_index().to_numpy(dtype=float)
    n = len(d)
    if n < 3:
        raise ValueError("Se necesitan al menos 3 meses en común.")

    if rezagos is None:
        rezagos = max(horizonte - 1, int(np.floor(n ** (1 / 3))))
    var = _varianza_hac(d, rezagos)
    media = d.mean()
    if var > 0:
        dm = media / np.sqrt(var / n)
        h = horizonte
        dm *= np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
        p = _p_valor_t(dm, n - 1)
    else:
        dm, p = np.nan, np.nan

    # Bootstrap circular por bloques.
    if largo_bloque is None:
        largo_bloque = max(2, int(round(n ** (1 / 3))))
    rng = np.random.default_rng(semilla)
    n_bloques = int(np.ceil(n / largo_bloque))
    extendido = np.concatenate([d, d[:largo_bloque]])
    inicios = rng.integers(0, n, size=(n_boot, n_bloques))
    idx = (inicios[:, :, None] + np.arange(largo_bloque)).reshape(n_boot, -1)[:, :n]
    medias = extendido[idx].mean(axis=1)
    alfa = 1 - nivel
    ic_inf, ic_sup = np.quantile(medias, [alfa / 2, 1 - alfa / 2])

    return {
        "perdida": perdida,
        "n": n,
        "diferencia_media": media,
        "ic_inf": ic_inf,
        "ic_sup": ic_sup,
        "ic_incluye_cero": bool(ic_inf <= 0 <= ic_sup),
        "dm": dm,
        "dm_p_valor": p,
        "rezagos_hac": rezagos,
        "largo_bloque": largo_bloque,
    }
