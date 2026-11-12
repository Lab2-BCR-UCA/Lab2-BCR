"""Salida mensual para la BCR: Excel e informe HTML (SCRUM-64).

Lo que corre el doble clic en ``correr_estimacion.bat``:

1. Guarda una copia fechada de la base y del registro en
   ``resultados/respaldo/`` y conserva las últimas 12 fechas.
2. Corre el pipeline (SCRUM-38): descargas, base, estimación, contribuciones
   y registro.
3. Guarda los datos del mes en ``resultados/estimacion_AAAA-MM.json``: la
   estimación, los factores (SCRUM-35), el seguimiento del registro (SCRUM-44)
   y las métricas. Se calcula todo una sola vez.
4. Arma desde ese JSON el Excel ``resultados/IACA_biocombustibles_AAAA-MM.xlsx``
   y el informe ``resultados/estimacion_AAAA-MM.html``, y abre el HTML.

El Excel y el HTML se pueden borrar y volver a generar desde el JSON sin
correr el modelo de nuevo (``--regenerar AAAA-MM``).

Si todavía no se puede estimar el mes (antes del día 28 del mes siguiente,
faltan las ventas de gasoil o las exportaciones de INDEC, o el sitio de la
producción no responde), frena sin armar informes. No es un error del programa:
termina con código 3 y el mensaje dice cuándo volver a correr.

Códigos de salida: 0 listo, 1 error, 3 todavía no se puede estimar.

Uso, desde la raíz del repo:

    python scripts/salida_mensual.py                     # corrida mensual
    python scripts/salida_mensual.py --simular 2026-09   # mes ya publicado, en resultados/simulacion/
    python scripts/salida_mensual.py --regenerar 2026-09 # rearma Excel y HTML desde el JSON
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import traceback
from datetime import date
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))

import informe_excel  # noqa: E402
import informe_html  # noqa: E402
import pipeline  # noqa: E402
import registro  # noqa: E402

CARPETA = RAIZ / "resultados"
CARPETA_SIMULACION = CARPETA / "simulacion"
CARPETA_RESPALDO = CARPETA / "respaldo"
RESPALDOS_A_CONSERVAR = 12
TODAVIA_NO = 3  # código de salida cuando todavía no se puede estimar el mes (no es un error)
A_RESPALDAR = {  # archivo -> prefijo de la copia
    RAIZ / "data" / "bcr.db": "base",
    registro.RUTA_REGISTRO: "registro_estimaciones",
    pipeline.RUTA_CONTRIBUCIONES: "registro_contribuciones",
}


def rutas(mes: str, carpeta: Path = CARPETA) -> dict[str, Path]:
    return {"json": carpeta / f"estimacion_{mes}.json",
            "excel": carpeta / f"IACA_biocombustibles_{mes}.xlsx",
            "html": carpeta / f"estimacion_{mes}.html"}


# ------------------------------------------------------------------ respaldo

def respaldar(carpeta: Path = CARPETA_RESPALDO, hoy: date | None = None,
              archivos: dict[Path, str] | None = None, conservar: int = RESPALDOS_A_CONSERVAR) -> list[Path]:
    """Copia fechada de la base y del registro; borra las fechas más viejas que las últimas ``conservar``.

    Se respaldan los CSV del registro además de la base porque el registro vive
    en el CSV (la base se rearma de cero en cada corrida).
    """
    hoy = hoy or date.today()
    archivos = A_RESPALDAR if archivos is None else archivos
    carpeta.mkdir(parents=True, exist_ok=True)
    copias = []
    for origen, prefijo in archivos.items():
        if Path(origen).exists():
            destino = carpeta / f"{prefijo}_{hoy:%Y-%m-%d}{Path(origen).suffix}"
            shutil.copy2(origen, destino)
            copias.append(destino)
    fechas = sorted({p.stem.rsplit("_", 1)[-1] for p in carpeta.iterdir() if p.is_file()})
    for vieja in fechas[:-conservar] if len(fechas) > conservar else []:
        for p in carpeta.glob(f"*_{vieja}.*"):
            p.unlink()
    return copias


# ------------------------------------------------------------------ datos del mes

def _estimados_anteriores(ruta_registro: Path, modelo: str = "modelo_final") -> dict[str, pd.Series]:
    """Lo que estimó un modelo en cada mes: evaluación (backtest y holdout) y registro."""
    archivo = "modelo_final_predicciones.csv" if modelo == "modelo_final" else "protocolo_predicciones.csv"
    pred = pd.read_csv(RAIZ / "results" / archivo)
    pred = pred[(pred["modelo"] == modelo) & pred["prediccion"].notna()]
    reg = registro.ultimas_estimaciones(registro.leer_registro(ruta_registro))
    reg = reg[reg["modelo"] == modelo]
    salida = {}
    for serie in pipeline.SERIES:
        p = pred[pred["serie"] == serie]
        s = pd.Series(p["prediccion"].to_numpy(), index=pd.PeriodIndex(p["fecha"], freq="M"))
        r = reg[reg["serie_id"] == pipeline.OBJETIVOS[serie]]
        s2 = pd.Series(r["pronostico"].to_numpy(), index=pd.PeriodIndex(r["mes_estimado"], freq="M"))
        salida[serie] = pd.concat([s[~s.index.isin(s2.index)], s2]).sort_index()
    return salida


def _seguimiento(ruta_registro: Path, simulado: pd.Period | None) -> pd.DataFrame:
    """Estimaciones anteriores con su error.

    En una corrida real es el registro. En una simulación, el registro que
    habría quedado si el pipeline hubiera corrido todo el holdout
    (``results/registro_holdout_simulado.csv``, SCRUM-44) hasta el mes simulado.
    """
    if simulado is None:
        return registro.ultimas_estimaciones(registro.leer_registro(ruta_registro))
    h = registro.leer_registro(RAIZ / "results" / "registro_holdout_simulado.csv")
    return h[pd.PeriodIndex(h["mes_estimado"], freq="M") <= simulado].reset_index(drop=True)


def datos_del_mes(res: dict) -> dict:
    """Arma, una sola vez, todo lo que muestran el Excel y el HTML."""
    mes = res["mes"]
    return informe_html.armar_datos(
        mes, res["tablas"], res["filas"], _seguimiento(res["ruta_registro"], mes if res["simulacion"] else None),
        {s: pipeline._serie(res["base"], s, hasta=mes - 1) for s in pipeline.SERIES},
        _estimados_anteriores(res["ruta_registro"]), _estimados_anteriores(res["ruta_registro"], "x13_bcr"),
        pipeline.NOMBRE, pipeline.UNIDAD, pipeline.OBJETIVOS, simulacion=res["simulacion"], reales=res["reales"])


# ------------------------------------------------------------------ archivos

def excel_abierto(ruta: Path) -> bool:
    """True si el archivo existe y otro programa lo tiene abierto (Excel lo bloquea en Windows)."""
    if not ruta.exists():
        return False
    try:
        with open(ruta, "r+b"):
            return False
    except PermissionError:
        return True


def _avisar_si_abierto(ruta: Path) -> None:
    if excel_abierto(ruta):
        raise RuntimeError(f"El Excel {ruta.name} está abierto. Cerralo y volvé a correr.")


def escribir_informes(datos: dict, carpeta: Path) -> dict[str, Path]:
    """Guarda el JSON del mes y arma el Excel y el HTML desde ese JSON."""
    r = rutas(datos["mes"], carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    _avisar_si_abierto(r["excel"])
    r["json"].write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    return regenerar(datos["mes"], carpeta)


def regenerar(mes: str, carpeta: Path = CARPETA) -> dict[str, Path]:
    """Arma el Excel y el HTML a partir del JSON guardado del mes, sin correr el modelo."""
    r = rutas(mes, carpeta)
    if not r["json"].exists():
        raise FileNotFoundError(f"No está {r['json'].relative_to(RAIZ)}: hay que correr la estimación de {mes}.")
    datos = json.loads(r["json"].read_text(encoding="utf-8"))
    _avisar_si_abierto(r["excel"])
    try:
        informe_excel.escribir(datos, r["excel"])
    except PermissionError as e:
        raise RuntimeError(f"El Excel {r['excel'].name} está abierto. Cerralo y volvé a correr "
                           f"(o usá --regenerar {mes}).") from e
    informe_html.escribir(datos, r["html"])
    return r


# ------------------------------------------------------------------ corrida

def correr(sin_descargas: bool = False, simular: str | None = None, abrir: bool = False) -> dict[str, Path]:
    carpeta = CARPETA_SIMULACION if simular else CARPETA
    if simular:
        _avisar_si_abierto(rutas(str(pd.Period(simular, freq="M")), carpeta)["excel"])
    else:
        print("0. Respaldo")
        copias = respaldar()
        print(f"  ok    {len(copias)} archivo{'' if len(copias) == 1 else 's'} copiado{'' if len(copias) == 1 else 's'} "
              f"en {CARPETA_RESPALDO.relative_to(RAIZ)} "
              f"(se conservan las últimas {RESPALDOS_A_CONSERVAR} fechas)\n", flush=True)
    res = pipeline.correr(sin_descargas=sin_descargas, simular=simular)
    print("\n7. Informes")
    r = escribir_informes(datos_del_mes(res), carpeta)
    for clave in ("excel", "html"):
        print(f"  ok    {r[clave].relative_to(RAIZ)}")
    if abrir and os.name == "nt":
        os.startfile(r["html"])  # noqa: S606  (solo Windows: abre el informe en el navegador)
    return r


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--sin-descargas", action="store_true", help="usar los datos que ya están")
    p.add_argument("--simular", metavar="AAAA-MM", help="estimar un mes ya publicado, sin tocar el registro real")
    p.add_argument("--regenerar", metavar="AAAA-MM", help="rearmar el Excel y el HTML de un mes desde su JSON")
    p.add_argument("--abrir", action="store_true", help="abrir el informe al terminar (Windows)")
    a = p.parse_args(argv)
    try:
        if a.regenerar:
            r = regenerar(str(pd.Period(a.regenerar, freq="M")),
                          CARPETA_SIMULACION if rutas(a.regenerar, CARPETA_SIMULACION)["json"].exists()
                          and not rutas(a.regenerar)["json"].exists() else CARPETA)
            print(f"Listo: {r['excel'].relative_to(RAIZ)} y {r['html'].relative_to(RAIZ)}")
        else:
            correr(a.sin_descargas, a.simular, a.abrir)
    except pipeline.TodaviaNoSePuedeEstimar as e:
        print(f"\nNO SE ESTIMÓ (no es un error): {e}")
        return TODAVIA_NO
    except (RuntimeError, ValueError, FileNotFoundError) as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001  (cualquier otra falla: mensaje claro y detalle en un archivo)
        CARPETA.mkdir(parents=True, exist_ok=True)
        detalle = CARPETA / "ultimo_error.txt"
        detalle.write_text(traceback.format_exc(), encoding="utf-8")
        print(f"\nERROR inesperado: {e}\nEl detalle quedó en {detalle.relative_to(RAIZ)}; "
              "mandáselo al equipo.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
