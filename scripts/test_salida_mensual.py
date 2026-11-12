"""Pruebas de la salida mensual (SCRUM-64).

- Mes ya publicado (septiembre 2026, simulado): se generan el JSON, el Excel y
  el HTML; la estimación, la variación del IACA y los factores coinciden entre
  el Excel, el HTML y el registro, y los factores suman la estimación.
- Mes sin publicar: las columnas de dato real y error quedan vacías.
- Se pueden borrar el Excel y el HTML y regenerarlos desde el JSON.
- El respaldo conserva las últimas 12 fechas.
- Si el Excel del mes está abierto, avisa en vez de romperse.
- Si todavía no se puede estimar el mes, termina con código 3 sin informes ni
  ``ultimo_error.txt``.

Corre X-13 (una simulación): tarda alrededor de un minuto.

Uso, desde la raíz del repo, con la base armada:
    python scripts/test_salida_mensual.py
"""

from __future__ import annotations

import copy
import json
import re
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import openpyxl
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import salida_mensual as sm  # noqa: E402

MES = "2026-09"


def test_mes_publicado_coincide_en_todos_lados():
    r = sm.correr(simular=MES)
    datos = json.loads(r["json"].read_text(encoding="utf-8"))
    reg = pd.read_csv(sm.pipeline.CARPETA_SIMULACION / f"registro_{MES}.csv")
    final = reg[reg["modelo"] == "modelo_final"].set_index("serie_id")

    wb = openpyxl.load_workbook(r["excel"])
    est, fac = wb["Estimación"], wb["Factores"]
    html = r["html"].read_text(encoding="utf-8")
    datos_html = json.loads(re.search(r'id="datos">(.*?)</script>', html, re.S).group(1).replace("<\\/", "</"))
    assert datos_html["series"] == datos["series"]

    for i, s in enumerate(datos["series"]):
        sid = sm.pipeline.OBJETIVOS[s["id"]]
        assert np.isclose(s["prediccion"], final.loc[sid, "pronostico"], rtol=1e-12)
        fila = 7 + i
        assert np.isclose(est.cell(fila, 4).value, s["prediccion"], rtol=1e-12), s["id"]
        if s["var_iaca"] is not None:
            assert np.isclose(est.cell(fila, 6).value * 100, final.loc[sid, "variacion_pronosticada_pct"], atol=1e-9)
        assert np.isclose(s["real_anterior"] + sum(f["cambio"] for f in s["factores"]), s["prediccion"], atol=1e-6)
        assert s["real"] is not None

    # En la hoja Factores, real anterior + factores = estimación (con los valores escritos).
    bloques = [c.row for c in fac["A"] if isinstance(c.value, str) and c.value.startswith("Real ")]
    for fila0, s in zip(bloques, datos["series"]):
        f, suma = fila0 + 1, fac.cell(fila0, 2).value
        while not str(fac.cell(f, 1).value).startswith("Estimación"):
            suma += fac.cell(f, 2).value
            f += 1
        assert np.isclose(suma, s["prediccion"], atol=0.05), s["id"]
        assert "producción" in fac.cell(fila0 - 1, 3).value, "la cabecera aclara que son puntos de producción"
    print("ok  mes publicado: estimación, IACA y factores coinciden entre Excel, HTML y registro")


def test_mes_sin_publicar_deja_real_vacio():
    datos = json.loads(sm.rutas(MES, sm.CARPETA_SIMULACION)["json"].read_text(encoding="utf-8"))
    sin = copy.deepcopy(datos)
    sin["simulacion"], sin["seguimiento"], sin["metricas"] = False, [], []
    for s in sin["series"]:
        s["real"] = None
    with tempfile.TemporaryDirectory() as tmp:
        carpeta = Path(tmp)
        sm.rutas(MES, carpeta)["json"].write_text(json.dumps(sin), encoding="utf-8")
        r = sm.regenerar(MES, carpeta)
        est = openpyxl.load_workbook(r["excel"])["Estimación"]
        cabeceras = [c.value for c in est[6] if c.value]
        assert "Dato publicado" not in cabeceras and len(cabeceras) == 8, cabeceras
        assert r["html"].exists()
    print("ok  mes sin publicar: sin columnas de real ni de error")


def test_regenerar_desde_json():
    r = sm.rutas(MES, sm.CARPETA_SIMULACION)
    antes = r["html"].read_text(encoding="utf-8")
    r["excel"].unlink()
    r["html"].unlink()
    sm.regenerar(MES, sm.CARPETA_SIMULACION)
    assert r["excel"].exists() and r["html"].read_text(encoding="utf-8") == antes
    print("ok  el Excel y el HTML se regeneran desde el JSON, igual que antes")


def test_respaldo_conserva_12_fechas():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        origen = tmp / "bcr.db"
        origen.write_text("x")
        carpeta = tmp / "respaldo"
        for k in range(15):
            sm.respaldar(carpeta, date(2026, 1, 1) + timedelta(days=k), {origen: "base"})
        fechas = sorted(p.name for p in carpeta.iterdir())
        assert len(fechas) == 12 and fechas[0] == "base_2026-01-04.db" and fechas[-1] == "base_2026-01-15.db", fechas
    print("ok  el respaldo conserva las últimas 12 fechas")


def test_todavia_no_se_puede_estimar():
    original, carpeta, respaldar = sm.pipeline.correr, sm.CARPETA, sm.respaldar
    def frena(**_):
        raise sm.pipeline.TodaviaNoSePuedeEstimar("Todavía no se puede estimar 10/2026. "
                                                  "Volver a correr desde el 28/11/2026.")
    with tempfile.TemporaryDirectory() as tmp:
        sm.pipeline.correr, sm.CARPETA, sm.respaldar = frena, Path(tmp) / "resultados", lambda: []
        try:
            assert sm.main(["--sin-descargas"]) == sm.TODAVIA_NO
        finally:
            sm.pipeline.correr, sm.CARPETA, sm.respaldar = original, carpeta, respaldar
        assert not (Path(tmp) / "resultados" / "ultimo_error.txt").exists()
        assert not list((Path(tmp) / "resultados").glob("estimacion_*"))
    print("ok  si todavía no se puede estimar, termina con código 3 y sin informes")


def test_avisa_si_el_excel_esta_abierto():
    original = sm.excel_abierto
    sm.excel_abierto = lambda ruta: True
    try:
        sm.regenerar(MES, sm.CARPETA_SIMULACION)
    except RuntimeError as e:
        assert "está abierto" in str(e)
    else:
        raise AssertionError("debió avisar que el Excel está abierto")
    finally:
        sm.excel_abierto = original
    print("ok  si el Excel está abierto, avisa que lo cierren")


if __name__ == "__main__":
    test_respaldo_conserva_12_fechas()
    test_mes_publicado_coincide_en_todos_lados()
    test_mes_sin_publicar_deja_real_vacio()
    test_regenerar_desde_json()
    test_avisa_si_el_excel_esta_abierto()
    test_todavia_no_se_puede_estimar()
    print("\nTodas las pruebas de la salida mensual pasaron.")
