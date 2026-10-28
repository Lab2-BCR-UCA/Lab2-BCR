"""Arma el corte nominal mensual (SCRUM-48) a partir de los tramos por norma.

Python 3.10+; usa pandas. Lee ``data/corte_tramos.csv`` (un renglón por cada
período en que rigió un porcentaje, con la norma y la fuente) y escribe
``data/corte_nominal_mensual.csv`` con un valor por mes:

- ``corte_biodiesel_nominal_pct``: % mínimo obligatorio de biodiesel en el gasoil.
- ``corte_biodiesel_cotab_pct``: % adicional transitorio de 2022 (COTAB), 0 el resto.
- ``corte_bioetanol_nominal_pct``: % mínimo obligatorio de bioetanol en la nafta.

Si una norma cambia el porcentaje a mitad de mes, el valor del mes es el
promedio por días (por ejemplo, junio 2022: 15 días al 5% y 15 al 7,5% = 6,25%).

Los tramos sin ``fecha_hasta`` siguen vigentes; se extienden hasta el mes en
curso. Cuando salga una norma nueva: cerrar el tramo vigente con la fecha en
que termina, agregar el renglón nuevo y volver a correr este script.
Ver ``docs/corte.md``.

Uso (desde la raíz del repo):
    python variables_externas/armar_corte_nominal.py
    python variables_externas/armar_corte_nominal.py --hasta 2026-12
"""
import argparse
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
TRAMOS = RAIZ / "data" / "corte_tramos.csv"
SALIDA = RAIZ / "data" / "corte_nominal_mensual.csv"
DESDE = "2010-01"

# (biocombustible, tipo_corte) -> columna de salida
COLUMNAS = {
    ("biodiesel", "obligatorio_base"): "corte_biodiesel_nominal_pct",
    ("biodiesel", "adicional_transitorio"): "corte_biodiesel_cotab_pct",
    ("bioetanol", "obligatorio_base"): "corte_bioetanol_nominal_pct",
}


def armar(hasta: str) -> pd.DataFrame:
    """Devuelve el corte nominal mensual, de DESDE a ``hasta`` (YYYY-MM)."""
    tramos = pd.read_csv(TRAMOS, dtype={"fecha_hasta": str})
    ultimo_dia = pd.Period(hasta, freq="M").end_time.normalize()
    dias = pd.date_range(f"{DESDE}-01", ultimo_dia, freq="D")
    diario = pd.DataFrame(index=dias, columns=list(COLUMNAS.values()), dtype=float)

    for t in tramos.itertuples(index=False):
        col = COLUMNAS.get((t.biocombustible, t.tipo_corte))
        if col is None:
            raise ValueError(f"tipo de corte desconocido: {t.biocombustible} / {t.tipo_corte}")
        fin = pd.Timestamp(t.fecha_hasta) if isinstance(t.fecha_hasta, str) and t.fecha_hasta else ultimo_dia
        tramo = diario.loc[pd.Timestamp(t.fecha_desde):fin, col]
        if tramo.notna().any():
            raise ValueError(f"tramos superpuestos en {col} a partir de {t.fecha_desde}")
        diario.loc[tramo.index, col] = float(t.corte_pct)

    # El adicional (COTAB) solo existe en los días de su tramo; el resto vale 0.
    diario["corte_biodiesel_cotab_pct"] = diario["corte_biodiesel_cotab_pct"].fillna(0.0)
    sin_norma = diario[diario.isna().any(axis=1)]
    if len(sin_norma):
        raise ValueError(f"días sin tramo definido, por ejemplo {sin_norma.index[0]:%Y-%m-%d}")

    mensual = diario.resample("MS").mean().round(4)
    mensual.index.name = "fecha"
    return mensual.reset_index()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--hasta", default=pd.Timestamp.today().strftime("%Y-%m"),
                   help="último mes a generar (YYYY-MM); por defecto el mes en curso")
    args = p.parse_args()
    df = armar(args.hasta)
    df.to_csv(SALIDA, index=False, date_format="%Y-%m-%d", lineterminator="\n")
    print(f"{SALIDA.relative_to(RAIZ)}: {len(df)} meses ({df.fecha.iloc[0]:%Y-%m} a {df.fecha.iloc[-1]:%Y-%m})")


if __name__ == "__main__":
    main()
