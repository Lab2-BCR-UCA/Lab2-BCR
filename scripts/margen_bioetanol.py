"""Margen doméstico del bioetanol de maíz (SCRUM-52).

Variable derivada, análoga al margen del biodiesel (SCRUM-51): un cociente
entre el precio regulado del bioetanol de maíz y el costo del maíz, ambos en
pesos del mismo mes, por lo que la inflación se cancela y no hace falta
deflactar.

    margen_bioetanol_maiz = precio_bioetanol_maiz_ars_l
                            / (precio_maiz_pizarra_ars_tn / RINDE_L_POR_TN)

Insumos (serie_id del catálogo):
    - precio_bioetanol_maiz_ars_l  (precio regulado, Secretaría de Energía)
    - precio_maiz_pizarra_ars_tn   (pizarra de maíz, Cámara Arbitral)

A diferencia del margen del biodiesel, acá NO entra el tipo de cambio: el maíz
de la pizarra ya está en pesos.

Unidad: **ratio** (adimensional): ARS/l ÷ (ARS/tn ÷ l/tn) = ARS/l ÷ ARS/l.
``RINDE_L_POR_TN`` solo cambia la escala, no el poder predictivo; sirve para
interpretar: un valor menor a 1 indica que el precio regulado no cubre el costo
del maíz. No incluye otros costos (enzimas, energía), así que un cociente
apenas por encima de 1 puede ser margen negativo en la práctica.

Huecos del precio regulado: NO se rellenan acá. El relleno (arrastrar el último
valor vigente entre resoluciones) es una regla del **mecanismo de derivadas**
(SCRUM-56): se declara una vez en ``db/series.csv`` y el build lo aplica a todas
las derivadas que usen esos precios. Esta función solo calcula la fórmula sobre
los insumos que recibe.

Destino: cuando esté el SCRUM-56, esta fórmula pasa a ``scripts/derivadas.py`` y
se registra en ``db/derivadas.csv``. No se toca ``build_db.py``.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA = Path(__file__).resolve().parent
# Rinde aproximado de etanol por tonelada de maíz (molienda seca, ~0,40 l/kg).
# Supuesto: solo fija la escala del ratio, no el poder predictivo.
RINDE_L_POR_TN = 400.0


def margen_bioetanol_maiz(
    precio_regulado: pd.Series,
    pizarra_maiz: pd.Series,
    rinde_l_por_tn: float = RINDE_L_POR_TN,
) -> pd.Series:
    """Calcula el margen (ratio) a partir de los dos insumos, alineados por fecha.

    Pura fórmula: no rellena huecos ni reindexa (eso es del mecanismo de
    derivadas, SCRUM-56). Opera donde ambos insumos tienen dato.

    Args:
        precio_regulado: Precio regulado del bioetanol de maíz, en ARS/l.
        pizarra_maiz: Precio de pizarra del maíz, en ARS/tn.
        rinde_l_por_tn: Litros de etanol por tonelada de maíz (supuesto de escala).

    Returns:
        Serie del margen (adimensional), indexada por mes.
    """
    costo_maiz_l = pizarra_maiz / rinde_l_por_tn
    return (precio_regulado / costo_maiz_l).dropna().rename("margen_bioetanol_maiz")


def _serie_mensual(archivo: str, col: str) -> pd.Series:
    """Lee una columna como serie mensual indexada por fecha, sin duplicados."""
    df = pd.read_csv(DATA / archivo)
    s = (
        df.assign(fecha=pd.to_datetime(df["fecha"]))
        .set_index("fecha")[col]
        .sort_index()
        .astype(float)
    )
    return s[~s.index.duplicated()]


if __name__ == "__main__":
    precio_reg = _serie_mensual("bioetanol_precios.csv", "precio_maiz_ars_l")
    pizarra = _serie_mensual("soja_maiz_cac_mensual.csv", "maiz_ars_tn")
    margen = margen_bioetanol_maiz(precio_reg, pizarra)
    margen.to_frame().to_csv(DATA / "margen_bioetanol.csv", index_label="fecha")
    print(f"Escrito margen_bioetanol.csv  ({len(margen)} meses, "
          f"{margen.index.min():%Y-%m} a {margen.index.max():%Y-%m})")
    print("NOTA: sin relleno de huecos del precio regulado (lo hará el "
          "mecanismo de derivadas, SCRUM-56); por eso solo los meses con "
          "resolución vigente en el CSV crudo.")
    print(f"margen: min={margen.min():.2f}  max={margen.max():.2f}  "
          f"media={margen.mean():.2f}  meses < 1: {int((margen < 1).sum())}")
