"""Descarga precios mensuales del Banco Mundial (Pink Sheet): aceite de soja y azúcar.

Python 3.10+; solo biblioteca estándar (``certifi`` opcional, ver abajo). Baja
el Excel "Monthly Prices" del Commodity Markets del Banco Mundial una sola vez
y extrae dos columnas, cada una a su CSV (ver ``SERIES``):

- ``aceite_soja_mensual.csv`` con ``fecha,aceite_soja_usd_tn`` (columna
  "Soybean oil", USD por tonelada métrica). SCRUM-49.
- ``azucar_mensual.csv`` con ``fecha,azucar_usd_kg`` (columna "Sugar, world",
  USD por kilo). SCRUM-58.

Aceite de soja: es el insumo del margen doméstico del biodiésel (SCRUM-51). Es
el principal costo de producción, y cuando el precio regulado no lo cubre, las
plantas dejan de entregar al corte (lo que se vio en 2020).

Azúcar: los ingenios reparten la caña entre azúcar y alcohol según cuál les
paga más. Si el azúcar sube, conviene hacer más azúcar y sale menos bioetanol
de caña. La época de zafra (mayo a noviembre) ya la captura la estacionalidad;
el precio explica *cuánto* alcohol sale dentro de esa época.
Limitación: es el precio internacional (referencia mundial de azúcar crudo;
la definición exacta está en la hoja "Description" del mismo Excel). Los
ingenios argentinos venden sobre todo en el mercado interno, así que es una
aproximación a la rentabilidad que ven, no su precio real.

Cada CSV se escribe solo si su columna se pudo leer completa; si una falla,
el script termina con error y no pisa ningún archivo.

La URL del archivo mensual del Banco Mundial cambia (lleva un hash y el mes en
la ruta). Si deja de responder, actualizar ``URL`` desde la página oficial
https://www.worldbank.org/en/research/commodity-markets (enlace "Monthly prices").

Verificación TLS: en algunas instalaciones de Python en Windows faltan los
certificados raíz y la descarga falla con CERTIFICATE_VERIFY_FAILED. El script
usa el bundle de ``certifi`` si está instalado (``pip install certifi``). Si no
hay red o certificados, bajar el xlsx a mano y usar ``--input``.

Uso, desde la raíz del repo (escribe los dos CSV donde los lee db/fuentes.csv):
    python variables_externas/descargar_aceite_soja.py --output variables_externas/data
    python variables_externas/descargar_aceite_soja.py --input CMO-Historical-Data-Monthly.xlsx --output variables_externas/data
"""
import argparse
import csv
import io
import re
import ssl
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

URL = (
    "https://thedocs.worldbank.org/en/doc/"
    "74e8be41ceb20fa0da750cda2f6b9e4e-0050012026/related/"
    "CMO-Historical-Data-Monthly.xlsx"
)
HOJA = "Monthly Prices"
# Series a extraer: (encabezado de la columna en el Excel, en minúsculas;
# unidad que el Excel debe declarar para esa columna; CSV de salida; nombre de
# la columna en el CSV). El encabezado se busca sin distinguir mayúsculas.
SERIES = (
    ("soybean oil", "$/mt", "aceite_soja_mensual.csv", "aceite_soja_usd_tn"),
    ("sugar, world", "$/kg", "azucar_mensual.csv", "azucar_usd_kg"),
)
UNIDAD = re.compile(r"\(\s*(\$/\w+)\s*\)")  # p. ej. "($/kg)" en la fila de unidades
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
NS_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
FECHA = re.compile(r"^(\d{4})M(\d{2})$")  # formato del Banco Mundial: 1960M01


def _contexto_ssl() -> ssl.SSLContext:
    """Contexto TLS con el bundle de certifi si está (robusto en Windows)."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _descargar(url: str) -> bytes:
    """Descarga el xlsx (con User-Agent, el sitio rechaza el de urllib)."""
    pedido = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(pedido, timeout=120, context=_contexto_ssl()) as r:
        return r.read()


def _col(ref: str) -> int:
    """Letra(s) de celda (p. ej. 'AB12') -> índice de columna 0-based."""
    letras = re.match(r"[A-Z]+", ref).group()
    n = 0
    for c in letras:
        n = n * 26 + (ord(c) - ord("A") + 1)
    return n - 1


def _hoja_objetivo(book: zipfile.ZipFile) -> str:
    """Devuelve la ruta interna del worksheet llamado ``HOJA``."""
    wb = ET.fromstring(book.read("xl/workbook.xml"))
    rels = ET.fromstring(book.read("xl/_rels/workbook.xml.rels"))
    destino = {r.attrib["Id"]: r.attrib["Target"] for r in rels}
    for hoja in wb.find(NS + "sheets"):
        if hoja.attrib["name"].strip().lower() == HOJA.lower():
            objetivo = destino[hoja.attrib[NS_R + "id"]]
            if objetivo.startswith("/"):  # ruta absoluta dentro del zip
                return objetivo.lstrip("/")
            return objetivo if objetivo.startswith("xl/") else "xl/" + objetivo
    raise ValueError(f"No se encontró la hoja {HOJA!r}")


def _cadenas(book: zipfile.ZipFile) -> list[str]:
    """Tabla de cadenas compartidas (sharedStrings) del libro."""
    if "xl/sharedStrings.xml" not in book.namelist():
        return []
    raiz = ET.fromstring(book.read("xl/sharedStrings.xml"))
    return ["".join(t.text or "" for t in si.iter(NS + "t")) for si in raiz]


def _leer_filas(data: bytes) -> list[dict]:
    """Lee la hoja ``HOJA`` como lista de filas; cada fila es dict{col: texto}."""
    with zipfile.ZipFile(io.BytesIO(data)) as book:
        cadenas = _cadenas(book)
        hoja = ET.fromstring(book.read(_hoja_objetivo(book)))

    filas = []
    for fila in hoja.iter(NS + "row"):
        celdas = {}
        for c in fila.findall(NS + "c"):
            tipo = c.attrib.get("t")
            if tipo == "inlineStr":  # cadena embebida en la celda
                texto = "".join(t.text or "" for t in c.iter(NS + "t"))
                if texto:
                    celdas[_col(c.attrib["r"])] = texto
                continue
            v = c.find(NS + "v")
            if v is None or v.text is None:
                continue
            if tipo == "s":  # referencia a sharedStrings
                celdas[_col(c.attrib["r"])] = cadenas[int(v.text)]
            else:
                celdas[_col(c.attrib["r"])] = v.text
        if celdas:
            filas.append(celdas)
    return filas


def _columna(filas: list[dict], etiqueta: str, unidad: str) -> int:
    """Índice de la columna cuyo encabezado contiene ``etiqueta``.

    Busca en las primeras filas (encabezado). Si el Excel declara la unidad de
    esa columna (p. ej. "($/kg)"), verifica que sea la esperada: un cambio de
    unidad cambiaría la escala de toda la serie sin dar error.
    """
    encabezado = filas[:10]
    col = None
    for fila in encabezado:
        for c, texto in fila.items():
            if isinstance(texto, str) and etiqueta in texto.strip().lower():
                col = c
                break
        if col is not None:
            break
    if col is None:
        raise ValueError(
            f"No se encontró la columna {etiqueta!r}; cambió el formato del Excel"
        )
    for fila in encabezado:
        m = UNIDAD.search(str(fila.get(col, "")))
        if m and m.group(1).lower() != unidad:
            raise ValueError(
                f"La columna {etiqueta!r} viene en {m.group(1)}, se esperaba {unidad}"
            )
    return col


def _serie(filas: list[dict], col: int) -> dict[str, float]:
    """Extrae {YYYY-MM-01: valor} de la columna ``col``."""
    serie = {}
    for fila in filas:
        # Columna de fecha: la que tiene celdas tipo 'YYYYMnn'.
        for texto in fila.values():
            m = FECHA.match(str(texto).strip())
            if not m:
                continue
            valor = fila.get(col)
            if valor in (None, "", ".."):  # el Banco Mundial usa '..' para faltantes
                break
            try:
                serie[f"{m.group(1)}-{m.group(2)}-01"] = float(valor)
            except (TypeError, ValueError):
                pass
            break
    return serie


def parse_series(data: bytes) -> dict[str, dict[str, float]]:
    """Extrae cada serie de ``SERIES``: {columna_csv: {YYYY-MM-01: valor}}."""
    filas = _leer_filas(data)
    resultado = {}
    for etiqueta, unidad, _, nombre in SERIES:
        serie = _serie(filas, _columna(filas, etiqueta, unidad))
        if len(serie) < 240:  # debería haber >60 años de datos mensuales
            raise ValueError(
                f"{nombre}: serie demasiado corta ({len(serie)}); revisar el parseo"
            )
        resultado[nombre] = serie
    return resultado


def parse_aceite(data: bytes) -> dict[str, float]:
    """Compatibilidad con SCRUM-49: solo el aceite de soja."""
    return parse_series(data)["aceite_soja_usd_tn"]


def main() -> None:
    """Descarga (o lee --input) y escribe un CSV por cada serie de ``SERIES``."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", default="data", help="carpeta de salida")
    ap.add_argument("--input", help="xlsx local (para reproducir sin red)")
    args = ap.parse_args()

    data = Path(args.input).read_bytes() if args.input else _descargar(URL)
    series = parse_series(data)  # si alguna falla, no se escribe nada

    salida = Path(args.output)
    salida.mkdir(parents=True, exist_ok=True)
    for _, _, archivo, nombre in SERIES:
        serie = series[nombre]
        destino = salida / archivo
        with destino.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["fecha", nombre])
            for fecha in sorted(serie):
                w.writerow([fecha, serie[fecha]])
        print(f"Escrito {destino} ({len(serie)} meses, "
              f"{min(serie)}..{max(serie)})")


if __name__ == "__main__":
    main()
