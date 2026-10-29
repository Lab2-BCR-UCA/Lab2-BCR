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

El objetivo del proyecto es **estimar y explicar las variaciones** de la
producción, comparando modelos simples, estadísticos e interpretables. En la
reunión del 20/10 la BCR priorizó entender qué factores mueven la producción;
por eso se recomienda el modelo más explicable cuyo error no sea
significativamente peor que el mejor. El target es la
**producción mensual** (toneladas de biodiesel; m³ de bioetanol total, de maíz
y de caña), no el precio. Las respuestas registradas de la BCR están en
[`docs/respuestas_bcr.md`](docs/respuestas_bcr.md).

## Estructura del repositorio

```
BCR/
├── data/           # series mensuales en CSV (target + variables externas)
├── notebooks/      # análisis exploratorio y modelado
├── scripts/        # scrapers, protocolo de evaluación y modelos de referencia
├── results/        # métricas y salidas de los modelos
├── spc/            # configuración real del X-13 de la BCR (archivos .spc)
├── docs/           # documentación (protocolo de evaluación, features, fuentes)
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
python variables_externas/procesar_indec_biodiesel.py --hasta 2026-09   # exportaciones de biodiesel (INDEC); --hasta = último mes publicado
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

Los modelos se comparan con el **protocolo largo** (SCRUM-43): walk-forward
a un mes, **backtest de selección de sep-2021 a ago-2025 (48 meses)** y
**holdout final de sep-2025 a ago-2026 (12 meses)**. Las decisiones de
selección se toman solo con el backtest; el holdout se reserva para el final.
La métrica principal es **MAE** (tn o m³); MAPE, RMSE y acierto de signo se
informan como métricas complementarias. Ver
[`docs/protocolo_evaluacion.md`](docs/protocolo_evaluacion.md).

```bash
python scripts/protocolo_largo.py --sin-holdout   # referencias en backtest, sin usar holdout para elegir
python scripts/baselines.py        # baselines de la ventana corta; genera results/baselines.csv
python scripts/replica_x13.py      # réplica del X-13 de la BCR (~15 min; --procesos N para paralelizar)
python scripts/comparar_bcr_x13.py ruta/al/BIOCOMBUSTIBLES.xlsx   # validación contra su corrida real
python scripts/comparacion.py      # integra baselines.csv con x13.csv para la ventana corta
```

El **constructor común de features** (`scripts/construir_features.py`) ya está
implementado y se utiliza en el trabajo de SARIMAX. Los modelos pendientes
(elastic net y suma contable) deberán reutilizarlo y comprobar la
disponibilidad temporal de sus variables. Detalle, grupos de features y
descomposición contable del biodiésel en
`docs/features.md`.

La réplica del X-13 usa los **`.spc` reales de la BCR** (en `spc/`) tal cual:
biodiesel y bioetanol, en log y en nivel, y aplica su **criterio de selección**
(menor desvío de la variación log de la tendencia-ciclo). La BCR **no tiene un
modelo fijo**: el ARIMA lo elige `automdl` en cada corrida. Con datos a julio
2026 el pronóstico de agosto coincide con el de la BCR (0,0 %). Detalle,
tratamiento de outliers y pendientes en `docs/x13_config_bcr.md`.

## Resultados de referencia (backtest largo)

**MAE** sobre producción original (menor es mejor), septiembre 2021 a agosto
2025, 48 meses. Fuente: [`results/protocolo_metricas.csv`](results/protocolo_metricas.csv).
Los MAE de biodiésel están en **toneladas**; los de bioetanol, en **m³**.

| Serie | Naive (mes anterior) | Naive estacional | X-13 BCR | Mejor de estos tres |
|---|---:|---:|---:|---|
| Biodiésel | **23.673** | 58.671 | 28.264 | Naive |
| Bioetanol total | 8.167 | 12.489 | **7.289** | X-13 BCR |
| Bioetanol maíz | 5.631 | 9.381 | **5.092** | X-13 BCR |
| Bioetanol caña | 7.849 | 8.526 | **5.282** | X-13 BCR |

**Hallazgo principal:** en el backtest largo de biodiésel, el **naive supera
al X-13 de la BCR** (MAE 23.673 frente a 28.264 tn). En las tres series de
bioetanol, el X-13 BCR supera a los baselines simples. La evaluación corta
sep-2025 → ago-2026 es ahora el **holdout**, no la ventana para elegir el
modelo; sus resultados históricos siguen en `results/comparacion.csv`.

Se prioriza MAE porque el MAPE atribuye más peso a un mismo error absoluto
cuando la producción del mes es muy baja. **No se cambió cómo se calcula el
MAPE**; sigue reportándose como referencia. Para la selección final, se
comparará con Diebold-Mariano/intervalos de confianza y se preferirá el
modelo más interpretable sin pérdida significativa de precisión (SCRUM-34).

`results/baselines.csv` es el **único CSV canónico** de métricas de baselines
para la ventana corta: lo genera `scripts/baselines.py` y lo consumen
`scripts/comparacion.py` y `notebooks/replica_x13.ipynb`. El protocolo largo
mantiene su propio resumen por modelo **y ventana** en
`results/protocolo_metricas.csv` (no es un duplicado).

## Notebooks

- `notebooks/eda_produccion.ipynb` — análisis exploratorio del target, en dos
  partes: descriptiva con toda la muestra (calidad de datos, nivel, índice base
  2013, log y variación mensual) y de decisiones para el modelo solo con datos
  hasta agosto 2021 (outliers, estacionalidad STL, ACF/PACF, ADF y KPSS,
  transformación y quiebres), para las cuatro series.
- `notebooks/replica_x13.ipynb` — réplica del X-13 de la BCR con su config
  real, descomposición, validación contra su corrida y comparación contra los
  baselines de la ventana corta. La selección final usa el backtest largo.
- `notebooks/eda_variables_externas.ipynb` — EDA de variables candidatas,
  correlación cruzada y criterios de disponibilidad temporal (SCRUM-28 finalizada).

## Estado del proyecto

- [x] **Etapa 1** — Entendimiento del problema y del modelo actual de la BCR.
- [x] **Etapa 2** — Recolección principal: producción, INDEC (SCRUM-57),
  precio del azúcar (SCRUM-58) y corte obligatorio (SCRUM-48).
- [x] **EDA del target** — EDA de producción y correcciones completadas.
- [x] **EDA de variables externas (SCRUM-28)** — Finalizada: notebook,
  tabla de candidatas y comprobaciones de fechas del backtest.
- [x] **Referencias y evaluación** — Baselines, réplica X-13 BCR,
  protocolo largo y constructor común de features (SCRUM-59).
- [x] **SARIMAX (SCRUM-29 y SCRUM-62)** — Implementación inicial y
  agregado de variables exógenas pendientes finalizados.
- [ ] **Modelado interpretable y entrega** — Faltan integrar la suma contable
  (SCRUM-60) y elastic net (SCRUM-54), elegir el modelo final (SCRUM-34),
  y completar el pipeline, registro e informe.

Estado del backlog consultado el **29/10/2026**. Los datos y métricas
versionados no prueban por sí solos la finalización de los tickets pendientes.

## Equipo

- Chocobares, Juan Cruz
- Formenti, Agustín
- Morenico, Andrés
- Romero, María Florencia
- Ortíz, Victoria
