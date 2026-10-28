# Lab 2 · BCR — Predicción de producción de biocombustibles

Proyecto del **Laboratorio de Consultoría de Datos 2** (UCA Rosario) junto a la
**Bolsa de Comercio de Rosario (BCR)**.

## Contexto

La BCR publica mensualmente el **IACA** (Índice de Actividad de la Cadena
Agropecuaria). Una de sus componentes es la producción de biodiesel y
bioetanol, cuyo dato oficial lo informa la **Secretaría de Energía** con unos
dos meses de retraso. Para publicar a tiempo, la BCR **estima** ese dato con
**X-13ARIMA-SEATS**, el software estándar de ajuste estacional del Census de
EE. UU. (el mismo que usa el INDEC).

El objetivo del proyecto es **mejorar esa estimación aplicando modelos de
machine learning** a la predicción de series de tiempo. El target es la
**producción mensual** (toneladas de biodiesel; m³ de bioetanol total, de maíz
y de caña), no el precio.

## Estructura del repositorio

```
BCR/
├── data/           # series mensuales en CSV (target + variables externas)
├── notebooks/      # análisis exploratorio y modelado
├── scripts/        # scrapers, protocolo de evaluación y modelos de referencia
├── results/        # métricas y salidas de los modelos
├── spc/            # configuración real del X-13 de la BCR (archivos .spc)
├── docs/           # documentación (protocolo de evaluación)
└── README.md
```

## Fuentes de datos

Todo es dato **público y oficial**.

| Archivo | Contenido | Fuente | Rango |
|---|---|---|---|
| `produccion_biodiesel.csv` | Producción, ventas y exportaciones de biodiesel (tn) — **target** | Secretaría de Energía | 2008→ |
| `produccion_bioetanol.csv` | Producción y ventas de bioetanol total, maíz y caña (m³) — **target** | Secretaría de Energía | 2009→ |
| `soja_maiz_cac_mensual.csv` | Precio de pizarra de soja y maíz | Cámara Arbitral de Cereales (BCR) | 2018→ |
| `tipo_cambio_mensual.csv` | Tipo de cambio oficial USD/ARS | API del BCRA | 2018→ |
| `biodiesel_precios.csv` | Precio regulado del biodiesel | Secretaría de Energía | 2018→ |
| `bioetanol_precios.csv` | Precio regulado del bioetanol (caña y maíz) | Secretaría de Energía | 2018→ |
| `exportaciones_biodiesel_indec.csv` y `exportaciones_biodiesel_indec_tn.csv` | Exportaciones de biodiesel (NCM 38260000): si hubo, si el monto está oculto, toneladas y FOB. Llegan ~20 días después del mes, antes que la Secretaría | INDEC (comercio exterior) | 2012→ |

Los precios, el tipo de cambio y los granos son **variables externas
candidatas**; se decide cuáles entran al modelo en el análisis de variables
(Etapa 3/4).

## Requisitos

```bash
pip install pandas numpy openpyxl xlrd requests beautifulsoup4 matplotlib statsmodels jupyter x13binary
```

`x13binary` trae el motor del X-13; no hace falta instalar el programa del
Census ni el Win X-13.

## Cómo actualizar los datos

Cada script descarga su fuente y regenera el CSV correspondiente en `data/`.
Correr desde la carpeta raíz del proyecto:

```bash
python scripts/scrape_produccion_se.py     # producción (target)
python scripts/scrape_cac_soja_maiz.py     # soja y maíz
python scripts/scrape_tipo_cambio.py       # tipo de cambio
python scripts/scrape_biocombustibles.py   # precios regulados
python variables_externas/procesar_indec_biodiesel.py   # exportaciones de biodiesel (INDEC)
```

Las exportaciones de INDEC no se descargan solas: cada mes hay que bajar a
mano el CSV del año en curso del sistema de consulta de INDEC y reemplazarlo en
`variables_externas/data/indec_biodiesel/` antes de correr el procesador. El
paso a paso está en `docs/exportaciones_indec.md`.

`scrape_produccion_se.py` también acepta la ruta a un `.xlsx` local como
argumento, por si la descarga automática falla, y guarda una copia fechada de
cada descarga en `data/historico/` (para analizar revisiones de provisorios):

```bash
python scripts/scrape_produccion_se.py ruta/al/estadisticas_biocombustibles.xlsx
```

## Modelos de referencia

Todo se evalúa con el **mismo protocolo** (`scripts/evaluacion.py`):
walk-forward a un mes (el modelo se reentrena cada mes y predice el
siguiente), ventana de test **sep-2025 → ago-2026**, métricas MAE/RMSE/MAPE y
acierto de signo.

```bash
python scripts/baselines.py        # naive y naive estacional
python scripts/replica_x13.py      # réplica del X-13 de la BCR (~15 min; --procesos N para paralelizar)
python scripts/comparar_bcr_x13.py ruta/al/BIOCOMBUSTIBLES.xlsx   # validación contra su corrida real
python scripts/comparacion.py      # arma la tabla comparativa final
```

La réplica del X-13 usa los **`.spc` reales de la BCR** (en `spc/`) tal cual:
biodiesel y bioetanol, en log y en nivel, y aplica su **criterio de selección**
(menor desvío de la variación log de la tendencia-ciclo). La BCR **no tiene un
modelo fijo**: el ARIMA lo elige `automdl` en cada corrida. Con datos a julio
2026 el pronóstico de agosto coincide con el de la BCR (0,0 %). Detalle,
tratamiento de outliers y pendientes en `docs/x13_config_bcr.md`.

## Resultados (benchmark a superar)

MAPE (%) por serie y modelo, test sep-2025 → ago-2026 (`results/comparacion.csv`):

| Serie | naive | naive estacional | X-13 auto | X-13 BCR (log) | X-13 BCR (nivel) | X-13 BCR (criterio 12 m) | Mejor |
|---|---|---|---|---|---|---|---|
| biodiesel | 18,2 | **15,8** | 21,0 | 21,0 | 19,7 | 21,0 | naive estacional |
| bioetanol total | 10,3 | **5,0** | 7,5 | 9,7 | 7,5 | 7,5 | naive estacional |
| bioetanol maíz | 6,6 | 6,6 | 6,0 | 6,1 | 6,0 | **5,9** | X-13 BCR |
| bioetanol caña | 28,4 | 15,5 | 16,4 | 15,4 | 16,4 | **15,0** | X-13 BCR |

**Hallazgo central:** con su procedimiento real, el X-13 de la BCR es superado
por un *naive estacional* en biodiesel y bioetanol total, y en maíz y caña
gana por poco. Ajustar el X-13 (la elección log/nivel) mueve el MAPE 1-2
puntos; el margen grande está en cambiar de modelo (SARIMAX, ML, LSTM) y
sumar variables externas, que la BCR hoy no usa.

## Notebooks

- `notebooks/eda_produccion.ipynb` — análisis exploratorio del target, en dos
  partes: descriptiva con toda la muestra (calidad de datos, nivel, índice base
  2013, log y variación mensual) y de decisiones para el modelo solo con datos
  hasta agosto 2021 (outliers, estacionalidad STL, ACF/PACF, ADF y KPSS,
  transformación y quiebres), para las cuatro series.
- `notebooks/replica_x13.ipynb` — réplica del X-13 de la BCR con su config
  real, descomposición, validación contra su corrida y comparación contra los
  baselines.

## Estado del proyecto

- [x] **Etapa 1** — Entendimiento del problema y del modelo actual de la BCR.
- [x] **Etapa 2** — Recolección de datos (target + variables externas).
- [x] **Etapa 3** — Análisis exploratorio (EDA del target).
- [~] **Etapa 4** — Modelado: baselines, protocolo de evaluación y réplica del
  X-13 **hechos**. Pendientes: variables externas, SARIMAX, ML y LSTM.

## Equipo

- Chocobares, Juan Cruz
- Formenti, Agustín
- Morenico, Andrés
- Romero, María Florencia
- Ortíz, Victoria
