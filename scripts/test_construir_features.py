"""Pruebas del constructor común de features (SCRUM-59).

Verifica los criterios del DoD:

    1. Anti-leakage: la fila del mes a estimar no cambia si se "envenena" la base
       con datos de meses posteriores a la fecha de corte (esos datos se
       publican después de que la BCR estima, no pueden entrar).
    2. Imputación de exportaciones ocultas: un mes oculto se completa con la
       mediana de la Secretaría de los meses ocultos anteriores y NUNCA con el
       valor real de la Secretaría de ese mismo mes.
    3. Compatibilidad: el conjunto por defecto (``incluir=("exogenas",)``) es el
       que ya consumía el SARIMAX de SCRUM-29.

Uso, desde la raíz del repo:
    python scripts/test_construir_features.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import construir_features as cf  # noqa: E402
from build_db import leer_dataset  # noqa: E402


def _base_sintetica() -> pd.DataFrame:
    """Base mínima del biodiésel para probar los contables sin tocar la real.

    12 meses de 2020. Tres meses ocultos (marzo, junio, septiembre) con
    ``expo_indec_tn`` vacío y valores distintivos en la expo de la Secretaría.
    """
    idx = pd.period_range("2020-01", "2020-12", freq="M")
    df = pd.DataFrame(index=idx)
    df["produccion_biodiesel_tn"] = 1000.0
    df["ventas_gasoil_total_m3"] = 100.0
    df["biodiesel_ventas_corte_tn"] = 10.0          # tasa de corte = 0,1
    df["biodiesel_otras_ventas_tn"] = 5.0
    # Expo de la Secretaría (rezago 1): valores distintivos en los ocultos.
    se = {"2020-03": 300.0, "2020-06": 500.0, "2020-09": 999.0}
    df["biodiesel_exportaciones_tn"] = 50.0
    for k, v in se.items():
        df.loc[pd.Period(k, "M"), "biodiesel_exportaciones_tn"] = v
    # INDEC: 200 salvo en los ocultos (NaN) con su indicador en 1.
    df["expo_indec_tn"] = 200.0
    df["expo_indec_oculto"] = 0.0
    for k in se:
        df.loc[pd.Period(k, "M"), "expo_indec_tn"] = np.nan
        df.loc[pd.Period(k, "M"), "expo_indec_oculto"] = 1.0
    return df


def test_imputacion_ocultos() -> None:
    """Un mes oculto usa la mediana de la Secretaría de los ocultos previos,
    nunca el valor real de ese mes."""
    base = _base_sintetica()
    X, _ = cf.construir_features(
        "biodiesel", "2020-12", base=base,
        con_calendario=False, incluir=("contables",),
    )
    p = lambda k: pd.Period(k, "M")  # noqa: E731

    # El primer oculto no tiene ocultos anteriores -> NaN.
    assert pd.isna(X.loc[p("2020-03"), "expo_est"]), X.loc[p("2020-03"), "expo_est"]
    # Junio: mediana de {marzo=300} = 300.
    assert X.loc[p("2020-06"), "expo_est"] == 300.0, X.loc[p("2020-06"), "expo_est"]
    # Septiembre: mediana de {300, 500} = 400, y NO el real de la Secretaría (999).
    assert X.loc[p("2020-09"), "expo_est"] == 400.0, X.loc[p("2020-09"), "expo_est"]
    assert X.loc[p("2020-09"), "expo_est"] != 999.0
    # Un mes no oculto conserva el valor de INDEC.
    assert X.loc[p("2020-05"), "expo_est"] == 200.0, X.loc[p("2020-05"), "expo_est"]
    # El indicador de oculto queda marcado.
    assert X.loc[p("2020-09"), "expo_indec_oculto"] == 1.0
    assert X.loc[p("2020-05"), "expo_indec_oculto"] == 0.0
    # demanda_interna_est(t) = gasoil(t) * tasa(t-1) = 100 * 0,1 = 10.
    assert abs(X.loc[p("2020-05"), "demanda_interna_est"] - 10.0) < 1e-9
    # otras_ventas_t1(t) = otras_ventas(t-1).
    assert X.loc[p("2020-05"), "otras_ventas_t1"] == 5.0
    print("ok  imputacion de meses ocultos (mediana de ocultos previos, no el real)")


def test_imputacion_no_mira_el_real_del_mes() -> None:
    """Aunque cambie el valor real de la Secretaría del propio mes oculto, la
    imputación de ese mes no se mueve."""
    base = _base_sintetica()
    X1, _ = cf.construir_features("biodiesel", "2020-12", base=base,
                                  con_calendario=False, incluir=("contables",))
    base2 = base.copy()
    base2.loc[pd.Period("2020-09", "M"), "biodiesel_exportaciones_tn"] = 123456.0
    X2, _ = cf.construir_features("biodiesel", "2020-12", base=base2,
                                  con_calendario=False, incluir=("contables",))
    val = X2.loc[pd.Period("2020-09", "M"), "expo_est"]
    assert val == X1.loc[pd.Period("2020-09", "M"), "expo_est"] == 400.0, val
    print("ok  la imputacion de un mes oculto ignora el real de la Secretaria de ese mes")


def test_anti_leakage_fila_a_estimar() -> None:
    """Envenenar la base con datos POSTERIORES al mes de corte no cambia ninguna
    fila hasta el mes a estimar (lo que se publica después no puede entrar)."""
    base = cf._base_mensual(leer_dataset())
    corte = pd.Period("2024-05", freq="M")
    casos = [
        ("biodiesel", ("exogenas", "contables", "lags")),
        ("bioetanol_maiz", ("exogenas", "lags")),
        ("bioetanol_cana", ("exogenas", "lags")),
    ]
    for obj, incluir in casos:
        X_ok, _ = cf.construir_features(obj, corte, base=base, incluir=incluir)
        envenenada = base.copy()
        posteriores = envenenada.index > corte
        envenenada.loc[posteriores, :] = 9.9e12   # basura en el futuro
        X_env, _ = cf.construir_features(obj, corte, base=envenenada, incluir=incluir)
        # Comparar sobre las columnas de datos, hasta el mes a estimar inclusive.
        comun = X_ok.loc[:corte]
        env = X_env.loc[:corte]
        dif = (comun.fillna(-1) != env.fillna(-1))
        assert not dif.to_numpy().any(), (obj, comun.columns[dif.any().to_numpy()].tolist())
    print("ok  anti-leakage: datos posteriores al corte no entran en la fila a estimar")


def test_rezagos_correctos() -> None:
    """Cada variable entra en la fila del corte con su rezago declarado."""
    base = cf._base_mensual(leer_dataset())
    corte = pd.Period("2024-05", freq="M")
    X, _ = cf.construir_features("biodiesel", corte, base=base,
                                 incluir=("contables",))
    # otras_ventas_t1 de la fila del corte == otras_ventas crudo del mes anterior.
    esperado = float(base.loc[corte - 1, "biodiesel_otras_ventas_tn"])
    assert abs(X.loc[corte, "otras_ventas_t1"] - esperado) < 1e-6
    # expo_indec_oculto es rezago 0: el del propio mes de corte.
    esperado_oc = float(base["expo_indec_oculto"].fillna(0).loc[corte])
    assert X.loc[corte, "expo_indec_oculto"] == esperado_oc
    print("ok  rezagos: otras_ventas_t1 usa t-1 y el indicador de oculto usa t")


def test_compatibilidad_default() -> None:
    """El default (``incluir=("exogenas",)``) da el conjunto de SCRUM-29:
    calendario + las exógenas elegidas de cada objetivo, sin lags ni contables."""
    base = cf._base_mensual(leer_dataset())
    corte = pd.Period("2024-05", freq="M")
    for obj in cf.OBJETIVOS:
        X, y = cf.construir_features(obj, corte, base=base)
        grupos = X.attrs["grupos"]
        assert set(grupos) <= {"calendario", "exogenas"}, (obj, grupos)
        esperadas = [sid for sid, _ in cf.EXOGENAS.get(obj, []) if sid in base.columns]
        assert grupos.get("exogenas", []) == esperadas, (obj, grupos.get("exogenas"))
        assert y.index[-1] == corte - 1
    print("ok  compatibilidad: el default reproduce el conjunto de exogenas de SCRUM-29")


def main() -> None:
    test_imputacion_ocultos()
    test_imputacion_no_mira_el_real_del_mes()
    test_anti_leakage_fila_a_estimar()
    test_rezagos_correctos()
    test_compatibilidad_default()
    print("\nTodas las pruebas de construir_features pasaron.")


if __name__ == "__main__":
    main()
