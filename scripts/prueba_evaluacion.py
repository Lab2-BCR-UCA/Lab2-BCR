from pathlib import Path

import pandas as pd

from evaluacion import evaluar_modelo, UltimoValor, Estacional


RAIZ = Path(__file__).resolve().parents[1]
INICIO_TEST = "2025-09"
FIN_TEST = "2026-08"

biodiesel = pd.read_csv(
    RAIZ / "data" / "produccion_biodiesel.csv",
    parse_dates=["fecha"],
).set_index("fecha")

bioetanol = pd.read_csv(
    RAIZ / "data" / "produccion_bioetanol.csv",
    parse_dates=["fecha"],
).set_index("fecha")

series = {
    "biodiesel": (biodiesel["produccion_tn"], "2008-01"),
    "bioetanol_total": (bioetanol["produccion_total_m3"], "2013-01"),
    "bioetanol_maiz": (bioetanol["produccion_maiz_m3"], "2012-09"),
    "bioetanol_cana": (bioetanol["produccion_cana_m3"], "2013-01"),
}

modelos = {
    "ultimo_valor": UltimoValor,
    "estacional": Estacional,
}

detalles = []
resumenes = []

for nombre_serie, (serie, inicio) in series.items():
    for nombre_modelo, crear_modelo in modelos.items():
        detalle, resumen = evaluar_modelo(
            serie=serie,
            crear_modelo=crear_modelo,
            inicio_entrenamiento=inicio,
            inicio_test=INICIO_TEST,
            fin_test=FIN_TEST,
            nombre_serie=nombre_serie,
            nombre_modelo=nombre_modelo,
        )

        # Comprobar que se evaluaron los 12 meses sin fallos.
        assert len(detalle) == 12
        assert resumen.iloc[0]["evaluacion_completa"], detalle[
            detalle["estado"] != "ok"
        ].to_string()

        # Comprobar las predicciones contra el valor histórico esperado.
        for fila in detalle.itertuples():
            mes = pd.Timestamp(fila.fecha)
            rezago = 1 if nombre_modelo == "ultimo_valor" else 12
            esperado = serie.loc[mes - pd.DateOffset(months=rezago)]
            assert abs(fila.prediccion - esperado) < 1e-8

        # Conservar la condición de provisorio indicada en la fuente.
        fuente = biodiesel if nombre_serie == "biodiesel" else bioetanol
        marcas = fuente["provisorio"].astype(str).str.strip().str.lower()

        if not marcas.isin(["true", "false"]).all():
            raise ValueError("Hay marcas de provisorio desconocidas.")

        detalle["provisorio"] = (
            detalle["fecha"]
            .map(marcas)
            .map({"true": True, "false": False})
        )

        if detalle["provisorio"].isna().any():
            raise ValueError("Falta la marca de provisorio en algún mes.")

        resumen["meses_provisorios"] = int(detalle["provisorio"].sum())

        detalles.append(detalle)
        resumenes.append(resumen)


# Prueba independiente con métricas calculables a mano.
# Estas fechas no forman parte del test del proyecto.
ejemplo = pd.Series(
    [10.0, 12.0, 12.0],
    index=pd.date_range("2023-01-01", periods=3, freq="MS"),
)

_, prueba = evaluar_modelo(
    serie=ejemplo,
    crear_modelo=UltimoValor,
    inicio_entrenamiento="2023-01",
    inicio_test="2023-02",
    fin_test="2023-03",
)

metricas = prueba.iloc[0]
assert abs(metricas["MAE"] - 1.0) < 1e-8
assert abs(metricas["RMSE"] - 2**0.5) < 1e-8
assert abs(metricas["MAPE_pct"] - 100 / 12) < 1e-8
assert metricas["acierto_signo_pct"] == 50.0


# Guardar los resultados en la carpeta común del equipo.
salida = RAIZ / "results"
salida.mkdir(exist_ok=True)

pd.concat(detalles, ignore_index=True).to_csv(
    salida / "predicciones_baselines.csv",
    index=False,
)

tabla = pd.concat(resumenes, ignore_index=True)
# No escribir otro CSV de métricas: el único archivo canónico es
# results/baselines.csv, que genera scripts/baselines.py.
print(tabla.to_string(index=False))
print("\nPruebas completadas. Predicciones guardadas en results/.")
