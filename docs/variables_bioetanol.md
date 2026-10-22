# Variables candidatas para bioetanol (SCRUM-52)

Las variables externas nuevas relevadas son casi todas de biodiesel; para
bioetanol, además del corte (SCRUM-48), hacían falta variables con mecanismo
económico. Este ticket releva y documenta esas variables, su fuente,
frecuencia, rango y rezago, y decide cuáles son viables.

Los rezagos salen de la tabla de disponibilidad
([`data/disponibilidad_variables.csv`](../data/disponibilidad_variables.csv),
SCRUM-26).

## Variables viables

| Variable | Mecanismo económico | Fuente | Frecuencia | Rango | Rezago | Estado |
|---|---|---|---|---|---|---|
| Precio regulado bioetanol de maíz | Precio de venta de la industria; determina rentabilidad | Secretaría de Energía (resolución) | Mensual | 2018-06 a 2026-09 | **0** | Ya en el repo (`data/bioetanol_precios.csv`) |
| Precio regulado bioetanol de caña | Ídem, para la fracción de caña | Secretaría de Energía (resolución) | Mensual | 2018-06 a 2026-09 | **0** | Ya en el repo (`data/bioetanol_precios.csv`) |
| Margen del bioetanol de maíz | Si el precio regulado no cubre el costo del maíz, cae el incentivo a producir | Derivada (precio regulado / pizarra de maíz) | Mensual | 2018-06 a 2026-09 | **0** | **Nuevo** (`scripts/margen_bioetanol.py` → `data/margen_bioetanol.csv`) |
| Ventas de nafta | Volumen sobre el que se aplica el corte de bioetanol | Secretaría de Energía (SESCO) | Mensual | ya relevada | **0** | Ya en el repo (`data/` combustibles) |

### Regla de huecos de los precios regulados

El precio regulado del bioetanol tiene **41 meses sin fila** entre 2018-06 y
2026-09 (59 filas en un span de 100 meses): solo cambia por resolución y sigue
vigente hasta la siguiente. El relleno (arrastrar el último valor vigente)
**no se hace en este script**: es una regla del **mecanismo de derivadas
(SCRUM-56)**, que se declara una vez en `db/series.csv` y el build la aplica a
todas las derivadas que usen esos precios. `margen_bioetanol.py` solo calcula
la fórmula sobre los insumos que recibe; cuando esté el 56, la fórmula pasa a
`scripts/derivadas.py` y se registra en `db/derivadas.csv` (sin tocar
`build_db.py`).

### Margen del bioetanol de maíz

Definido como cociente, análogo al margen del biodiesel (SCRUM-51):

```
margen_bioetanol_maiz = precio_regulado_maiz [$/l] / (precio_maiz_pizarra [$/tn] / rinde_l_por_tn)
```

- `rinde_l_por_tn` ≈ 400 l de etanol por tonelada de maíz (molienda seca,
  ~0,40 l/kg). Al ser una constante, **solo cambia la escala del cociente, no
  su poder predictivo**; sirve para interpretar: un valor menor a 1 indica que
  el precio regulado no cubre el costo del maíz.
- Al ser un cociente de valores en pesos del mismo mes, la inflación se
  cancela: no hace falta deflactar con IPC.
- **Limitación:** no incluye otros costos (enzimas, energía, mano de obra),
  así que un cociente apenas por encima de 1 puede ser margen negativo real.
- Resultado con datos a 2026-09, **sin relleno** (solo los meses con resolución
  vigente): 59 meses (2018-06 a 2026-09), margen medio 1,33, mínimo 0,98,
  máximo 1,65; 2 meses con margen < 1. Cuando el mecanismo de derivadas (56)
  aplique el relleno, la serie pasa a cubrir los 100 meses.

## Variable descartada

| Variable | Motivo del descarte |
|---|---|
| Costo de la caña / zafra (margen del bioetanol de caña) | La única fuente mensual relevada es IPAAT (SCRUM-25), disponible **solo como PDF mensual**, con alto costo de extracción. El bioetanol de caña es además la serie más chica y volátil. Por relación costo/beneficio se descarta por ahora; si se necesita, se reevalúa extrayendo los PDFs de IPAAT o buscando otra fuente de zafra/molienda de caña. |

## Limitación común: inicio en 2018

Los precios regulados del bioetanol (y por lo tanto el margen de maíz)
arrancan en **2018-06**, mientras que la producción de bioetanol va desde
2010-2013. Estas variables solo cubren el tramo reciente. No es un problema
para el backtest del protocolo (SCRUM-43), que empieza en septiembre 2021 y
queda íntegramente cubierto; sí hay que tenerlo en cuenta si se entrena sobre
la serie completa.

## Siguiente paso

La prueba de si estas variables mejoran el pronóstico se hace en el EDA
(SCRUM-28) y en el modelado (SARIMAX / elastic net), no en este ticket. Acá
solo se dejan relevadas, documentadas y en la base.
