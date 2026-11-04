# Eventos y su uso en el entrenamiento (SCRUM-53)

Código: `scripts/eventos.py`. Tabla: `data/eventos.csv`. Pruebas:
`scripts/test_eventos.py`.

## La tabla

Un renglón por evento: `nombre`, `serie` (`biodiesel`, `bioetanol` o `todas`),
`inicio`, `fin`, `criterio` y `fuente`. Un evento sin `fin` está en curso.

| Evento | Serie | Desde | Hasta | Cómo se fijan las fechas |
|---|---|---|---|---|
| `cotab` | biodiésel | 16/6/2022 | 16/10/2022 | Por norma: DNU 330/2022 y prórrogas (Res. SE 636, 637 y 638/2022). |
| `regimen_2020_2021` | biodiésel | 1/8/2020 | 31/7/2021 | Inicio: primer mes con corte efectivo menor a 2% (agosto 2020, 1,2%; julio 2020 tenía 7,7%). Fin: último mes antes de la Ley 27.640 (vigencia 4/8/2021). |

Las fechas del régimen 2020-2021 salen de datos observables en el momento
(ventas al corte sobre ventas de gasoil) y de una norma, nunca de la producción.
El fin coincide con el corte de régimen "Ley 27.640" que ya usa el protocolo
para el error por subperíodo (`CORTES_REGIMEN` en `evaluacion.py`). No se toma
"mientras el efectivo siga bajo 2%" porque ese criterio corta el período en
pedazos (enero 2021 da 2,6%, mayo y junio 2021 vuelven a caer) y no marca un
régimen sino meses sueltos.

La BCR no informó eventos puntuales en la reunión (`docs/respuestas_bcr.md`:
quedan como pregunta abierta). Si los informa, se agregan como renglones nuevos
con su fuente.

No se cargó la pandemia (ASPO, abril y mayo 2020) para bioetanol: no lo pide
el ticket ni la BCR, y en biodiésel queda antes del régimen 2020-2021. Si se
quiere probar, es un renglón más con `serie = bioetanol`.

## Regla de uso: limpiar el entrenamiento

Los meses de un evento se **excluyen del ajuste** (o se les da menos peso con
`pesos_entrenamiento`). No se agregan columnas al modelo.

**Regla anti-leakage.** En cada iteración del walk-forward un evento se usa solo
si terminó antes del mes que se predice (`fin` < mes predicho, a nivel mensual).
Si sigue en curso, su fecha de fin todavía no se conoce: usarla sería leakage,
así que en esa iteración ese evento no excluye nada. Un mes cuenta como del
evento si el evento lo toca aunque sea un día.

Qué significa en las ventanas actuales:

- Régimen 2020-2021: termina en julio 2021 y el backtest arranca en septiembre
  2021, así que se excluye en todas las iteraciones (12 meses).
- COTAB: se excluye recién desde la predicción de noviembre 2022 (5 meses).
  Prediciendo junio a octubre 2022 el evento estaba en curso y esos meses
  quedan en el entrenamiento tal cual.

## Integración al protocolo

`evaluacion.evaluar_modelo` y `evaluar_ventanas` aceptan `excluir`, una función
`excluir(indice_entrenamiento, mes_predicho)` que devuelve un booleano por mes.
`eventos.excluir_eventos(serie)` arma esa función. La máscara se recalcula en
cada iteración, y el modelo la recibe como `fit(entrenamiento, excluir=mascara)`.

- Sin `excluir`, el protocolo no cambia: mismos resultados y mismas columnas.
- Con `excluir`, el detalle suma la columna `meses_excluidos`.
- Si el `fit` de un modelo no acepta `excluir`, la evaluación se frena en vez
  de ignorar la máscara en silencio.

Cada modelo decide cómo usar la máscara. El elastic net (SCRUM-54) la usa como
`sample_weight` en 0. En un SARIMAX lo natural es pasar esos meses como
faltantes (el filtro de Kalman los saltea); queda para quien mantenga ese
modelo.

## Por qué no se usan como predictores

Una dummy de evento solo puede ser predictor si se calcula con lo conocido en el
momento. Las fechas de la tabla no sirven (son leakage mientras el evento está
en curso), así que la versión válida sería una regla como "corte efectivo del mes
anterior menor a 2%". Con los datos actuales:

- Vale 1 en 12 meses de toda la historia y en solo **2 de los 48 meses del
  backtest** (abril 2022 y enero 2024). Un coeficiente estimado con tan pocos
  casos no es confiable y casi no se puede evaluar.
- Es función del corte efectivo, que ya entra al modelo: la demanda interna
  estimada es gasoil del mes por corte efectivo del mes anterior
  (`docs/features.md`). Correlación con el corte efectivo t-1: −0,61.

## Resultado empírico (SCRUM-54)

En el elastic net del biodiésel (`docs/elastic_net.md`, backtest de 48 meses):

| Variante | MAE (tn) |
|---|---|
| Excluyendo eventos (regla de este ticket) | 27.114 |
| Sin excluir | 24.407 |
| Sin excluir, con la dummy como predictor | 25.411 |

- **Excluir empeora**: sin excluir el MAE baja 2.708 tn (IC 95% −4.251 a −1.434,
  p 0,001). Los meses de 2020-2021 con corte casi nulo no enseñan una relación
  falsa: muestran que, cuando cae el corte, cae la producción. La demanda
  interna estimada (gasoil por corte efectivo t-1) ya captura esa caída, y
  sacarlos le quita al modelo la variación que identifica ese efecto (su
  coeficiente baja a menos de la mitad).
- **La dummy no suma**: contra el modelo sin excluir, el MAE sube 1.004 tn
  (IC +72 a +2.136, p 0,07).

Conclusión: para el elastic net del biodiésel conviene no excluir. Queda la
tabla y la función para los modelos donde sí sirvan. La decisión final por
modelo se toma en SCRUM-34.
