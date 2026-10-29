"""Arma la tabla comparativa de los modelos de referencia (integración 21/22/23).

Junta las métricas de los baselines (SCRUM-22, archivo canónico
`results/baselines.csv`) y de
las réplicas del X-13 (`results/x13.csv`), que salen del mismo protocolo de
evaluación (SCRUM-21), en un único `results/comparacion.csv`. Es el "piso" a
superar por los modelos propios.

Modelos X-13 (ver scripts/replica_x13.py):
    x13_bcr             config exacta de BCR (.spc) + su criterio de selección
                        log/nivel sobre los últimos 12 meses (reproduce a BCR)
    x13_bcr_selcompleta idem, con el criterio calculado sobre toda la serie
    x13_bcr_log    config BCR, siempre en log
    x13_bcr_nivel  config BCR, siempre en nivel
    x13_auto       réplica automática anterior (spec mínimo), como referencia

Los dos CSV traen columnas algo distintas, así que se normalizan a un esquema
común antes de concatenar.

Requiere que existan results/baselines.csv y results/x13.csv.

Uso: python scripts/comparacion.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

# columnas comunes de la tabla comparativa
COMUNES = ["serie", "modelo", "inicio_test", "fin_test", "n_test",
           "MAE", "RMSE", "MAPE_pct", "acierto_signo_pct"]
# orden de modelos en el resumen (de más simple a más complejo)
ORDEN = ["naive", "naive_estacional", "x13_auto", "x13_bcr_log", "x13_bcr_nivel", "x13_bcr_selcompleta", "x13_bcr"]


def _normalizar(df: pd.DataFrame) -> pd.DataFrame:
    """Lleva un CSV de métricas al esquema común.

    Acepta tanto el formato de baselines.csv (con 'n_test') como el del
    protocolo (x13.csv, con 'meses_evaluados').
    """
    df = df.copy()
    if "n_test" not in df.columns and "meses_evaluados" in df.columns:
        df["n_test"] = df["meses_evaluados"]
    return df[COMUNES]


def main() -> None:
    res = Path(__file__).resolve().parent.parent / "results"
    partes = []
    for nombre in ("baselines.csv", "x13.csv"):
        p = res / nombre
        if not p.exists():
            raise FileNotFoundError(f"Falta {p}; corré primero baselines.py y replica_x13.py.")
        partes.append(_normalizar(pd.read_csv(p)))

    comp = pd.concat(partes, ignore_index=True)
    comp.to_csv(res / "comparacion.csv", index=False)

    # MAE es la métrica principal; MAPE queda como referencia.
    mae = comp.pivot_table(index="serie", columns="modelo", values="MAE").round(0)
    mape = comp.pivot_table(index="serie", columns="modelo", values="MAPE_pct").round(1)
    signo = comp.pivot_table(index="serie", columns="modelo", values="acierto_signo_pct").round(0)
    orden = [c for c in ORDEN if c in mae.columns]
    mae, mape, signo = mae[orden], mape[orden], signo[orden]

    print("MAE por serie y modelo (tn para biodiesel, m³ para bioetanol; menor = mejor):")
    print(mae.to_string())
    print("\nMejor modelo por serie (MAE):")
    for s in mae.index:
        best = mae.loc[s].idxmin()
        print(f"  {s:16s}: {best}  ({mae.loc[s, best]:,.0f})")
    print("\nMAPE % (referencia):")
    print(mape.to_string())
    print("\nAcierto de signo % (mayor = mejor):")
    print(signo.to_string())
    print(f"\nGuardado en {res / 'comparacion.csv'}")


if __name__ == "__main__":
    main()
