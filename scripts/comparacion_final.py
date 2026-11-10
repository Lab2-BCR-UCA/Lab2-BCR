"""Comparación de los modelos y elección del final (SCRUM-34).

Junta las predicciones walk-forward de todos los modelos, las compara por serie
con el protocolo (SCRUM-43) y aplica la regla de elección:

    el modelo más interpretable cuyo error no sea significativamente peor que
    el del mejor, con Diebold-Mariano (varianza HAC).

Orden de interpretabilidad: suma contable, elastic net, SARIMAX, X-13 BCR. El
naive y el naive estacional entran como referencia: pueden ser "el mejor",
pero no se eligen.

Detalles de la regla
--------------------
- El mejor es el de menor MAE (métrica principal) en el backtest, entre todos
  los modelos de la grilla de la serie.
- "Significativamente peor" = diferencia de error absoluto contra el mejor
  positiva y Diebold-Mariano con p < 0,05 (bilateral). Se reporta también el
  IC 95 % por bootstrap de bloques.
- La elección se hace solo con el backtest. El holdout se reporta para
  confirmar y no cambia la elección.

Grilla (ticket SCRUM-34):
- Biodiésel: naive, naive estacional, X-13 BCR, suma contable (SCRUM-60),
  SARIMAX (SCRUM-29) y elastic net (SCRUM-54, versión ``con_contables_sin_eventos``,
  la recomendada en SCRUM-54 y SCRUM-31).
- Bioetanol (maíz, caña y total): naive, naive estacional, X-13 BCR, SARIMAX y
  elastic net. El total de SARIMAX y elastic net es la suma de maíz y caña.

Entradas (results/): protocolo_predicciones.csv, suma_contable_predicciones.csv,
elastic_net_predicciones.csv y sarimax_predicciones.csv.

Salidas (results/):
    comparacion_final_metricas.csv       métricas por serie, modelo y ventana
    comparacion_final_diferencias.csv    cada modelo contra el mejor, el naive y el X-13
    comparacion_final_subperiodos.csv    error por subperíodo
    comparacion_final_eleccion.csv       modelo elegido por serie y motivo
    comparacion_final_<serie>.png        predicción contra real

Uso, desde la raíz del proyecto:
    python scripts/comparacion_final.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))

from evaluacion import _metricas_basicas, comparar_modelos, error_por_subperiodo  # noqa: E402

RESULTS = RAIZ / "results"
ARCHIVOS = {
    "protocolo": "protocolo_predicciones.csv",
    "suma_contable": "suma_contable_predicciones.csv",
    "elastic_net": "elastic_net_predicciones.csv",
    "sarimax": "sarimax_predicciones.csv",
}

# (modelo en el CSV, archivo, familia). Familia None = referencia, no se elige.
_REFERENCIAS = [
    ("naive", "protocolo", None),
    ("naive_estacional", "protocolo", None),
    ("x13_bcr", "protocolo", "x13"),
]
GRILLA = {
    "biodiesel": _REFERENCIAS + [
        ("suma_contable", "suma_contable", "suma_contable"),
        ("elastic_net_biodiesel_con_contables_sin_eventos", "elastic_net", "elastic_net"),
        ("sarimax_directo", "sarimax", "sarimax"),
    ],
    "bioetanol_maiz": _REFERENCIAS + [
        ("elastic_net_bioetanol_maiz", "elastic_net", "elastic_net"),
        ("sarimax_directo", "sarimax", "sarimax"),
    ],
    "bioetanol_cana": _REFERENCIAS + [
        ("elastic_net_bioetanol_cana", "elastic_net", "elastic_net"),
        ("sarimax_directo", "sarimax", "sarimax"),
    ],
    "bioetanol_total": _REFERENCIAS + [
        ("elastic_net_bioetanol_total", "elastic_net", "elastic_net"),
        ("sarimax_suma_maiz_cana", "sarimax", "sarimax"),
    ],
}
ORDEN_INTERPRETABILIDAD = ("suma_contable", "elastic_net", "sarimax", "x13")
ALFA = 0.05


def cargar_predicciones() -> pd.DataFrame:
    """Todas las predicciones de la grilla, con la familia de cada modelo."""
    tablas = {k: pd.read_csv(RESULTS / v, parse_dates=["fecha"]) for k, v in ARCHIVOS.items()}
    partes = []
    for serie, modelos in GRILLA.items():
        for modelo, origen, familia in modelos:
            t = tablas[origen]
            d = t[(t["serie"] == serie) & (t["modelo"] == modelo)].copy()
            if d.empty:
                raise ValueError(f"No hay predicciones de {modelo} para {serie} en {ARCHIVOS[origen]}.")
            d["familia"] = familia if familia else "referencia"
            partes.append(d)
    cols = ["serie", "modelo", "familia", "ventana", "fecha", "real", "real_anterior",
            "prediccion", "error", "acierto_signo", "estado"]
    return pd.concat([p[cols] for p in partes], ignore_index=True)


def _verificar_meses(pred: pd.DataFrame) -> None:
    """Todos los modelos de una serie y ventana tienen que cubrir los mismos meses."""
    for (serie, ventana), g in pred.groupby(["serie", "ventana"]):
        meses = g.groupby("modelo")["fecha"].apply(lambda s: frozenset(s))
        if meses.nunique() != 1:
            raise ValueError(f"{serie} / {ventana}: los modelos no cubren los mismos meses.")
        malos = g[g["estado"] != "ok"]
        if not malos.empty:
            raise ValueError(f"{serie} / {ventana}: hay predicciones fallidas:\n{malos}")


def metricas(pred: pd.DataFrame) -> pd.DataFrame:
    filas = []
    for (serie, ventana, modelo, familia), g in pred.groupby(
            ["serie", "ventana", "modelo", "familia"], sort=False):
        filas.append({"serie": serie, "ventana": ventana, "modelo": modelo,
                      "familia": familia, **_metricas_basicas(g)})
    return pd.DataFrame(filas)


def diferencias(pred: pd.DataFrame, met: pd.DataFrame) -> pd.DataFrame:
    """Cada modelo contra el mejor de su serie y ventana, contra el naive y contra el X-13."""
    filas = []
    for (serie, ventana), g in pred.groupby(["serie", "ventana"], sort=False):
        m = met[(met["serie"] == serie) & (met["ventana"] == ventana)]
        mejor = m.loc[m["MAE"].idxmin(), "modelo"]
        detalle = {mod: d for mod, d in g.groupby("modelo")}
        for contra_tipo, contra in (("mejor", mejor), ("naive", "naive"), ("x13_bcr", "x13_bcr")):
            for modelo, d in detalle.items():
                if modelo == contra:
                    continue
                r = comparar_modelos(d, detalle[contra], perdida="ae")
                filas.append({"serie": serie, "ventana": ventana, "modelo": modelo,
                              "contra": contra_tipo, "modelo_contra": contra, **r})
    return pd.DataFrame(filas)


def _significativamente_peor(fila: pd.Series) -> bool:
    return bool(fila["diferencia_media"] > 0 and fila["dm_p_valor"] < ALFA)


def elegir(met: pd.DataFrame, dif: pd.DataFrame) -> pd.DataFrame:
    """Aplica la regla en el backtest, serie por serie."""
    filas = []
    for serie, modelos in GRILLA.items():
        m = met[(met["serie"] == serie) & (met["ventana"] == "backtest")].set_index("modelo")
        mejor = m["MAE"].idxmin()
        por_familia = {fam: mod for mod, _, fam in modelos if fam}
        descartados = []
        elegido = None
        for familia in ORDEN_INTERPRETABILIDAD:
            if familia not in por_familia:
                continue
            modelo = por_familia[familia]
            if modelo == mejor:
                elegido, motivo = modelo, "es el de menor MAE"
                break
            d = dif[(dif["serie"] == serie) & (dif["ventana"] == "backtest")
                    & (dif["modelo"] == modelo) & (dif["contra"] == "mejor")].iloc[0]
            if not _significativamente_peor(d):
                elegido = modelo
                motivo = (f"no es significativamente peor que {mejor} "
                          f"(dif {d['diferencia_media']:+,.0f}, p = {d['dm_p_valor']:.3f})")
                break
            descartados.append(f"{modelo} (dif {d['diferencia_media']:+,.0f}, p = {d['dm_p_valor']:.3f})")
        if elegido is None:
            raise RuntimeError(f"{serie}: ningún candidato cumple la regla.")

        def _vs(contra):
            if elegido == contra:
                return None
            return dif[(dif["serie"] == serie) & (dif["ventana"] == "backtest")
                       & (dif["modelo"] == elegido) & (dif["contra"] == contra)].iloc[0]

        fila = {"serie": serie, "elegido": elegido, "MAE_elegido": m.loc[elegido, "MAE"],
                "mejor": mejor, "MAE_mejor": m.loc[mejor, "MAE"], "motivo": motivo,
                "descartados_por_ser_peores": "; ".join(descartados)}
        for contra in ("naive", "x13_bcr"):
            r = _vs(contra)
            fila[f"dif_vs_{contra}"] = None if r is None else r["diferencia_media"]
            fila[f"p_vs_{contra}"] = None if r is None else r["dm_p_valor"]
            fila[f"le_gana_claramente_a_{contra}"] = (
                None if r is None else bool(r["diferencia_media"] < 0 and r["dm_p_valor"] < ALFA))
        filas.append(fila)
    return pd.DataFrame(filas)


def graficos(pred: pd.DataFrame, eleccion: pd.DataFrame) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    unidades = {"biodiesel": "tn"}
    for _, e in eleccion.iterrows():
        serie = e["serie"]
        g = pred[pred["serie"] == serie]
        fig, ax = plt.subplots(figsize=(10, 4))
        real = g.drop_duplicates("fecha").set_index("fecha")["real"].sort_index()
        ax.plot(real.index, real.values, color="black", lw=2, label="real")
        for modelo, estilo in ((e["elegido"], "-"), ("x13_bcr", "--"), ("naive", ":")):
            if modelo == e["elegido"] and modelo in ("x13_bcr", "naive"):
                continue
            s = g[g["modelo"] == modelo].set_index("fecha")["prediccion"].sort_index()
            etiqueta = f"{modelo} (elegido)" if modelo == e["elegido"] else modelo
            ax.plot(s.index, s.values, estilo, lw=1.5, label=etiqueta)
        if (g["ventana"] == "holdout").any():
            inicio = g.loc[g["ventana"] == "holdout", "fecha"].min()
            ax.axvline(inicio, color="gray", lw=1)
            ax.text(inicio, ax.get_ylim()[1], " holdout", va="top", color="gray")
        ax.set_title(f"{serie}: predicción a un mes contra real")
        ax.set_ylabel(unidades.get(serie, "m³"))
        ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(RESULTS / f"comparacion_final_{serie}.png", dpi=120)
        plt.close(fig)


def main() -> None:
    pred = cargar_predicciones()
    _verificar_meses(pred)
    met = metricas(pred)
    dif = diferencias(pred, met)
    eleccion = elegir(met, dif)
    sub = error_por_subperiodo(pred)

    met.to_csv(RESULTS / "comparacion_final_metricas.csv", index=False)
    dif.to_csv(RESULTS / "comparacion_final_diferencias.csv", index=False)
    sub.to_csv(RESULTS / "comparacion_final_subperiodos.csv", index=False)
    eleccion.to_csv(RESULTS / "comparacion_final_eleccion.csv", index=False)
    graficos(pred, eleccion)

    # Predicciones del modelo elegido en cada serie, con un solo nombre
    # ("modelo_final"), para la métrica del IACA (error_iaca.py --predicciones-extra).
    elegidos = dict(zip(eleccion["serie"], eleccion["elegido"]))
    final = pred[[elegidos[s] == m for s, m in zip(pred["serie"], pred["modelo"])]].copy()
    final["modelo_elegido"] = final["modelo"]
    final["modelo"] = "modelo_final"
    final.drop(columns="familia").to_csv(RESULTS / "modelo_final_predicciones.csv", index=False)

    for ventana in met["ventana"].unique():
        t = met[met["ventana"] == ventana].pivot(index="serie", columns="modelo", values="MAE")
        print(f"\nMAE ({ventana}; tn biodiésel, m³ bioetanol):")
        print(t.round(0).to_string())
    print("\nElección (backtest):")
    print(eleccion[["serie", "elegido", "MAE_elegido", "mejor", "MAE_mejor", "motivo"]].to_string(index=False))


if __name__ == "__main__":
    main()
