"""Descarga el precio mensual del aceite de soja (World Bank, Pink Sheet).

Python 3.10+; solo biblioteca estándar (``certifi`` opcional, ver abajo). Baja
el Excel "Monthly Prices" del Commodity Markets del Banco Mundial, extrae la
columna de aceite de soja (USD por tonelada métrica) y escribe
``data/aceite_soja_mensual.csv`` con ``fecha,aceite_soja_usd_tn``.

El insumo es el margen doméstico del biodiésel (SCRUM-51): el aceite de soja
es el principal costo de producción, y cuando el precio regulado no lo cubre,
las plantas dejan de entregar al corte (lo que se vio en 2020).

La URL del archivo mensual del Banco Mundial cambia (lleva un hash y el mes en
la ruta). Si deja de responder, actualizar ``URL`` desde la página oficial
https://www.worldbank.org/en/research/commodity-markets (enlace "Monthly prices").

Verificación TLS: en algunas instalaciones de Python en Windows faltan los
certificados raíz y la descarga falla con CERTIFICATE_VERIFY_FAILED. El script
usa el bundle de ``certifi`` si está instalado (``pip install certifi``). Si no
hay red o certificados, bajar el xlsx a mano y usar ``--input``.

Uso:
    python descargar_aceite_soja.py --output data
    python descargar_aceite_soja.py --input CMO-Historical-Data-Monthly.xlsx
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
ETIQUETA = "soybean oil"  # encabezado de la columna buscada (case-insensitive)
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


def parse_aceite(data: bytes) -> dict[str, float]:
    """Extrae {YYYY-MM-01: precio_usd_tn} del Excel del Banco Mundial."""
    with zipfile.ZipFile(io.BytesIO(data)) as book:
        cadenas = _cadenas(book)
        hoja = ET.fromstring(book.read(_hoja_objetivo(book)))

        # Leer la grilla como lista de filas; cada fila es dict{col: texto}.
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

    # Columna del aceite de soja: buscar en las primeras filas de encabezado.
    col_aceite = None
    for fila in filas[:10]:
        for col, texto in fila.items():
            if isinstance(texto, str) and ETIQUETA in texto.strip().lower():
                col_aceite = col
                break
        if col_aceite is not None:
            break
    if col_aceite is None:
        raise ValueError(
            f"No se encontró la columna {ETIQUETA!r}; cambió el formato del Excel"
        )

    # Columna de fecha: la que tiene celdas tipo 'YYYYMnn'.
    serie = {}
    for fila in filas:
        for col, texto in fila.items():
            m = FECHA.match(str(texto).strip())
            if not m:
                continue
            valor = fila.get(col_aceite)
            if valor in (None, "", ".."):  # el Banco Mundial usa '..' para faltantes
                continue
            try:
                precio = float(valor)
            except (TypeError, ValueError):
                continue
            serie[f"{m.group(1)}-{m.group(2)}-01"] = precio
            break
    if len(serie) < 240:  # debería haber >60 años de datos mensuales
        raise ValueError(f"Serie demasiado corta ({len(serie)}); revisar el parseo")
    return serie


def main() -> None:
    """Descarga (o lee --input) y escribe data/aceite_soja_mensual.csv."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", default="data", help="carpeta de salida")
    ap.add_argument("--input", help="xlsx local (para reproducir sin red)")
    args = ap.parse_args()

    data = Path(args.input).read_bytes() if args.input else _descargar(URL)
    serie = parse_aceite(data)

    salida = Path(args.output)
    salida.mkdir(parents=True, exist_ok=True)
    destino = salida / "aceite_soja_mensual.csv"
    with destino.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["fecha", "aceite_soja_usd_tn"])
        for fecha in sorted(serie):
            w.writerow([fecha, serie[fecha]])
    print(f"Escrito {destino} ({len(serie)} meses, "
          f"{min(serie)}..{max(serie)})")


if __name__ == "__main__":
    main()
