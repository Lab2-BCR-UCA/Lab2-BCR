"""Excel de cada corrida del pipeline (SCRUM-64).

Sale de los mismos datos que el informe HTML (el JSON del mes que guarda ``salida_mensual.py``),
así que los dos dicen siempre lo mismo. Diseño acordado con el equipo (Flor):

- **Estimación**: Tabla 1 (estimación, variación de la producción y del IACA,
  X-13 BCR y, si ya se publicó, el real y el error), el texto "En palabras" y
  las notas.
- **Factores**: para cada serie, del real del mes anterior a la estimación,
  factor por factor, con su gráfico; y las variables que forman cada factor del
  bioetanol.
- **Historial**: resumen del error (con fórmulas, se recalcula si se agregan
  filas) y el detalle mes a mes del modelo y el X-13.
- **Serie mensual**: real y estimaciones a un mes, con gráficos.

Las variaciones y los errores de las tablas son fórmulas de Excel, para que
la BCR vea de dónde sale cada número. Cada hoja está lista para imprimir
(apaisada, una página de ancho).
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.drawing.line import LineProperties
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

AZUL = "1F3A5F"
CELESTE = "EAF1F8"
GRIS = "595959"
VERDE = "2F6B3A"
ROJO = "9C3524"
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
MESES_L = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
           "septiembre", "octubre", "noviembre", "diciembre"]

F_ENTERO = "#,##0;\\-#,##0;\\-"
F_PCT1 = "\\+0.0%;\\-0.0%;0.0%"
F_PCT2 = "\\+0.00%;\\-0.00%;0.00%"
F_PP = '\\+0.0" pp";\\-0.0" pp";\\-'
F_PP2 = '\\+0.00" pp";\\-0.00" pp";0.00" pp"'

LINEA = Side(style="thin", color="BFBFBF")
T_TITULO = Font(bold=True, size=14, color=AZUL)
T_SUB = Font(size=10, color=GRIS)
T_NOTA = Font(size=9, color=GRIS, italic=True)
T_SECCION = Font(bold=True, size=11, color=AZUL)
T_CABECERA = Font(bold=True, size=10, color="FFFFFF")
T_NORMAL = Font(size=10)
T_NEGRITA = Font(bold=True, size=10)


def _mes_corto(m: str) -> str:
    a, b = m.split("-")
    return f"{MESES[int(b) - 1]} {a[2:]}"


def _mes_largo(m: str) -> str:
    a, b = m.split("-")
    return f"{MESES_L[int(b) - 1]} {a}"


def _anterior(m: str) -> str:
    return str(pd.Period(m, freq="M") - 1)


def _sin_html(t: str) -> str:
    return re.sub(r"<[^>]+>", "", t.replace("<sup>1</sup>", " (ver nota 1)"))


def _cabecera(ws, fila: int, textos: list[str], col: int = 1) -> None:
    for j, t in enumerate(textos):
        c = ws.cell(fila, col + j, t)
        c.font, c.fill = T_CABECERA, PatternFill("solid", fgColor=AZUL)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[fila].height = 30


def _celda(ws, fila, col, valor, formato=None, negrita=False, resaltar=False, color=None, derecha=False):
    c = ws.cell(fila, col, valor)
    c.font = Font(bold=negrita, size=10, color=color)
    c.border = Border(bottom=LINEA)
    if formato:
        c.number_format = formato
    if resaltar:
        c.fill = PatternFill("solid", fgColor=CELESTE)
    if derecha:
        c.alignment = Alignment(horizontal="right")
    return c


def _texto(ws, fila, valor, fuente=T_SUB, hasta=10, alto=None):
    c = ws.cell(fila, 1, valor)
    c.font = fuente
    if hasta > 1:
        ws.merge_cells(start_row=fila, start_column=1, end_row=fila, end_column=hasta)
        c.alignment = Alignment(wrap_text=True, vertical="top")
    if alto:
        ws.row_dimensions[fila].height = alto
    return c


def _imprimir(ws) -> None:
    ws.sheet_view.showGridLines = False
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_options.horizontalCentered = True
    ws.page_margins.left = ws.page_margins.right = 0.4


def _anchos(ws, anchos: dict[str, float]) -> None:
    for col, w in anchos.items():
        ws.column_dimensions[col].width = w


# ------------------------------------------------------------------ hojas

def _hoja_estimacion(wb: Workbook, d: dict) -> None:
    ws = wb.active
    ws.title = "Estimación"
    mes, ant = d["mes"], _anterior(d["mes"])
    sim = any(s["real"] is not None for s in d["series"])
    ws["A1"] = f"Estimación de {_mes_largo(mes)} — Biodiésel y bioetanol"
    ws["A1"].font = T_TITULO
    ws["A2"] = (f"Datos hasta {_mes_largo(ant)}  ·  Corrida {d['corrida']}  ·  "
                "Modelos: suma contable (biodiésel) y elastic net (bioetanol)")
    ws["A2"].font = T_SUB
    if d["simulacion"]:
        ws["A3"] = (f"Ejercicio sobre un mes ya publicado: se estima {_mes_largo(mes)} con los datos que había "
                    f"hasta {_mes_largo(ant)} y se compara con el dato real que salió después.")
        ws["A3"].font = T_NOTA

    ws["A5"] = "Tabla 1. Estimación del mes y variación que se publicaría en el IACA"
    ws["A5"].font = T_SECCION
    cab = ["Serie", "Unidad", f"Real {_mes_largo(ant)}", f"Estimación {_mes_largo(mes)}",
           "Variación de la producción", "Variación IACA (modelo)", "Variación IACA (X-13 BCR)",
           "Estimación X-13 BCR"]
    if sim:
        cab += ["Dato publicado", "Error (estimación − real)", "Error %"]
    _cabecera(ws, 6, cab)
    for i, s in enumerate(d["series"]):
        f = 7 + i
        detalle = s["id"] in ("bioetanol_maiz", "bioetanol_cana")
        _celda(ws, f, 1, ("   " if detalle else "") + s["nombre"] + (" (detalle)" if detalle else ""), negrita=not detalle)
        _celda(ws, f, 2, s["unidad"])
        _celda(ws, f, 3, s["real_anterior"], F_ENTERO)
        _celda(ws, f, 4, s["prediccion"], F_ENTERO, negrita=True, resaltar=True)
        _celda(ws, f, 5, f"=D{f}/C{f}-1", F_PCT1, color=VERDE if s["var_produccion"] > 0 else ROJO)
        if s["var_iaca"] is not None:
            _celda(ws, f, 6, s["var_iaca"] / 100, F_PCT2, negrita=True, resaltar=True)
            _celda(ws, f, 7, s["x13_var_iaca"] / 100 if s["x13_var_iaca"] is not None else "—", F_PCT2, derecha=True)
            _celda(ws, f, 8, s["x13"], F_ENTERO)
        else:
            for c in (6, 7, 8):
                _celda(ws, f, c, "—", derecha=True)
        if sim:
            _celda(ws, f, 9, s["real"], F_ENTERO)
            _celda(ws, f, 10, f"=D{f}-I{f}", F_ENTERO)
            _celda(ws, f, 11, f"=J{f}/I{f}", F_PCT1)
    n = 7 + len(d["series"])
    ws.cell(n, 1, "Biodiésel en toneladas, bioetanol en m³. El total de bioetanol es la suma de maíz y caña; "
                  "solo biodiésel y bioetanol total entran al IACA.").font = T_NOTA

    fila = n + 3
    ws.cell(fila, 1, "En palabras").font = T_SECCION
    for s in d["series"]:
        if s["id"] in ("biodiesel", "bioetanol_total"):
            fila += 1
            _texto(ws, fila, _sin_html(s["texto"]), T_NORMAL, hasta=11, alto=62)
    fila += 2
    ws.cell(fila, 1, "Notas").font = T_SECCION
    notas = [
        "1. El IACA se calcula sobre la serie desestacionalizada y suavizada (X-13 con la configuración de la BCR, "
        "base 2013 = 100). Por eso una baja de la producción puede ser una suba del índice: alcanza con que la caída "
        "sea menor que la habitual para ese mes.",
        "2. Variación de la producción: contra el dato real del mes anterior, sin desestacionalizar.",
        "3. Los modelos se reentrenan en cada corrida con los datos hasta el mes anterior.",
    ]
    if d["aviso_expo"]:
        notas.append("4. Este mes INDEC protegió el dato de exportación de biodiésel por secreto estadístico: "
                     "el modelo usa un estimado (la mediana de los meses ocultos anteriores).")
    notas.append("Fuentes: Secretaría de Energía, INDEC, CAC, BCRA, SAGyP y Banco Mundial. Datos públicos.")
    for t in notas:
        fila += 1
        _texto(ws, fila, t, T_NOTA, hasta=11, alto=28 if len(t) > 120 else None)
    _anchos(ws, {"A": 30, "B": 8, "C": 16, "D": 18, "E": 14, "F": 14, "G": 14, "H": 15, "I": 15, "J": 15, "K": 10})
    ws.freeze_panes = "A7"
    _imprimir(ws)


def _hoja_factores(wb: Workbook, d: dict) -> None:
    ws = wb.create_sheet("Factores")
    mes, ant = d["mes"], _anterior(d["mes"])
    ws["A1"] = "Qué explica cada estimación"
    ws["A1"].font = T_TITULO
    ws["A2"] = (f"El cambio de {_mes_largo(ant)} a {_mes_largo(mes)} se reparte entre los factores del modelo. "
                "Arranca en el dato real del mes anterior, se suman los factores y se llega a la estimación. "
                "Los puntos son de la variación de la producción, no del IACA.")
    ws["A2"].font = T_SUB
    fila = 4
    for s in d["series"]:
        u = s["unidad"]
        ws.cell(fila, 1, f"{s['nombre']} ({u})").font = T_SECCION
        _cabecera(ws, fila + 1, ["Concepto", f"Cambio ({u})", "Aporte a la var. de la producción", "Tipo"])
        f0 = fila + 2
        _celda(ws, f0, 1, f"Real {_mes_largo(ant)}", negrita=True)
        _celda(ws, f0, 2, s["real_anterior"], F_ENTERO)
        for c in (3, 4):
            _celda(ws, f0, c, None)
        f = f0
        for fac in s["factores"]:
            f += 1
            _celda(ws, f, 1, "   " + fac["factor"][0].upper() + fac["factor"][1:])
            _celda(ws, f, 2, round(fac["cambio"], 2), F_ENTERO, color=VERDE if fac["cambio"] > 0 else ROJO)
            _celda(ws, f, 3, fac["pp"], F_PP)
            _celda(ws, f, 4, "Ajuste (no se repite)" if fac["residuo"] else "Factor del modelo",
                   color=GRIS if fac["residuo"] else None)
        f += 1
        _celda(ws, f, 1, f"Estimación {_mes_largo(mes)}", negrita=True)
        _celda(ws, f, 2, f"=B{f0}+SUM(B{f0 + 1}:B{f - 1})", F_ENTERO, negrita=True, resaltar=True)
        _celda(ws, f, 3, f"=SUM(C{f0 + 1}:C{f - 1})", F_PP, negrita=True)
        _celda(ws, f, 4, None)

        graf = BarChart()
        graf.type = "bar"
        graf.title = f"{s['nombre']}: aporte de cada factor ({u})"
        graf.legend = None
        graf.y_axis.numFmt = "#,##0"
        graf.y_axis.majorGridlines = None
        graf.x_axis.scaling.orientation = "maxMin"
        graf.x_axis.tickLblPos = "low"   # etiquetas a la izquierda, no sobre las barras negativas
        graf.add_data(Reference(ws, min_col=2, min_row=f0 + 1, max_row=f - 1), titles_from_data=False)
        graf.set_categories(Reference(ws, min_col=1, min_row=f0 + 1, max_row=f - 1))
        graf.series[0].graphicalProperties.solidFill = AZUL
        graf.series[0].invertIfNegative = False
        graf.height, graf.width = max(5.5, 0.75 * (f - f0) + 2.5), 15
        ws.add_chart(graf, f"F{fila}")
        fila = max(f + 3, fila + int(graf.height * 2) + 2)

    con_variables = [s for s in d["series"] if s["variables"] and s["id"] != "bioetanol_total"]
    if con_variables:
        ws.cell(fila, 1, "Detalle: variables que forman cada factor del bioetanol").font = T_SECCION
        _cabecera(ws, fila + 1, ["Factor", "Variable", "Modelo", "Cambio (m³)"])
        f = fila + 1
        for s in con_variables:
            for v in sorted(s["variables"], key=lambda v: (v["factor"], -abs(v["cambio"]))):
                f += 1
                _celda(ws, f, 1, v["factor"][0].upper() + v["factor"][1:])
                _celda(ws, f, 2, v["nombre"][0].upper() + v["nombre"][1:])
                _celda(ws, f, 3, s["nombre"].replace("Bioetanol ", "").capitalize())
                _celda(ws, f, 4, round(v["cambio"], 2), F_ENTERO, color=VERDE if v["cambio"] > 0 else ROJO)
        fila = f + 2
    for t in ['"Variación de stock del mes anterior" (biodiésel) y "ajuste del mes anterior" (bioetanol) no son '
              "factores: es lo que el mes anterior se apartó de lo que el modelo esperaba y se supone que no se repite.",
              "Aporte a la variación de la producción: cuántos puntos porcentuales de la variación de la producción "
              "(contra el real del mes anterior, sin desestacionalizar) explica cada factor. No son puntos del IACA: "
              "el índice se desestacionaliza y se suaviza, así que la estacionalidad o la zafra ahí no aparecen."]:
        ws.cell(fila, 1, t).font = T_NOTA
        fila += 1
    _anchos(ws, {"A": 38, "B": 32, "C": 20, "D": 22})
    _imprimir(ws)


def _hoja_historial(wb: Workbook, d: dict) -> None:
    ws = wb.create_sheet("Historial")
    ws["A1"] = "Seguimiento: cómo le fue a las estimaciones anteriores"
    ws["A1"].font = T_TITULO
    ws["A2"] = ("Cada mes se agrega una fila por serie; cuando sale el dato real se completa el error. "
                "El modelo se compara contra la réplica del X-13 de la BCR.")
    ws["A2"].font = T_SUB

    seg = pd.DataFrame(d["seguimiento"])
    filas = []
    if not seg.empty:
        for (mes, serie), g in seg.groupby(["mes", "serie"], sort=False):
            m = g.set_index("modelo")
            fin = m.loc["Modelo final"] if "Modelo final" in m.index else None
            x13 = m.loc["X-13 BCR"] if "X-13 BCR" in m.index else None
            if fin is None:
                continue
            filas.append({"mes": mes, "serie": serie, "real": fin["real"], "modelo": fin["estimacion"],
                          "x13": None if x13 is None else x13["estimacion"],
                          "var_real": fin["var_iaca_real"], "var_modelo": fin["var_iaca"],
                          "var_x13": None if x13 is None else x13["var_iaca"],
                          "signo_modelo": fin["signo"], "signo_x13": None if x13 is None else x13["signo"]})
    filas.sort(key=lambda r: (r["mes"], r["serie"]), reverse=True)

    series_hist = list(dict.fromkeys(r["serie"] for r in sorted(filas, key=lambda r: r["serie"] != "Biodiésel")))
    resumen = [(s, m) for s in series_hist for m in ("Modelo final", "X-13 BCR")
               if m == "Modelo final" or any(r["serie"] == s and r["x13"] is not None for r in filas)]
    inicio = 8 + len(resumen) + 4          # fila de la cabecera de la tabla 3
    p, u = inicio + 1, inicio + max(len(filas), 1)
    rng = lambda c: f"${c}${p}:${c}${u}"   # noqa: E731

    ws["A4"] = "Tabla 2. Resumen del error (meses con dato real publicado)"
    ws["A4"].font = T_SECCION
    _cabecera(ws, 5, ["Serie", "Modelo", "Meses", "Error medio (abs.)", "Error medio %",
                      "Error medio IACA", "Acertó suba/baja"])
    for i, (serie, modelo) in enumerate(resumen):
        f = 6 + i
        err, err_iaca, signo = ("E", "K", "M") if modelo == "Modelo final" else ("G", "L", "N")
        cond = f'({rng("B")}=A{f})*({rng("C")}<>"")'
        _celda(ws, f, 1, serie, negrita=True)
        _celda(ws, f, 2, modelo)
        _celda(ws, f, 3, f'=COUNTIFS({rng("B")},A{f},{rng("C")},"<>")')
        # Las celdas de error quedan vacías mientras no hay real: ABS de vacío es 0
        # y (C="") evita dividir por cero en el error porcentual.
        _celda(ws, f, 4, f'=IF(C{f}=0,"—",SUMPRODUCT({cond}*ABS({rng(err)}))/C{f})', F_ENTERO)
        _celda(ws, f, 5, f'=IF(C{f}=0,"—",SUMPRODUCT({cond}*ABS({rng(err)})/({rng("C")}+({rng("C")}="")))/C{f})', "0.0%")
        _celda(ws, f, 6, f'=IF(C{f}=0,"—",SUMPRODUCT({cond}*ABS({rng(err_iaca)}))/C{f})', '0.00" pp"')
        _celda(ws, f, 7, f'=IF(C{f}=0,"—",COUNTIFS({rng("B")},A{f},{rng(signo)},"Sí")/C{f})', "0%")
    nota = 6 + len(resumen)
    ws.cell(nota, 1, "Error medio (abs.): en tn o m³. Error medio IACA: diferencia promedio, en puntos, entre la "
                     "variación del IACA estimada y la que da el dato real.").font = T_NOTA

    ws.cell(inicio - 1, 1, "Tabla 3. Detalle por mes").font = T_SECCION
    _cabecera(ws, inicio, ["Mes", "Serie", "Dato real", "Estimación modelo", "Error modelo", "Estimación X-13",
                           "Error X-13", "Var. IACA real", "Var. IACA modelo", "Var. IACA X-13",
                           "Error IACA modelo", "Error IACA X-13", "Signo modelo", "Signo X-13"])
    sino = lambda v: "" if v is None or pd.isna(v) else ("Sí" if v else "No")  # noqa: E731
    pc = lambda v: None if v is None or pd.isna(v) else v / 100                  # noqa: E731
    for i, r in enumerate(filas):
        f = p + i
        _celda(ws, f, 1, _mes_corto(r["mes"]))
        _celda(ws, f, 2, r["serie"])
        _celda(ws, f, 3, r["real"], F_ENTERO)
        _celda(ws, f, 4, r["modelo"], F_ENTERO)
        hay_real = r["real"] is not None and not pd.isna(r["real"])
        _celda(ws, f, 5, f"=D{f}-C{f}" if hay_real else None, F_ENTERO)
        _celda(ws, f, 6, r["x13"], F_ENTERO)
        _celda(ws, f, 7, f"=F{f}-C{f}" if hay_real and r["x13"] is not None else None, F_ENTERO)
        _celda(ws, f, 8, pc(r["var_real"]), F_PCT2)
        _celda(ws, f, 9, pc(r["var_modelo"]), F_PCT2)
        _celda(ws, f, 10, pc(r["var_x13"]), F_PCT2)
        hay_var = pc(r["var_real"]) is not None
        _celda(ws, f, 11, f"=(I{f}-H{f})*100" if hay_var and pc(r["var_modelo"]) is not None else None, F_PP)
        _celda(ws, f, 12, f"=(J{f}-H{f})*100" if hay_var and pc(r["var_x13"]) is not None else None, F_PP)
        _celda(ws, f, 13, sino(r["signo_modelo"]), derecha=True)
        _celda(ws, f, 14, sino(r["signo_x13"]), derecha=True)
    if not filas:
        ws.cell(p, 1, "Todavía no hay estimaciones registradas.").font = T_NOTA
    _anchos(ws, {"A": 16, "B": 16, **{get_column_letter(c): 13 for c in range(3, 15)}})
    ws.freeze_panes = ws.cell(inicio + 1, 3)
    _imprimir(ws)


def _hoja_serie(wb: Workbook, d: dict) -> None:
    ws = wb.create_sheet("Serie mensual")
    ws["A1"] = "Real y estimaciones a un mes"
    ws["A1"].font = T_TITULO
    ws["A2"] = "Cada estimación es lo que el modelo (o el X-13) habría dicho con los datos hasta el mes anterior."
    ws["A2"].font = T_SUB
    series = [s for s in d["series"] if s["id"] in ("biodiesel", "bioetanol_total")]
    meses = sorted({m for s in series for m in s["historia"]["modelo"]} | {d["mes"]})
    meses = [m for m in meses if m <= d["mes"]]
    cab = ["Mes"]
    for s in series:
        n = s["nombre"].replace("Bioetanol total", "Bioetanol")
        cab += [f"{n} real ({s['unidad']})", f"{n} modelo", f"{n} X-13"]
    _cabecera(ws, 4, cab)
    for i, m in enumerate(meses):
        f = 5 + i
        _celda(ws, f, 1, _mes_corto(m))
        for j, s in enumerate(series):
            h = s["historia"]
            es_mes = m == d["mes"]
            real = s["real"] if es_mes else h["real"].get(m)
            modelo = s["prediccion"] if es_mes else h["modelo"].get(m)
            x13 = s["x13"] if es_mes else h["x13"].get(m)
            _celda(ws, f, 2 + 3 * j, real, F_ENTERO)
            _celda(ws, f, 3 + 3 * j, modelo, F_ENTERO, negrita=es_mes, resaltar=es_mes)
            _celda(ws, f, 4 + 3 * j, x13, F_ENTERO)
    ult = 4 + len(meses)
    for j, s in enumerate(series):
        g = LineChart()
        g.title = f"{s['nombre']} ({s['unidad']})"
        g.y_axis.numFmt = "#,##0"
        g.y_axis.majorGridlines = None
        g.legend.position = "b"
        g.add_data(Reference(ws, min_col=2 + 3 * j, max_col=4 + 3 * j, min_row=4, max_row=ult), titles_from_data=True)
        g.set_categories(Reference(ws, min_col=1, min_row=5, max_row=ult))
        for serie, color, ancho, guion in zip(g.series, ("262626", AZUL, "B07A17"), (28000, 19000, 15000),
                                              (None, None, "dash")):
            serie.smooth = False
            serie.graphicalProperties = GraphicalProperties(ln=LineProperties(solidFill=color, w=ancho, prstDash=guion))
        g.height, g.width = 8, 22
        ws.add_chart(g, f"I{4 + 17 * j}")
    _anchos(ws, {"A": 10, **{get_column_letter(c): 15 for c in range(2, 8)}})
    ws.freeze_panes = "B5"
    _imprimir(ws)


def escribir(datos: dict, ruta: Path) -> Path:
    """Escribe el Excel de la corrida y devuelve su ruta."""
    wb = Workbook()
    _hoja_estimacion(wb, datos)
    _hoja_factores(wb, datos)
    _hoja_historial(wb, datos)
    _hoja_serie(wb, datos)
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    wb.save(ruta)
    return ruta
