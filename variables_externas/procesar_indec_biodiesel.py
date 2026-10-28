"""Exportaciones mensuales de biodiesel según INDEC (SCRUM-57).

Lee los CSV anuales que se bajan del Sistema de Consulta de Comercio Exterior
de INDEC y escribe las dos series que usa la base unificada.

Por qué INDEC: las exportaciones son el componente que más mueve la producción
de biodiesel, pero la Secretaría de Energía las publica junto con la producción
(rezago 1). INDEC publica el comercio exterior del mes alrededor del día 20 del
mes siguiente, antes de que la BCR estime (días 22 a 28). Ver
``docs/exportaciones_indec.md``.

Cómo bajar los archivos (https://comex.indec.gob.ar):
    Tipo de comercio = Exportación, Año = <año>, Período = Mensual,
    Consulta por país = Total exportado,
    Productos = 38260000 (Biodiésel y sus mezclas...).
Guardar cada año como
``variables_externas/data/indec_biodiesel/indec_38260000_<año>.csv``.
Cada mes alcanza con volver a bajar el año en curso y reemplazar su archivo.

Formato de INDEC: separador ``;``, miles con ``.`` y decimales con ``,``.
Un mes con exportación tiene su fila; un mes sin exportación no aparece; un mes
con el monto protegido por secreto estadístico trae ``s`` en peso y valor.

Salidas (dos archivos porque la base no admite valores nulos):

* ``data/exportaciones_biodiesel_indec.csv``: todos los meses publicados, con
  ``expo_indec_hubo`` (1 si INDEC registra exportación, con monto o con ``s``)
  y ``expo_indec_oculto`` (1 si el monto viene con ``s``).
* ``data/exportaciones_biodiesel_indec_tn.csv``: solo los meses con monto
  visible, con ``expo_indec_tn`` (toneladas; 0 si no hubo exportación) y
  ``expo_indec_fob_usd``. Los meses ocultos quedan como hueco esperado.

La imputación de los meses ocultos no se hace acá: va en el constructor de
features (SCRUM-59), con datos hasta t-1.

Último mes publicado: un mes sin fila puede ser "sin exportación" o "todavía no
publicado". Por defecto se toma como publicado hasta el mes anterior al que
corresponde a hoy menos 20 días (INDEC publica alrededor del día 20). Se puede
fijar con ``--hasta``.

Uso, desde la raíz del repo:
    python variables_externas/procesar_indec_biodiesel.py
    python variables_externas/procesar_indec_biodiesel.py --hasta 2026-09
"""
from __future__ import annotations

import argparse
import re
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
CARPETA = RAIZ / "variables_externas" / "data" / "indec_biodiesel"
SALIDA_MESES = RAIZ / "data" / "exportaciones_biodiesel_indec.csv"
SALIDA_TN = RAIZ / "data" / "exportaciones_biodiesel_indec_tn.csv"
NCM = "38260000"
DIAS_PUBLICACION = 20  # INDEC publica el mes t alrededor del día 20 de t+1

MESES = {"Enero": 1, "Febrero": 2, "Marzo": 3, "Abril": 4, "Mayo": 5, "Junio": 6,
         "Julio": 7, "Agosto": 8, "Septiembre": 9, "Octubre": 10,
         "Noviembre": 11, "Diciembre": 12}
COLUMNAS = ["NCM", "Mes", "Peso Neto (Kg)", "Monto FOB en u$s"]


def _numero(texto: str) -> float | None:
    """'76.176.000,000' -> 76176000.0; 's' (secreto estadístico) -> None."""
    texto = str(texto).strip()
    if texto.lower() == "s":
        return None
    return float(texto.replace(".", "").replace(",", "."))


def anio_de(ruta: Path) -> int:
    """Año del archivo: el único grupo de exactamente 4 dígitos del nombre."""
    encontrados = re.findall(r"(?<!\d)(\d{4})(?!\d)", ruta.stem)
    if len(encontrados) != 1:
        raise ValueError(f"{ruta.name}: el nombre tiene que incluir el año (4 dígitos)")
    return int(encontrados[0])


def leer_anio(ruta: Path) -> pd.DataFrame:
    """Lee un CSV anual de INDEC y devuelve una fila por mes con exportación."""
    anio = anio_de(ruta)
    df = pd.read_csv(ruta, sep=";", dtype=str, encoding="utf-8-sig")
    faltan = [c for c in COLUMNAS if c not in df.columns]
    if faltan:
        raise ValueError(f"{ruta.name}: faltan columnas {faltan}. "
                         "¿Se bajó con 'Total exportado' y período mensual?")
    if "País/es" in df.columns:
        raise ValueError(f"{ruta.name}: está abierto por país; bajarlo con 'Total exportado'")
    otros = set(df["NCM"].str.strip()) - {NCM}
    if otros:
        raise ValueError(f"{ruta.name}: trae otras posiciones {sorted(otros)}")
    desconocidos = set(df["Mes"].str.strip()) - set(MESES)
    if desconocidos:
        raise ValueError(f"{ruta.name}: meses no reconocidos {sorted(desconocidos)}")

    filas = []
    for _, r in df.iterrows():
        kg = _numero(r["Peso Neto (Kg)"])
        fob = _numero(r["Monto FOB en u$s"])
        filas.append({
            "fecha": pd.Timestamp(year=anio, month=MESES[r["Mes"].strip()], day=1),
            "oculto": int(kg is None),
            "tn": None if kg is None else kg / 1000,
            "fob_usd": fob,
        })
    out = pd.DataFrame(filas)
    if out["fecha"].duplicated().any():
        raise ValueError(f"{ruta.name}: meses repetidos")
    return out


def ultimo_mes_publicado(hoy: date | None = None) -> pd.Timestamp:
    """Mes anterior al de (hoy - 20 días): el último que INDEC ya publicó."""
    ref = (hoy or date.today()) - timedelta(days=DIAS_PUBLICACION)
    return pd.Timestamp(year=ref.year, month=ref.month, day=1) - pd.DateOffset(months=1)


def armar(hasta: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Devuelve (serie de todos los meses, serie de meses con monto visible)."""
    archivos = sorted(CARPETA.glob("*.csv"))
    if not archivos:
        raise FileNotFoundError(f"No hay CSV de INDEC en {CARPETA}")
    datos = pd.concat([leer_anio(a) for a in archivos]).set_index("fecha").sort_index()

    anios = sorted({anio_de(a) for a in archivos})
    meses = pd.date_range(f"{anios[0]}-01-01", hasta, freq="MS")
    posteriores = datos.index[datos.index > hasta]
    if len(posteriores):
        raise ValueError(f"Hay datos posteriores a --hasta ({posteriores[0]:%Y-%m}); revisar la fecha")
    faltan_anios = [a for a in range(anios[0], hasta.year + 1) if a not in anios]
    if faltan_anios:
        raise ValueError(f"Faltan los archivos de los años {faltan_anios}")

    todos = datos.reindex(meses)
    hubo = todos["oculto"].notna()          # el mes tiene fila en INDEC
    oculto = todos["oculto"].fillna(0).astype(int)
    serie_meses = pd.DataFrame({
        "fecha": meses.strftime("%Y-%m-%d"),
        "expo_indec_hubo": hubo.astype(int).values,
        "expo_indec_oculto": oculto.values,
    })

    visibles = todos[oculto == 0]
    serie_tn = pd.DataFrame({
        "fecha": visibles.index.strftime("%Y-%m-%d"),
        "expo_indec_tn": visibles["tn"].fillna(0).round(3).values,
        "expo_indec_fob_usd": visibles["fob_usd"].fillna(0).round(2).values,
    })
    return serie_meses, serie_tn


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hasta", help="último mes publicado por INDEC (YYYY-MM)")
    args = parser.parse_args()
    hasta = pd.Timestamp(f"{args.hasta}-01") if args.hasta else ultimo_mes_publicado()

    serie_meses, serie_tn = armar(hasta)
    serie_meses.to_csv(SALIDA_MESES, index=False)
    serie_tn.to_csv(SALIDA_TN, index=False)

    n_hubo = int(serie_meses["expo_indec_hubo"].sum())
    n_ocultos = int(serie_meses["expo_indec_oculto"].sum())
    print(f"Meses {serie_meses['fecha'].iloc[0][:7]} a {hasta:%Y-%m} ({len(serie_meses)}): "
          f"{n_hubo} con exportación, {n_ocultos} con monto oculto (s).")
    print(f"Escrito {SALIDA_MESES.relative_to(RAIZ)} y {SALIDA_TN.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
