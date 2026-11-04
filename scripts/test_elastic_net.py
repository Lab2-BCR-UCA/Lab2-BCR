"""Pruebas del elastic net (SCRUM-54). Uso: python scripts/test_elastic_net.py"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_db import leer_dataset  # noqa: E402
from elastic_net import MODELOS, ModeloElasticNet, armar_X, serie_objetivo  # noqa: E402
from eventos import excluir_eventos  # noqa: E402

BASE = leer_dataset()
MES = pd.Period("2024-05", freq="M")
CFG = MODELOS["biodiesel_con_contables"]


def _ajustar(base, cfg=CFG, mes=MES, con_eventos=True):
    serie = serie_objetivo(cfg.objetivo, BASE)
    serie = serie[(serie.index < mes) & (serie.index >= pd.Period(cfg.inicio, "M"))]
    excl = excluir_eventos(cfg.objetivo)(serie.index, mes) if con_eventos else None
    return ModeloElasticNet(cfg, base).fit(serie, excluir=excl)


def test_sin_leakage():
    """Cambiar el target del mes y todo lo posterior no mueve la predicción."""
    original = _ajustar(BASE).predict()
    sucia = BASE.copy()
    fecha = MES.to_timestamp()
    sucia.loc[sucia.index >= fecha, "produccion_biodiesel_tn"] = 9e9
    for col in ("biodiesel_ventas_corte_tn", "biodiesel_otras_ventas_tn",
                "biodiesel_exportaciones_tn", "corte_efectivo_biodiesel"):
        sucia.loc[sucia.index >= fecha, col] = 9e9      # se usan con rezago 1
    for col in ("ventas_gasoil_total_m3", "expo_indec_tn", "molienda_soja_tn"):
        sucia.loc[sucia.index > fecha, col] = 9e9       # rezago 0: solo el futuro
    assert np.isclose(_ajustar(sucia).predict(), original)
    print("ok  sin leakage: el mes estimado y el futuro no mueven la predicción")


def test_transformaciones_solo_con_entrenamiento():
    """Escalado e imputación salen del entrenamiento, no de la fila a estimar."""
    m = _ajustar(BASE)
    X, _ = armar_X(CFG, MES, BASE)
    serie = serie_objetivo("biodiesel", BASE)
    excl = excluir_eventos("biodiesel")(serie.index[serie.index < MES], MES)
    fuera = set(serie.index[serie.index < MES][excl])
    usados = [p for p in X.index if p < MES and p not in fuera]
    reg = m.mejor_.regressor_
    imputador, escalador = reg.named_steps["imputar"], reg.named_steps["estandarizar"]
    X_tr = X.loc[usados]
    assert np.allclose(imputador.statistics_, X_tr.mean().to_numpy(), equal_nan=True)
    Z = imputador.transform(X_tr)
    assert np.allclose(escalador.mean_, Z.mean(axis=0))
    y_tr = serie.reindex(usados)
    assert np.isclose(m.mejor_.transformer_.mean_[0], y_tr.mean())
    assert m.n_train_ == len(usados)
    print("ok  imputación y estandarización (X e y) ajustadas solo con el entrenamiento")


def test_excluye_eventos():
    con = _ajustar(BASE, con_eventos=True)
    sin = _ajustar(BASE, con_eventos=False)
    assert sin.n_train_ - con.n_train_ == 17   # régimen 2020-2021 (12) + COTAB (5)
    print("ok  los meses de eventos terminados quedan fuera del ajuste")


def test_coeficientes_y_prediccion():
    m = _ajustar(BASE)
    c = m.coeficientes()
    assert {"variable", "coef_unidades", "seleccionada"} <= set(c.columns)
    assert c["seleccionada"].any()
    assert m.predict() >= 0
    # La predicción es intercepto + suma de aportes (lineal en X estandarizada).
    reg = m.mejor_.regressor_
    z = reg.named_steps["estandarizar"].transform(reg.named_steps["imputar"].transform(m.fila_))
    y_std = reg.named_steps["en"].intercept_ + z @ reg.named_steps["en"].coef_
    y = m.mejor_.transformer_.inverse_transform(np.atleast_2d(y_std).reshape(-1, 1))[0, 0]
    assert np.isclose(max(0.0, y), m.predict())
    print("ok  coeficientes en unidades y predicción reconstruible por aportes")


if __name__ == "__main__":
    test_sin_leakage()
    test_transformaciones_solo_con_entrenamiento()
    test_excluye_eventos()
    test_coeficientes_y_prediccion()
    print("\nTodas las pruebas del elastic net pasaron.")
