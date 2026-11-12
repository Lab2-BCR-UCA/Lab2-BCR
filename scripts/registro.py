"""Registro de estimaciones mensuales (SCRUM-44).

Guarda cada estimación que se hace y, cuando la Secretaría de Energía publica
el dato, la compara con el real. Así la BCR puede seguir mes a mes el error
del modelo sin hacer cuentas a mano.

Qué guarda cada fila:

1. Al estimar (``registrar``): fecha de la corrida, serie, mes, modelo,
   configuración, pronóstico y versión de la base usada. En biodiesel y
   bioetanol total también la variación del IACA que se publicaría con ese
   pronóstico y los componentes de X-13 con que se calculó. Hay que guardarla
   en el momento porque cada publicación del IACA revisa toda la serie y
   después no se puede reconstruir.
2. Al publicarse el dato (``completar``): el valor real, el error en
   producción y el error en la variación del índice (la métrica de SCRUM-42,
   ``docs/error_iaca.md``). La variación con el real se calcula con los mismos
   componentes de X-13 que se usaron al estimar.

Contribuciones (SCRUM-38): ``data/registro_contribuciones.csv``, al lado del
registro. Una fila por factor de cada estimación del modelo final, unida al
registro por ``estimacion_id`` (``agregar``). Los aportes suman el pronóstico
de esa estimación; los puntos (``aporte_variacion_produccion_pp``) son de la
variación de la producción, no del IACA. No se guarda la fila ``total``.

Dónde vive: ``data/registro_estimaciones.csv``, que se versiona en el repo.
La base (``data/bcr.db``) se borra y se vuelve a armar en cada
``build_db.py``, así que el CSV es la fuente de verdad: el armado lo carga en
la tabla ``registro_estimaciones`` y este script la actualiza cada vez que
escribe el CSV.

Reglas:

- Solo se agregan filas; nunca se modifica una fila existente (tampoco en
  las contribuciones).
- Las columnas del dato real se completan una sola vez, con la primera versión
  publicada del mes que hay en la base, aunque ``completar`` se corra después
  de una revisión (si era provisorio queda marcado en ``real_provisorio``).
- Cada vez que se escribe se controla que las filas anteriores no cambiaron.
- Si un mes se estima más de una vez quedan todas las corridas; para medir el
  error cuenta la última (``ultimas_estimaciones``).

Uso, desde la raíz del repo (antes correr ``python scripts/build_db.py``):

    python scripts/registro.py registrar --serie biodiesel --mes 2026-10 --modelo modelo_final --pronostico 123456.7
    python scripts/registro.py completar
    python scripts/registro.py exportar

Desde Python (lo que va a usar el pipeline, SCRUM-38):

    from registro import registrar, completar, exportar_excel
    registrar("biodiesel", "2026-10", "modelo_final", 123456.7, {"modelo_elegido": "suma_contable"})

El pipeline usa ``preparar`` (arma las filas sin escribir) y ``agregar``
(valida el registro y las contribuciones juntos y recién después escribe los
dos CSV).

Por defecto, al registrar biodiesel o bioetanol total se agrega también una
fila con el pronóstico de la réplica del X-13 de la BCR (``x13_bcr``), que sale
de la misma corrida de X-13 que hace falta para calcular la variación. Así el
registro compara los dos todos los meses. Se desactiva con ``--sin-x13``.

Requiere: pip install pandas numpy openpyxl x13binary
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from error_iaca import base_2013, calcular_variacion, contexto_desde_salida, signo  # noqa: E402
from replica_x13 import INICIO_BCR, SPC_BCR, _correr, _leer_tabla, criterio_bcr, spec_desde_spc  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
RUTA_REGISTRO = RAIZ / "data" / "registro_estimaciones.csv"
RUTA_DB = RAIZ / "data" / "bcr.db"
RUTA_EXCEL = RAIZ / "results" / "registro_estimaciones.xlsx"
RUTA_CONTRIBUCIONES = RAIZ / "data" / "registro_contribuciones.csv"
FILA_TABLA_CONTRIBUCIONES = 2  # en la hoja del Excel, la tabla arranca abajo del aviso (fila 3)

# Nombre corto de cada serie (el que usan los scripts de X-13) y su id en la base.
SERIES_IACA = {
    "biodiesel": "produccion_biodiesel_tn",
    "bioetanol_total": "produccion_bioetanol_total_m3",
}
SERIES = {
    **SERIES_IACA,
    "bioetanol_maiz": "produccion_bioetanol_maiz_m3",
    "bioetanol_cana": "produccion_bioetanol_cana_m3",
}
NOMBRE_DE_ID = {v: k for k, v in SERIES.items()}

COLUMNAS_ESTIMACION = [
    "fecha_corrida", "serie_id", "mes_estimado", "modelo", "configuracion", "pronostico",
    "fecha_descarga_datos", "variante_x13", "factor_base_2013", "x13_estacional",
    "x13_filtrado_penultimo", "x13_filtrado_ultimo", "indice_pronosticado",
    "variacion_pronosticada_pct",
]
COLUMNAS_REAL = [
    "valor_real", "real_provisorio", "fecha_real", "error_produccion",
    "variacion_con_real_pct", "error_variacion_pp", "acierto_signo",
]
COLUMNAS = ["estimacion_id"] + COLUMNAS_ESTIMACION + COLUMNAS_REAL
TEXTO = ["fecha_corrida", "serie_id", "mes_estimado", "modelo", "configuracion",
         "fecha_descarga_datos", "variante_x13", "fecha_real"]
ENTEROS = ["estimacion_id", "real_provisorio", "acierto_signo"]
CLAVE = ["serie_id", "mes_estimado", "modelo", "fecha_corrida"]

# Contribuciones (SCRUM-38): una fila por factor de cada estimación del modelo
# final. Sin la fila "total": es la suma de las demás.
COLUMNAS_CONTRIBUCIONES = ["estimacion_id", "factor", "aporte", "aporte_variacion_produccion_pp", "nota"]
NUMEROS_CONTRIBUCIONES = ["aporte", "aporte_variacion_produccion_pp"]
MODELO_CON_CONTRIBUCIONES = "modelo_final"
TOLERANCIA_SUMA = 1e-9  # relativa: los aportes tienen que sumar el pronóstico
AVISO_PUNTOS = ("Los puntos (aporte_variacion_produccion_pp) son de variación de la PRODUCCIÓN "
                "contra el real del mes anterior, sin desestacionalizar. No son puntos de la "
                "variación del IACA, que se desestacionaliza y se suaviza.")


# ------------------------------------------------------------ lectura y escritura

def _registro_vacio() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype=object if c in TEXTO else float) for c in COLUMNAS})


def leer_registro(ruta: Path | str = RUTA_REGISTRO) -> pd.DataFrame:
    """Lee el registro. Si todavía no existe, devuelve una tabla vacía."""
    ruta = Path(ruta)
    if not ruta.exists():
        df = _registro_vacio()
    else:
        # round_trip: los números se leen exactamente como se escribieron.
        df = pd.read_csv(ruta, dtype={c: str for c in TEXTO}, float_precision="round_trip")
        faltan = set(COLUMNAS) - set(df.columns)
        if faltan:
            raise ValueError(f"Al registro le faltan columnas: {sorted(faltan)}")
        df = df[COLUMNAS]
    for c in ENTEROS:
        df[c] = df[c].astype("Int64")
    return df


def ruta_contribuciones_de(ruta: Path | str) -> Path:
    """Las contribuciones viven al lado del registro: ``registro_contribuciones.csv``."""
    return Path(ruta).with_name(RUTA_CONTRIBUCIONES.name)


def leer_contribuciones(ruta: Path | str = RUTA_CONTRIBUCIONES) -> pd.DataFrame:
    """Lee las contribuciones. Si todavía no existe el archivo, devuelve una tabla vacía."""
    ruta = Path(ruta)
    if not ruta.exists():
        df = pd.DataFrame({c: pd.Series(dtype=object) for c in COLUMNAS_CONTRIBUCIONES})
    else:
        df = pd.read_csv(ruta, dtype={"factor": str, "nota": str}, keep_default_na=False,
                         float_precision="round_trip")
        if list(df.columns) != COLUMNAS_CONTRIBUCIONES:
            raise ValueError(f"{ruta.name}: las columnas tienen que ser {COLUMNAS_CONTRIBUCIONES}, "
                             f"no {list(df.columns)}")
    for c in NUMEROS_CONTRIBUCIONES:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    df["estimacion_id"] = pd.to_numeric(df["estimacion_id"], errors="coerce").astype("Int64")
    return df


def validar_contribuciones(contribuciones: pd.DataFrame, registro_df: pd.DataFrame,
                           esperadas=None) -> None:
    """Frena si las contribuciones no cierran con el registro.

    Controla que tengan exactamente las columnas acordadas; que no haya vacíos
    ni valores no numéricos; que no esté la fila ``total``; que no se repita un
    factor dentro de una estimación; que cada ``estimacion_id`` exista en el
    registro y sea del modelo final; que los aportes de cada estimación sumen
    su pronóstico; y, si se pasa ``esperadas``, que estén exactamente esas
    estimaciones (ni una de más ni una de menos).
    """
    c = contribuciones
    if list(c.columns) != COLUMNAS_CONTRIBUCIONES:
        raise ValueError(f"Las contribuciones tienen que tener las columnas {COLUMNAS_CONTRIBUCIONES}, "
                         f"no {list(c.columns)}.")
    if c.empty:
        raise ValueError("No hay contribuciones para guardar.")
    numeros = c[NUMEROS_CONTRIBUCIONES].apply(pd.to_numeric, errors="coerce").astype(float)
    ids = pd.to_numeric(c["estimacion_id"], errors="coerce")
    factor = c["factor"].astype("string").str.strip()
    vacios = (ids.isna() | factor.isna() | (factor == "").fillna(True)
              | ~np.isfinite(numeros.to_numpy()).all(axis=1))
    if vacios.any():
        raise ValueError(f"Contribuciones con datos vacíos o no numéricos en las filas {list(c.index[vacios])}.")
    ids = ids.astype(int)
    if (factor == "total").any():
        raise ValueError("La fila 'total' no se guarda en las contribuciones: es la suma de las demás.")
    repetidos = pd.DataFrame({"id": ids, "factor": factor}).duplicated()
    if repetidos.any():
        raise ValueError(f"Factores repetidos en una misma estimación: "
                         f"{list(zip(ids[repetidos], factor[repetidos]))}.")

    reg = registro_df.assign(estimacion_id=registro_df["estimacion_id"].astype(int)).set_index("estimacion_id")
    unicos = pd.Index(sorted(ids.unique()))
    faltan = unicos.difference(reg.index)
    if len(faltan):
        raise ValueError(f"Contribuciones de estimaciones que no están en el registro: {list(faltan)}.")
    otro_modelo = reg.loc[unicos, "modelo"] != MODELO_CON_CONTRIBUCIONES
    if otro_modelo.any():
        raise ValueError(f"Solo se guardan contribuciones del modelo final; las estimaciones "
                         f"{list(otro_modelo[otro_modelo].index)} son de otro modelo.")
    if esperadas is not None:
        esperadas = sorted({int(i) for i in esperadas})
        if list(unicos) != esperadas:
            raise ValueError(f"Faltan o sobran contribuciones: se esperaban las estimaciones {esperadas} "
                             f"y llegaron {list(unicos)}.")

    suma = numeros["aporte"].groupby(ids).sum()
    pronostico = reg.loc[suma.index, "pronostico"].astype(float)
    mal = ~np.isclose(suma.to_numpy(), pronostico.to_numpy(), rtol=TOLERANCIA_SUMA, atol=1e-6)
    if mal.any():
        detalle = "; ".join(f"estimación {i}: los aportes suman {suma[i]:,.4f} y el pronóstico es "
                            f"{pronostico[i]:,.4f}" for i in suma.index[mal])
        raise ValueError(f"Los aportes no suman el pronóstico del registro ({detalle}).")


def _controlar_solo_agrega(anterior: pd.DataFrame, nuevo: pd.DataFrame) -> None:
    """Frena si una fila que ya estaba cambió o desapareció.

    Las columnas de la estimación no pueden cambiar nunca; las del real solo
    pueden pasar de vacías a completas.
    """
    if anterior.empty:
        return
    nuevo = nuevo.set_index("estimacion_id")
    anterior = anterior.set_index("estimacion_id")
    faltan = anterior.index.difference(nuevo.index)
    if len(faltan):
        raise RuntimeError(f"Se borrarían filas del registro: {list(faltan)}")
    for col in COLUMNAS_ESTIMACION + COLUMNAS_REAL:
        a = anterior[col]
        b = nuevo.loc[anterior.index, col]
        if col in COLUMNAS_REAL:
            a, b = a[a.notna()], b[a.notna()]
        distintos = ~((a == b) | (a.isna() & b.isna()))
        if distintos.any():
            raise RuntimeError(f"Se modificaría la columna '{col}' en las filas "
                               f"{list(distintos[distintos].index)}; el registro solo admite agregar.")


def _guardar(nuevo: pd.DataFrame, ruta: Path, ruta_db: Path | None) -> None:
    """Escribe el CSV (todo o nada) y actualiza la tabla de la base."""
    ruta = Path(ruta)
    _controlar_solo_agrega(leer_registro(ruta), nuevo)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(".tmp")
    nuevo[COLUMNAS].to_csv(tmp, index=False)
    os.replace(tmp, ruta)
    if ruta_db and Path(ruta_db).exists():
        cargar_en_base(ruta_db, ruta)


def _filas_sql(df: pd.DataFrame, columnas: list[str]) -> list[tuple]:
    return [tuple(None if pd.isna(v) else (int(v) if isinstance(v, (np.integer,)) else v)
                  for v in fila) for fila in df[columnas].itertuples(index=False)]


def cargar_en_base(ruta_db: Path | str, ruta: Path | str = RUTA_REGISTRO,
                   ruta_contribuciones: Path | str | None = None) -> int:
    """Copia los CSV del registro y de las contribuciones a sus tablas. Devuelve las filas del registro.

    Las tablas son un derivado de los CSV: se vacían y se vuelven a llenar.
    Las contribuciones se leen de ``ruta_contribuciones`` (por defecto, el
    archivo al lado del registro).
    """
    df = leer_registro(ruta)
    contrib = leer_contribuciones(ruta_contribuciones or ruta_contribuciones_de(ruta))
    filas = _filas_sql(df, COLUMNAS)
    filas_c = _filas_sql(contrib, COLUMNAS_CONTRIBUCIONES)
    con = sqlite3.connect(ruta_db)
    try:
        con.execute("PRAGMA foreign_keys = ON")
        with con:
            con.execute("DELETE FROM registro_contribuciones")
            con.execute("DELETE FROM registro_estimaciones")
            con.executemany(f"INSERT INTO registro_estimaciones ({', '.join(COLUMNAS)}) "
                            f"VALUES ({', '.join('?' * len(COLUMNAS))})", filas)
            con.executemany(f"INSERT INTO registro_contribuciones ({', '.join(COLUMNAS_CONTRIBUCIONES)}) "
                            f"VALUES ({', '.join('?' * len(COLUMNAS_CONTRIBUCIONES))})", filas_c)
    except sqlite3.OperationalError as e:
        raise RuntimeError(f"La base no tiene la tabla del registro actualizada ({e}). "
                           "Correr python scripts/build_db.py --solo-reconstruir") from e
    finally:
        con.close()
    return len(filas)


# ------------------------------------------------------------ datos de la base

def produccion_en_base(ruta_db: Path | str = RUTA_DB) -> tuple[dict[str, pd.Series], str]:
    """Producción (última versión de cada mes) y fecha de la base.

    Returns:
        Un diccionario nombre -> serie mensual (PeriodIndex) y la fecha de la
        descarga más reciente de la base, que identifica la versión de los
        datos usada (sirve para la consulta "qué se sabía en una fecha dada"
        de db/README.md).
    """
    _exigir_base(ruta_db)
    con = sqlite3.connect(ruta_db)
    try:
        ids = ", ".join(f"'{i}'" for i in SERIES.values())
        df = pd.read_sql(f"SELECT serie_id, fecha, valor FROM v_ultima_version "
                         f"WHERE serie_id IN ({ids})", con)
        fecha = con.execute("SELECT MAX(fecha_descarga) FROM descargas").fetchone()[0]
    finally:
        con.close()
    df["fecha"] = pd.PeriodIndex(df["fecha"], freq="M")
    series = {NOMBRE_DE_ID[i]: g.set_index("fecha")["valor"].sort_index().astype(float)
              for i, g in df.groupby("serie_id")}
    return series, fecha


def reales_en_base(ruta_db: Path | str = RUTA_DB) -> pd.DataFrame:
    """Primer dato publicado de cada mes: serie_id, mes_estimado, valor, provisorio y fecha de la descarga.

    Toma la primera versión de cada mes que hay en la base, no la última: así
    el real es el mismo aunque ``completar`` se corra después de que la
    Secretaría revise el dato.
    """
    _exigir_base(ruta_db)
    con = sqlite3.connect(ruta_db)
    try:
        ids = ", ".join(f"'{i}'" for i in SERIES.values())
        df = pd.read_sql(f"""
            SELECT serie_id, fecha AS mes_estimado, valor, provisorio, fecha_descarga
            FROM (
                SELECT o.serie_id, o.fecha, o.valor, o.provisorio, d.fecha_descarga,
                       ROW_NUMBER() OVER (PARTITION BY o.serie_id, o.fecha
                                          ORDER BY d.fecha_descarga, o.descarga_id) AS orden
                FROM observaciones o JOIN descargas d USING (descarga_id)
                WHERE o.serie_id IN ({ids})
            )
            WHERE orden = 1""", con)
    finally:
        con.close()
    return df


def _exigir_base(ruta_db: Path | str | None) -> None:
    if ruta_db is None:
        raise ValueError("Sin base (ruta_db=None) hay que pasar los datos a mano "
                         "(produccion y fecha_descarga_datos al registrar, reales al completar).")
    if not Path(ruta_db).exists():
        raise FileNotFoundError(f"No existe {ruta_db}. Correr antes python scripts/build_db.py")


# ------------------------------------------------------------ X-13 y variación

def contexto_iaca(nombre: str, entrenamiento: pd.Series) -> dict:
    """Corre el X-13 de la BCR (log y nivel) y devuelve el contexto del IACA.

    Elige entre log y nivel con el criterio de la BCR sobre los últimos 12
    meses (el mismo que ``x13_bcr`` en replica_x13.py) y arma los componentes
    con la misma función que SCRUM-42 (``contexto_desde_salida``).

    Returns:
        ``variante``, ``spc``, ``pronostico_x13``, ``estacional``,
        ``filtrado_penultimo`` y ``filtrado_ultimo``.
    """
    inicio = pd.Period(INICIO_BCR[nombre], freq="M")
    ent = entrenamiento[entrenamiento.index >= inicio]
    ultimo = ent.index[-1]
    salidas, criterios = {}, {}
    for variante, spc in zip(("log", "nivel"), SPC_BCR[nombre]):
        salidas[variante] = _correr(spec_desde_spc(spc, ent))
        d12 = _leer_tabla(salidas[variante].get("d12"))
        criterios[variante] = criterio_bcr(d12, ultimo, ultimos_meses=12) if len(d12) else np.nan
    # Mismo desempate que pronostico_bcr: log salvo que nivel tenga menor desvío.
    c_log, c_niv = criterios["log"], criterios["nivel"]
    variante = "log" if np.isnan(c_niv) or (not np.isnan(c_log) and c_log <= c_niv) else "nivel"
    contexto = contexto_desde_salida(salidas[variante], ultimo, f"{nombre}, {variante}")
    spc = SPC_BCR[nombre][0 if variante == "log" else 1]
    return {"variante": variante, "spc": spc, **contexto}


def _columnas_iaca(pronostico: float, ctx: dict, factor: float) -> dict:
    indice, variacion = calcular_variacion(pronostico, ctx, factor, ctx["variante"])
    return {
        "variante_x13": ctx["variante"],
        "factor_base_2013": factor,
        "x13_estacional": ctx["estacional"],
        "x13_filtrado_penultimo": ctx["filtrado_penultimo"],
        "x13_filtrado_ultimo": ctx["filtrado_ultimo"],
        "indice_pronosticado": indice,
        "variacion_pronosticada_pct": variacion,
    }


def _contexto_de_fila(fila) -> dict:
    return {
        "estacional": fila.x13_estacional,
        "filtrado_penultimo": fila.x13_filtrado_penultimo,
        "filtrado_ultimo": fila.x13_filtrado_ultimo,
    }


# ------------------------------------------------------------ operaciones

def registrar(
    serie: str,
    mes: str | pd.Period,
    modelo: str,
    pronostico: float,
    configuracion: dict | None = None,
    *,
    incluir_x13: bool = True,
    ruta: Path | str = RUTA_REGISTRO,
    ruta_db: Path | str | None = RUTA_DB,
    produccion: dict[str, pd.Series] | None = None,
    fecha_descarga_datos: str | None = None,
    fecha_corrida: str | None = None,
    contexto: dict | None = None,
) -> pd.DataFrame:
    """Agrega al registro la estimación de un mes. Devuelve las filas agregadas.

    Sin contribuciones: para guardar la estimación junto con sus
    contribuciones (lo que hace el pipeline) usar ``preparar`` y ``agregar``.
    Los argumentos son los de ``preparar``; ``ruta`` es el CSV del registro.
    """
    anterior = leer_registro(ruta)
    nuevas = preparar(serie, mes, modelo, pronostico, configuracion, incluir_x13=incluir_x13,
                      anterior=anterior, ruta_db=ruta_db, produccion=produccion,
                      fecha_descarga_datos=fecha_descarga_datos, fecha_corrida=fecha_corrida,
                      contexto=contexto)
    todo = pd.concat([anterior, nuevas], ignore_index=True) if len(anterior) else nuevas
    _guardar(todo, ruta, ruta_db)
    return nuevas


def preparar(
    serie: str,
    mes: str | pd.Period,
    modelo: str,
    pronostico: float,
    configuracion: dict | None = None,
    *,
    incluir_x13: bool = True,
    anterior: pd.DataFrame | None = None,
    ruta_db: Path | str | None = RUTA_DB,
    produccion: dict[str, pd.Series] | None = None,
    fecha_descarga_datos: str | None = None,
    fecha_corrida: str | None = None,
    contexto: dict | None = None,
) -> pd.DataFrame:
    """Arma las filas del registro para la estimación de un mes, sin escribir nada.

    Args:
        serie: ``biodiesel``, ``bioetanol_total``, ``bioetanol_maiz`` o
            ``bioetanol_cana``. La variación del IACA solo se calcula en las
            dos primeras.
        mes: Mes estimado (``"2026-10"``). Tiene que ser el siguiente al
            último mes con dato.
        modelo: Nombre del modelo (``modelo_final``, ``x13_bcr``, ...).
        pronostico: Producción estimada (tn o m³).
        configuracion: Parámetros del modelo; se guardan como JSON.
        incluir_x13: Agregar también la fila de la réplica del X-13 BCR.
        anterior: Registro hasta ahora (incluidas las filas ya preparadas en
            la misma corrida); de ahí salen los ``estimacion_id`` y el control
            de corridas repetidas. Por defecto, vacío.
        ruta_db: Base de donde se lee la producción. ``None``: hay que pasar
            ``produccion`` y ``fecha_descarga_datos``.
        produccion: Series de producción a usar en lugar de la base (pruebas).
        fecha_descarga_datos: Versión de los datos, si no se lee de la base.
        fecha_corrida: Por defecto, el momento actual.
        contexto: Contexto de X-13 ya calculado (pruebas); si no, corre X-13.
    """
    if serie not in SERIES:
        raise ValueError(f"Serie desconocida: {serie}. Opciones: {sorted(SERIES)}")
    mes = pd.Period(mes, freq="M")
    if produccion is None:
        produccion, fecha_base = produccion_en_base(ruta_db)
        fecha_descarga_datos = fecha_descarga_datos or fecha_base
    if not fecha_descarga_datos:
        raise ValueError("Falta la versión de los datos (fecha_descarga_datos).")
    s = produccion[serie].dropna().sort_index()
    if mes in s.index:
        raise ValueError(f"{serie} {mes} ya está publicado en los datos: no es una estimación.")
    entrenamiento = s[s.index < mes]
    if entrenamiento.empty or entrenamiento.index[-1] != mes - 1:
        hasta = entrenamiento.index[-1] if len(entrenamiento) else "ningún mes"
        raise ValueError(f"Los datos de {serie} llegan hasta {hasta}; "
                         f"el mes a estimar tiene que ser el siguiente, no {mes}.")

    fecha_corrida = fecha_corrida or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    base = {
        "fecha_corrida": fecha_corrida,
        "serie_id": SERIES[serie],
        "mes_estimado": mes.to_timestamp().strftime("%Y-%m-%d"),
        "fecha_descarga_datos": fecha_descarga_datos,
    }
    filas = [{**base, "modelo": modelo, "pronostico": float(pronostico),
              "configuracion": json.dumps(configuracion or {}, ensure_ascii=False, sort_keys=True)}]

    if serie in SERIES_IACA:
        ctx = contexto or contexto_iaca(serie, entrenamiento)
        factor = base_2013(s)
        if incluir_x13 and modelo != "x13_bcr":
            filas.append({**base, "modelo": "x13_bcr", "pronostico": ctx["pronostico_x13"],
                          "configuracion": json.dumps({"variante": ctx["variante"], "spc": ctx["spc"]},
                                                      sort_keys=True)})
        for f in filas:
            f.update(_columnas_iaca(f["pronostico"], ctx, factor))

    if anterior is None:
        anterior = _registro_vacio()
        for c in ENTEROS:
            anterior[c] = anterior[c].astype("Int64")
    nuevas = pd.DataFrame(filas).reindex(columns=COLUMNAS)
    claves = set(map(tuple, anterior[CLAVE].to_numpy()))
    repetidas = [tuple(k) for k in nuevas[CLAVE].to_numpy() if tuple(k) in claves]
    if repetidas:
        raise ValueError(f"Ya está registrada: {repetidas}")
    inicio = int(anterior["estimacion_id"].max()) + 1 if len(anterior) else 1
    nuevas["estimacion_id"] = range(inicio, inicio + len(nuevas))
    for c in ENTEROS:
        nuevas[c] = nuevas[c].astype("Int64")
    return nuevas


def agregar(
    nuevas: pd.DataFrame,
    contribuciones: pd.DataFrame,
    *,
    ruta: Path | str = RUTA_REGISTRO,
    ruta_contribuciones: Path | str | None = None,
    ruta_db: Path | str | None = RUTA_DB,
) -> None:
    """Agrega las estimaciones al registro y sus contribuciones, todo o nada.

    Primero valida todo: que el registro solo agregue filas, que haya
    contribuciones para cada estimación nueva del modelo final y solo para
    esas, que no esté la fila ``total`` y que los aportes sumen el pronóstico
    (``validar_contribuciones``). Recién entonces escribe los dos CSV en
    temporales, los vuelve a leer y controla, y los reemplaza. Si algo falla
    no se toca ninguno de los dos archivos.

    Args:
        nuevas: Filas de ``preparar`` (de una o varias series).
        contribuciones: Columnas ``COLUMNAS_CONTRIBUCIONES``.
        ruta_contribuciones: Por defecto, al lado del registro.
    """
    ruta = Path(ruta)
    ruta_c = Path(ruta_contribuciones) if ruta_contribuciones else ruta_contribuciones_de(ruta)
    anterior = leer_registro(ruta)
    ids_nuevos = set(nuevas["estimacion_id"].astype(int))
    repetidos = ids_nuevos & set(anterior["estimacion_id"].dropna().astype(int))
    if repetidos:
        raise ValueError(f"Las estimaciones {sorted(repetidos)} ya están en el registro.")
    todo = (pd.concat([anterior, nuevas[COLUMNAS]], ignore_index=True) if len(anterior)
            else nuevas[COLUMNAS].reset_index(drop=True))
    for c in ENTEROS:
        todo[c] = todo[c].astype("Int64")
    _controlar_solo_agrega(anterior, todo)

    c_ant = leer_contribuciones(ruta_c)
    contrib = contribuciones.copy()
    contrib["nota"] = contrib["nota"].fillna("")
    contrib = contrib[COLUMNAS_CONTRIBUCIONES].reset_index(drop=True)
    finales = nuevas.loc[nuevas["modelo"] == MODELO_CON_CONTRIBUCIONES, "estimacion_id"].astype(int)
    validar_contribuciones(contrib, todo, esperadas=finales)
    ya = set(contrib["estimacion_id"].astype(int)) & set(c_ant["estimacion_id"].dropna().astype(int))
    if ya:
        raise ValueError(f"Ya hay contribuciones guardadas para las estimaciones {sorted(ya)}.")
    contrib_todo = pd.concat([c_ant, contrib], ignore_index=True) if len(c_ant) else contrib

    for r in (ruta, ruta_c):
        r.parent.mkdir(parents=True, exist_ok=True)
    tmp_r, tmp_c = ruta.with_suffix(".tmp"), ruta_c.with_suffix(".tmp")
    try:
        todo[COLUMNAS].to_csv(tmp_r, index=False)
        contrib_todo.to_csv(tmp_c, index=False)
        # Lo escrito se vuelve a leer y se controla antes de reemplazar.
        releido_r, releido_c = leer_registro(tmp_r), leer_contribuciones(tmp_c)
        _controlar_solo_agrega(anterior, releido_r)
        if len(c_ant) and not releido_c.iloc[:len(c_ant)].reset_index(drop=True).equals(
                c_ant.reset_index(drop=True)):
            raise RuntimeError("Se modificarían contribuciones ya guardadas; no se escribió nada.")
        validar_contribuciones(releido_c.iloc[len(c_ant):].reset_index(drop=True), releido_r,
                               esperadas=finales)
    except Exception:
        tmp_r.unlink(missing_ok=True)
        tmp_c.unlink(missing_ok=True)
        raise
    os.replace(tmp_r, ruta)
    os.replace(tmp_c, ruta_c)
    if ruta_db and Path(ruta_db).exists():
        cargar_en_base(ruta_db, ruta, ruta_c)


def completar(
    *,
    ruta: Path | str = RUTA_REGISTRO,
    ruta_db: Path | str | None = RUTA_DB,
    reales: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Completa el real y los errores de las estimaciones ya publicadas.

    Solo toca filas sin real. Devuelve las filas completadas.

    Args:
        reales: Tabla con ``serie_id``, ``mes_estimado`` (YYYY-MM-01),
            ``valor``, ``provisorio`` y ``fecha_descarga`` (pruebas). Por
            defecto se lee de la base.
    """
    df = leer_registro(ruta)
    pendientes = df["valor_real"].isna()
    if not pendientes.any():
        return df.iloc[0:0]
    if reales is None:
        reales = reales_en_base(ruta_db)
    reales = reales.set_index(["serie_id", "mes_estimado"])

    completadas = []
    for i in df.index[pendientes]:
        fila = df.loc[i]
        clave = (fila.serie_id, fila.mes_estimado)
        if clave not in reales.index:
            continue
        r = reales.loc[clave]
        real = float(r["valor"])
        df.loc[i, "valor_real"] = real
        df.loc[i, "real_provisorio"] = None if pd.isna(r["provisorio"]) else int(r["provisorio"])
        df.loc[i, "fecha_real"] = r["fecha_descarga"]
        df.loc[i, "error_produccion"] = fila.pronostico - real
        if pd.notna(fila.variante_x13):
            _, var_real = calcular_variacion(real, _contexto_de_fila(fila),
                                             fila.factor_base_2013, fila.variante_x13)
            df.loc[i, "variacion_con_real_pct"] = var_real
            df.loc[i, "error_variacion_pp"] = fila.variacion_pronosticada_pct - var_real
            df.loc[i, "acierto_signo"] = int(signo(fila.variacion_pronosticada_pct) == signo(var_real))
        completadas.append(i)

    if completadas:
        _guardar(df, ruta, ruta_db)
    return df.loc[completadas]


DESCRIPCIONES = {
    "estimacion_id": "Número de la estimación (correlativo).",
    "fecha_corrida": "Cuándo se corrió el modelo.",
    "serie_id": "Serie estimada (producción de biodiesel en tn o de bioetanol en m³).",
    "mes_estimado": "Mes que se estimó.",
    "modelo": "Modelo que hizo la estimación. x13_bcr es la réplica del X-13 de la BCR.",
    "configuracion": "Parámetros del modelo.",
    "pronostico": "Producción estimada.",
    "fecha_descarga_datos": "Fecha de la versión de los datos usada para estimar.",
    "variante_x13": "Variante del X-13 usada para el índice (log o nivel), elegida con el criterio de la BCR.",
    "factor_base_2013": "Factor que lleva la producción a índice base 2013 = 100.",
    "x13_estacional": "Factor estacional del mes estimado según X-13.",
    "x13_filtrado_penultimo": "Serie filtrada de X-13 en el anteúltimo mes con dato.",
    "x13_filtrado_ultimo": "Serie filtrada de X-13 en el último mes con dato.",
    "indice_pronosticado": "Índice que se publicaría con este pronóstico.",
    "variacion_pronosticada_pct": "Variación mensual del índice que se publicaría con este pronóstico (%).",
    "valor_real": "Producción publicada por la Secretaría de Energía (primer dato disponible).",
    "real_provisorio": "1 si el primer dato publicado era provisorio.",
    "fecha_real": "Fecha de la descarga que trajo el dato real.",
    "error_produccion": "Pronóstico menos real (positivo: se sobreestimó).",
    "variacion_con_real_pct": "Variación del índice que habría dado el dato real, con los mismos ajustes de X-13 (%).",
    "error_variacion_pp": "Variación pronosticada menos variación con el real, en puntos porcentuales.",
    "acierto_signo": "1 si la variación pronosticada tuvo la misma dirección (sube o baja) que la real.",
}


DESCRIPCIONES_CONTRIBUCIONES = {
    "estimacion_id": "Estimación del modelo final que se explica (la misma fila del registro).",
    "serie_id": "Serie estimada (se trae del registro para leer la hoja; no está en el CSV).",
    "mes_estimado": "Mes estimado (se trae del registro; no está en el CSV).",
    "factor": "Factor que empuja la estimación. 'constante' es el nivel medio del modelo.",
    "aporte": "Aporte del factor a la producción estimada, en tn o m³. Los aportes de una "
              "estimación suman su pronóstico.",
    "aporte_variacion_produccion_pp": "Aporte del factor a la variación de la PRODUCCIÓN contra el real "
                                      "del mes anterior, en puntos porcentuales y sin desestacionalizar. "
                                      "NO son puntos de la variación del IACA.",
    "nota": "Aviso del factor (por ejemplo, exportación estimada porque INDEC ocultó el dato).",
}


def ultimas_estimaciones(df: pd.DataFrame) -> pd.DataFrame:
    """Se queda con la última corrida de cada serie, mes y modelo.

    Si un mes se estimó más de una vez (por ejemplo, porque se corrigieron
    datos y se volvió a correr), todas las corridas quedan en el registro,
    pero para medir el error cuenta la última: es la que se habría publicado.
    """
    orden = df.sort_values(["fecha_corrida", "estimacion_id"])
    return (orden.drop_duplicates(["serie_id", "mes_estimado", "modelo"], keep="last")
            .sort_values("estimacion_id").reset_index(drop=True))


def exportar_excel(ruta: Path | str = RUTA_REGISTRO, ruta_excel: Path | str = RUTA_EXCEL,
                   ruta_contribuciones: Path | str | None = None) -> Path:
    """Exporta el registro a Excel.

    Hojas: ``ultima_por_mes`` (la última estimación de cada mes, la que se usa
    para medir el error), ``registro`` (todas las corridas), ``contribuciones``
    (una fila por factor de cada estimación del modelo final, con el aviso de
    que los puntos son de producción y no del IACA) y ``columnas`` (qué es cada
    columna de cada hoja).
    """
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    df = leer_registro(ruta)
    contrib = leer_contribuciones(ruta_contribuciones or ruta_contribuciones_de(ruta))
    contrib = contrib.merge(df[["estimacion_id", "serie_id", "mes_estimado"]], on="estimacion_id",
                            how="left")[list(DESCRIPCIONES_CONTRIBUCIONES)]
    columnas = pd.concat([
        pd.DataFrame({"hoja": "registro y ultima_por_mes", "columna": list(DESCRIPCIONES),
                      "qué es": list(DESCRIPCIONES.values())}),
        pd.DataFrame({"hoja": "contribuciones", "columna": list(DESCRIPCIONES_CONTRIBUCIONES),
                      "qué es": list(DESCRIPCIONES_CONTRIBUCIONES.values())}),
    ], ignore_index=True)
    ruta_excel = Path(ruta_excel)
    ruta_excel.parent.mkdir(parents=True, exist_ok=True)
    formatos = {"pronostico": "#,##0", "valor_real": "#,##0", "error_produccion": "#,##0",
                "indice_pronosticado": "0.00", "variacion_pronosticada_pct": "0.00",
                "variacion_con_real_pct": "0.00", "error_variacion_pp": "0.00"}
    with pd.ExcelWriter(ruta_excel, engine="openpyxl") as w:
        ultimas_estimaciones(df).to_excel(w, sheet_name="ultima_por_mes", index=False)
        df.to_excel(w, sheet_name="registro", index=False)
        # Contribuciones: el aviso arriba de la tabla, que arranca en la fila 3.
        contrib.to_excel(w, sheet_name="contribuciones", index=False, startrow=FILA_TABLA_CONTRIBUCIONES)
        hoja = w.sheets["contribuciones"]
        hoja["A1"] = "Atención: " + AVISO_PUNTOS
        hoja["A1"].font = Font(bold=True)
        hoja.freeze_panes = f"A{FILA_TABLA_CONTRIBUCIONES + 2}"
        anchos = {"estimacion_id": 14, "serie_id": 30, "mes_estimado": 13, "factor": 40, "aporte": 14,
                  "aporte_variacion_produccion_pp": 30, "nota": 60}
        for j, col in enumerate(contrib.columns, 1):
            letra = get_column_letter(j)
            hoja.column_dimensions[letra].width = anchos[col]
            formato = {"aporte": "#,##0", "aporte_variacion_produccion_pp": "0.00"}.get(col)
            if formato:
                for celda in hoja[letra][FILA_TABLA_CONTRIBUCIONES + 1:]:
                    celda.number_format = formato
        columnas.to_excel(w, sheet_name="columnas", index=False)
        for nombre in ("ultima_por_mes", "registro"):
            hoja = w.sheets[nombre]
            hoja.freeze_panes = "B2"
            for j, col in enumerate(df.columns, 1):
                letra = get_column_letter(j)
                hoja.column_dimensions[letra].width = max(12, min(30, len(col) + 2))
                if col in formatos:
                    for celda in hoja[letra][1:]:
                        celda.number_format = formatos[col]
        w.sheets["columnas"].column_dimensions["A"].width = 26
        w.sheets["columnas"].column_dimensions["B"].width = 30
        w.sheets["columnas"].column_dimensions["C"].width = 110
    return ruta_excel


# ------------------------------------------------------------ línea de comandos

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="accion", required=True)

    r = sub.add_parser("registrar", help="agregar la estimación de un mes")
    r.add_argument("--serie", required=True, choices=sorted(SERIES))
    r.add_argument("--mes", required=True, help="mes estimado, por ejemplo 2026-10")
    r.add_argument("--modelo", required=True)
    r.add_argument("--pronostico", required=True, type=float)
    r.add_argument("--configuracion", default="{}", help="JSON con los parámetros del modelo")
    r.add_argument("--sin-x13", action="store_true", help="no agregar la fila de la réplica del X-13 BCR")

    sub.add_parser("completar", help="completar el real y los errores de los meses ya publicados")
    sub.add_parser("exportar", help=f"exportar el registro a {RUTA_EXCEL.relative_to(RAIZ)}")

    a = p.parse_args(argv)
    if a.accion == "registrar":
        nuevas = registrar(a.serie, a.mes, a.modelo, a.pronostico, json.loads(a.configuracion),
                           incluir_x13=not a.sin_x13)
        print(nuevas[["estimacion_id", "serie_id", "mes_estimado", "modelo", "pronostico",
                      "variacion_pronosticada_pct"]].to_string(index=False))
    elif a.accion == "completar":
        hechas = completar()
        print(f"Filas completadas: {len(hechas)}")
        if len(hechas):
            print(hechas[["estimacion_id", "serie_id", "mes_estimado", "modelo", "error_produccion",
                          "error_variacion_pp", "acierto_signo"]].to_string(index=False))
    else:
        print(f"Registro exportado a {exportar_excel()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
