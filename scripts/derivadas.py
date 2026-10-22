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

import pandas as pd  # noqa: F401  (lo usan las firmas de las funciones)
