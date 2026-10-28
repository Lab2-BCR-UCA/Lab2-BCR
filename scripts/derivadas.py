"""Fórmulas de las variables derivadas de la base unificada (SCRUM-56).

Una variable derivada se calcula a partir de otras series de la base (por
ejemplo, un margen a partir de dos precios). No se descarga: build_db.py la
recalcula en cada armado, una versión por cada versión de sus insumos, así
nunca queda desactualizada y se puede consultar como estaba en cualquier fecha.

Para agregar una derivada:

    1. Escribir acá una función con esta firma:

           def nombre(insumos: pd.DataFrame) -> pd.Series

       `insumos` tiene una fila por mes (índice de fechas, primer día del mes)
       y una columna por insumo, con el mismo nombre que su serie_id. La
       función devuelve la serie calculada con el mismo índice; los meses que
       no se pueden calcular quedan como NaN y se descartan.

       La función es solo la fórmula: no lee ni escribe archivos y no rellena
       huecos. El relleno de los insumos lo aplica build_db.py según la columna
       `relleno` de db/series.csv (por ejemplo, el precio regulado sigue
       vigente hasta la siguiente resolución).

    2. Sumar una fila en db/derivadas.csv con el nombre de la función y sus
       insumos separados por "|". Los insumos tienen que ser series crudas
       (no se permiten derivadas de derivadas).

    3. Sumar la variable en data/disponibilidad_variables.csv. Su rezago tiene
       que ser mayor o igual al de todos sus insumos.

Las constantes de cada fórmula van con nombre y documentadas como supuesto.
"""

from __future__ import annotations

import pandas as pd


# ------------------------------------------------------------------ bioetanol

# Rinde aproximado de etanol por tonelada de maíz (molienda seca, ~0,40 l/kg).
# Supuesto: solo fija la escala del ratio, no su poder predictivo.
RINDE_L_POR_TN = 400.0


def margen_bioetanol_maiz(insumos: pd.DataFrame) -> pd.Series:
    """Margen doméstico del bioetanol de maíz (SCRUM-52), adimensional.

        precio regulado [ARS/l] / (pizarra de maíz [ARS/tn] / RINDE_L_POR_TN [l/tn])

    Cociente de dos valores en pesos del mismo mes: la inflación se cancela y
    no hace falta deflactar. Un valor menor a 1 indica que el precio regulado
    no cubre el costo del maíz. No incluye otros costos (enzimas, energía), así
    que un valor apenas por encima de 1 puede ser margen negativo en la práctica.
    Los huecos del precio regulado los rellena el mecanismo (relleno = ffill).
    """
    costo_maiz_por_litro = insumos["precio_maiz_pizarra_ars_tn"] / RINDE_L_POR_TN
    return insumos["precio_bioetanol_maiz_ars_l"] / costo_maiz_por_litro


# ------------------------------------------------------------------ biodiésel

# Toneladas de aceite de soja por tonelada de biodiésel. Supuesto: ~1 a 1 (la
# transesterificación conserva la masa a grandes rasgos). Solo fija la escala
# del ratio, no su poder predictivo.
TN_ACEITE_POR_TN_BIODIESEL = 1.0


def margen_domestico_biodiesel(insumos: pd.DataFrame) -> pd.Series:
    """Margen doméstico del biodiésel (SCRUM-51), adimensional.

        precio regulado [ARS/tn] / (aceite [USD/tn] · TC [ARS/USD] · tn_aceite/tn_bd)

    El aceite de soja es el principal costo de producción del biodiésel. Como
    el precio del aceite viene en dólares (World Bank), se pasa a pesos con el
    tipo de cambio del mismo mes; recién ahí es comparable con el precio
    regulado en pesos. Un valor menor a 1 indica que el precio regulado no
    cubre el costo del aceite: es el mecanismo detrás del desabastecimiento del
    corte de 2020, cuando las plantas dejaron de entregar. No incluye metanol,
    energía ni logística, así que un valor apenas por encima de 1 puede ser
    margen negativo en la práctica.

    El aceite es promedio mensual y se publica a principios de t+1, así que esta
    derivada hereda rezago 1 (ver data/disponibilidad_variables.csv).
    """
    costo_aceite_ars_tn = (
        insumos["aceite_soja_usd_tn"]
        * insumos["tipo_cambio_promedio"]
        * TN_ACEITE_POR_TN_BIODIESEL
    )
    return insumos["precio_biodiesel_ars_tn"] / costo_aceite_ars_tn


# ------------------------------------------------------- corte efectivo (SCRUM-48)
#
# El corte efectivo es qué porcentaje del combustible vendido fue realmente
# biocombustible. Se calcula con las ventas al corte (archivo de producción)
# sobre las ventas de combustible en surtidor (SESCO). Puede quedar por debajo
# del corte nominal (la norma) cuando las plantas no entregan todo lo pedido.
# Se expresa en %, igual que el corte nominal, para poder compararlos.
#
# Supuesto: las ventas de gasoil y nafta de SESCO ya incluyen el
# biocombustible mezclado (se vende la mezcla). Con eso, en agosto 2026 el
# corte efectivo de biodiesel da ~7,2% contra un nominal de 7,5%, lo que es
# coherente. Ver docs/corte.md.

# Densidad del biodiesel para pasar toneladas a m3 (~0,88 tn/m3, rango típico
# 0,86-0,90). Supuesto: un error de densidad cambia la escala, no la forma.
DENSIDAD_BIODIESEL_TN_M3 = 0.88


def corte_efectivo_biodiesel(insumos: pd.DataFrame) -> pd.Series:
    """% de biodiesel en el gasoil vendido.

        ventas al corte [tn] / DENSIDAD_BIODIESEL_TN_M3 / ventas de gasoil [m3] × 100
    """
    biodiesel_m3 = insumos["biodiesel_ventas_corte_tn"] / DENSIDAD_BIODIESEL_TN_M3
    return biodiesel_m3 / insumos["ventas_gasoil_total_m3"] * 100


def corte_efectivo_bioetanol(insumos: pd.DataFrame) -> pd.Series:
    """% de bioetanol (caña + maíz) en la nafta vendida. Comparable con el 12% nominal."""
    return insumos["bioetanol_ventas_total_m3"] / insumos["ventas_nafta_total_m3"] * 100


def corte_efectivo_bioetanol_maiz(insumos: pd.DataFrame) -> pd.Series:
    """% de bioetanol de maíz en la nafta vendida.

    La norma (Ley 27.640) pide al menos 6% de caña y 6% de maíz; cuando la caña
    no llega, el maíz completa. Por eso la parte de cada materia prima se mide
    con este dato y no con la norma.
    """
    return insumos["bioetanol_ventas_maiz_m3"] / insumos["ventas_nafta_total_m3"] * 100


def corte_efectivo_bioetanol_cana(insumos: pd.DataFrame) -> pd.Series:
    """% de bioetanol de caña en la nafta vendida (ver corte_efectivo_bioetanol_maiz)."""
    return insumos["bioetanol_ventas_cana_m3"] / insumos["ventas_nafta_total_m3"] * 100
