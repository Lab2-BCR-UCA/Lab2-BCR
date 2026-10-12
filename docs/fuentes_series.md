# Series externas candidatas: fuentes, frecuencia y rango

Este documento describe las cuatro series externas que ya tenían scraper en el
repositorio: precios de soja y maíz, tipo de cambio y precios regulados de
biodiesel y bioetanol. Son **candidatas a variables explicativas** de la
producción de biocombustibles. Que estén acá no significa que vayan al modelo:
su utilidad predictiva se evalúa más adelante.

Las variables nuevas (molienda de soja, ventas de gasoil y nafta) están
documentadas en `variables_externas/README.md`.

Rangos verificados el **11 de octubre de 2026** sobre los CSV de `data/` de la
rama `datos-y-eda`. Los extremos pueden cambiar cuando se vuelvan a correr los
scripts.

## Series

| Serie | Archivo | Script | Fuente | Frecuencia original | Frecuencia en el CSV | Rango | Meses | Meses faltantes |
|---|---|---|---|---|---|---|---|---|
| Soja y maíz, precio de pizarra | `data/soja_maiz_cac_mensual.csv` | `scrape_cac_soja_maiz.py` | Cámara Arbitral de Cereales (BCR) | Diaria; la fuente informa el promedio mensual | Mensual | 2018-01 → 2026-09 | 105 | 0 |
| Tipo de cambio USD/ARS | `data/tipo_cambio_mensual.csv` | `scrape_tipo_cambio.py` | BCRA, API de Estadísticas Cambiarias | Diaria (días hábiles) | Mensual (promedio y cierre) | 2018-01 → 2026-09 | 105 | 0 |
| Precio regulado del biodiesel | `data/biodiesel_precios.csv` | `scrape_biocombustibles.py` | Secretaría de Energía | Por resolución de precio | Mensual | 2018-01 → 2026-09 | 77 | 28 |
| Precio regulado del bioetanol (caña y maíz) | `data/bioetanol_precios.csv` | `scrape_biocombustibles.py` | Secretaría de Energía | Por resolución de precio | Mensual | 2018-06 → 2026-09 | 59 | 41 |

## Columnas y unidades

| Archivo | Columna | Significado | Unidad |
|---|---|---|---|
| `soja_maiz_cac_mensual.csv` | `maiz_ars_tn` | Precio de pizarra del maíz, promedio del mes | ARS por tonelada |
| | `soja_ars_tn` | Precio de pizarra de la soja, promedio del mes | ARS por tonelada |
| `tipo_cambio_mensual.csv` | `tc_promedio_mes` | Promedio de la cotización diaria del dólar | ARS por USD |
| | `tc_cierre_mes` | Cotización del último día informado del mes | ARS por USD |
| `biodiesel_precios.csv` | `precio_ars_tn` | Precio regulado del biodiesel | ARS por tonelada |
| `bioetanol_precios.csv` | `precio_cana_ars_l` | Precio regulado del bioetanol de caña | ARS por litro |
| | `precio_maiz_ars_l` | Precio regulado del bioetanol de maíz | ARS por litro |

## Convenciones

- Todas las series son mensuales y tienen la columna `fecha` en el **primer día
  del mes** (por ejemplo `2026-09-01`). Se verificó que no hay fechas con otro
  día ni fechas duplicadas.
- El tipo de cambio se descarga diario y el script lo agrega a mensual.
- Los datos faltantes **no se reemplazan por cero**.

## Meses faltantes en los precios regulados

Biodiesel y bioetanol tienen meses sin dato. Los tramos son estos:

| Serie | Tramos sin dato |
|---|---|
| Biodiesel (28 meses) | 2020-01 a 2020-12; 2021-06 a 2021-08; 2022-10 y 2022-11; 2023-04 y 2023-05; 2023-07 a 2023-10; 2024-01; 2024-03 y 2024-04; 2024-07; 2026-03 |
| Bioetanol (41 meses) | 2020-01 a 2020-12; 2021-06 a 2021-08; 2021-10 a 2022-03; 2022-05; 2022-11 y 2022-12; 2023-02 a 2023-11; 2024-01; 2024-03 y 2024-04; 2024-07; 2025-01; 2026-03 y 2026-04 |

**Origen de los huecos.** Al correr el scraper actualizado se obtienen las mismas
filas que ya estaban en el CSV (más el mes en curso), así que el scraper no está
perdiendo meses que la página sí publica. Falta una comparación directa entre la
tabla de la página de la Secretaría y el CSV para confirmarlo.

**Hipótesis sin verificar.** Estos precios se fijan por resolución y rigen hasta
que cambia la resolución siguiente. Es posible que los meses sin fila sean
períodos sin cambio de precio. Si fuera así, arrastrar el último valor conocido
sería razonable, pero ese tratamiento todavía no está acordado.

**Decisión pendiente para el equipo:** cómo tratar estos meses antes de modelar
(dejarlos como faltantes, arrastrar el último valor u otro criterio). Hasta
decidirlo, los CSV conservan los meses faltantes como ausentes.

## Notas sobre el último mes

- El precio de soja y maíz y el tipo de cambio del mes en curso son parciales.
  Al volver a correr los scripts aparece una fila del mes actual calculada con
  los días transcurridos.
- Los CSV commiteados llegan hasta septiembre de 2026.
- Los scripts escriben los precios regulados con decimal (`15447.0` en lugar de
  `15447`). El valor es el mismo; solo cambia el formato.

## Cómo regenerar los datos

Desde la raíz del repositorio:

```bash
python scripts/scrape_cac_soja_maiz.py
python scripts/scrape_tipo_cambio.py
python scripts/scrape_biocombustibles.py
```

Cada script sobrescribe su CSV en `data/`. Requieren conexión a internet.
