
"""SCRUM-42: error de la variación IACA para X-13 BCR y cualquier modelo del protocolo.

Calcula la variación mensual del IACA usando los componentes de X-13.
Las corridas se hacen con datos anteriores al mes pronosticado.

Si un pronóstico recalculado difiere del protocolo, se registra la
diferencia. Para X-13 BCR se usa el pronóstico de la corrida actual.

Uso:
    python scripts/error_iaca.py --mes 2026-08
    python scripts/error_iaca.py --max-meses 1
    python scripts/error_iaca.py
    python scripts/error_iaca.py --modelo-final NOMBRE_MODELO
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from math import isclose, log
from pathlib import Path

import numpy as np
import pandas as pd

from replica_x13 import (
    INICIO_BCR,
    SPC_BCR,
    SPC_DIR,
    _correr,
    _leer_tabla,
    cargar_series,
    spec_desde_spc,
)


RAIZ = Path(__file__).resolve().parents[1]
PREDICCIONES = RAIZ / "results" / "protocolo_predicciones.csv"
CACHE = RAIZ / "data" / "cache_x13.db"

SERIES = ("biodiesel", "bioetanol_total")
VERSION_CALCULO = "iaca-componentes-v1"


# ---------------------------------------------------------
# Funciones para calcular el índice
# ---------------------------------------------------------

def base_2013(serie: pd.Series) -> float:
    """Calcula el factor para que el promedio de 2013 sea 100."""

    valores = serie.loc["2013-01":"2013-12"]

    if (
        len(valores) != 12
        or valores.isna().any()
        or valores.mean() <= 0
    ):
        raise ValueError(
            "No hay 12 meses válidos para calcular la base 2013."
        )

    return 100.0 / float(valores.mean())


def signo(valor: float) -> int:
    """Devuelve 1, -1 o 0 según la dirección de la variación."""

    return int(valor > 0) - int(valor < 0)


def calcular_variacion(
    produccion: float,
    contexto: dict,
    factor: float,
    variante: str,
) -> tuple[float, float]:
    """Calcula el índice estimado y su variación logarítmica mensual."""

    if variante == "log":
        desestacionalizado = (
            produccion / contexto["estacional"]
        )

    elif variante == "nivel":
        desestacionalizado = (
            produccion - contexto["estacional"]
        )

    else:
        raise ValueError(
            f"Transformación no reconocida: {variante}"
        )

    # Últimos dos valores filtrados conocidos.
    anterior = (
        factor * contexto["filtrado_ultimo"]
    )

    penultimo = (
        factor * contexto["filtrado_penultimo"]
    )

    # Media móvil de cierre del último mes observado.
    indice_anterior = (
        penultimo + 2 * anterior
    ) / 3

    # Fórmula del mes estimado utilizada por BCR.
    indice_estimado = (
        anterior + 2 * factor * desestacionalizado
    ) / 3

    if indice_anterior <= 0 or indice_estimado <= 0:
        raise ValueError(
            "Los índices deben ser positivos."
        )

    # Variación logarítmica en porcentaje.
    variacion = (
        100 * log(indice_estimado / indice_anterior)
    )

    return indice_estimado, variacion


# ---------------------------------------------------------
# Caché de componentes X-13
# ---------------------------------------------------------

def _abrir_cache() -> sqlite3.Connection:
    """Abre la caché sin modificar las tablas del protocolo."""

    CACHE.parent.mkdir(
        parents=True, exist_ok=True
    )

    con = sqlite3.connect(CACHE)

    con.execute(
        "CREATE TABLE IF NOT EXISTS iaca_componentes ("
        "serie TEXT, "
        "variante TEXT, "
        "datos_hasta TEXT, "
        "hash_datos TEXT, "
        "hash_config TEXT, "
        "resultado TEXT NOT NULL, "
        "PRIMARY KEY ("
        "serie, variante, datos_hasta, "
        "hash_datos, hash_config"
        "))"
    )

    return con


def _clave(
    nombre: str,
    variante: str,
    entrenamiento: pd.Series,
) -> tuple:
    """Identifica cada corrida por sus datos y configuración."""

    spc = SPC_BCR[nombre][
        0 if variante == "log" else 1
    ]

    datos = hashlib.sha256(
        str(entrenamiento.index[0]).encode()
    )

    datos.update(
        np.round(
            entrenamiento.to_numpy(dtype=float),
            6,
        ).tobytes()
    )

    config = hashlib.sha256(
        VERSION_CALCULO.encode()
    )

    config.update(
        (SPC_DIR / f"{spc}.spc").read_bytes()
    )

    return (
        nombre,
        variante,
        str(entrenamiento.index[-1]),
        datos.hexdigest()[:16],
        config.hexdigest()[:16],
    )


def obtener_contexto(
    con: sqlite3.Connection,
    nombre: str,
    variante: str,
    entrenamiento: pd.Series,
) -> tuple[dict, bool]:
    """Obtiene los componentes de X-13 desde la caché o los calcula."""

    clave = _clave(
        nombre, variante, entrenamiento
    )

    fila = con.execute(
        "SELECT resultado "
        "FROM iaca_componentes "
        "WHERE serie=? "
        "AND variante=? "
        "AND datos_hasta=? "
        "AND hash_datos=? "
        "AND hash_config=?",
        clave,
    ).fetchone()

    if fila:
        return json.loads(fila[0]), True

    # Si no está en caché, ejecuto X-13.
    spc = SPC_BCR[nombre][
        0 if variante == "log" else 1
    ]

    salida = _correr(
        spec_desde_spc(
            spc, entrenamiento
        )
    )

    tablas = {
        k: _leer_tabla(salida.get(k))
        for k in (
            "fct", "c17", "d11", "d12", "d16"
        )
    }

    if any(
        tabla.empty
        for tabla in tablas.values()
    ):
        raise RuntimeError(
            f"X-13 no devolvió todos los componentes: "
            f"{nombre}, {variante}."
        )

    ultimo = entrenamiento.index[-1]
    penultimo = ultimo - 1
    proximo = ultimo + 1

    def filtrado(mes: pd.Period) -> float:
        """Combina desestacionalizada y tendencia."""

        peso = float(
            tablas["c17"].loc[mes]
        )

        desest = float(
            tablas["d11"].loc[mes]
        )

        tendencia = float(
            tablas["d12"].loc[mes]
        )

        return (
            peso * desest
            + (1 - peso) * tendencia
        )

    resultado = {
        "pronostico_x13": float(
            tablas["fct"].loc[proximo]
        ),
        "estacional": float(
            tablas["d16"].loc[proximo]
        ),
        "filtrado_penultimo": filtrado(
            penultimo
        ),
        "filtrado_ultimo": filtrado(
            ultimo
        ),
    }

    # Guardo la corrida para reutilizarla.
    con.execute(
        "INSERT OR REPLACE INTO "
        "iaca_componentes "
        "VALUES (?,?,?,?,?,?)",
        (
            *clave,
            json.dumps(resultado),
        ),
    )

    con.commit()

    return resultado, False


# ---------------------------------------------------------
# Predicciones existentes del protocolo
# ---------------------------------------------------------

def _predicciones_mes(
    tabla: pd.DataFrame,
    nombre: str,
    ventana: str,
    mes: pd.Period,
) -> dict:
    """Obtiene las predicciones de una serie y un mes."""

    filas = tabla.loc[
        (tabla["serie"] == nombre)
        & (tabla["ventana"] == ventana)
        & (tabla["mes"] == mes)
        & (tabla["estado"] == "ok")
    ]

    return {
        fila.modelo: fila
        for fila in filas.itertuples(
            index=False
        )
    }


def _variante_bcr(filas: dict) -> str:
    """Identifica la variante seleccionada en el protocolo."""

    if "x13_bcr" not in filas:
        raise ValueError(
            "Falta la predicción de x13_bcr."
        )

    elegido = float(
        filas["x13_bcr"].prediccion
    )

    variantes = []

    for variante in ("log", "nivel"):
        nombre = f"x13_bcr_{variante}"

        if nombre in filas and isclose(
            elegido,
            float(filas[nombre].prediccion),
            rel_tol=1e-8,
            abs_tol=1e-5,
        ):
            variantes.append(variante)

    if len(variantes) != 1:
        raise ValueError(
            "No se pudo identificar una única "
            "variante de X-13 BCR."
        )

    return variantes[0]


# ---------------------------------------------------------
# Evaluación mensual del IACA
# ---------------------------------------------------------

def evaluar(args: argparse.Namespace) -> None:

    if not PREDICCIONES.exists():
        raise FileNotFoundError(
            f"Falta el archivo: {PREDICCIONES}"
        )

    tabla = pd.read_csv(
        PREDICCIONES,
        parse_dates=["fecha"],
    )

    # Predicciones de modelos que no corre el protocolo largo (por ejemplo,
    # el modelo final de SCRUM-34). Mismo formato de columnas.
    if args.predicciones_extra:
        extra = pd.read_csv(
            args.predicciones_extra,
            parse_dates=["fecha"],
        )
        repetidos = set(extra["modelo"]) & set(tabla["modelo"])
        if repetidos:
            raise ValueError(
                f"Modelos repetidos con el protocolo: {sorted(repetidos)}"
            )
        tabla = pd.concat([tabla, extra], ignore_index=True)

    tabla["mes"] = (
        tabla["fecha"].dt.to_period("M")
    )

    # Selecciono los meses a evaluar.
    if args.mes:

        mes_objetivo = pd.Period(
            args.mes, freq="M"
        )

        ventanas = tabla.loc[
            (tabla["modelo"] == "x13_bcr")
            & (tabla["mes"] == mes_objetivo),
            "ventana",
        ].unique()

        if len(ventanas) != 1:
            raise ValueError(
                f"No existe un único período "
                f"para {args.mes}."
            )

        ventana = str(ventanas[0])
        meses = [mes_objetivo]

    else:

        ventana = args.ventana

        meses = sorted(
            tabla.loc[
                (tabla["ventana"] == ventana)
                & (tabla["modelo"] == "x13_bcr"),
                "mes",
            ].unique()
        )

        if args.max_meses:
            meses = meses[:args.max_meses]

    if not meses:
        raise ValueError(
            "No hay predicciones para el período solicitado."
        )

    todas_las_series = cargar_series()

    registros = []
    discrepancias = []

    con = _abrir_cache()

    try:

        for mes in meses:

            for nombre in SERIES:

                filas = _predicciones_mes(
                    tabla,
                    nombre,
                    ventana,
                    mes,
                )

                if "x13_bcr" not in filas:
                    raise ValueError(
                        f"Falta X-13 BCR para "
                        f"{nombre}, {mes}."
                    )

                # Variante que eligió el protocolo.
                variante = _variante_bcr(
                    filas
                )

                serie = todas_las_series[
                    nombre
                ]

                inicio = pd.Period(
                    INICIO_BCR[nombre],
                    freq="M",
                )

                # Evito incorporar datos del mes pronosticado.
                entrenamiento = serie.loc[
                    (serie.index >= inicio)
                    & (serie.index < mes)
                ]

                if (
                    entrenamiento.empty
                    or entrenamiento.index[-1] != mes - 1
                ):
                    raise ValueError(
                        f"Entrenamiento incompleto: "
                        f"{nombre}, {mes}."
                    )

                contexto, desde_cache = obtener_contexto(
                    con,
                    nombre,
                    variante,
                    entrenamiento,
                )

                # -----------------------------------------
                # Comparación con el protocolo original
                # -----------------------------------------

                pred_x13_csv = float(
                    filas["x13_bcr"].prediccion
                )

                pred_x13_corrida = float(
                    contexto["pronostico_x13"]
                )

                diferencia_x13 = (
                    pred_x13_corrida - pred_x13_csv
                )

                coincide_x13 = isclose(
                    pred_x13_corrida,
                    pred_x13_csv,
                    rel_tol=1e-5,
                    abs_tol=0.1,
                )

                if not coincide_x13:

                    print(
                        f"ADVERTENCIA: {nombre}, {mes}: "
                        f"protocolo={pred_x13_csv:.2f}, "
                        f"recalculado={pred_x13_corrida:.2f}, "
                        f"diferencia={diferencia_x13:.2f}",
                        flush=True,
                    )

                    discrepancias.append({
                        "serie": nombre,
                        "fecha": str(mes),
                        "ventana": ventana,
                        "variante": variante,
                        "pronostico_protocolo": pred_x13_csv,
                        "pronostico_recalculado": pred_x13_corrida,
                        "diferencia": diferencia_x13,
                    })

                # -----------------------------------------
                # Variación utilizando la producción real
                # -----------------------------------------

                factor = base_2013(
                    serie
                )

                real = float(
                    serie.loc[mes]
                )

                _, variacion_real = calcular_variacion(
                    real,
                    contexto,
                    factor,
                    variante,
                )

                # -----------------------------------------
                # Modelos a evaluar
                # -----------------------------------------

                modelos = ["x13_bcr"]

                if (
                    args.modelo_final
                    and args.modelo_final != "x13_bcr"
                ):
                    modelos.append(
                        args.modelo_final
                    )

                for modelo in modelos:

                    if modelo not in filas:
                        raise ValueError(
                            f"No existe la predicción "
                            f"de '{modelo}' para "
                            f"{nombre}, {mes}."
                        )

                    # Uso el pronóstico de la misma
                    # corrida que generó los componentes.
                    if modelo == "x13_bcr":
                        pred = pred_x13_corrida

                    else:
                        pred = float(
                            filas[modelo].prediccion
                        )

                    # Calculo el índice pronosticado.
                    indice, variacion = calcular_variacion(
                        pred,
                        contexto,
                        factor,
                        variante,
                    )

                    # Error en puntos porcentuales.
                    error_pp = (
                        variacion - variacion_real
                    )

                    error_absoluto_pp = abs(
                        error_pp
                    )

                    acierto_signo = int(
                        signo(variacion)
                        == signo(variacion_real)
                    )

                    registros.append({
                        "serie": nombre,
                        "modelo": modelo,
                        "ventana": ventana,
                        "fecha": str(mes),
                        "variante_x13": variante,
                        "produccion_pronosticada": pred,
                        "produccion_real": real,
                        "indice_pronosticado": indice,
                        "variacion_pronosticada_pct": variacion,
                        "variacion_con_real_pct": variacion_real,
                        "error_pp": error_pp,
                        "error_absoluto_pp": error_absoluto_pp,
                        "acierto_signo": acierto_signo,
                        "pronostico_x13_protocolo": pred_x13_csv,
                        "pronostico_x13_recalculado": pred_x13_corrida,
                        "diferencia_x13": diferencia_x13,
                        "coincide_x13_protocolo": coincide_x13,
                    })

                origen = (
                    "caché"
                    if desde_cache
                    else "X-13 nuevo"
                )

                print(
                    f"{mes} | {nombre} | "
                    f"{variante} | {origen}",
                    flush=True,
                )

    finally:
        con.close()

    # ---------------------------------------------------------
    # Métricas generales
    # ---------------------------------------------------------

    detalle = pd.DataFrame(
        registros
    )

    resumen = (
        detalle.groupby(
            ["serie", "modelo", "ventana"],
            as_index=False,
        )
        .agg(
            meses=("fecha", "count"),
            error_medio_absoluto_pp=(
                "error_absoluto_pp",
                "mean",
            ),
            error_medio_pp=(
                "error_pp",
                "mean",
            ),
            aciertos=(
                "acierto_signo",
                "sum",
            ),
        )
    )

    resumen["acierto_signo_pct"] = (
        100
        * resumen["aciertos"]
        / resumen["meses"]
    )

    # ---------------------------------------------------------
    # Guardar resultados
    # ---------------------------------------------------------

    carpeta = RAIZ / "results"

    carpeta.mkdir(
        exist_ok=True
    )

    if args.mes:
        sufijo = args.mes

    elif args.max_meses:
        sufijo = f"{ventana}_parcial"

    else:
        sufijo = ventana

    ruta_detalle = (
        carpeta / f"iaca_{sufijo}_detalle.csv"
    )

    ruta_resumen = (
        carpeta / f"iaca_{sufijo}_metricas.csv"
    )

    ruta_discrepancias = (
        carpeta / f"iaca_{sufijo}_discrepancias.csv"
    )

    detalle.to_csv(
        ruta_detalle,
        index=False,
    )

    resumen.to_csv(
        ruta_resumen,
        index=False,
    )

    # Guardo todas las diferencias encontradas.
    columnas_discrepancias = [
        "serie",
        "fecha",
        "ventana",
        "variante",
        "pronostico_protocolo",
        "pronostico_recalculado",
        "diferencia",
    ]

    pd.DataFrame(
        discrepancias,
        columns=columnas_discrepancias,
    ).to_csv(
        ruta_discrepancias,
        index=False,
    )

    print("\nMétricas del IACA:")

    print(
        resumen.to_string(
            index=False,
            float_format=lambda n: f"{n:.4f}",
        )
    )

    print(
        f"\nDiscrepancias encontradas: "
        f"{len(discrepancias)}"
    )

    if discrepancias:
        print(
            "ATENCIÓN: las métricas son provisionales "
            "hasta revisar estas diferencias."
        )

    print(
        f"\nArchivos guardados:\n"
        f"- {ruta_detalle.name}\n"
        f"- {ruta_resumen.name}\n"
        f"- {ruta_discrepancias.name}"
    )


# ---------------------------------------------------------
# Ejecución principal
# ---------------------------------------------------------

def main() -> None:

    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0]
    )

    parser.add_argument(
        "--mes",
        help="Evaluar un mes, por ejemplo 2026-08.",
    )

    parser.add_argument(
        "--ventana",
        choices=("backtest", "holdout"),
        default="backtest",
    )

    parser.add_argument(
        "--max-meses",
        type=int,
        default=0,
        help="Limitar los meses de la evaluación.",
    )

    parser.add_argument(
        "--modelo-final",
        help="Modelo existente en protocolo_predicciones.csv o en --predicciones-extra.",
    )

    parser.add_argument(
        "--predicciones-extra",
        help="CSV con predicciones de otros modelos, mismo formato "
             "(por ejemplo results/modelo_final_predicciones.csv).",
    )

    args = parser.parse_args()

    if args.max_meses < 0:
        parser.error(
            "--max-meses debe ser positivo."
        )

    evaluar(args)


if __name__ == "__main__":
    main()
