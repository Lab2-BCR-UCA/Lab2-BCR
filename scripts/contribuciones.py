"""Explicación por contribuciones del modelo final (SCRUM-35).

``explicar(modelo, fecha)`` devuelve qué factores empujan la estimación de un
mes, en toneladas o m³ y en puntos de variación.

Modelos (los elegidos en SCRUM-34, ver ``results/comparacion_final_eleccion.csv``):

- ``suma_contable`` (biodiésel): la predicción es la suma de sus destinos,
  así que cada destino es un factor: mercado interno (demanda estimada para el
  corte), exportaciones y otras ventas. Constante = 0.
- ``elastic_net_bioetanol_maiz`` / ``_cana`` / ``_total`` (el total es maíz +
  caña) y ``elastic_net_biodiesel_con_contables_sin_eventos``: la predicción
  es lineal,

      predicción = constante + Σ coef_j × (valor_j − media_j del entrenamiento)

  donde la constante es la media del target en el entrenamiento (más el
  intercepto, que con datos centrados es 0). Cada término es el aporte de una
  variable y se agrupa en factores (ver ``grupo_de``). El indicador de faltante
  de una variable va con su variable.

Puntos de variación de la producción
------------------------------------
La variación estimada es la de la producción tal cual (sin desestacionalizar)
contra el dato real del mes anterior,
``100 × (predicción − real_{t−1}) / real_{t−1}``. **No es la variación del
IACA**: el índice se desestacionaliza y se suaviza (``error_iaca.py``), así que
efectos como la estacionalidad o la zafra ahí no aparecen. Se reparte así:

- Suma contable: cada destino aporta ``estimado_t − real_{t−1}`` (ventas al
  corte, exportaciones de la Secretaría y otras ventas del mes anterior). La
  fila "variación de stock del mes anterior" es ``−(real_{t−1} − ventas_{t−1})``:
  el modelo no predice stock, así que lo que el mes anterior se produjo de más
  (o de menos) que lo vendido no se repite. Otras ventas entran con un mes de
  rezago, así que su aporte a la variación es siempre 0.
- Elastic net: cada factor aporta el cambio de su aporte entre t−1 y t, con el
  mismo modelo ajustado. La fila "ajuste del mes anterior" es
  ``ajustado_{t−1} − real_{t−1}``: lo que el modelo no explicaba del mes
  anterior.

En los dos casos las filas suman exactamente la predicción (aportes más
constante) y la variación estimada (puntos).

El ajuste replica al del protocolo (``elastic_net.correr``): mismo inicio,
misma exclusión de eventos y mismos hiperparámetros elegidos por validación
temporal. Las pruebas comparan contra las predicciones guardadas en
``results/``.

Uso:
    from contribuciones import explicar
    explicar("suma_contable", "2026-08")

    python scripts/contribuciones.py suma_contable 2026-08
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))

from elastic_net import (  # noqa: E402
    MODELOS, ModeloElasticNet, ModeloSumaBioetanol, _base, armar_X, serie_objetivo,
)
from eventos import excluir_eventos  # noqa: E402
from suma_contable import COMPONENTES, ModeloSumaContable, serie_biodiesel  # noqa: E402

FACTOR_SUMA = {
    "demanda_interna_est": "mercado interno",
    "expo_est": "exportaciones",
    "otras_ventas_t1": "otras ventas",
}
# Ventas reales del mes anterior con las que se compara cada destino.
REAL_SUMA = {
    "demanda_interna_est": "biodiesel_ventas_corte_tn",
    "expo_est": "biodiesel_exportaciones_tn",
    "otras_ventas_t1": "biodiesel_otras_ventas_tn",
}
MODELOS_EN = {
    "elastic_net_biodiesel_con_contables_sin_eventos": "biodiesel_con_contables_sin_eventos",
    "elastic_net_bioetanol_maiz": "bioetanol_maiz",
    "elastic_net_bioetanol_cana": "bioetanol_cana",
}
TOTAL = "elastic_net_bioetanol_total"


def grupo_de(variable: str, objetivo: str) -> str:
    """Factor al que pertenece una variable del elastic net."""
    v = variable.removeprefix("missingindicator_")
    # lag_12 (el mismo mes del año anterior) trae la estacionalidad; lag_1 y
    # lag_2 son inercia de corto plazo.
    if v.startswith("mes_") or v == "lag_12":
        return {"bioetanol_cana": "estacionalidad (zafra)",
                "bioetanol_maiz": "estacionalidad (maíz)"}.get(objetivo, "estacionalidad")
    if v.startswith(("lag_", "corte_efectivo")):
        return "inercia"   # el corte efectivo es casi circular: resume la mezcla reciente (SCRUM-31)
    if v.startswith("expo_"):
        return "exportaciones"
    if v.startswith(("ventas_gasoil", "ventas_nafta", "demanda_interna", "otras_ventas",
                     "corte_biodiesel_nominal", "corte_biodiesel_cotab")):
        return "mercado interno"
    if v.startswith(("margen_", "aceite_soja")):
        return "márgenes"
    if v.startswith("azucar"):
        return "zafra/azúcar"
    if v.startswith("molienda"):
        return "molienda de soja"
    raise KeyError(f"La variable '{variable}' no tiene factor asignado.")


def _periodo(fecha) -> pd.Period:
    return pd.Period(fecha, freq="M")


# ---------------------------------------------------------------- suma contable

def _explicar_suma(fecha: pd.Period, base: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    serie = serie_biodiesel(base)
    modelo = ModeloSumaContable(base).fit(serie[serie.index < fecha])
    aportes = modelo.contribuciones()
    pred = modelo.predict()

    b = base.copy()
    b.index = pd.PeriodIndex(pd.to_datetime(b.index), freq="M")
    previo = fecha - 1
    real_ant = float(serie.loc[previo])
    reales = {c: float(b.loc[previo, REAL_SUMA[c]]) for c in COMPONENTES}

    filas = [{"factor": FACTOR_SUMA[c], "aporte": aportes[c],
              "cambio": aportes[c] - reales[c]} for c in COMPONENTES]
    filas.append({"factor": "constante", "aporte": 0.0, "cambio": 0.0})
    filas.append({"factor": "variación de stock del mes anterior", "aporte": 0.0,
                  "cambio": -(real_ant - sum(reales.values()))})
    return pd.DataFrame(filas), {"prediccion": pred, "real_anterior": real_ant}


# ---------------------------------------------------------------- elastic net

def _ajustar_en(nombre_cfg: str, fecha: pd.Period, base: pd.DataFrame) -> ModeloElasticNet:
    """Igual que elastic_net.correr: mismo inicio y misma exclusión de eventos."""
    cfg = MODELOS[nombre_cfg]
    serie = serie_objetivo(cfg.objetivo, base)
    s = serie[(serie.index >= pd.Period(cfg.inicio, freq="M")) & (serie.index < fecha)]
    mascara = (excluir_eventos(cfg.objetivo)(s.index, fecha) if cfg.eventos
               else np.zeros(len(s), bool))
    return ModeloElasticNet(cfg, base).fit(s, excluir=mascara)


def _aportes_fila(modelo: ModeloElasticNet, fila: pd.DataFrame) -> tuple[pd.Series, float]:
    """Aporte de cada variable (en unidades del target) y la constante."""
    reg = modelo.mejor_.regressor_
    imp, esc, en = (reg.named_steps[k] for k in ("imputar", "estandarizar", "en"))
    z = esc.transform(imp.transform(fila))[0]
    t = modelo.mejor_.transformer_
    escala, media = float(t.scale_[0]), float(t.mean_[0])
    aportes = pd.Series(escala * en.coef_ * z, index=imp.get_feature_names_out())
    return aportes, media + escala * float(en.intercept_)


def _partes_en(modelo_nombre: str, fecha: pd.Period, base: pd.DataFrame):
    """[(objetivo, modelo ajustado)] — el total son las dos partes."""
    if modelo_nombre == TOTAL:
        serie = serie_objetivo("bioetanol_total", base)
        suma = ModeloSumaBioetanol(base).fit(serie[serie.index < fecha])
        return [(MODELOS[n].objetivo, m) for n, m in suma.partes_.items()]
    cfg = MODELOS_EN[modelo_nombre]
    return [(MODELOS[cfg].objetivo, _ajustar_en(cfg, fecha, base))]


def _explicar_en(modelo_nombre: str, fecha: pd.Period, base: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    filas, constante, pred, ajustado_ant = [], 0.0, 0.0, 0.0
    for objetivo, m in _partes_en(modelo_nombre, fecha, base):
        X, _ = armar_X(m.config, fecha, base)
        a_t, c = _aportes_fila(m, X.loc[[fecha]])
        a_ant, _ = _aportes_fila(m, X.loc[[fecha - 1]])
        p = m.predict()
        if not np.isclose(c + a_t.sum(), p, rtol=1e-9, atol=1e-6):
            raise RuntimeError(f"{objetivo} {fecha}: la predicción quedó recortada en 0 "
                               "y los aportes no la reconstruyen.")
        constante += c
        pred += p
        ajustado_ant += c + a_ant.sum()
        for var in a_t.index:
            filas.append({"factor": grupo_de(var, objetivo), "variable": var,
                          "aporte": a_t[var], "cambio": a_t[var] - a_ant[var]})
    objetivo_total = "bioetanol_total" if modelo_nombre == TOTAL else objetivo
    real_ant = float(serie_objetivo(objetivo_total, base).loc[fecha - 1])

    por_var = pd.DataFrame(filas)
    tabla = por_var.groupby("factor", as_index=False, sort=False)[["aporte", "cambio"]].sum()
    extra = pd.DataFrame([
        {"factor": "constante", "aporte": constante, "cambio": 0.0},
        {"factor": "ajuste del mes anterior", "aporte": 0.0, "cambio": ajustado_ant - real_ant},
    ])
    return (pd.concat([tabla, extra], ignore_index=True),
            {"prediccion": pred, "real_anterior": real_ant, "detalle_variables": por_var})


# ---------------------------------------------------------------- interfaz

AVISO_EXPO = ("INDEC ocultó la exportación del mes: el valor es un estimado "
              "(mediana de los meses ocultos anteriores), no un dato")


def _expo_oculta(fecha: pd.Period, base: pd.DataFrame) -> bool:
    b = base["expo_indec_oculto"].copy()
    b.index = pd.PeriodIndex(pd.to_datetime(b.index), freq="M")
    return bool(b.get(fecha, 0) == 1)


def explicar(modelo: str, fecha, base: pd.DataFrame | None = None) -> pd.DataFrame:
    """Tabla de contribuciones de ``modelo`` para el mes ``fecha``.

    Columnas: ``factor``, ``aporte`` (tn o m³; suman la predicción),
    ``aporte_variacion_produccion_pp`` (puntos; suman la variación estimada de
    la producción contra el dato real del mes anterior, sin desestacionalizar:
    no es la variación del IACA) y ``nota`` (aviso cuando el factor
    exportaciones es un estimado porque INDEC ocultó el dato). En ``.attrs``:
    ``prediccion``, ``real_anterior``, ``variacion_produccion_estimada_pct``,
    ``exportaciones_estimadas`` y, para el elastic net, ``detalle_variables``.
    """
    base = _base() if base is None else base
    fecha = _periodo(fecha)
    if modelo == "suma_contable":
        tabla, info = _explicar_suma(fecha, base)
    elif modelo in MODELOS_EN or modelo == TOTAL:
        tabla, info = _explicar_en(modelo, fecha, base)
    else:
        raise ValueError(f"Modelo no soportado: {modelo}")

    real_ant = info["real_anterior"]
    col = "aporte_variacion_produccion_pp"
    tabla[col] = 100 * tabla.pop("cambio") / real_ant
    total = {"factor": "total", "aporte": tabla["aporte"].sum(), col: tabla[col].sum()}
    tabla = pd.concat([tabla, pd.DataFrame([total])], ignore_index=True)
    # Solo importa si el modelo usa exportaciones (bioetanol no las usa).
    expo_estimada = (tabla["factor"] == "exportaciones").any() and _expo_oculta(fecha, base)
    tabla["nota"] = ""
    if expo_estimada:
        tabla.loc[tabla["factor"] == "exportaciones", "nota"] = AVISO_EXPO
    tabla.insert(0, "fecha", str(fecha))
    tabla.insert(1, "modelo", modelo)
    tabla.attrs.update(info)
    tabla.attrs["variacion_produccion_estimada_pct"] = 100 * (info["prediccion"] / real_ant - 1)
    tabla.attrs["exportaciones_estimadas"] = expo_estimada
    return tabla


def main() -> None:
    if len(sys.argv) != 3:
        print(__doc__.split("Uso:")[1])
        sys.exit(1)
    t = explicar(sys.argv[1], sys.argv[2])
    pd.set_option("display.float_format", lambda v: f"{v:,.1f}")
    print(t[["factor", "aporte", "aporte_variacion_produccion_pp"]].to_string(index=False))
    print(f"\npredicción: {t.attrs['prediccion']:,.0f} | mes anterior (real): "
          f"{t.attrs['real_anterior']:,.0f} | variación estimada de la producción: "
          f"{t.attrs['variacion_produccion_estimada_pct']:+.1f} % (sin desestacionalizar; "
          "no es la variación del IACA)")
    if t.attrs["exportaciones_estimadas"]:
        print(f"Aviso: {AVISO_EXPO}.")


if __name__ == "__main__":
    main()
