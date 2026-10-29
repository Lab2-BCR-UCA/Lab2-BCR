"""Ablación de exógenas del SARIMAX (SCRUM-62).

Decide con datos, no por intuición, qué variables que dejaron SCRUM-48 (corte),
SCRUM-57 (INDEC) y SCRUM-58 (azúcar) conviene sumar al SARIMAX de cada serie.
Compara, en el backtest del protocolo (SCRUM-43), el modelo BASE de SCRUM-29
contra el mismo + cada candidata, con la métrica principal (MAE) y el intervalo
de la diferencia por bootstrap de bloques + Diebold-Mariano (``evaluacion``).

Lectura: ``dif MAE = MAE(con candidata) − MAE(base)``. Negativo = la candidata
baja el error. Si el IC95 cruza 0, no se distingue de no tenerla (no justifica
sumarla, por el principio de parsimonia del proyecto).

Ventana de entrenamiento igualada
---------------------------------
Las contables del biodiésel arrancan cuando arranca INDEC (2012), no en 2008
como la serie. Comparar "base desde 2008" contra "contables desde 2012" mezcla
dos efectos: el de las variables y el de acortar la ventana. Por eso cada
variante que recorta el inicio se compara contra una base **con el mismo
inicio** (``inicio`` en ``VARIANTES``). Sin esto, el biodiésel parecía mejorar
−385 cuando en realidad era el efecto de la ventana (review de SCRUM-62).

Se reporta también el **error máximo** de cada configuración, para verificar el
"sin blow-ups" del DoD: con las contables en toneladas el mes 2022-02 se iba a
~355 mil tn contra 177 mil reales, porque el salto de exportaciones entra
multiplicando en un modelo en log. Ahora las contables van en ``log1p``
(SCRUM-59, ``contables_en_log``).

Variantes por serie:
    biodiésel:        + contables (demanda_interna_est, expo_est de INDEC con
                        imputación, otras_ventas_t1, oculto)  [grupo "contables"]
                      + contables + corte_biodiesel_nominal_pct (régimen, rz0)
                      (ambas con la base recortada al inicio de las contables)
    bioetanol maíz:   + corte_efectivo_bioetanol_maiz (rz1)
    bioetanol caña:   + azucar_usd_kg (rz0)
                      + corte_efectivo_bioetanol_cana (rz1)
                      + azúcar + corte efectivo
    bioetanol total:  + corte_efectivo_bioetanol (rz1)

Las candidatas se pasan por ``exogenas_extra`` del ModeloSARIMAX (SCRUM-59), sin
editar ``EXOGENAS``.

Límites de esta ablación (leer antes de concluir)
-------------------------------------------------
1. **El corte efectivo es casi circular.** Sale de ventas al corte / ventas del
   combustible, y las ventas al corte siguen a la producción del mismo mes (ver
   ``docs/corte.md``). Entra con rezago 1, así que no hay leakage, pero su efecto
   —a favor o en contra— puede ser en parte tautológico y no un mecanismo
   económico. Su CCF de +0,86 con la caña es el síntoma, no evidencia.
2. **Son varias comparaciones sin corrección por comparaciones múltiples.** Con
   7 tests al 95% se espera ~0,35 rechazos falsos, así que un p apenas por
   debajo de 0,05 se lee como "no hay evidencia de que ayude" y no como "está
   probado que empeora".
3. **Cada candidata se prueba sola contra una base fija**: no hay selección
   conjunta ni hacia adelante, así que no se detectan combinaciones que solo
   funcionen juntas (más allá de la variante azúcar + corte de la caña).
4. **Las diferencias están dentro del ruido** y son sensibles a detalles de
   implementación (imputación del primer mes oculto, transformación de las
   contables, ventana de entrenamiento).

Uso, desde la raíz del repo:
    python scripts/experimento_exogenas.py

Salida: results/experimento_exogenas.csv. Requiere statsmodels, scipy, pandas.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))

from construir_features import construir_features  # noqa: E402
from sarimax import ModeloSARIMAX, _serie_base, INICIO_ENTRENAMIENTO, OBJETIVOS  # noqa: E402
from evaluacion import comparar_modelos, evaluar_ventanas, ventanas_protocolo  # noqa: E402

# Variantes por serie: (etiqueta, incluir, exogenas_extra, recortar_a_contables).
# Si la última es True, la variante y su base arrancan en el primer mes con
# contables completas (INDEC), para no confundir el efecto con el de la ventana.
VARIANTES: dict[str, list[tuple[str, tuple, list, bool]]] = {
    "biodiesel": [
        ("+contables", ("exogenas", "contables"), [], True),
        ("+contables+corte_nominal", ("exogenas", "contables"),
         [("corte_biodiesel_nominal_pct", 0)], True),
    ],
    "bioetanol_maiz": [
        ("+corte_efectivo", ("exogenas",), [("corte_efectivo_bioetanol_maiz", 1)], False),
    ],
    "bioetanol_cana": [
        ("+azucar", ("exogenas",), [("azucar_usd_kg", 0)], False),
        ("+corte_efectivo", ("exogenas",), [("corte_efectivo_bioetanol_cana", 1)], False),
        ("+azucar+corte_efectivo", ("exogenas",),
         [("azucar_usd_kg", 0), ("corte_efectivo_bioetanol_cana", 1)], False),
    ],
    "bioetanol_total": [
        ("+corte_efectivo", ("exogenas",), [("corte_efectivo_bioetanol", 1)], False),
    ],
}


def _inicio_contables(nombre: str, ultimo: pd.Period) -> str:
    """Primer mes con contables completas (lo expone construir_features)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        # Solo se consulta metadata, así que no se exige que la fila del mes a
        # estimar esté completa (puede faltar un insumo del último mes).
        X, _ = construir_features(nombre, ultimo, incluir=("exogenas", "contables"),
                                  exigir_fila_completa=False)
    desde = X.attrs.get("contables_desde")
    return desde or INICIO_ENTRENAMIENTO[nombre]


def _evaluar(nombre: str, incluir: tuple, extra: list, ventanas: dict,
             inicio: str) -> pd.DataFrame:
    """Backtest de una configuración (exógenas de la serie + ``extra``)."""
    detalle, _ = evaluar_ventanas(
        serie=_serie_base(nombre),
        crear_modelo=lambda: ModeloSARIMAX(nombre, incluir=incluir,
                                           exogenas_extra=extra or None),
        inicio_entrenamiento=inicio,
        ventanas=ventanas,
        nombre_serie=nombre,
        nombre_modelo="x",
    )
    return detalle


def _metricas(detalle: pd.DataFrame) -> tuple[float, float, str]:
    """MAE, error absoluto máximo y el mes en que ocurre."""
    ok = detalle.loc[detalle["estado"] == "ok"].copy()
    ok["abs"] = ok["error"].abs()
    peor = ok.loc[ok["abs"].idxmax()]
    return ok["abs"].mean(), float(peor["abs"]), str(pd.Period(peor["fecha"], freq="M"))


def main() -> None:
    ultimo = min(_serie_base(n).index[-1] for n in OBJETIVOS)
    ventanas = {"backtest": ventanas_protocolo(ultimo)["backtest"]}

    filas = []
    print("Ablación de exógenas del SARIMAX (backtest, MAE = métrica principal)")
    print("La base se recorta a la misma ventana cuando la variante lo hace.\n")
    for nombre, variantes in VARIANTES.items():
        bases: dict[str, pd.DataFrame] = {}
        print(f"== {nombre} ==")
        for etiq, incluir, extra, recortar in variantes:
            inicio = (_inicio_contables(nombre, ultimo + 1) if recortar
                      else INICIO_ENTRENAMIENTO[nombre])
            if inicio not in bases:
                bases[inicio] = _evaluar(nombre, ("exogenas",), [], ventanas, inicio)
                b_mae, b_max, b_mes = _metricas(bases[inicio])
                print(f"  base (desde {inicio}): MAE={b_mae:,.0f}  "
                      f"error máx={b_max:,.0f} ({b_mes})")
            base_det = bases[inicio]
            b_mae, b_max, b_mes = _metricas(base_det)

            det = _evaluar(nombre, incluir, extra, ventanas, inicio)
            mae, err_max, mes_max = _metricas(det)
            c = comparar_modelos(det, base_det, perdida="ae")
            distinguible = bool(c["ic_inf"] > 0 or c["ic_sup"] < 0)
            mejora = c["diferencia_media"] < 0
            print(f"  {etiq:26s} MAE={mae:,.0f}  dif={c['diferencia_media']:+,.0f}  "
                  f"IC95 [{c['ic_inf']:,.0f}, {c['ic_sup']:,.0f}]  p={c['dm_p_valor']:.3f}  "
                  f"máx={err_max:,.0f} ({mes_max})  -> "
                  f"{'MEJORA' if mejora else 'empeora'}, "
                  f"{'distinguible' if distinguible else 'no distinguible'}")
            filas.append({
                "serie": nombre, "variante": etiq,
                "inicio_entrenamiento": inicio,
                "MAE_base": round(b_mae, 2), "MAE_variante": round(mae, 2),
                "dif_MAE": round(c["diferencia_media"], 2),
                "ic95_inf": round(c["ic_inf"], 2), "ic95_sup": round(c["ic_sup"], 2),
                "dm_p_valor": round(c["dm_p_valor"], 4),
                "error_max_base": round(b_max, 2), "mes_error_max_base": b_mes,
                "error_max_variante": round(err_max, 2), "mes_error_max_variante": mes_max,
                "mejora": mejora, "distinguible_95": distinguible,
            })
        print()

    out = RAIZ / "results" / "experimento_exogenas.csv"
    out.parent.mkdir(exist_ok=True)
    pd.DataFrame(filas).to_csv(out, index=False)
    print(f"Guardado en {out}")
    print("Criterio: se suma al modelo la candidata que baja el MAE y es "
          "distinguible de 0 (IC95 que no cruza 0), sin empeorar el error máximo.")


if __name__ == "__main__":
    main()
