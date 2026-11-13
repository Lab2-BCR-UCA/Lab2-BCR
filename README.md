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
├── data/               # series mensuales en CSV (target + variables externas) y la base data/bcr.db (no versionada)
├── db/                 # esquema, fuentes y series de la base unificada
├── variables_externas/ # descarga de gasoil, nafta, molienda, aceite de soja, azúcar, INDEC y corte
├── notebooks/          # análisis exploratorio y modelado
├── scripts/            # scrapers, base, protocolo de evaluación, modelos y pruebas
├── results/            # métricas y salidas de los modelos
├── spc/                # configuración real del X-13 de la BCR (archivos .spc)
├── docs/               # documentación (protocolo, features, modelos, informe)
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
| `corte_tramos.csv` → `corte_nominal_mensual.csv` | Corte obligatorio nominal de biodiesel y bioetanol, por norma | Boletín Oficial (ver `docs/corte.md`) | — |
| `eventos.csv` | Eventos que se excluyen del entrenamiento | Elaboración propia (ver `docs/eventos.md`) | — |
| `variables_externas/data/` | Ventas de gasoil y nafta, molienda de soja, aceite de soja y azúcar | Secretaría de Energía, SAGyP, Banco Mundial | ver `variables_externas/README.md` |

Todas las series se cargan en la **base unificada** (`data/bcr.db`, SQLite),
que guarda cada versión descargada sin pisar la anterior y calcula las
variables derivadas (márgenes, corte efectivo). Detalle en `db/README.md`.

## Requisitos

```bash
pip install pandas numpy scipy scikit-learn openpyxl xlrd requests beautifulsoup4 matplotlib statsmodels jupyter x13binary
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
python variables_externas/descargar_variables.py --output variables_externas/data     # molienda de soja
python variables_externas/descargar_combustibles.py --output variables_externas/data  # ventas de gasoil y nafta
python variables_externas/descargar_aceite_soja.py   # aceite de soja y azúcar (Banco Mundial)
python variables_externas/armar_corte_nominal.py     # corte nominal mensual desde data/corte_tramos.csv
python scripts/build_db.py                           # arma la base data/bcr.db con todo lo anterior
```

**La base hay que armarla antes de correr cualquier modelo**: `data/bcr.db` no
está en el repo. Cada uno la genera en su máquina con `build_db.py` y todos
obtienen la misma, porque sale de las copias fechadas de `data/snapshots/`.

El corte nominal no se descarga: cuando sale una norma nueva hay que cargar el
tramo a mano en `data/corte_tramos.csv` (ver `docs/corte.md`).

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

## Modelos

Los modelos se comparan con el **protocolo largo** (SCRUM-43): walk-forward
a un mes, **backtest de selección de sep-2021 a ago-2025 (48 meses)** y
**holdout final de sep-2025 a sep-2026 (13 meses)**. Las decisiones de
selección se toman solo con el backtest; el holdout se reserva para el final.
La métrica principal es **MAE** (tn o m³); MAPE, RMSE y acierto de signo se
informan como métricas complementarias. Ver
[`docs/protocolo_evaluacion.md`](docs/protocolo_evaluacion.md).

Referencias:

```bash
python scripts/protocolo_largo.py --sin-holdout   # naive, naive estacional y X-13 BCR en el backtest
python scripts/protocolo_largo.py                 # lo mismo con el holdout
python scripts/replica_x13.py      # réplica del X-13 de la BCR (~15 min; --procesos N para paralelizar)
python scripts/comparar_bcr_x13.py ruta/al/BIOCOMBUSTIBLES.xlsx   # validación contra su corrida real
python scripts/baselines.py        # baselines de la ventana corta (histórico); results/baselines.csv
python scripts/comparacion.py      # integra baselines.csv con x13.csv para la ventana corta (histórico)
```

Modelos propios (todos usan el **constructor común de features**,
`scripts/construir_features.py`, ver `docs/features.md`):

| Modelo | Script | Documentación |
|---|---|---|
| Suma contable (biodiésel): mercado interno + exportaciones + otras ventas | `scripts/suma_contable.py` | `docs/suma_contable.md` |
| Elastic net con variables externas | `scripts/elastic_net.py` | `docs/elastic_net.md` |
| SARIMAX con variables exógenas | `scripts/sarimax.py` | docstring del script |

```bash
python scripts/suma_contable.py --con-holdout
python scripts/elastic_net.py --con-holdout
python scripts/sarimax.py --con-holdout
python scripts/comparacion_final.py      # compara todo y elige el modelo final (docs/comparacion_final.md)
python scripts/error_iaca.py --modelo-final modelo_final --predicciones-extra results/modelo_final_predicciones.csv   # error sobre la variación del IACA (docs/error_iaca.md)
python scripts/contribuciones.py suma_contable 2026-08   # qué factores explican la estimación de un mes (docs/contribuciones.md)
```

Sin `--con-holdout` los modelos corren solo el backtest. Las pruebas están en
`scripts/test_*.py` y `scripts/prueba_*.py`; cada una se corre sola, por ejemplo
`python scripts/test_suma_contable.py`.

**Reproducibilidad:** la suma contable y el elastic net dan lo mismo en Windows
y Linux. El X-13 cambia en meses puntuales entre Windows y Linux, y el SARIMAX
de bioetanol según la versión de statsmodels. Los `results/` versionados se
generaron en Linux; detalle en `docs/comparacion_final.md`, sección 8.

La réplica del X-13 usa los **`.spc` reales de la BCR** (en `spc/`) tal cual:
biodiesel y bioetanol, en log y en nivel, y aplica su **criterio de selección**
(menor desvío de la variación log de la tendencia-ciclo). La BCR **no tiene un
modelo fijo**: el ARIMA lo elige `automdl` en cada corrida. Con datos a julio
2026 el pronóstico de agosto coincide con el de la BCR (0,0 %). Detalle,
tratamiento de outliers y pendientes en `docs/x13_config_bcr.md`.

## Resultados

### Referencias (backtest largo)

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
MAPE**; sigue reportándose como referencia.

### Modelo final (SCRUM-34)

Regla: el modelo más interpretable cuyo error no sea significativamente peor
que el del mejor (Diebold-Mariano, p < 0,05), elegido solo con el backtest. El
holdout se corrió una vez para confirmar. MAE en tn (biodiésel) y m³
(bioetanol); fuente `results/comparacion_final_metricas.csv`.

| Serie | Modelo final | MAE backtest | X-13 BCR backtest | MAE holdout | X-13 BCR holdout |
|---|---|---:|---:|---:|---:|
| Biodiésel | suma contable | **21.947** | 28.264 | **11.896** | 17.360 |
| Bioetanol total | elastic net (maíz + caña) | **7.242** | 7.289 | 8.069 | **7.372** |
| Bioetanol maíz | elastic net | 5.449 | **5.092** | 5.155 | **3.812** |
| Bioetanol caña | elastic net | 5.661 | **5.282** | 4.610 | **4.289** |

**Ningún modelo final le gana al X-13 de la BCR de forma significativa.** En
biodiésel la suma contable tiene menos error en las dos ventanas, pero sin
significancia (p = 0,10 y 0,16). En bioetanol los errores son prácticamente
iguales. Lo que se gana es la explicación: cada estimación se descompone en
factores (`docs/contribuciones.md`). Lo mismo vale para el error sobre la
variación del IACA (`docs/comparacion_final.md`, sección 7).

`results/baselines.csv` es el **único CSV canónico** de métricas de baselines
para la ventana corta: lo genera `scripts/baselines.py` y lo consumen
`scripts/comparacion.py` y `notebooks/replica_x13.ipynb`. El protocolo largo
mantiene su propio resumen por modelo **y ventana** en
`results/protocolo_metricas.csv` (no es un duplicado).

## Estimación mensual (SCRUM-38)

Un comando descarga los datos, arma la base, estima el mes siguiente al último
dato con el modelo final, explica la estimación y la guarda en el registro
junto con sus contribuciones. Detalle en [`docs/pipeline.md`](docs/pipeline.md).

```bash
python scripts/pipeline.py                    # corrida mensual (desde el día 28)
python scripts/pipeline.py --simular 2026-09  # demo con un mes ya publicado (no toca el registro)
python scripts/test_pipeline.py               # pruebas (~2 min, corre X-13)
```

## Salida mensual para la BCR (SCRUM-64)

En Windows: doble clic en `instalar.bat` la primera vez y, cada mes desde el
día 28, doble clic en `correr_estimacion.bat`. Deja en `resultados/` el Excel
`IACA_biocombustibles_AAAA-MM.xlsx` y el informe `estimacion_AAAA-MM.html`
(se abre solo), ambos armados desde los mismos datos, una copia de respaldo
de la base y del registro, y el detalle de la corrida en
`resultados/ultima_corrida.log` (si algo falla, es lo que hay que mandarle al
equipo). Instalación, qué trae cada archivo, qué hacer si
falla y cómo restaurar un respaldo: [`docs/salida_mensual.md`](docs/salida_mensual.md).

```bash
python scripts/salida_mensual.py --simular 2026-09   # demo con un mes ya publicado (archivos SIMULACION_*; arma la base si falta)
python scripts/test_salida_mensual.py                # pruebas (~1 min)
```

## Registro de estimaciones (SCRUM-44)

Cada estimación mensual se guarda en `data/registro_estimaciones.csv` (solo se
agregan filas) junto con la variación del IACA que se publicaría. Cuando se
publica el dato real, se completan el real, el error en producción y el error
en la variación (métrica de SCRUM-42). Detalle en
[`docs/registro.md`](docs/registro.md).

```bash
python scripts/registro.py completar     # después de actualizar los datos
python scripts/registro.py registrar --serie biodiesel --mes 2026-10 --modelo modelo_final --pronostico 123456.7
python scripts/registro.py exportar      # results/registro_estimaciones.xlsx para la BCR
python scripts/test_registro.py          # pruebas rápidas
python scripts/prueba_registro_holdout.py   # simula el holdout y compara con SCRUM-42 (~6 min)
```

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
  precio del azúcar (SCRUM-58), corte obligatorio (SCRUM-48) y base
  unificada (SCRUM-27 y SCRUM-56). Septiembre 2026 sumado (SCRUM-63).
- [x] **EDA** — Producción (SCRUM-19 y SCRUM-45) y variables externas (SCRUM-28).
- [x] **Referencias y evaluación** — Baselines, réplica X-13 BCR, protocolo
  largo con holdout de 13 meses (SCRUM-43 y SCRUM-63) y constructor común de
  features (SCRUM-59).
- [x] **Modelos** — SARIMAX (SCRUM-29 y SCRUM-62), suma contable (SCRUM-60),
  eventos (SCRUM-53), elastic net (SCRUM-54) y aporte de las variables clave
  (SCRUM-31).
- [x] **Modelo final** — Comparación y elección (SCRUM-34) y error sobre la
  variación del IACA (SCRUM-42).
- [x] **Informe, parte 1** — Contexto y método (SCRUM-36), en `docs/informe/`.
- [x] **Explicación y registro** — Contribuciones (SCRUM-35) y registro de
  estimaciones (SCRUM-44).
- [ ] **Entrega** — Pipeline (SCRUM-38, probado en Windows), informe parte 2
  (SCRUM-61) y presentación final (SCRUM-37).

Estado del backlog consultado el **11/11/2026**. Los datos y métricas
versionados no prueban por sí solos la finalización de los tickets pendientes.

## Equipo

- Chocobares, Juan Cruz
- Formenti, Agustín
- Morenico, Andrés
- Romero, María Florencia
- Ortíz, Victoria
