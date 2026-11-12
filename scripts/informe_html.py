"""Informe HTML de cada corrida del pipeline (SCRUM-64).

Un solo archivo, sin conexión a internet ni librerías externas: los datos van
embebidos como JSON y los gráficos se dibujan en el navegador con SVG. Se abre
con doble clic.

Estructura, como un informe técnico:
- Encabezado y un texto que resume qué se estima, cuánto cambia y por qué
  (armado con los datos de la corrida).
- Tabla 1: estimación de cada serie, variación de la producción y del IACA,
  y la réplica del X-13 de la BCR.
- Sección 1, por serie: de qué factores sale el cambio contra el mes anterior
  (SCRUM-35; al pasar el mouse, las variables de cada factor) y la historia del
  real contra el modelo final y el X-13 BCR.
- Sección 2: seguimiento de las estimaciones anteriores con su error (SCRUM-44).
- Notas.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

import pandas as pd

MESES_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
            "septiembre", "octubre", "noviembre", "diciembre"]
# Filas de la explicación que no son un factor: lo que el mes anterior se
# apartó de lo esperado y no se repite.
RESIDUOS = ("variación de stock del mes anterior", "ajuste del mes anterior")


def _mes_largo(p: pd.Period) -> str:
    return f"{MESES_ES[p.month - 1]} de {p.year}"


def _num(v):
    """float o None (JSON no admite NaN)."""
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


def _n(x: float, dec: int = 0) -> str:
    """Número con formato argentino."""
    s = f"{abs(x):,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("−" if x < 0 else "") + s


def _pct(x: float, dec: int = 1) -> str:
    return ("+" if x > 0 else "") + _n(x, dec) + " %"


def nombre_variable(v: str) -> str:
    """Nombre legible de una variable del elastic net."""
    faltante = v.startswith("missingindicator_")
    v = v.removeprefix("missingindicator_")
    if v.startswith("mes_"):
        texto = f"mes de {MESES_ES[int(v[4:]) - 1]}"
    elif v == "lag_1":
        texto = "producción del mes anterior"
    elif v == "lag_2":
        texto = "producción de hace 2 meses"
    elif v == "lag_12":
        texto = "mismo mes del año anterior"
    else:
        texto = v.replace("_", " ")
    return f"{texto} (dato faltante)" if faltante else texto


def _factores(t: pd.DataFrame) -> list[dict]:
    real_ant = t.attrs["real_anterior"]
    detalle = t.attrs.get("detalle_variables")
    salida = []
    for _, f in t[~t["factor"].isin(["total", "constante"])].iterrows():
        cambio = f["aporte_variacion_produccion_pp"] * real_ant / 100
        variables = []
        if detalle is not None:
            d = detalle[detalle["factor"] == f["factor"]]
            d = d[d["cambio"].abs() > 0.5]
            d = d.loc[d["cambio"].abs().sort_values(ascending=False).index]
            variables = [{"nombre": nombre_variable(r["variable"]), "cambio": _num(r["cambio"])}
                         for _, r in d.head(5).iterrows()]
        salida.append({"factor": f["factor"], "cambio": _num(cambio),
                       "pp": _num(f["aporte_variacion_produccion_pp"]),
                       "nota": f["nota"] or "", "variables": variables,
                       "residuo": f["factor"] in RESIDUOS})
    salida.sort(key=lambda x: -abs(x["cambio"] or 0))
    return salida


# ------------------------------------------------------------------ texto

# Cómo se nombra cada factor dentro de una oración.
EN_PROSA = {
    "exportaciones": "las exportaciones", "mercado interno": "el mercado interno",
    "otras ventas": "otras ventas", "inercia": "la inercia de los meses anteriores",
    "estacionalidad": "la estacionalidad", "estacionalidad (maíz)": "la estacionalidad del maíz",
    "estacionalidad (zafra)": "la zafra de caña", "márgenes": "los márgenes",
    "zafra/azúcar": "el precio del azúcar", "molienda de soja": "la molienda de soja",
}


def _lista(partes: list[str]) -> str:
    return partes[0] if len(partes) == 1 else ", ".join(partes[:-1]) + " y " + partes[-1]


def parrafo(s: dict, mes: pd.Period) -> str:
    """Texto de una serie: qué se estima, cuánto cambia, por qué y qué daría en el IACA."""
    u, anterior = s["unidad"], mes - 1
    var = s["var_produccion"]
    txt = (f"Para <b>{s['nombre'].lower()}</b> se estima una producción de <b>{_n(s['prediccion'])} {u}</b>, "
           f"{_n(abs(var), 1)} % {'más' if var > 0 else 'menos'} que en {MESES_ES[anterior.month - 1]} "
           f"({_n(s['real_anterior'])} {u}). ")
    factores = [f for f in s["factores"] if not f["residuo"] and abs(f["cambio"]) >= 0.5]
    principales = []
    if factores:
        mayor = max(abs(x["cambio"]) for x in factores)
        principales = [f for f in factores if abs(f["cambio"]) >= 0.15 * mayor][:2]
    if principales:
        txt += (f"La {'suba' if var > 0 else 'baja'} se explica principalmente por "
                + _lista([f"{EN_PROSA.get(f['factor'], f['factor'])} ({'+' if f['cambio'] > 0 else '−'}{_n(abs(f['cambio']))} {u})"
                          for f in principales]) + ". ")
    residuo = next((f for f in s["factores"] if f["residuo"]), None)
    if residuo and principales and abs(residuo["cambio"]) > abs(principales[0]["cambio"]):
        txt += (f"Pesa también que {MESES_ES[anterior.month - 1]} quedó "
                f"{'por debajo' if residuo['cambio'] > 0 else 'por encima'} de lo que el modelo esperaba "
                f"({_n(abs(residuo['cambio']))} {u}), algo que se supone que no se repite. ")
    if s["var_iaca"] is not None:
        txt += (f"Con esta estimación, la variación mensual del IACA sería de <b>{_pct(s['var_iaca'], 2)}</b>"
                + (f" (la réplica del X-13 de la BCR da {_pct(s['x13_var_iaca'], 2)})"
                   if s["x13_var_iaca"] is not None else "") + ".")
        if (s["var_iaca"] > 0) != (var > 0):
            txt += "<sup>1</sup>"
        txt += " "
    if s["real"] is not None:
        e = s["prediccion"] - s["real"]
        txt += (f"El dato publicado fue {_n(s['real'])} {u}: la estimación quedó "
                f"{_n(abs(e))} {u} {'por encima' if e > 0 else 'por debajo'} ({_pct(100 * e / s['real'])}).")
    return txt.strip()


def _metricas_seguimiento(seg: list[dict]) -> list[dict]:
    """Error medio absoluto por serie y modelo, en los meses con dato real."""
    df = pd.DataFrame(seg)
    if df.empty:
        return []
    df = df[df["real"].notna()]
    salida = []
    for (serie, modelo), g in df.groupby(["serie", "modelo"], sort=False):
        salida.append({"serie": serie, "modelo": modelo, "meses": len(g),
                       "mae": _num(g["error"].abs().mean()),
                       "mape": _num((g["error"].abs() / g["real"]).mean() * 100),
                       "mae_iaca": _num(g["error_iaca"].abs().mean()) if g["error_iaca"].notna().any() else None,
                       "signo": _num(g["signo"].mean() * 100) if g["signo"].notna().any() else None})
    return salida


# ------------------------------------------------------------------ armado

def armar_datos(mes: pd.Period, tablas: dict[str, pd.DataFrame], filas_registro: pd.DataFrame,
                seguimiento: pd.DataFrame, reales_series: dict[str, pd.Series],
                estimados_series: dict[str, pd.Series], x13_series: dict[str, pd.Series],
                nombres: dict[str, str], unidades: dict[str, str], ids_serie: dict[str, str],
                simulacion: bool = False, reales: dict[str, float] | None = None) -> dict:
    """Datos de la corrida que usan el informe HTML y el Excel (una sola fuente)."""
    series = []
    for serie, t in tablas.items():
        reg = filas_registro[filas_registro["serie_id"] == ids_serie[serie]].set_index("modelo")
        final = reg.loc["modelo_final"] if "modelo_final" in reg.index else None
        x13 = reg.loc["x13_bcr"] if "x13_bcr" in reg.index else None
        s = {
            "id": serie, "nombre": nombres[serie], "unidad": unidades[serie],
            "modelo": str(t["modelo"].iloc[0]),
            "prediccion": _num(t.attrs["prediccion"]),
            "real_anterior": _num(t.attrs["real_anterior"]),
            "var_produccion": _num(t.attrs["variacion_produccion_estimada_pct"]),
            "var_iaca": _num(final["variacion_pronosticada_pct"]) if final is not None else None,
            "x13": _num(x13["pronostico"]) if x13 is not None else None,
            "x13_var_iaca": _num(x13["variacion_pronosticada_pct"]) if x13 is not None else None,
            "real": _num(reales[serie]) if reales else None,
            "expo_estimada": bool(t.attrs["exportaciones_estimadas"]),
            "factores": _factores(t),
            "historia": {k: {str(m): _num(v) for m, v in ser.items()} for k, ser in
                         (("real", reales_series[serie]), ("modelo", estimados_series[serie]),
                          ("x13", x13_series.get(serie, pd.Series(dtype=float))))},
        }
        s["texto"] = parrafo(s, mes)
        detalle = t.attrs.get("detalle_variables")
        s["variables"] = [] if detalle is None else [
            {"factor": r["factor"], "nombre": nombre_variable(r["variable"]), "cambio": _num(r["cambio"])}
            for _, r in detalle[detalle["cambio"].abs() > 0.5].iterrows()]
        series.append(s)

    nombre_de_id = {v: nombres[k] for k, v in ids_serie.items()}
    etiqueta = {"modelo_final": "Modelo final", "x13_bcr": "X-13 BCR"}
    seg = [{
        "mes": str(f["mes_estimado"])[:7], "serie": nombre_de_id.get(f["serie_id"], f["serie_id"]),
        "modelo": etiqueta.get(f["modelo"], f["modelo"]),
        "estimacion": _num(f["pronostico"]), "real": _num(f["valor_real"]), "error": _num(f["error_produccion"]),
        "var_iaca": _num(f["variacion_pronosticada_pct"]), "var_iaca_real": _num(f["variacion_con_real_pct"]),
        "error_iaca": _num(f["error_variacion_pp"]), "signo": _num(f["acierto_signo"]),
    } for _, f in seguimiento.iterrows()]

    return {
        "mes": str(mes), "corrida": f"{datetime.now():%d/%m/%Y %H:%M}", "simulacion": simulacion,
        "series": series, "seguimiento": seg, "metricas": _metricas_seguimiento(seg),
        "aviso_expo": any(s["expo_estimada"] for s in series),
    }


def escribir(datos: dict, ruta: Path) -> Path:
    """Escribe el informe HTML y devuelve su ruta."""
    mes = pd.Period(datos["mes"], freq="M")
    json_datos = json.dumps(datos, ensure_ascii=False).replace("</", "<\\/")
    pagina = (PLANTILLA.replace("__TITULO__", f"Estimación de {_mes_largo(mes)}")
              .replace("__MES__", _mes_largo(mes)).replace("__ANTERIOR__", _mes_largo(mes - 1))
              .replace("__DATOS__", json_datos))
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(pagina, encoding="utf-8")
    return ruta


PLANTILLA = r"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITULO__</title>
<style>
:root{--papel:#ffffff;--fondo:#f5f4f0;--tinta:#1c1c1c;--gris:#5f6368;--claro:#8a8f95;--linea:#d8d6d0;--fina:#ebe9e4;
--real:#1c1c1c;--modelo:#1f4e79;--x13:#b07a17;--sube:#2f6b3a;--baja:#9c3524;--base:#8a8f95;--marca:#eef2f7}
@media (prefers-color-scheme:dark){:root{--papel:#17191c;--fondo:#0f1113;--tinta:#e8e6e1;--gris:#a5a9ae;--claro:#80858b;
--linea:#33363a;--fina:#25282b;--real:#e8e6e1;--modelo:#7fb0e0;--x13:#e0a640;--sube:#6cbd7c;--baja:#e5765f;--base:#80858b;--marca:#1d2733}}
*{box-sizing:border-box}
html{background:var(--fondo)}
body{margin:0;color:var(--tinta);font:15.5px/1.6 "Segoe UI",Arial,Helvetica,sans-serif;-webkit-font-smoothing:antialiased}
.hoja{max-width:1040px;margin:0 auto;background:var(--papel);padding:44px 56px 56px;border-left:1px solid var(--linea);border-right:1px solid var(--linea);min-height:100vh}
@media (max-width:700px){.hoja{padding:26px 16px 40px;border:0}}
h1,h2{font-family:Georgia,"Times New Roman",serif;font-weight:normal}
.volanta{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--gris);border-bottom:2px solid var(--tinta);padding-bottom:8px;
display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}
h1{font-size:34px;line-height:1.15;margin:22px 0 6px}
@media (max-width:700px){h1{font-size:27px}}
.bajada{font-family:Georgia,"Times New Roman",serif;font-size:19px;color:var(--gris);margin:0 0 14px}
.ficha{font-size:13px;color:var(--gris);border-top:1px solid var(--linea);border-bottom:1px solid var(--linea);padding:8px 0;display:flex;flex-wrap:wrap;gap:6px 24px}
.ficha b{color:var(--tinta);font-weight:600}
.nota-sim{margin:18px 0 0;font-size:13.5px;border-left:3px solid var(--x13);padding:4px 0 4px 12px;color:var(--gris)}
.resumen{margin:26px 0 8px}
.resumen p{margin:0 0 12px;max-width:74ch}
.resumen b{font-weight:600}
h2{font-size:23px;margin:46px 0 4px;padding-top:12px;border-top:1px solid var(--linea)}
h2 .num{color:var(--claro);margin-right:8px}
.intro{color:var(--gris);font-size:14px;margin:0 0 16px;max-width:74ch}
.rotulo{font-size:12.5px;color:var(--gris);margin:18px 0 6px}
.rotulo b{color:var(--tinta);font-weight:600}
table{border-collapse:collapse;width:100%;font-size:14px;font-variant-numeric:tabular-nums}
th{font-weight:600;font-size:12.5px;color:var(--gris);text-align:right;padding:6px 10px;border-bottom:1px solid var(--tinta);vertical-align:bottom;line-height:1.3}
td{padding:7px 10px;text-align:right;border-bottom:1px solid var(--fina);white-space:nowrap}
th.izq,td.izq{text-align:left}
tr.grupo td{border-bottom:1px solid var(--linea)}
tfoot td{border:0;font-size:12.5px;color:var(--gris);text-align:left;white-space:normal;padding-top:8px}
.sube{color:var(--sube)}.baja{color:var(--baja)}.tenue{color:var(--claro)}
.desplaza{overflow-x:auto}
.pestanas{display:flex;gap:22px;border-bottom:1px solid var(--linea);margin:8px 0 0;overflow-x:auto}
.pestanas button{all:unset;cursor:pointer;padding:8px 0;font-size:14.5px;color:var(--gris);border-bottom:2px solid transparent;margin-bottom:-1px;white-space:nowrap}
.pestanas button:hover{color:var(--tinta)}
.pestanas button:focus-visible{outline:2px solid var(--modelo);outline-offset:2px}
.pestanas button[aria-selected=true]{color:var(--tinta);border-color:var(--tinta);font-weight:600}
.dos{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.2fr);gap:36px}
@media (max-width:820px){.dos{grid-template-columns:1fr;gap:10px}}
.texto-serie{font-size:14.5px;margin:14px 0 0;max-width:80ch}
.zoom{display:inline-flex;gap:14px;font-size:12.5px;margin-left:10px;flex-wrap:wrap}
.zoom button{all:unset;cursor:pointer;color:var(--gris);border-bottom:1px solid transparent}
.zoom button:hover{color:var(--tinta)}
.zoom button[aria-pressed=true]{color:var(--tinta);border-bottom-color:var(--tinta)}
.zoom label{color:var(--gris);cursor:pointer;display:inline-flex;align-items:center;gap:4px}
.zoom input{margin:0;accent-color:var(--x13)}
svg{display:block;width:100%;overflow:visible}
svg text{font-family:"Segoe UI",Arial,sans-serif}
.ref{display:flex;gap:16px;flex-wrap:wrap;font-size:12.5px;color:var(--gris);margin-top:4px}
.ref span{display:inline-flex;align-items:center;gap:6px}
.ref svg{width:18px;height:10px;display:inline}
.fuente{font-size:12px;color:var(--claro);margin-top:6px}
#tip{position:fixed;pointer-events:none;z-index:10;background:var(--papel);color:var(--tinta);border:1px solid var(--tinta);font-size:12.5px;line-height:1.5;
padding:8px 10px;max-width:290px;opacity:0;transition:opacity .1s}
#tip.ver{opacity:1}
#tip .t{color:var(--gris)}#tip .r{display:flex;justify-content:space-between;gap:18px;font-variant-numeric:tabular-nums}
#tip .tit{font-weight:600;border-bottom:1px solid var(--linea);margin-bottom:4px;padding-bottom:3px}
.filtro{display:flex;align-items:center;gap:10px;font-size:13px;color:var(--gris);margin:18px 0 6px;flex-wrap:wrap}
.filtro b{color:var(--tinta);font-weight:600}
.filtro select{font:inherit;color:var(--tinta);background:var(--papel);border:1px solid var(--linea);padding:3px 6px}
#seg th{cursor:pointer;user-select:none}#seg th:hover{color:var(--tinta)}
.notas{font-size:13px;color:var(--gris);padding-left:18px;max-width:80ch}
.notas li{margin:0 0 6px}
footer{margin-top:40px;padding-top:10px;border-top:2px solid var(--tinta);font-size:12px;color:var(--gris);display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px}
.aparece{animation:aparece .35s ease-out both}@keyframes aparece{from{opacity:0}to{opacity:1}}
@media (prefers-reduced-motion:reduce){.aparece{animation:none}}
@media print{html{background:#fff}.hoja{border:0;padding:0}.zoom,.filtro select{display:none}}
</style></head>
<body><div class="hoja">
<div class="volanta"><span>Laboratorio de Consultoría de Datos 2 · UCA Rosario</span><span>Informe de estimación mensual</span></div>
<h1>Producción de biodiésel y bioetanol</h1>
<p class="bajada">Estimación de __MES__</p>
<div class="ficha" id="ficha"></div>
<div id="sim"></div>
<section class="resumen" id="resumen"></section>

<div class="rotulo"><b>Tabla 1.</b> Estimación del mes y variación que se publicaría en el IACA</div>
<div class="desplaza"><table id="t1"></table></div>

<h2><span class="num">1.</span>Qué explica cada estimación</h2>
<p class="intro">El cambio contra el mes anterior se reparte entre los factores del modelo, en toneladas o m³. Al pasar el mouse por una barra se ven las variables que forman cada factor; en la historia, el detalle de cada mes.</p>
<div class="pestanas" role="tablist" id="pestanas"></div>
<p class="texto-serie" id="texto-serie"></p>
<div class="dos">
  <div><div class="rotulo"><b>Figura 1.</b> Del real de __ANTERIOR__ a la estimación</div><div id="cascada"></div></div>
  <div><div class="rotulo"><b>Figura 2.</b> Real y estimaciones a un mes<span class="zoom" id="zoom"></span></div>
    <div id="historia"></div><div class="ref" id="ref"></div></div>
</div>

<h2><span class="num">2.</span>Seguimiento</h2>
<p class="intro" id="intro-seg"></p>
<div class="rotulo"><b>Tabla 2.</b> Error de las estimaciones anteriores</div>
<div class="desplaza"><table id="t2"></table></div>
<div class="filtro"><span><b>Tabla 3.</b> Detalle por mes</span>
  <select id="filtro" aria-label="Serie"></select><span id="cuenta"></span></div>
<div class="desplaza"><table id="seg"></table></div>

<h2><span class="num">3.</span>Notas</h2>
<ol class="notas">
<li>El IACA se calcula sobre la serie desestacionalizada y suavizada (X-13 con la configuración de la BCR, base 2013 = 100). Por eso una baja de la producción puede ser una suba del índice: alcanza con que la caída sea menor que la habitual para ese mes.</li>
<li>Variación de la producción: contra el dato real del mes anterior, sin desestacionalizar. Los puntos de cada factor son de esta variación, no de la del IACA.</li>
<li>"Variación de stock del mes anterior" (biodiésel) y "ajuste del mes anterior" (bioetanol) no son factores: es lo que el mes anterior se apartó de lo que el modelo esperaba y se supone que no se repite.</li>
<li>Modelos: suma contable para biodiésel (mercado interno, exportaciones y otras ventas) y elastic net para bioetanol de maíz y de caña; el total es su suma. Se reentrenan en cada corrida con los datos hasta el mes anterior. En la evaluación (septiembre de 2021 a septiembre de 2026) no le ganan al X-13 de forma significativa: su ventaja es que cada número se puede explicar.</li>
<li id="nota-expo" hidden>En los meses en que INDEC protege el dato de exportación de biodiésel por secreto estadístico, el modelo usa un estimado (la mediana de los meses ocultos anteriores).</li>
</ol>
<footer><span>Fuentes: Secretaría de Energía, INDEC, CAC, BCRA, SAGyP y Banco Mundial. Datos públicos.</span><span id="pie"></span></footer>
</div>
<div id="tip" role="tooltip"></div>
<script type="application/json" id="datos">__DATOS__</script>
<script>
(function(){
const D=JSON.parse(document.getElementById('datos').textContent);
const ML=['enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre'];
const MC=['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'];
const f0=new Intl.NumberFormat('es-AR',{maximumFractionDigits:0}),f1=new Intl.NumberFormat('es-AR',{minimumFractionDigits:1,maximumFractionDigits:1}),
 f2=new Intl.NumberFormat('es-AR',{minimumFractionDigits:2,maximumFractionDigits:2});
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const sg=(v,f)=>(v>0?'+':v<0?'−':'')+f.format(Math.abs(v));
const pct=(v,d=1)=>v==null?'—':sg(v,d===2?f2:f1)+' %';
const cls=v=>v==null?'':v>0?'sube':v<0?'baja':'';
const ml=m=>{const[a,b]=m.split('-');return ML[+b-1]+' '+a},mc=m=>{const[a,b]=m.split('-');return MC[+b-1]+' '+a.slice(2)};
const sumar=(m,k)=>{const[a,b]=m.split('-').map(Number);const t=a*12+b-1+k;return Math.floor(t/12)+'-'+String(t%12+1).padStart(2,'0')};
const NS='http://www.w3.org/2000/svg',sv=(t,a={})=>{const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);return e};
const tx=(g,x,y,s,a={})=>{const e=sv('text',Object.assign({x,y,'font-size':12,fill:css('--gris')},a));e.textContent=s;g.appendChild(e);return e};
const tip=document.getElementById('tip');
function ver(ev,h){tip.innerHTML=h;tip.classList.add('ver');const w=tip.offsetWidth,hh=tip.offsetHeight;let x=ev.clientX+14,y=ev.clientY+14;
 if(x+w>innerWidth-8)x=ev.clientX-w-14;if(y+hh>innerHeight-8)y=ev.clientY-hh-14;tip.style.left=x+'px';tip.style.top=y+'px'}
const ocultar=()=>tip.classList.remove('ver');
const fila=(a,b,c)=>'<div class="r"><span class="t">'+(c?'<span style="display:inline-block;width:10px;height:2px;background:'+c+';vertical-align:middle;margin-right:6px"></span>':'')+a+'</span><span>'+b+'</span></div>';
function ticks(lo,hi,n=4){const p0=(hi-lo)/n,m=Math.pow(10,Math.floor(Math.log10(p0))),p=[1,2,2.5,5,10].map(k=>k*m).find(s=>s>=p0);
 const t=[];for(let v=Math.floor(lo/p)*p;v<=Math.ceil(hi/p)*p+1e-9;v+=p)t.push(v);return t}
const abrev=v=>v>=1000?f0.format(v/1000)+' mil':f0.format(v);
const prev=sumar(D.mes,-1);

// ficha y resumen
document.getElementById('ficha').innerHTML='<span>Datos hasta <b>'+ml(prev)+'</b></span><span>Corrida <b>'+D.corrida+'</b></span>'+
 '<span>Modelo final: <b>suma contable</b> (biodiésel) y <b>elastic net</b> (bioetanol)</span>';
if(D.simulacion)document.getElementById('sim').innerHTML='<p class="nota-sim">Ejercicio sobre un mes ya publicado: se estima '+ml(D.mes)+
 ' con los datos que había hasta '+ml(prev)+' y se compara con el dato real que salió después.</p>';
const res=document.getElementById('resumen');
D.series.filter(s=>s.id==='biodiesel'||s.id==='bioetanol_total').forEach(s=>{const p=document.createElement('p');p.innerHTML=s.texto;res.appendChild(p)});
const mz=D.series.find(s=>s.id==='bioetanol_maiz'),cn=D.series.find(s=>s.id==='bioetanol_cana');
if(mz&&cn){const p=document.createElement('p');p.innerHTML='Por insumo, el bioetanol de maíz se estima en '+f0.format(mz.prediccion)+' m³ ('+pct(mz.var_produccion)+
 ') y el de caña en '+f0.format(cn.prediccion)+' m³ ('+pct(cn.var_produccion)+').';res.appendChild(p)}
document.getElementById('pie').textContent='Generado por scripts/salida_mensual.py';
document.getElementById('nota-expo').hidden=!D.aviso_expo;

// tabla 1
(function(){const sim=D.series.some(s=>s.real!=null);
 let h='<thead><tr><th class="izq">Serie</th><th>Estimación</th><th>'+ml(prev)+'<br>(real)</th><th>Var.<br>producción</th><th>Var.<br>IACA</th><th>X-13 BCR</th><th>Var. IACA<br>X-13</th>'+
  (sim?'<th>Real<br>publicado</th><th>Error</th>':'')+'</tr></thead><tbody>';
 D.series.forEach((s,i)=>{const e=s.real!=null?s.prediccion-s.real:null;
  h+='<tr'+(i===1?' class="grupo"':'')+'><td class="izq">'+s.nombre+(s.expo_estimada?'<sup>5</sup>':'')+' <span class="tenue">('+s.unidad+')</span></td><td><b>'+f0.format(s.prediccion)+'</b></td><td>'+f0.format(s.real_anterior)+
  '</td><td class="'+cls(s.var_produccion)+'">'+pct(s.var_produccion)+'</td><td class="'+cls(s.var_iaca)+'">'+pct(s.var_iaca,2)+'</td><td>'+(s.x13!=null?f0.format(s.x13):'—')+
  '</td><td>'+pct(s.x13_var_iaca,2)+'</td>'+(sim?'<td>'+(s.real!=null?f0.format(s.real):'—')+'</td><td>'+(e!=null?sg(e,f0)+' <span class="tenue">('+pct(100*e/s.real)+')</span>':'—')+'</td>':'')+'</tr>'});
 h+='</tbody><tfoot><tr><td colspan="9">Biodiésel en toneladas; bioetanol en m³. Solo biodiésel y bioetanol total entran al IACA. Variaciones contra el mes anterior (notas 1 y 2).</td></tr></tfoot>';
 document.getElementById('t1').innerHTML=h})();

// pestañas
let act=0,rango=24,conX13=true;
const pes=document.getElementById('pestanas');
D.series.forEach((s,i)=>{const b=document.createElement('button');b.setAttribute('role','tab');b.textContent=s.nombre;b.onclick=()=>elegir(i);pes.appendChild(b)});
const zoom=document.getElementById('zoom');
[[12,'12 m'],[24,'24 m'],[48,'48 m'],[0,'todo']].forEach(([n,t])=>{const b=document.createElement('button');b.textContent=t;b.dataset.n=n;b.onclick=()=>{rango=n;historia()};zoom.appendChild(b)});
const lb=document.createElement('label');lb.innerHTML='<input type="checkbox" checked> X-13';lb.querySelector('input').onchange=e=>{conX13=e.target.checked;historia()};zoom.appendChild(lb);
function elegir(i){act=i;[...pes.children].forEach((b,j)=>b.setAttribute('aria-selected',j===i));
 document.getElementById('texto-serie').innerHTML=D.series[i].texto;cascada();historia()}

// figura 1: cascada
function cascada(){const s=D.series[act],box=document.getElementById('cascada');box.innerHTML='';
 const fac=s.factores.filter(f=>Math.abs(f.cambio)>=0.5);
 const pasos=[{n:'Real de '+ML[+prev.split('-')[1]-1],a:0,b:s.real_anterior,c:'--base'}];let ac=s.real_anterior;
 fac.forEach(f=>{pasos.push({n:f.factor,a:ac,b:ac+f.cambio,c:f.cambio>0?'--sube':'--baja',f});ac+=f.cambio});
 pasos.push({n:'Estimación',a:0,b:s.prediccion,c:'--modelo'});
 if(s.real!=null)pasos.push({n:'Real publicado',a:0,b:s.real,c:'--real',hueco:true});
 const W=Math.max(300,box.clientWidth),iz=Math.min(200,W*.42),de=70,hb=17,sp=11,H=pasos.length*(hb+sp)+4;
 const lo=Math.max(0,Math.min(...pasos.flatMap(p=>p.f?[p.a,p.b]:[p.b]))*0.96),hi=Math.max(...pasos.flatMap(p=>[p.a,p.b]))*1.01;
 const x=v=>iz+(Math.max(v,lo)-lo)/(hi-lo)*(W-iz-de);
 const g=sv('svg',{viewBox:'0 0 '+W+' '+H,role:'img','aria-label':'Cascada de factores'});
 g.appendChild(sv('line',{x1:iz,x2:iz,y1:0,y2:H,stroke:css('--linea')}));
 pasos.forEach((p,i)=>{const y=i*(hb+sp)+2,x0=Math.min(x(p.a),x(p.b)),x1=Math.max(x(p.a),x(p.b)),res=p.f&&p.f.residuo;
  tx(g,iz-8,y+hb-4,p.n.length>34?p.n.slice(0,33)+'…':p.n,{'text-anchor':'end',fill:css(res?'--claro':'--tinta'),'font-size':12.5,'font-style':res?'italic':'normal'});
  const r=sv('rect',{x:x0,y,width:Math.max(x1-x0,1.5),height:hb,fill:p.hueco?css('--papel'):css(p.c),'fill-opacity':res?.12:1,stroke:p.hueco?css('--real'):res?css(p.c):'none',
   'stroke-width':1.2,'stroke-dasharray':res?'3 2':'',class:'aparece',style:'animation-delay:'+(i*35)+'ms'});
  g.appendChild(r);
  tx(g,x1+6,y+hb-4,p.f?sg(p.b-p.a,f0):f0.format(p.b),{fill:css(p.f?p.c:'--tinta'),'font-size':12,'font-weight':p.f?400:600});
  if(p.f)g.appendChild(sv('line',{x1:x(p.b),x2:x(p.b),y1:y+hb,y2:y+hb+sp,stroke:css('--claro'),'stroke-width':.8}));
  r.addEventListener('mousemove',ev=>{let h='<div class="tit">'+p.n+'</div>';
   if(p.f){h+=fila('Cambio',sg(p.f.cambio,f0)+' '+s.unidad)+fila('Puntos de var. de la producción',sg(p.f.pp,f1));
    if(res)h+='<div class="t" style="margin-top:4px">Lo que el mes anterior se apartó de lo esperado (nota 3).</div>';
    if(p.f.variables.length)h+='<div class="t" style="margin-top:4px">Variables que más lo mueven</div>'+p.f.variables.map(v=>fila(v.nombre,sg(v.cambio,f0))).join('');
    if(p.f.nota)h+='<div class="t" style="margin-top:4px">'+p.f.nota+'.</div>'}
   else h+=fila('Valor',f0.format(p.b)+' '+s.unidad);ver(ev,h)});
  r.addEventListener('mouseleave',ocultar)});
 box.appendChild(g);
 const nota=document.createElement('div');nota.className='fuente';nota.textContent='En '+s.unidad+'. Verde suma, rojo resta; punteado, lo que viene del mes anterior (nota 3).';box.appendChild(nota)}

// figura 2: historia
function historia(){[...zoom.querySelectorAll('button')].forEach(b=>b.setAttribute('aria-pressed',+b.dataset.n===rango));
 const s=D.series[act],box=document.getElementById('historia');box.innerHTML='';
 const fin=D.mes,primero=Object.keys(s.historia.modelo).sort()[0]||Object.keys(s.historia.real).sort()[0];
 const ini=rango?sumar(fin,-rango):primero;
 const meses=[];for(let m=ini;m<=fin;m=sumar(m,1))meses.push(m);
 const tomar=o=>Object.entries(o).filter(([m,v])=>v!=null&&m>=ini&&m<fin).sort();
 const R=tomar(s.historia.real),M=tomar(s.historia.modelo),X=conX13?tomar(s.historia.x13):[];
 const vals=[...R,...M,...X].map(p=>p[1]).concat([s.prediccion],s.real!=null?[s.real]:[],conX13&&s.x13?[s.x13]:[]);
 const W=Math.max(300,box.clientWidth),H=250,L=50,Rm=8,T=8,B=24,tk=ticks(Math.min(...vals),Math.max(...vals)),lo=tk[0],hi=tk[tk.length-1];
 const px=m=>L+meses.indexOf(m)/(meses.length-1)*(W-L-Rm),py=v=>T+(hi-v)/(hi-lo)*(H-T-B);
 const g=sv('svg',{viewBox:'0 0 '+W+' '+H,role:'img','aria-label':'Historia'});
 tk.forEach(v=>{g.appendChild(sv('line',{x1:L,x2:W-Rm,y1:py(v),y2:py(v),stroke:css('--fina')}));tx(g,L-6,py(v)+4,abrev(v),{'text-anchor':'end','font-size':11})});
 g.appendChild(sv('line',{x1:L,x2:W-Rm,y1:H-B,y2:H-B,stroke:css('--tinta'),'stroke-width':.8}));
 const paso=Math.max(1,Math.ceil(meses.length/7));meses.forEach((m,i)=>{if((meses.length-1-i)%paso)return;tx(g,px(m),H-6,mc(m),{'text-anchor':'middle','font-size':11})});
 const ancho=(W-L-Rm)/(meses.length-1);g.appendChild(sv('rect',{x:px(fin)-ancho/2,y:T,width:ancho,height:H-T-B,fill:css('--marca')}));
 const linea=(arr,col,w,dash)=>{if(arr.length<2)return;g.appendChild(sv('polyline',{points:arr.map(p=>px(p[0])+','+py(p[1])).join(' '),fill:'none',stroke:col,'stroke-width':w,'stroke-dasharray':dash||'','stroke-linejoin':'round',class:'aparece'}))};
 linea(X,css('--x13'),1.2,'4 3');linea(M,css('--modelo'),1.4);linea(R,css('--real'),2);
 const ult=R[R.length-1];
 if(ult)g.appendChild(sv('line',{x1:px(ult[0]),y1:py(ult[1]),x2:px(fin),y2:py(s.prediccion),stroke:css('--modelo'),'stroke-width':1.4,'stroke-dasharray':'2 2'}));
 if(conX13&&s.x13)g.appendChild(sv('rect',{x:px(fin)-3.5,y:py(s.x13)-3.5,width:7,height:7,fill:css('--x13')}));
 if(s.real!=null)g.appendChild(sv('circle',{cx:px(fin),cy:py(s.real),r:4.5,fill:css('--papel'),stroke:css('--real'),'stroke-width':1.6}));
 g.appendChild(sv('circle',{cx:px(fin),cy:py(s.prediccion),r:4.5,fill:css('--modelo')}));
 tx(g,px(fin)-9,py(s.prediccion)+(s.real!=null&&s.real<s.prediccion?-9:15),f0.format(s.prediccion),{'text-anchor':'end','font-size':11.5,fill:css('--modelo'),'font-weight':600,stroke:css('--papel'),'stroke-width':4,'paint-order':'stroke'});
 const guia=sv('line',{y1:T,y2:H-B,stroke:css('--claro'),'stroke-width':.8,opacity:0});g.appendChild(guia);
 const capa=sv('rect',{x:L,y:T,width:W-L-Rm,height:H-T-B,fill:'transparent'});g.appendChild(capa);
 const oR=Object.fromEntries(R),oM=Object.fromEntries(M),oX=Object.fromEntries(X);
 capa.addEventListener('mousemove',ev=>{const bb=g.getBoundingClientRect(),xx=(ev.clientX-bb.left)*W/bb.width;
  const m=meses[Math.max(0,Math.min(meses.length-1,Math.round((xx-L)/ancho)))];guia.setAttribute('x1',px(m));guia.setAttribute('x2',px(m));guia.setAttribute('opacity',1);
  let h='<div class="tit">'+ml(m)+'</div>';const u=' '+s.unidad;
  if(m===fin){h+=fila('Estimación',f0.format(s.prediccion)+u,css('--modelo'));if(conX13&&s.x13)h+=fila('X-13 BCR',f0.format(s.x13)+u,css('--x13'));if(s.real!=null)h+=fila('Real publicado',f0.format(s.real)+u,css('--real'))}
  else{if(oR[m]!=null)h+=fila('Real',f0.format(oR[m])+u,css('--real'));if(oM[m]!=null)h+=fila('Modelo final',f0.format(oM[m])+u,css('--modelo'));if(oX[m]!=null)h+=fila('X-13 BCR',f0.format(oX[m])+u,css('--x13'));
   if(oR[m]!=null&&oM[m]!=null)h+=fila('Error del modelo',sg(oM[m]-oR[m],f0)+' ('+pct(100*(oM[m]-oR[m])/oR[m])+')');
   if(oR[m]!=null&&oX[m]!=null)h+=fila('Error del X-13',sg(oX[m]-oR[m],f0)+' ('+pct(100*(oX[m]-oR[m])/oR[m])+')')}
  ver(ev,h)});
 capa.addEventListener('mouseleave',()=>{guia.setAttribute('opacity',0);ocultar()});
 box.appendChild(g);
 const sw=(c,d,w)=>'<svg viewBox="0 0 18 10"><line x1="0" x2="18" y1="5" y2="5" stroke="'+c+'" stroke-width="'+w+'" stroke-dasharray="'+(d||'')+'"/></svg>';
 document.getElementById('ref').innerHTML='<span>'+sw(css('--real'),'',2)+'Real</span><span>'+sw(css('--modelo'),'',1.4)+'Modelo final</span>'+
  (conX13?'<span>'+sw(css('--x13'),'4 3',1.2)+'X-13 BCR</span>':'')+'<span><svg viewBox="0 0 10 10" style="width:10px"><circle cx="5" cy="5" r="4" fill="'+css('--modelo')+'"/></svg>Estimación de '+MC[+fin.split('-')[1]-1]+'</span>'+
  (s.real!=null?'<span><svg viewBox="0 0 10 10" style="width:10px"><circle cx="5" cy="5" r="3.6" fill="none" stroke="'+css('--real')+'" stroke-width="1.4"/></svg>Real publicado</span>':'')}

// seguimiento
(function(){const met=D.metricas,box=document.getElementById('t2'),intro=document.getElementById('intro-seg');
 const meses=[...new Set(D.seguimiento.filter(r=>r.real!=null).map(r=>r.mes))].sort();
 if(!met.length){intro.textContent='Todavía no hay estimaciones con dato real publicado. A medida que se publiquen, el pipeline completa el real y el error de cada mes.';box.innerHTML='';return}
 intro.textContent=(D.simulacion?'Estimaciones que habría dejado el pipeline corriendo cada mes del período de prueba (':'Estimaciones registradas con dato real publicado (')+
  ml(meses[0])+' a '+ml(meses[meses.length-1])+', '+meses.length+' meses), cada una con los datos que había en su momento.';
 let h='<thead><tr><th class="izq">Serie</th><th class="izq">Modelo</th><th>Meses</th><th>Error medio<br>absoluto</th><th>Error medio<br>absoluto (%)</th><th>Error medio en la<br>var. IACA (pp)</th><th>Acierto de<br>dirección</th></tr></thead><tbody>';
 met.forEach((m,i)=>{const sigue=met[i+1]&&met[i+1].serie===m.serie;
  h+='<tr'+(sigue?'':' class="grupo"')+'><td class="izq">'+(i&&met[i-1].serie===m.serie?'':m.serie)+'</td><td class="izq">'+m.modelo+'</td><td>'+m.meses+'</td><td>'+f0.format(m.mae)+
  '</td><td>'+f1.format(m.mape)+' %</td><td>'+(m.mae_iaca!=null?f2.format(m.mae_iaca):'—')+'</td><td>'+(m.signo!=null?f0.format(m.signo)+' %':'—')+'</td></tr>'});
 box.innerHTML=h+'</tbody><tfoot><tr><td colspan="7">Error medio absoluto en toneladas (biodiésel) o m³ (bioetanol). Acierto de dirección: meses en que la variación del IACA estimada tuvo el mismo signo que la calculada con el dato real.</td></tr></tfoot>'})();
const sel=document.getElementById('filtro');['Todas',...new Set(D.seguimiento.map(r=>r.serie))].forEach(n=>{const o=document.createElement('option');o.textContent=n;sel.appendChild(o)});
const COLS=[['mes','Mes',1],['serie','Serie',1],['modelo','Modelo',1],['estimacion','Estimación'],['real','Real'],['error','Error'],['var_iaca','Var. IACA<br>estimada'],['var_iaca_real','Var. IACA<br>con el real'],['error_iaca','Error<br>(pp)']];
let ord={k:'mes',asc:false},todas=false;const LIM=16;
function seg(){const f=sel.value,todasFilas=D.seguimiento.filter(r=>f==='Todas'||r.serie===f).sort((a,b)=>{const x=a[ord.k],y=b[ord.k];if(x==null)return 1;if(y==null)return -1;
  const c=(x>y?1:x<y?-1:0)*(ord.asc?1:-1);return c||(a.serie>b.serie?1:-1)||(a.modelo>b.modelo?-1:1)});
 const rows=todas?todasFilas:todasFilas.slice(0,LIM);
 const cuenta=document.getElementById('cuenta');
 cuenta.innerHTML=(todasFilas.length>LIM?(todas?todasFilas.length+' filas · ':'Primeras '+LIM+' de '+todasFilas.length+' · ')+
  '<a href="#" id="mas" style="color:inherit">'+(todas?'mostrar menos':'mostrar todas')+'</a> · ':'')+'tocar una columna para ordenar';
 const mas=document.getElementById('mas');if(mas)mas.onclick=e=>{e.preventDefault();todas=!todas;seg()};
 const fm=(k,v)=>v==null?'—':k==='mes'?ml(v):typeof v!=='number'?v:k==='error'?sg(v,f0):k==='error_iaca'?sg(v,f2):k.startsWith('var')?pct(v,2):f0.format(v);
 document.getElementById('seg').innerHTML='<thead><tr>'+COLS.map(([k,t,i])=>'<th'+(i?' class="izq"':'')+' data-k="'+k+'">'+t+(ord.k===k?(ord.asc?' ↑':' ↓'):'')+'</th>').join('')+
  '</tr></thead><tbody>'+(rows.length?rows.map(r=>'<tr>'+COLS.map(([k,,i])=>'<td'+(i?' class="izq"':'')+'>'+fm(k,r[k])+'</td>').join('')+'</tr>').join(''):'<tr><td class="izq" colspan="9">Sin estimaciones.</td></tr>')+'</tbody>';
 document.querySelectorAll('#seg th').forEach(th=>th.onclick=()=>{const k=th.dataset.k;ord={k,asc:ord.k===k?!ord.asc:k!=='mes'};seg()})}
sel.onchange=seg;seg();

elegir(0);
let t;addEventListener('resize',()=>{clearTimeout(t);t=setTimeout(()=>{cascada();historia()},150)});
matchMedia('(prefers-color-scheme: dark)').addEventListener('change',()=>{cascada();historia()});
})();
</script></body></html>"""
