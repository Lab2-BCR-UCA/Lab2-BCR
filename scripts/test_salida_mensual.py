"""Pruebas de la salida mensual (SCRUM-64).

- Mes ya publicado (septiembre 2026, simulado): se generan el JSON, el Excel y
  el HTML; la estimación, la variación del IACA y los factores coinciden entre
  el Excel, el HTML y el registro, y los factores suman la estimación.
- Mes sin publicar: las columnas de dato real y error quedan vacías.
- Se pueden borrar el Excel y el HTML y regenerarlos desde el JSON.
- El respaldo conserva las últimas 12 fechas.
- Si el Excel del mes está abierto, avisa en vez de romperse, y el JSON queda
  con la estimación nueva (``--regenerar`` arma el Excel con esos números).
- Si todavía no se puede estimar el mes, termina con código 3 sin informes, y
  el detalle de la corrida queda en ``resultados/ultima_corrida.log``.
- Los gráficos del Excel tienen los ejes visibles.
- Los archivos de una simulación empiezan con ``SIMULACION_``.
- Si falló una fuente secundaria, el Excel y el HTML lo avisan arriba con el
  mes del dato que se usó.
- En bioetanol total, cada variable dice si es de maíz o de caña.

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
import zipfile
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
    for clave in ("json", "excel", "html"):
        assert r[clave].name.startswith("SIMULACION_"), r[clave].name
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
    print("ok  los archivos de la simulación empiezan con SIMULACION_")


def test_graficos_con_ejes():
    excel = sm.rutas(MES, sm.CARPETA_SIMULACION)["excel"]
    with zipfile.ZipFile(excel) as z:
        graficos = [n for n in z.namelist() if n.startswith("xl/charts/chart")]
        assert graficos, "el Excel no tiene gráficos"
        for n in graficos:
            xml = z.read(n).decode("utf-8")
            ejes = re.findall(r"<(?:c:)?(?:catAx|valAx)>.*?</(?:c:)?(?:catAx|valAx)>", xml, re.S)
            assert len(ejes) == 2, n
            for eje in ejes:
                assert re.search(r'<(?:c:)?delete val="(?:0|false)"\s*/>', eje), f"{n}: eje oculto"
    print(f"ok  los {len(graficos)} gráficos del Excel tienen los ejes visibles")


def test_bioetanol_total_dice_el_insumo():
    datos = json.loads(sm.rutas(MES, sm.CARPETA_SIMULACION)["json"].read_text(encoding="utf-8"))
    total = next(s for s in datos["series"] if s["id"] == "bioetanol_total")
    nombres = [v["nombre"] for f in total["factores"] for v in f["variables"]] + [v["nombre"] for v in total["variables"]]
    assert nombres, "bioetanol total sin variables"
    sin_insumo = [n for n in nombres if not (n.endswith("(maíz)") or n.endswith("(caña)"))]
    assert not sin_insumo, f"variables sin (maíz)/(caña): {sin_insumo}"
    for f in total["factores"]:
        repetidas = [n for n in {v["nombre"] for v in f["variables"]} if [v["nombre"] for v in f["variables"]].count(n) > 1]
        assert not repetidas, (f["factor"], repetidas)
    print("ok  en bioetanol total cada variable dice si es de maíz o de caña")


def test_aviso_de_fuente_caida():
    datos = json.loads(sm.rutas(MES, sm.CARPETA_SIMULACION)["json"].read_text(encoding="utf-8"))
    con = copy.deepcopy(datos)
    con["fuentes_caidas"] = [{"fuente": "tipo de cambio (BCRA)", "motivo": "el sitio no responde", "dato_hasta": "2026-08"}]
    con["aviso_fuentes"] = sm.informe_html.texto_fuentes_caidas(con["fuentes_caidas"])
    with tempfile.TemporaryDirectory() as tmp:
        r = sm.rutas(MES, Path(tmp), simulacion=False)
        r["json"].write_text(json.dumps(con), encoding="utf-8")
        sm.regenerar(MES, Path(tmp))
        aviso = openpyxl.load_workbook(r["excel"])["Estimación"]["A4"].value or ""
        assert "tipo de cambio (BCRA)" in aviso and "08/2026" in aviso, aviso
        assert "tipo de cambio (BCRA)" in r["html"].read_text(encoding="utf-8")
    assert not datos.get("aviso_fuentes"), "sin fuentes caídas no hay aviso"
    print("ok  si falla una fuente, el Excel y el HTML avisan cuál y de qué mes es el dato")


def test_ultimo_dato_de_una_fuente():
    with tempfile.TemporaryDirectory() as tmp:
        raiz = Path(tmp)
        (raiz / "db").mkdir()
        (raiz / "data").mkdir()
        (raiz / "db" / "fuentes.csv").write_text("fuente,archivo_origen,descripcion\n"
                                                 "aceite_soja,data/a.csv,x\nazucar,data/b.csv,y\n", encoding="utf-8")
        (raiz / "db" / "series.csv").write_text("serie_id,fuente,columna_origen\n"
                                                "s1,aceite_soja,aceite\ns2,azucar,azucar\n", encoding="utf-8")
        (raiz / "data" / "a.csv").write_text("fecha,aceite\n2026-07-01,1\n2026-08-01,2\n2026-09-01,\n", encoding="utf-8")
        (raiz / "data" / "b.csv").write_text("fecha,azucar\n2026-07-01,1\n", encoding="utf-8")
        assert sm.pipeline.ultimo_dato("aceite de soja y azúcar", raiz) == "2026-07"
        assert sm.pipeline.ultimo_dato("no existe", raiz) is None
    print("ok  el aviso de fuente caída toma el último mes con dato de la fuente")


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


def test_excel_abierto_guarda_igual_el_json():
    datos = json.loads(sm.rutas(MES, sm.CARPETA_SIMULACION)["json"].read_text(encoding="utf-8"))
    nuevo = copy.deepcopy(datos)
    nuevo["corrida"] = "corrida nueva"
    original = sm.excel_abierto
    with tempfile.TemporaryDirectory() as tmp:
        r = sm.rutas(MES, Path(tmp))
        r["json"].write_text(json.dumps(datos), encoding="utf-8")
        sm.excel_abierto = lambda ruta: True
        try:
            sm.escribir_informes(nuevo, Path(tmp))
        except RuntimeError as e:
            assert "--regenerar" in str(e), e
        else:
            raise AssertionError("debió avisar que el Excel está abierto")
        finally:
            sm.excel_abierto = original
        assert json.loads(r["json"].read_text(encoding="utf-8"))["corrida"] == "corrida nueva"
    print("ok  con el Excel abierto, el JSON queda con la estimación nueva para --regenerar")


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
        assert not list((Path(tmp) / "resultados").glob("estimacion_*"))
        log = (Path(tmp) / "resultados" / sm.LOG).read_text(encoding="utf-8")
        assert "NO SE ESTIMÓ" in log and "28/11/2026" in log and "Código de salida: 3" in log, log
    print("ok  si todavía no se puede estimar, termina con código 3, sin informes y con el detalle en el log")


def test_error_inesperado_queda_en_el_log():
    original, carpeta, respaldar = sm.pipeline.correr, sm.CARPETA, sm.respaldar
    def rompe(**_):
        raise KeyError("columna_que_no_esta")
    with tempfile.TemporaryDirectory() as tmp:
        sm.pipeline.correr, sm.CARPETA, sm.respaldar = rompe, Path(tmp) / "resultados", lambda: []
        try:
            assert sm.main(["--sin-descargas"]) == 1
        finally:
            sm.pipeline.correr, sm.CARPETA, sm.respaldar = original, carpeta, respaldar
        log = (Path(tmp) / "resultados" / sm.LOG).read_text(encoding="utf-8")
        assert "Traceback" in log and "columna_que_no_esta" in log, log
        assert not (Path(tmp) / "resultados" / "ultimo_error.txt").exists()
    print("ok  un error inesperado deja el detalle en ultima_corrida.log")


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
    test_ultimo_dato_de_una_fuente()
    test_mes_publicado_coincide_en_todos_lados()
    test_graficos_con_ejes()
    test_bioetanol_total_dice_el_insumo()
    test_aviso_de_fuente_caida()
    test_mes_sin_publicar_deja_real_vacio()
    test_regenerar_desde_json()
    test_avisa_si_el_excel_esta_abierto()
    test_excel_abierto_guarda_igual_el_json()
    test_todavia_no_se_puede_estimar()
    test_error_inesperado_queda_en_el_log()
    print("\nTodas las pruebas de la salida mensual pasaron.")
