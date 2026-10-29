"""Pruebas del constructor común de features (SCRUM-59).

Verifica los criterios del DoD y las correcciones de la review:

    1. Anti-leakage: la fila del mes a estimar no cambia si se "envenena" la base
       con datos posteriores al corte NI con datos del propio mes de corte en las
       variables de rezago 1. La decisión de log tampoco mira el futuro.
    2. Imputación de exportaciones ocultas: un mes oculto se completa con la
       mediana de la Secretaría (ocultos previos; o todos los previos si es el
       primero) y NUNCA con el valor real de la Secretaría de ese mismo mes. Sin
       NaN en el medio de la serie.
    3. Fila del mes a estimar incompleta: si queda un NaN en una feature de datos,
       el constructor frena nombrando la variable.
    4. Una exógena ausente de la base frena.
    5. Los rezagos de EXOGENAS, de las candidatas y de las contables no son
       menores que los de data/disponibilidad_variables.csv.
    6. Compatibilidad: el default reproduce el conjunto de SCRUM-29.

Uso, desde la raíz del repo:
    python scripts/test_construir_features.py
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))
import construir_features as cf  # noqa: E402
from build_db import leer_dataset  # noqa: E402

P = lambda k: pd.Period(k, "M")  # noqa: E731


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
    se = {"2020-03": 300.0, "2020-06": 500.0, "2020-09": 999.0}   # ocultos
    df["biodiesel_exportaciones_tn"] = 50.0
    for k, v in se.items():
        df.loc[P(k), "biodiesel_exportaciones_tn"] = v
    df["expo_indec_tn"] = 200.0
    df["expo_indec_oculto"] = 0.0
    for k in se:
        df.loc[P(k), "expo_indec_tn"] = np.nan
        df.loc[P(k), "expo_indec_oculto"] = 1.0
    return df


def test_imputacion_ocultos() -> None:
    base = _base_sintetica()
    X, _ = cf.construir_features("biodiesel", "2020-12", base=base,
                                 con_calendario=False, incluir=("contables",))
    # Primer oculto (marzo): sin ocultos previos -> mediana de TODOS los previos
    # (ene, feb = 50) = 50, no NaN.
    assert X.loc[P("2020-03"), "expo_est"] == 50.0, X.loc[P("2020-03"), "expo_est"]
    # Junio: mediana de los ocultos previos {marzo=300} = 300.
    assert X.loc[P("2020-06"), "expo_est"] == 300.0, X.loc[P("2020-06"), "expo_est"]
    # Septiembre: mediana de {300, 500} = 400, y NO el real de la Secretaría (999).
    assert X.loc[P("2020-09"), "expo_est"] == 400.0, X.loc[P("2020-09"), "expo_est"]
    assert X.loc[P("2020-09"), "expo_est"] != 999.0
    # Sin NaN en el medio de expo_est.
    assert not X["expo_est"].iloc[1:].isna().any(), X["expo_est"]
    # Un mes no oculto conserva INDEC.
    assert X.loc[P("2020-05"), "expo_est"] == 200.0
    assert X.loc[P("2020-09"), "expo_indec_oculto"] == 1.0
    assert abs(X.loc[P("2020-05"), "demanda_interna_est"] - 10.0) < 1e-9
    assert X.loc[P("2020-05"), "otras_ventas_t1"] == 5.0
    print("ok  imputacion de ocultos (fallback al primero, sin NaN en el medio)")


def test_imputacion_no_mira_el_real_del_mes() -> None:
    base = _base_sintetica()
    X1, _ = cf.construir_features("biodiesel", "2020-12", base=base,
                                  con_calendario=False, incluir=("contables",))
    base2 = base.copy()
    base2.loc[P("2020-09"), "biodiesel_exportaciones_tn"] = 123456.0
    X2, _ = cf.construir_features("biodiesel", "2020-12", base=base2,
                                  con_calendario=False, incluir=("contables",))
    assert X2.loc[P("2020-09"), "expo_est"] == X1.loc[P("2020-09"), "expo_est"] == 400.0
    print("ok  la imputacion de un oculto ignora el real de la Secretaria de ese mes")


def test_anti_leakage_posterior_al_corte() -> None:
    base = cf._base_mensual(leer_dataset())
    corte = P("2024-05")
    casos = [
        ("biodiesel", ("exogenas", "contables", "lags")),
        ("bioetanol_maiz", ("exogenas", "lags")),
        ("bioetanol_cana", ("exogenas", "lags")),
    ]
    for obj, incluir in casos:
        X_ok, _ = cf.construir_features(obj, corte, base=base, incluir=incluir)
        env = base.copy()
        env.loc[env.index > corte, :] = 9.9e12
        X_env, _ = cf.construir_features(obj, corte, base=env, incluir=incluir)
        dif = (X_ok.loc[:corte].fillna(-1) != X_env.loc[:corte].fillna(-1))
        assert not dif.to_numpy().any(), (obj, X_ok.columns[dif.any().to_numpy()].tolist())
    print("ok  anti-leakage: datos posteriores al corte no entran en la fila a estimar")


def test_anti_leakage_mes_de_corte_rezago_1() -> None:
    """Envenenar el PROPIO mes de corte en las variables de rezago 1 no cambia la
    fila del corte (esas variables entran con t-1)."""
    base = cf._base_mensual(leer_dataset())
    corte = P("2024-05")
    incluir = ("exogenas", "contables", "lags")
    X_ok, _ = cf.construir_features("biodiesel", corte, base=base, incluir=incluir)
    env = base.copy()
    for col in ("biodiesel_ventas_corte_tn", "biodiesel_otras_ventas_tn",
                "biodiesel_exportaciones_tn", "produccion_biodiesel_tn"):
        env.loc[corte, col] = 9.9e12
    X_env, _ = cf.construir_features("biodiesel", corte, base=env, incluir=incluir)
    fila_ok, fila_env = X_ok.loc[corte], X_env.loc[corte]
    dif = fila_ok.fillna(-1) != fila_env.fillna(-1)
    assert not dif.any(), fila_ok.index[dif.to_numpy()].tolist()
    print("ok  anti-leakage: el mes de corte en variables de rezago 1 no toca la fila a estimar")


def test_log_fijo_no_mira_el_futuro() -> None:
    """Un 0 en un mes posterior al corte no cambia la decisión de log (fija por
    variable), así que la fila del corte no se mueve."""
    base = cf._base_mensual(leer_dataset())
    corte = P("2024-05")
    X_ok, _ = cf.construir_features("bioetanol_maiz", corte, base=base, incluir=("exogenas",))
    env = base.copy()
    env.loc[corte + 3, "ventas_nafta_total_m3"] = 0.0   # 0 en el futuro
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        X_env, _ = cf.construir_features("bioetanol_maiz", corte, base=env, incluir=("exogenas",))
    assert (X_ok.loc[corte, "ventas_nafta_total_m3"]
            == X_env.loc[corte, "ventas_nafta_total_m3"])
    print("ok  log fijo por variable: un 0 futuro no cambia la fila del corte")


def test_fila_a_estimar_incompleta_frena() -> None:
    base = cf._base_mensual(leer_dataset())
    corte = P("2024-05")
    env = base.copy()
    env.loc[corte, "ventas_gasoil_total_m3"] = np.nan   # falta el gasoil del mes a estimar
    try:
        cf.construir_features("biodiesel", corte, base=env, incluir=("exogenas", "contables"))
        assert False, "debería haber frenado por la fila incompleta"
    except ValueError as e:
        assert "demanda_interna_est" in str(e), e
    print("ok  frena si la fila del mes a estimar tiene NaN, nombrando la variable")


def test_exogena_ausente_frena() -> None:
    base = cf._base_mensual(leer_dataset())
    try:
        cf.construir_features("bioetanol_cana", "2024-05", base=base,
                              exogenas_extra=[("no_existe_en_la_base", 0)])
        assert False, "debería haber frenado por la exógena ausente"
    except KeyError as e:
        assert "no_existe_en_la_base" in str(e), e
    print("ok  una exogena ausente de la base frena nombrandola")


def test_exogenas_extra() -> None:
    base = cf._base_mensual(leer_dataset())
    X, _ = cf.construir_features("bioetanol_cana", "2024-05", base=base,
                                 exogenas_extra=[("azucar_usd_kg", 0)])
    assert "azucar_usd_kg" in X.attrs["grupos"]["exogenas"], X.attrs["grupos"]
    print("ok  exogenas_extra agrega candidatas sin tocar EXOGENAS")


def test_rezagos_no_menores_que_disponibilidad() -> None:
    """Los rezagos declarados (EXOGENAS, candidatas y contables) no pueden ser
    menores que el rezago_min de data/disponibilidad_variables.csv."""
    disp = pd.read_csv(RAIZ / "data" / "disponibilidad_variables.csv")
    rezago_min = dict(zip(disp["variable"], disp["rezago_min"]))
    series = pd.read_csv(RAIZ / "db" / "series.csv")
    der = pd.read_csv(RAIZ / "db" / "derivadas.csv")
    var_disp = dict(zip(series["serie_id"], series["variable_disponibilidad"]))
    var_disp.update(dict(zip(der["serie_id"], der["variable_disponibilidad"])))

    def chequear(sid, rez, origen):
        assert sid in var_disp, f"{sid} ({origen}) no está en db/series.csv ni derivadas.csv"
        vmin = rezago_min[var_disp[sid]]
        assert rez >= vmin, f"{sid} ({origen}): rezago {rez} < disponibilidad {vmin}"

    for obj, pares in cf.EXOGENAS.items():
        for sid, rez in pares:
            chequear(sid, rez, f"EXOGENAS[{obj}]")
    for obj, pares in cf.CANDIDATAS_POR_PROBAR.items():
        for sid, rez in pares:
            chequear(sid, rez, f"CANDIDATAS[{obj}]")
    for sid, rez in cf.CONTABLES_REZAGO_USADO.items():
        chequear(sid, rez, "contables")
    print("ok  rezagos de exogenas/candidatas/contables >= disponibilidad")


def test_compatibilidad_default() -> None:
    base = cf._base_mensual(leer_dataset())
    corte = P("2024-05")
    for obj in cf.OBJETIVOS:
        X, y = cf.construir_features(obj, corte, base=base)
        grupos = X.attrs["grupos"]
        assert set(grupos) <= {"calendario", "exogenas"}, (obj, grupos)
        esperadas = [sid for sid, _ in cf.EXOGENAS.get(obj, [])]
        assert grupos.get("exogenas", []) == esperadas, (obj, grupos.get("exogenas"))
        assert y.index[-1] == corte - 1
    print("ok  compatibilidad: el default reproduce el conjunto de exogenas de SCRUM-29")


def main() -> None:
    test_imputacion_ocultos()
    test_imputacion_no_mira_el_real_del_mes()
    test_anti_leakage_posterior_al_corte()
    test_anti_leakage_mes_de_corte_rezago_1()
    test_log_fijo_no_mira_el_futuro()
    test_fila_a_estimar_incompleta_frena()
    test_exogena_ausente_frena()
    test_exogenas_extra()
    test_rezagos_no_menores_que_disponibilidad()
    test_compatibilidad_default()
    print("\nTodas las pruebas de construir_features pasaron.")


if __name__ == "__main__":
    main()
