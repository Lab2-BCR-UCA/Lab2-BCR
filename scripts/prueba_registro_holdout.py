"""Prueba del registro (SCRUM-44) contra los resultados de SCRUM-42.

Simula que el registro hubiera estado andando durante el holdout
(2025-09 a 2026-09): cada mes registra el pronóstico del modelo final con los
datos que había hasta el mes anterior, después completa los reales y compara
todo contra results/iaca_holdout_detalle.csv, que calculó error_iaca.py.

Si coinciden, el registro calcula la variación y los errores igual que
SCRUM-42, para el modelo final y para la réplica del X-13 BCR. Además prueba
que la elección log/nivel que hace el registro es la misma del protocolo.

Corre X-13 de verdad (4 corridas por mes): tarda unos 5 minutos con
2 núcleos. Escribe en archivos temporales y deja una copia del registro
simulado en results/registro_holdout_simulado.csv para mirarlo.

Uso, desde la raíz del repo:
    python scripts/prueba_registro_holdout.py [--procesos N]
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import registro  # noqa: E402
from replica_x13 import cargar_series  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
ESPERADO = RAIZ / "results" / "iaca_holdout_detalle.csv"
PREDICCIONES = RAIZ / "results" / "modelo_final_predicciones.csv"
SALIDA = RAIZ / "results" / "registro_holdout_simulado.csv"
TOLERANCIA = 1e-6


def _contexto(tarea: tuple[str, str]) -> tuple[str, str, dict]:
    serie, mes = tarea
    s = cargar_series()[serie]
    return serie, mes, registro.contexto_iaca(serie, s[s.index < pd.Period(mes, freq="M")])


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--procesos", type=int, default=2)
    a = p.parse_args()

    esperado = pd.read_csv(ESPERADO)
    pred = pd.read_csv(PREDICCIONES, parse_dates=["fecha"])
    pred = pred[(pred["ventana"] == "holdout") & pred["serie"].isin(registro.SERIES_IACA)]
    pred["mes"] = pred["fecha"].dt.strftime("%Y-%m")
    meses = sorted(esperado["fecha"].unique())
    series = cargar_series()

    # X-13 en paralelo; el registro se escribe después, en orden.
    tareas = [(s, m) for m in meses for s in registro.SERIES_IACA]
    print(f"Corriendo X-13 para {len(tareas)} meses-serie en {a.procesos} procesos...", flush=True)
    with ProcessPoolExecutor(max_workers=a.procesos) as ex:
        contextos = {(s, m): c for s, m, c in ex.map(_contexto, tareas)}

    with tempfile.TemporaryDirectory() as tmp:
        ruta = Path(tmp) / "registro.csv"
        for mes in meses:
            periodo = pd.Period(mes, freq="M")
            for serie in registro.SERIES_IACA:
                fila = pred[(pred["serie"] == serie) & (pred["mes"] == mes)].iloc[0]
                registro.registrar(
                    serie, mes, "modelo_final", fila["prediccion"],
                    {"modelo_elegido": fila["modelo_elegido"]},
                    ruta=ruta, ruta_db=None,
                    produccion={serie: series[serie][series[serie].index < periodo]},
                    fecha_descarga_datos=f"simulado {mes}",
                    fecha_corrida=f"{(periodo + 1).to_timestamp():%Y-%m-%d} (simulada)",
                    contexto=contextos[(serie, mes)],
                )
        reales = pd.DataFrame(
            [(registro.SERIES[k], pr.to_timestamp().strftime("%Y-%m-%d"), float(v), None, "real")
             for k in registro.SERIES_IACA for pr, v in series[k].items()],
            columns=["serie_id", "mes_estimado", "valor", "provisorio", "fecha_descarga"])
        registro.completar(ruta=ruta, ruta_db=None, reales=reales)
        reg = registro.leer_registro(ruta)
        shutil.copy(ruta, SALIDA)

    return comparar(esperado, reg, len(meses))


def comparar(esperado: pd.DataFrame, reg: pd.DataFrame, n_meses: int) -> int:
    """Compara el registro simulado con el detalle de SCRUM-42. Devuelve 0 si coincide."""
    reg = reg.add_prefix("reg_")
    reg["serie"] = reg["reg_serie_id"].map(registro.NOMBRE_DE_ID)
    reg["modelo"] = reg["reg_modelo"]
    reg["fecha"] = reg["reg_mes_estimado"].str[:7]
    cruce = esperado.merge(reg, on=["serie", "modelo", "fecha"], how="outer", indicator=True)
    problemas = []
    if (cruce["_merge"] != "both").any():
        problemas.append(f"filas sin pareja:\n{cruce.loc[cruce['_merge'] != 'both', ['serie', 'modelo', 'fecha', '_merge']]}")
    columnas = {
        "produccion_pronosticada": "reg_pronostico",
        "produccion_real": "reg_valor_real",
        "indice_pronosticado": "reg_indice_pronosticado",
        "variacion_pronosticada_pct": "reg_variacion_pronosticada_pct",
        "variacion_con_real_pct": "reg_variacion_con_real_pct",
        "error_pp": "reg_error_variacion_pp",
        "acierto_signo": "reg_acierto_signo",
    }
    for col_esp, col_reg in columnas.items():
        dif = (cruce[col_esp] - cruce[col_reg].astype(float)).abs()
        tol = TOLERANCIA * cruce[col_esp].abs().clip(lower=1)
        if (dif > tol).any():
            problemas.append(f"{col_reg}: difiere en {int((dif > tol).sum())} filas (máx. {dif.max():.3g})")
    if (cruce["variante_x13"] != cruce["reg_variante_x13"]).any():
        problemas.append("variante_x13: la elección log/nivel no coincide con el protocolo")

    print(f"\nFilas comparadas: {len(cruce)} ({n_meses} meses x 2 series x 2 modelos)")
    resumen = (reg.groupby(["serie", "modelo"])
               .agg(meses=("fecha", "count"),
                    error_medio_absoluto_pp=("reg_error_variacion_pp", lambda e: e.abs().mean()),
                    aciertos_signo=("reg_acierto_signo", "sum")))
    print(resumen.to_string(float_format=lambda n: f"{n:.4f}"))
    print(f"\nRegistro simulado guardado en {SALIDA.relative_to(RAIZ)}")
    if problemas:
        print("\nNO COINCIDE con results/iaca_holdout_detalle.csv:\n  " + "\n  ".join(problemas))
        return 1
    print("\nCoincide con results/iaca_holdout_detalle.csv (SCRUM-42) en todas las filas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
