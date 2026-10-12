"""Descarga oficial reproducible; Python 3.10+, sin dependencias externas.

Uso: python descargar_variables.py --output data
Descarga molienda mensual de soja; ventas en descargar_combustibles.py.
"""
import argparse
import csv
import hashlib
import json
import re
import time
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path

SOJA = 'https://www.magyp.gob.ar/sitio/areas/ss_mercados_agropecuarios/areas/granos/_archivos/000058_Estad%C3%ADsticas/000032_Evolucion%20de%20la%20Molienda%20%28Cereales%20y%20Oleaginosas%29/000002_Evoluci%C3%B3n%20de%20la%20Molienda%20Mensual%20-%20Oleaginosas/000002_Evoluci%C3%B3n%20de%20la%20Molienda%20Mensual%20-%20Oleaginosas.php'
MESES = {m: i for i, m in enumerate('ENERO FEBRERO MARZO ABRIL MAYO JUNIO JULIO AGOSTO SEPTIEMBRE OCTUBRE NOVIEMBRE DICIEMBRE'.split(), 1)}
MESES['ENER0'] = 1  # Errata publicada en enero 2017 (cero en vez de O).


class Tablas(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.row = None
        self.cell = None
        self.table_id = 0
        self.row_tables = []

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            self.table_id += 1
        elif tag == 'tr':
            self.row = []
        elif tag in ('td', 'th') and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split()))
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row_tables.append(self.table_id)
            self.row = None


def parse_soja(data):
    parser = Tablas()
    parser.feed(data.decode('utf-8-sig'))
    # Verificar que soja es la primera columna de granos, no la de aceites.
    headers = [r for r in parser.rows if r and r[0].upper() in ('AÑO', 'ANO')]
    if not any(len(r) > 2 and r[1].upper() == 'SOJA' for r in headers):
        raise ValueError('Cambió el encabezado de la tabla de molienda')
    targets = [t for t, r in zip(parser.row_tables, parser.rows)
               if len(r) > 2 and r[0].upper() in ('AÑO', 'ANO') and r[1].upper() == 'SOJA']
    year = None
    active = False
    result = {}
    for table, row in zip(parser.row_tables, parser.rows):
        if table not in targets:
            continue
        if row and 'G R A N O S' in row[0]:
            active = True
        elif row and 'P E L L E T S' in row[0]:
            active = False
        if not active:
            continue
        if len(row) == 1 and re.fullmatch(r'(19|20)\d{2}', row[0]):
            year = int(row[0])
        elif year and row and row[0].upper() in MESES:
            if len(row) < 15:
                raise ValueError(f'Fila incompleta: {year} {row[0]}')
            value = row[1].strip()
            if value in ('', '-', '–'):
                continue  # No convertir ausencia en cero.
            if not re.fullmatch(r'\d+(?:\.\d{3})*(?:,\d+)?', value):
                raise ValueError(f'Valor no reconocido: {value}')
            date = f'{year:04d}-{MESES[row[0].upper()]:02d}-01'
            number = Decimal(value.replace('.', '').replace(',', '.'))
            if date in result:
                raise ValueError(f'Mes duplicado: {date}')
            result[date] = number
    if not result:
        raise ValueError('No se extrajeron datos de soja')
    return [(d, str(v)) for d, v in sorted(result.items())], ['fecha', 'molienda_soja_tn']


def download(url):
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'Lab2-BCR/1.0'})
            with urllib.request.urlopen(request, timeout=90) as response:
                return response.read()
        except (OSError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def main():
    arg = argparse.ArgumentParser(description=__doc__)
    arg.add_argument('--output', type=Path, default=Path('data'))
    arg.add_argument('--input', type=Path, help='Reprocesar archivo local sin descargar')
    args = arg.parse_args()
    url, parser, extension = SOJA, parse_soja, 'html'
    args.variable = 'soja'
    data = args.input.read_bytes() if args.input else download(url)
    rows, columns = parser(data)
    args.output.mkdir(parents=True, exist_ok=True)
    raw = args.output / f'{args.variable}_raw.{extension}'
    raw.write_bytes(data)
    output = args.output / f'{args.variable}_mensual.csv'
    with output.open('w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(rows)
    dates = [r[0] for r in rows]
    observed = {(int(d[:4]), int(d[5:7])) for d in dates}
    start, end = min(observed), max(observed)
    missing = []
    y, m = start
    while (y, m) <= end:
        if (y, m) not in observed:
            missing.append(f'{y:04d}-{m:02d}')
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    meta = {'variable': args.variable, 'fuente': url,
            'procesado_utc': datetime.now(timezone.utc).isoformat(),
            'modo': 'archivo_local' if args.input else 'descarga',
            'sha256_raw': hashlib.sha256(data).hexdigest(),
            'frecuencia': 'mensual', 'inicio': dates[0], 'fin': dates[-1],
            'filas': len(rows), 'meses_faltantes': missing,
            'advertencia': 'Verificar rezago de publicación y revisiones antes de modelar'}
    (args.output / f'{args.variable}_metadata.json').write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
