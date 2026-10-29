"""Ablación de exógenas del SARIMAX (SCRUM-62).

Decide con datos, no por intuición, qué variables que dejaron SCRUM-48 (corte),
SCRUM-57 (INDEC) y SCRUM-58 (azúcar) conviene sumar al SARIMAX de cada serie.
Compara, en el backtest del protocolo (SCRUM-43), el modelo BASE de SCRUM-29
contra el mismo + cada candidata, con la métrica principal (MAE) y el intervalo
de la diferencia por bootstrap de bloques + Diebold-Mariano (``evaluacion``).

Lectura: ``dif MAE = MAE(con candidata) − MAE(base)``. Negativo = la candidata
baja el error. Si el IC95 cruza 0, no se distingue de no tenerla (no justifica
sumarla, por el principio de parsimonia del proyecto).

Variantes por serie:
    biodiésel:        + contables (demanda_interna_est, expo_est de INDEC con
                        imputación, otras_ventas_t1, oculto)  [grupo "contables"]
                      + contables + corte_biodiesel_nominal_pct (régimen, rz0)
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
   económico. Si alguna vez "gana", hay que mirar por qué antes de celebrarlo.
2. **Son 7 comparaciones sin corrección por comparaciones múltiples.** Con 7
   tests al 95% se espera ~0,35 rechazos falsos. El único resultado distinguible
   (total + corte efectivo, p=0,041) está al borde, así que conviene leerlo como
   "no hay evidencia de que ayude" y no como "está probado que empeora".
3. **Cada candidata se prueba sola contra una base fija**: no hay selección
   conjunta ni hacia adelante, así que no se detectan combinaciones que solo
   funcionen juntas (más allá de la variante azúcar + corte de la caña).
4. **Las diferencias están dentro del ruido** y son sensibles a detalles de
   implementación: los números del biodiésel cambiaron de +567 a −385 solo por
   tapar el NaN del primer mes oculto (corrección de SCRUM-59).

Uso, desde la raíz del repo:
    python scripts/experimento_exogenas.py

Salida: results/experimento_exogenas.csv. Requiere statsmodels, scipy, pandas.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))

from sarimax import ModeloSARIMAX, _serie_base, INICIO_ENTRENAMIENTO, OBJETIVOS  # noqa: E402
from evaluacion import comparar_modelos, evaluar_ventanas, ventanas_protocolo  # noqa: E402

# Variantes por serie: etiqueta -> (incluir, exogenas_extra). La base de cada
# serie es incluir=("exogenas",) sin extras (el conjunto de SCRUM-29). Las extras
# se pasan a construir_features vía ModeloSARIMAX, sin tocar EXOGENAS (SCRUM-59).
VARIANTES: dict[str, list[tuple[str, tuple, list]]] = {
    "biodiesel": [
        ("+contables", ("exogenas", "contables"), []),
        ("+contables+corte_nominal", ("exogenas", "contables"),
         [("corte_biodiesel_nominal_pct", 0)]),
    ],
    "bioetanol_maiz": [
        ("+corte_efectivo", ("exogenas",), [("corte_efectivo_bioetanol_maiz", 1)]),
    ],
    "bioetanol_cana": [
        ("+azucar", ("exogenas",), [("azucar_usd_kg", 0)]),
        ("+corte_efectivo", ("exogenas",), [("corte_efectivo_bioetanol_cana", 1)]),
        ("+azucar+corte_efectivo", ("exogenas",),
         [("azucar_usd_kg", 0), ("corte_efectivo_bioetanol_cana", 1)]),
    ],
    "bioetanol_total": [
        ("+corte_efectivo", ("exogenas",), [("corte_efectivo_bioetanol", 1)]),
    ],
}


def _evaluar(nombre: str, incluir: tuple, extra: list, ventanas: dict) -> pd.DataFrame:
    """Backtest de una configuración (exógenas de la serie + ``extra``)."""
    detalle, _ = evaluar_ventanas(
        serie=_serie_base(nombre),
        crear_modelo=lambda: ModeloSARIMAX(nombre, incluir=incluir,
                                           exogenas_extra=extra or None),
        inicio_entrenamiento=INICIO_ENTRENAMIENTO[nombre],
        ventanas=ventanas,
        nombre_serie=nombre,
        nombre_modelo="x",
    )
    return detalle


def main() -> None:
    ultimo = min(_serie_base(n).index[-1] for n in OBJETIVOS)
    ventanas = {"backtest": ventanas_protocolo(ultimo)["backtest"]}

    filas = []
    print("Ablación de exógenas del SARIMAX (backtest, MAE = métrica principal)\n")
    for nombre, variantes in VARIANTES.items():
        base_det = _evaluar(nombre, ("exogenas",), [], ventanas)
        base_mae = base_det.loc[base_det["estado"] == "ok", "error"].abs().mean()
        print(f"== {nombre} ==")
        print(f"  base (SCRUM-29): MAE={base_mae:,.0f}")
        for etiq, incluir, extra in variantes:
            det = _evaluar(nombre, incluir, extra, ventanas)
            mae = det.loc[det["estado"] == "ok", "error"].abs().mean()
            c = comparar_modelos(det, base_det, perdida="ae")
            distinguible = bool(c["ic_inf"] > 0 or c["ic_sup"] < 0)
            mejora = c["diferencia_media"] < 0
            print(f"  {etiq:28s} MAE={mae:,.0f}  dif={c['diferencia_media']:+,.0f}  "
                  f"IC95 [{c['ic_inf']:,.0f}, {c['ic_sup']:,.0f}]  DM p={c['dm_p_valor']:.3f}  -> "
                  f"{'MEJORA' if mejora else 'empeora'}, "
                  f"{'distinguible' if distinguible else 'no distinguible'}")
            filas.append({
                "serie": nombre, "variante": etiq,
                "MAE_base": round(base_mae, 2), "MAE_variante": round(mae, 2),
                "dif_MAE": round(c["diferencia_media"], 2),
                "ic95_inf": round(c["ic_inf"], 2), "ic95_sup": round(c["ic_sup"], 2),
                "dm_p_valor": round(c["dm_p_valor"], 4),
                "mejora": mejora, "distinguible_95": distinguible,
            })
        print()

    out = RAIZ / "results" / "experimento_exogenas.csv"
    out.parent.mkdir(exist_ok=True)
    pd.DataFrame(filas).to_csv(out, index=False)
    print(f"Guardado en {out}")
    print("Criterio: se suma al modelo la candidata que baja el MAE y es "
          "distinguible de 0 (IC95 que no cruza 0).")


if __name__ == "__main__":
    main()
