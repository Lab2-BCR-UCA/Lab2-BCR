"""
Modelos de referencia (baselines) para la producción de biocombustibles.

- Naive: la predicción es el valor del mes anterior.
- Naive estacional: la predicción es el valor del mismo mes del año anterior.

Ambos se evalúan con el protocolo de docs/protocolo_evaluacion.md
(walk-forward a un mes, test 2025-09 a 2026-08) para las cuatro series
del protocolo: biodiesel, bioetanol total, bioetanol de maíz y bioetanol
de caña.

Uso, desde la raíz del proyecto:

    python scripts/baselines.py

Salida canónica de métricas: results/baselines.csv (también la usan
comparacion.py y notebooks/replica_x13.ipynb).
"""
from pathlib import Path

import pandas as pd

from evaluacion import Estacional, UltimoValor, evaluar_modelo

RAIZ = Path(__file__).resolve().parents[1]
INICIO_TEST = "2025-09"
FIN_TEST = "2026-08"

# serie: (archivo, columna, unidad, inicio de entrenamiento según protocolo)
SERIES = {
    "biodiesel": ("produccion_biodiesel.csv", "produccion_tn", "tn", "2008-01"),
    "bioetanol_total": ("produccion_bioetanol.csv", "produccion_total_m3", "m3", "2013-01"),
    "bioetanol_maiz": ("produccion_bioetanol.csv", "produccion_maiz_m3", "m3", "2012-09"),
    "bioetanol_cana": ("produccion_bioetanol.csv", "produccion_cana_m3", "m3", "2013-01"),
}

MODELOS = {
    "naive": UltimoValor,
    "naive_estacional": Estacional,
}


def main():
    filas = []

    for nombre_serie, (archivo, columna, unidad, inicio) in SERIES.items():
        datos = pd.read_csv(
            RAIZ / "data" / archivo, parse_dates=["fecha"]
        ).set_index("fecha")

        for nombre_modelo, crear_modelo in MODELOS.items():
            _, resumen = evaluar_modelo(
                serie=datos[columna],
                crear_modelo=crear_modelo,
                inicio_entrenamiento=inicio,
                inicio_test=INICIO_TEST,
                fin_test=FIN_TEST,
                nombre_serie=nombre_serie,
                nombre_modelo=nombre_modelo,
            )
            r = resumen.iloc[0]

            if not r["evaluacion_completa"]:
                raise RuntimeError(
                    f"Evaluación incompleta: {nombre_serie} / {nombre_modelo}"
                )

            # La salida conserva los metadatos que antes se duplicaban en
            # metricas_baselines.csv. Las métricas no se redondean al guardar.
            marcas = datos["provisorio"].astype(str).str.strip().str.lower()
            if not marcas.isin(["true", "false"]).all():
                raise ValueError(f"Marcas de provisorio inválidas en {archivo}")
            meses_test = datos.index.to_period("M")
            en_test = ((meses_test >= pd.Period(INICIO_TEST, freq="M")) &
                       (meses_test <= pd.Period(FIN_TEST, freq="M")))

            filas.append({
                "serie": nombre_serie,
                "modelo": nombre_modelo,
                "unidad": unidad,
                "inicio_test": r["inicio_test"],
                "fin_test": r["fin_test"],
                "n_test": int(r["meses_evaluados"]),
                "meses_previstos": int(r["meses_previstos"]),
                "meses_evaluados": int(r["meses_evaluados"]),
                "cobertura_pct": r["cobertura_pct"],
                "evaluacion_completa": r["evaluacion_completa"],
                "MAE": r["MAE"],
                "RMSE": r["RMSE"],
                "MAPE_pct": r["MAPE_pct"],
                "meses_validos_MAPE": int(r["meses_validos_MAPE"]),
                "ceros_excluidos_MAPE": int(r["ceros_excluidos_MAPE"]),
                "acierto_signo_pct": r["acierto_signo_pct"],
                "meses_provisorios": int((marcas.loc[en_test] == "true").sum()),
            })

    tabla = pd.DataFrame(filas)

    salida = RAIZ / "results"
    salida.mkdir(exist_ok=True)
    tabla.to_csv(salida / "baselines.csv", index=False)

    print(tabla.to_string(index=False))
    print(f"\nGuardado en {salida / 'baselines.csv'}")


if __name__ == "__main__":
    main()
