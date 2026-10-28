"""Experimento controlado: aísla el efecto de d en el SARIMAX (review, SCRUM-29).

Compara dos órdenes FIJOS que solo difieren en d:
    d=1 -> (1,1,1)(0,1,1,12)
    d=0 -> (1,0,1)(0,1,1,12)
mismo p, q, P, D, Q. Así el contraste mide SOLO el efecto de diferenciar, sin
mezclarlo con la búsqueda por AIC (que cambiaba también p,q,P,Q).

Se corre solo en biodiésel y caña: son las únicas que ADF+KPSS dejan como
estacionarias en log (total y maíz dan contradictorio -> d=1, no se discuten).

Reporta MAE (métrica principal, decisión del 27/10) y MAPE, y la diferencia
d0-d1 con IC por bootstrap de bloques + Diebold-Mariano (pérdida 'ae'):
negativo = d0 tiene menos error; si el IC cruza 0, no son distinguibles.

Resultado (backtest, para referencia; reproducir corriendo este script):
    biodiésel: d=1 MAE 29.221 vs d=0 31.555 -> dif +2.333, IC95 [294, 4.208],
               DM p=0,025  -> d=1 mejor y DISTINGUIBLE.
    caña:      d=1 MAE  7.628 vs d=0  7.039 -> dif -588, IC95 [-1.631, 475],
               p=0,286    -> d=0 apenas mejor, NO distinguible.
Conclusión: d=1 en las 4 series (ver docstring de sarimax.py).

Uso, desde la raíz del proyecto:
    python scripts/experimento_d.py
"""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))

from sarimax import ModeloSARIMAX, _objetivos_desde_base, INICIO_ENTRENAMIENTO  # noqa: E402
from evaluacion import comparar_modelos, evaluar_ventanas, ventanas_protocolo  # noqa: E402

ORDENES = {
    "d1": ((1, 1, 1), (0, 1, 1, 12)),
    "d0": ((1, 0, 1), (0, 1, 1, 12)),
}
SERIES = ["biodiesel", "bioetanol_cana"]


def main() -> None:
    series = _objetivos_desde_base()
    ultimo = min(s.index[-1] for s in series.values())
    ventanas = {"backtest": ventanas_protocolo(ultimo)["backtest"]}

    print("Experimento controlado d=0 vs d=1 (mismo p,q,P,Q), backtest\n")
    for nombre in SERIES:
        serie = series[nombre]
        det, res = {}, {}
        for etiq, (orden, seasonal) in ORDENES.items():
            d, r = evaluar_ventanas(
                serie=serie,
                crear_modelo=lambda o=orden, so=seasonal: ModeloSARIMAX(nombre, o, so),
                inicio_entrenamiento=INICIO_ENTRENAMIENTO[nombre],
                ventanas=ventanas,
                nombre_serie=nombre,
                nombre_modelo=etiq,
            )
            det[etiq], res[etiq] = d, r.iloc[0]

        print(f"== {nombre} ==")
        for etiq in ("d1", "d0"):
            print(f"  {etiq}: MAE={res[etiq]['MAE']:,.0f}  MAPE={res[etiq]['MAPE_pct']:.2f}%")
        c = comparar_modelos(det["d0"], det["d1"], perdida="ae")
        signo = "d0 mejor" if c["diferencia_media"] < 0 else "d1 mejor"
        distingue = ("DISTINGUIBLE" if (c["ic_inf"] > 0 or c["ic_sup"] < 0)
                     else "no distinguible (IC cruza 0)")
        print(f"  dif MAE (d0-d1) = {c['diferencia_media']:,.0f}  "
              f"IC95 [{c['ic_inf']:,.0f}, {c['ic_sup']:,.0f}]  "
              f"DM p={c['dm_p_valor']:.3f}  -> {signo}, {distingue}\n")


if __name__ == "__main__":
    main()
