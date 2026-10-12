# Disponibilidad temporal de las variables (SCRUM-26)

Objetivo: no usar información que la BCR **no tendría** en el momento de
estimar. La tabla legible por código está en
[`data/disponibilidad_variables.csv`](../data/disponibilidad_variables.csv) y
es la que leen los notebooks para armar las features.

## Momento de estimación

- La BCR publica el IACA del mes `t` a **fines de `t+1`**. Ejemplo: el IACA de
  julio-2026 salió el **28/8/2026**.
- La estimación de biocombustibles se corre unos días antes de esa
  publicación. Tomamos como corte **≈ día 20–25 de `t+1`** (a confirmar con la
  BCR, ver abajo).
- La Secretaría de Energía publica la producción con **dos meses de rezago**
  (a principios de noviembre, septiembre). Al estimar `t`, el último dato de
  producción disponible es `t-1` (confirmado por la BCR, mail del 9/10). Esto
  coincide con el walk-forward del protocolo de evaluación.

**Regla:** una variable externa del mes `t` puede usarse sin rezago
(`rezago_min = 0`) si se publica antes del corte de estimación. Si no, se usa
desde `t-1` (`rezago_min = 1`).

Convención de rezago (la misma del EDA de variables externas): rezago `k`
significa usar `x[t-k]` para estimar `y[t]`.

## Tabla

| Variable | Fuente | Frecuencia | Publica el mes `t` | Días tras cierre | ¿Mismo mes? | Rezago mín. | Estado |
|---|---|---|---|---|---|---|---|
| Producción biodiesel / bioetanol (target) | Secretaría de Energía | Mensual | Principios de `t+2` | ~35 | No | **1** | Confirmado (mail BCR) |
| Tipo de cambio | BCRA | Diaria | Cierre de `t` | 0 | Sí | **0** | Confirmado |
| Precio pizarra soja / maíz | Cámara Arbitral (BCR) | Diaria | Cierre de `t` | 0 | Sí | **0** | Confirmado |
| Precio regulado biodiesel / bioetanol caña / maíz | Secretaría de Energía | Mensual (por resolución) | Antes o al inicio de `t` | ≤ 0 | Sí | **0** | Confirmado |
| Molienda de soja | SAGyP | Mensual | Dentro de `t+1` | ~20–25 | Sí | **0** | Evidencia indirecta |
| Ventas de gasoil / nafta | Secretaría de Energía (SESCO) | Mensual | Fines de `t+1` | ~25–27 | Ajustado | **1** | A confirmar con BCR |

### Evidencia por variable

- **Precios regulados:** se fijan por resolución para el mes. El IACA de
  julio-2026 ya cita los precios de julio (biodiesel 1.924.080 $/tn, bioetanol
  caña 1.043,6 $/l y maíz 956,5 $/l), iguales a los de `data/`.
- **Tipo de cambio y pizarra:** series diarias; el promedio mensual de `t`
  está completo al cierre de `t`, mucho antes del corte.
- **Molienda de soja:** el IACA de julio-2026 incluye la molienda de soja de
  julio como dato observado (solo biocombustibles aparece como estimación), así
  que la BCR la tiene al estimar. Además, la molienda de agosto-2025 ya estaba
  en prensa el 25/9/2025.
- **Ventas de combustibles:** la prensa publicó las ventas de julio-2026 el
  27/8/2026 y las de agosto-2026 el 25/9/2026. El IACA de julio salió el 28/8:
  el dato llega apenas 1–3 días antes de la publicación y probablemente
  **después** de que la BCR corre la estimación. Adoptamos `rezago_min = 1`
  por prudencia.

## Pendiente de confirmar con la BCR

1. **Día exacto en que corren la estimación** de biocombustibles para el IACA.
   Si es posterior a la publicación de ventas de la SE (~día 25–27), las ventas
   de gasoil y nafta pasan a `rezago_min = 0`.
2. Que la molienda que usan en el IACA es la de SAGyP.

Esto importa: en el EDA, la correlación de las ventas de nafta con bioetanol
de maíz y de caña es mucho mayor en rezago 0 (≈ 0,49–0,50) que en el mejor
rezago disponible con `rezago_min = 1` (≈ 0,27–0,30). Lo mismo con la
molienda de soja y el biodiesel (0,34 en rezago 0 contra 0,17 en rezago 4).

## Limitación: versiones de los datos

La BCR no puede reconstruir qué versión de cada dato tenía en cada fecha (mail
del 9/10: el historial de SharePoint mezcla información confidencial y
rehacerlo es muy costoso). Por lo tanto esta tabla controla **qué mes** de
cada variable se usa, pero no **qué versión**: el backtest usa los valores
actuales, que pueden incluir revisiones posteriores (por ejemplo, los
provisorios de la SE). El registro mensual de estimaciones que la BCR aprobó
servirá para medir esto hacia adelante.
