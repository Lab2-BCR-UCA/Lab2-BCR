"""Pruebas de las funciones del protocolo largo (SCRUM-43).

No corre X-13 ni escribe en results/: usa ejemplos chicos calculables a mano
y los baselines sobre la serie real.

Uso: python scripts/prueba_protocolo_largo.py
"""

from pathlib import Path

import numpy as np
import pandas as pd

from evaluacion import (
    Estacional,
    UltimoValor,
    comparar_modelos,
    error_por_subperiodo,
    evaluar_modelo,
    evaluar_ventanas,
    ventanas_protocolo,
)

RAIZ = Path(__file__).resolve().parents[1]


# 1. Ventanas: con datos a agosto 2026, backtest 2021-09 a 2025-08 (48 meses)
#    y holdout 2025-09 a 2026-08 (12 meses), sin superposición.
ventanas = ventanas_protocolo("2026-08")
assert ventanas == {"backtest": ("2021-09", "2025-08"), "holdout": ("2025-09", "2026-08")}
assert len(pd.period_range(*ventanas["backtest"], freq="M")) == 48

# Si llega un mes nuevo, las dos ventanas se corren un mes.
assert ventanas_protocolo("2026-09")["holdout"] == ("2025-10", "2026-09")
assert ventanas_protocolo("2026-09")["backtest"] == ("2021-09", "2025-09")


# 2. evaluar_ventanas da lo mismo que evaluar_modelo en cada ventana.
biodiesel = pd.read_csv(RAIZ / "data/produccion_biodiesel.csv",
                        parse_dates=["fecha"]).set_index("fecha")["produccion_tn"]
detalle, resumen = evaluar_ventanas(biodiesel, Estacional, "2008-01", ventanas,
                                    "biodiesel", "naive_estacional")
assert list(resumen["ventana"]) == ["backtest", "holdout"]
assert resumen["evaluacion_completa"].all()
assert (detalle.groupby("ventana").size() == pd.Series({"backtest": 48, "holdout": 12})).all()

_, solo_holdout = evaluar_modelo(biodiesel, Estacional, "2008-01", "2025-09", "2026-08")
assert abs(solo_holdout["MAPE_pct"].iloc[0]
           - resumen.set_index("ventana").loc["holdout", "MAPE_pct"]) < 1e-9

# Ningún mes de entrenamiento es posterior al mes evaluado: el naive del
# primer mes del holdout es el último mes del backtest.
primero = detalle[(detalle["ventana"] == "holdout")].iloc[0]
assert primero["fecha"] == pd.Timestamp("2025-09-01")
assert primero["prediccion"] == biodiesel.loc["2024-09-01"]


# 3. Subperíodos con un ejemplo a mano.
ejemplo = pd.DataFrame({
    "serie": "s", "modelo": "m",
    "fecha": pd.date_range("2025-09-01", periods=4, freq="MS"),
    "real": [100.0, 100.0, 100.0, 100.0],
    "error": [10.0, -10.0, 20.0, 0.0],
    "acierto_signo": [1, 0, 1, 1],
    "estado": "ok",
})
sub = error_por_subperiodo(ejemplo, {"corte": "2025-11"}).set_index("subperiodo")
assert list(sub.index) == ["antes de corte", "desde corte"]
assert sub.loc["antes de corte", "MAE"] == 10.0
assert sub.loc["desde corte", "MAE"] == 10.0
assert sub.loc["desde corte", "desde"] == "2025-11"


# 4. Comparación de modelos.
fechas = pd.date_range("2020-01-01", periods=24, freq="MS")
rng = np.random.default_rng(1)
real = np.full(24, 100.0)


def armar(errores):
    return pd.DataFrame({"fecha": fechas, "real": real, "error": errores, "estado": "ok"})


base = armar(rng.normal(0, 10, 24))

# Contra sí mismo: diferencia cero e intervalo degenerado en cero.
r = comparar_modelos(base, base, perdida="ae")
assert r["diferencia_media"] == 0 and r["ic_inf"] == 0 and r["ic_sup"] == 0

# Un modelo con la mitad de error en todos los meses: la diferencia es
# exactamente la mitad del MAE de base y el intervalo no incluye el cero.
mejor = armar(base["error"] / 2)
r = comparar_modelos(mejor, base, perdida="ae")
assert abs(r["diferencia_media"] + base["error"].abs().mean() / 2) < 1e-9
assert not r["ic_incluye_cero"] and r["ic_sup"] < 0
assert r["dm"] < 0 and r["dm_p_valor"] < 0.05

# Diebold-Mariano a mano con rezagos = 0: d / sqrt(var/n) por la corrección HLN.
d = mejor["error"].abs().to_numpy() - base["error"].abs().to_numpy()
n = len(d)
dm_mano = d.mean() / np.sqrt(((d - d.mean()) ** 2).mean() / n) * np.sqrt((n - 1) / n)
r = comparar_modelos(mejor, base, perdida="ae", rezagos=0)
assert abs(r["dm"] - dm_mano) < 1e-9

# La pérdida "ape" usa el error porcentual del MAPE.
r = comparar_modelos(mejor, base, perdida="ape")
assert abs(r["diferencia_media"] - d.mean()) < 1e-9  # real = 100

# Solo se comparan los meses que los dos modelos tienen ok.
con_fallo = mejor.copy()
con_fallo.loc[0, "estado"] = "fallo"
assert comparar_modelos(con_fallo, base, perdida="ae")["n"] == 23

# Naive contra naive estacional en la serie real corre sin errores.
det_naive, _ = evaluar_ventanas(biodiesel, UltimoValor, "2008-01", ventanas)
for v in ventanas:
    r = comparar_modelos(det_naive[det_naive["ventana"] == v],
                         detalle[detalle["ventana"] == v])
    assert r["n"] == (48 if v == "backtest" else 12)
    assert r["ic_inf"] <= r["diferencia_media"] <= r["ic_sup"]

print("Pruebas del protocolo largo: OK")
