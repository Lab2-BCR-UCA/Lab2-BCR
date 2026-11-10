
"""Verifica el cálculo del IACA usando componentes reales de X-13."""

from math import isclose, log
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

from replica_x13 import (
    cargar_series,
    spec_desde_spc,
    _correr,
    _leer_tabla,
)


RAIZ = Path(__file__).resolve().parents[1]
CORTE = "2026-07"
JUNIO = pd.Period("2026-06", freq="M")
JULIO = pd.Period("2026-07", freq="M")
AGOSTO = pd.Period("2026-08", freq="M")


def signo(valor):
    if valor > 0:
        return 1
    if valor < 0:
        return -1
    return 0


def verificar(hoja, nombre, spc, factor_celda, indice_celdas, logaritmico):
    # Entreno X-13 solamente con datos hasta julio.
    serie_completa = cargar_series()[nombre]
    serie = serie_completa.loc[:CORTE]

    salida = _correr(spec_desde_spc(spc, serie))

    componentes = {
        clave: _leer_tabla(salida.get(clave))
        for clave in ("fct", "c17", "d11", "d12", "d16")
    }

    if any(s.empty for s in componentes.values()):
        raise RuntimeError(f"Faltan componentes de X-13: {nombre}")

    factor = float(hoja[factor_celda].value)

    def filtrado(mes):
        peso = componentes["c17"].loc[mes]
        desest = componentes["d11"].loc[mes]
        tendencia = componentes["d12"].loc[mes]

        return factor * (peso * desest + (1 - peso) * tendencia)

    # Serie filtrada de los dos últimos meses conocidos.
    filtrado_junio = filtrado(JUNIO)
    filtrado_julio = filtrado(JULIO)

    # Media móvil de cierre para julio.
    indice_julio = (filtrado_junio + 2 * filtrado_julio) / 3

    # Pronóstico y estacionalidad generados por X-13.
    pronostico = float(componentes["fct"].loc[AGOSTO])
    estacionalidad = float(componentes["d16"].loc[AGOSTO])

    if logaritmico:
        filtrado_agosto = factor * pronostico / estacionalidad
    else:
        filtrado_agosto = factor * (pronostico - estacionalidad)

    # Índice y variación calculados con el pronóstico.
    indice_agosto = (2 * filtrado_agosto + filtrado_julio) / 3
    variacion = 100 * log(indice_agosto / indice_julio)

    # Valores de referencia del Excel de BCR.
    esperado_julio = float(hoja[indice_celdas[0]].value)
    esperado_agosto = float(hoja[indice_celdas[1]].value)
    esperado_variacion = 100 * float(hoja[indice_celdas[2]].value)

    print(f"\n{'=' * 55}")
    print(f"SERIE: {nombre.upper()}")
    print(f"{'=' * 55}")

    print("\n1. VALIDACIÓN CONTRA EL EXCEL DE BCR")
    print(f"Pronóstico X-13: {pronostico:.2f}")
    print(f"Índice julio: {indice_julio:.6f} (Excel: {esperado_julio:.6f})")
    print(f"Índice agosto: {indice_agosto:.6f} (Excel: {esperado_agosto:.6f})")
    print(
        f"Variación pronosticada: {variacion:.6f}% "
        f"(Excel: {esperado_variacion:.6f}%)"
    )

    assert isclose(indice_julio, esperado_julio, abs_tol=0.001)
    assert isclose(indice_agosto, esperado_agosto, abs_tol=0.001)
    assert isclose(variacion, esperado_variacion, abs_tol=0.001)

    print("Validación X-13 → IACA: OK")

    # ---------------------------------------------------------
    # 2. Cálculo de la variación utilizando la producción real
    # ---------------------------------------------------------

    # El dato real de agosto se usa solo para evaluar el pronóstico.
    real = float(serie_completa.loc[AGOSTO])

    # Mantengo la estacionalidad estimada con datos hasta julio.
    if logaritmico:
        filtrado_real = factor * real / estacionalidad
    else:
        filtrado_real = factor * (real - estacionalidad)

    # Recalculo el índice reemplazando el pronóstico por el valor real.
    indice_agosto_real = (2 * filtrado_real + filtrado_julio) / 3

    # Variación logarítmica con producción real.
    variacion_real = 100 * log(indice_agosto_real / indice_julio)

    # ---------------------------------------------------------
    # 3. Métricas de evaluación
    # ---------------------------------------------------------

    # Error de la variación expresado en puntos porcentuales.
    error_pp = variacion - variacion_real
    error_absoluto_pp = abs(error_pp)

    # Acierto de la dirección de la variación.
    acierto_signo = int(signo(variacion) == signo(variacion_real))

    print("\n2. COMPARACIÓN CON LA PRODUCCIÓN REAL")
    print(f"Producción pronosticada: {pronostico:.2f}")
    print(f"Producción real: {real:.2f}")
    print(f"Índice agosto con dato real: {indice_agosto_real:.6f}")
    print(f"Variación pronosticada: {variacion:.6f}%")
    print(f"Variación con dato real: {variacion_real:.6f}%")

    print("\n3. MÉTRICAS DEL SCRUM-42")
    print(f"Error con signo: {error_pp:.6f} pp")
    print(f"Error absoluto: {error_absoluto_pp:.6f} pp")
    print(f"Acierto del signo: {acierto_signo}")

    if acierto_signo == 1:
        print("El modelo acertó la dirección de la variación.")
    else:
        print("El modelo no acertó la dirección de la variación.")

    return {
        "serie": nombre,
        "fecha": str(AGOSTO),
        "produccion_pronosticada": pronostico,
        "produccion_real": real,
        "variacion_pronosticada_pct": variacion,
        "variacion_real_pct": variacion_real,
        "error_pp": error_pp,
        "error_absoluto_pp": error_absoluto_pp,
        "acierto_signo": acierto_signo,
    }


def main():
    excel = RAIZ / "data" / "modelo_bcr_biocombustibles.xlsx"
    libro = load_workbook(excel, read_only=True, data_only=True)

    resultados = []

    try:
        hoja = libro["BIOCOMBUSTIBLES"]

        resultados.append(
            verificar(
                hoja,
                "biodiesel",
                "IACA-BIODIESEL_L",
                "C2",
                ("K226", "K227", "L227"),
                True,
            )
        )

        resultados.append(
            verificar(
                hoja,
                "bioetanol_total",
                "IACA-BIOETANOL_N",
                "P2",
                ("X226", "X227", "Y227"),
                False,
            )
        )

    finally:
        libro.close()

    # Guardo los resultados para poder consultarlos.
    carpeta_resultados = RAIZ / "results"
    carpeta_resultados.mkdir(exist_ok=True)

    archivo = carpeta_resultados / "validacion_iaca_agosto_2026.csv"
    pd.DataFrame(resultados).to_csv(archivo, index=False)

    print(f"\nResultados guardados en: {archivo}")


if __name__ == "__main__":
    main()
