# Explicación por contribuciones del modelo final (SCRUM-35)

Código: `scripts/contribuciones.py`. Pruebas: `scripts/test_contribuciones.py`.

Para cada mes estimado, la función `explicar(modelo, fecha)` devuelve qué
factores empujan la estimación, en toneladas o m³ y en puntos de variación contra
el mes anterior. Sirve para los modelos elegidos en SCRUM-34
(`docs/comparacion_final.md`): suma contable para biodiésel y elastic net para
bioetanol maíz, caña y total. También admite el elastic net de biodiésel
(`elastic_net_biodiesel_con_contables_sin_eventos`), aunque no quedó elegido.

    python scripts/contribuciones.py suma_contable 2026-08
    python scripts/contribuciones.py elastic_net_bioetanol_total 2025-06

    from contribuciones import explicar
    tabla = explicar("suma_contable", "2026-08")

## 1. Método

### Aportes en nivel

- **Suma contable.** La predicción es la suma de los destinos (`docs/suma_contable.md`),
  así que cada destino es un factor: mercado interno (demanda estimada para el
  corte), exportaciones y otras ventas. No hay constante.
- **Elastic net.** La predicción es lineal en las variables estandarizadas:

      predicción = constante + Σ_j  s_y · β_j · z_j

  donde `z_j` es la variable j estandarizada con la media y el desvío del
  entrenamiento, `β_j` su coeficiente, `s_y` el desvío del target y la constante
  es la media del target más `s_y` por el intercepto. Cada término es el aporte
  de una variable en m³. El indicador de faltante de una variable va con ella.
  En el total se suman los aportes de los modelos de maíz y caña.

Los aportes se agrupan en factores (`grupo_de`):

| Factor | Variables |
|---|---|
| estacionalidad (en caña: "estacionalidad (zafra)") | dummies de mes y `lag_12` (el mismo mes del año anterior) |
| inercia | `lag_1`, `lag_2` y el corte efectivo (que resume la mezcla reciente, SCRUM-31) |
| exportaciones | `expo_*` |
| mercado interno | ventas de gasoil y nafta, demanda interna estimada, otras ventas, corte nominal y cotab |
| márgenes | `margen_*` y precio del aceite de soja |
| zafra/azúcar | variables de azúcar |
| molienda de soja | `molienda*` |

Una variable que no está en la tabla hace frenar al script: así no se pierde
un aporte si se agrega una variable nueva al modelo.

### Puntos de variación

La variación estimada es contra el dato real del mes anterior:
`100 × (predicción − real(t−1)) / real(t−1)`. Se reparte así:

- **Suma contable.** Cada destino aporta su estimación de t menos su valor real
  de t−1 (ventas al corte, exportaciones de la Secretaría y otras ventas). La
  fila "variación de stock del mes anterior" es `−(real(t−1) − ventas(t−1))`:
  el modelo no predice stock, así que lo que el mes anterior se produjo de más
  (o de menos) que lo vendido no se repite. Otras ventas entran con un mes de
  rezago, así que su aporte a la variación es siempre 0.
- **Elastic net.** Cada factor aporta el cambio de su aporte entre t−1 y t, con
  el mismo modelo ajustado. La fila "ajuste del mes anterior" es
  `ajustado(t−1) − real(t−1)`: lo que el modelo no explicaba del mes anterior.

En los dos casos las filas suman exactamente la predicción (en nivel) y la
variación estimada (en puntos).

### Validación

El ajuste replica al del protocolo (`elastic_net.correr`: mismo inicio, misma
exclusión de eventos, mismos hiperparámetros). Las pruebas verifican, para los
cinco modelos en 2022-10, 2024-03 (backtest) y 2026-08 (holdout), que los
aportes suman la predicción guardada en `results/` y que los puntos suman la
variación estimada. También que todas las variables de los modelos tienen
factor y que otras ventas no mueven la variación.

## 2. Ejemplos

### Biodiésel, agosto de 2026: suben las exportaciones

Predicción 145.484 tn contra 101.097 tn reales de julio: **+43,9 %** estimado.
El dato real fue 146.604 tn (+45,0 %).

| Factor | Aporte (tn) | Puntos de variación |
|---|---:|---:|
| mercado interno | 67.890 | −5,0 |
| exportaciones | 76.176 | +61,5 |
| otras ventas | 1.418 | 0,0 |
| variación de stock del mes anterior | — | −12,6 |
| **total** | **145.484** | **+43,9** |

La suba se explica por exportaciones: pasan de 14.000 tn en julio a 76.176 tn
en agosto. El mercado interno resta un poco (demanda estimada 67.890 tn contra
72.945 tn de ventas al corte en julio) y en julio se produjo más de lo que se
vendió, algo que el modelo no repite.

### Biodiésel, noviembre de 2025: el modelo no ve la suba del corte

Predicción 60.156 tn contra 81.462 tn reales de octubre: **−26,2 %** estimado.
El dato real fue 65.351 tn (−19,8 %).

| Factor | Aporte (tn) | Puntos de variación |
|---|---:|---:|
| mercado interno | 28.515 | −1,4 |
| exportaciones | 31.500 | −35,0 |
| otras ventas | 141 | 0,0 |
| variación de stock del mes anterior | — | +10,2 |
| **total** | **60.156** | **−26,2** |

La caída de exportaciones (60.000 → 31.500 tn) se capta bien. Lo que el modelo
no ve es el mercado interno: el corte efectivo pasó de 2,81 % en octubre a
6,08 % en noviembre y las ventas al corte de 29.658 a 61.672 tn. La demanda
interna estimada usa la tasa de corte del mes anterior (`docs/features.md`), así
que no puede anticipar un cambio de corte en su primer mes. Es la principal
limitación de la suma contable: depende de que el corte no cambie de golpe.

### Bioetanol total, junio de 2025: empieza la zafra

Predicción 111.406 m³ contra 100.442 m³ reales de mayo: **+10,9 %** estimado.
El dato real fue 113.706 m³ (+13,2 %).

| Factor | Aporte (m³) | Puntos de variación |
|---|---:|---:|
| estacionalidad (maíz) | 3.560 | −0,1 |
| mercado interno | 2.950 | −1,6 |
| márgenes | 947 | 0,0 |
| inercia | 12.192 | +5,1 |
| estacionalidad (zafra) | 12.650 | +12,1 |
| zafra/azúcar | −79 | +0,2 |
| constante | 79.185 | 0,0 |
| ajuste del mes anterior | — | −4,7 |
| **total** | **111.406** | **+10,9** |

El factor principal es la zafra: la caña pasó de 31.776 m³ en mayo a 55.713 m³
en junio, mientras el maíz bajó de 68.666 a 57.993 m³. El modelo capta el
arranque de la zafra por la estacionalidad de caña.

## 3. Limitaciones

- **Puntos de variación en el elastic net.** Cuando el mes anterior fue atípico,
  la fila "ajuste del mes anterior" domina y los demás factores se leen mal.
  Ejemplo: caña en mayo de 2026 da +65,7 % estimado, con +114,4 puntos de
  ajuste del mes anterior y −66,7 de inercia. En esos casos conviene leer la
  descomposición en nivel (toneladas o m³), no la de puntos.
- **Aportes contra la media.** En el elastic net cada aporte es relativo a la
  media del entrenamiento: un aporte negativo significa "por debajo de lo
  normal", no que la variable reste producción en términos absolutos.
- **No es causalidad.** Las variables están correlacionadas entre sí (por
  ejemplo, los rezagos y la estacionalidad) y el elastic net reparte el efecto
  entre ellas. Los aportes describen cómo llega el modelo a su número.
- **Integración.** La función todavía no está en el flujo de entrega ni guarda
  un registro mensual: eso queda para los tickets de pipeline y de registro.
