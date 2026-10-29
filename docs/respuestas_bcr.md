# Respuestas de la BCR y decisiones de alcance (SCRUM-32 / SCRUM-46)

Este registro reúne las respuestas comunicadas por la Bolsa de Comercio de
Rosario (BCR) y su traducción al protocolo. **Es un resumen de las respuestas
ya registradas por el equipo**, no una transcripción literal de correos ni
una confirmación de puntos que todavía están abiertos. Las fuentes internas
de cada afirmación se indican abajo.

## Confirmaciones

| Origen | Respuesta registrada | Consecuencia para el proyecto |
|---|---|---|
| Correo de BCR del **9/10/2026**, registrado en SCRUM-26 | La Secretaría publica la producción con aproximadamente **dos meses de retraso**: al estimar el mes `t` a fines de `t+1`, BCR dispone de producción oficial hasta `t-1`. | El walk-forward entrena hasta `t-1`. La disponibilidad mensual de cada variable se documenta en [`disponibilidad_temporal.md`](disponibilidad_temporal.md). |
| Respuesta de BCR documentada en SCRUM-43 | Los **últimos doce meses** de la serie de producción se consideran **provisorios**; no se trata de una clasificación definitiva de cada observación. | El holdout de doce meses se reporta como provisorio y sus métricas pueden cambiar cuando se revisen los datos. |
| Archivos `.spc` proporcionados por BCR y validación de SCRUM-41 | BCR corre X-13 con cuatro configuraciones (biodiésel y bioetanol, en log y nivel). Selecciona la transformación según la menor dispersión de la variación logarítmica mensual de la tendencia-ciclo (D12). La réplica reproduce sus doce pronósticos del Excel. | Se preservan los `.spc` originales y el criterio implementado; [`x13_config_bcr.md`](x13_config_bcr.md) documenta las diferencias entre variantes. |
| Reunión del **20/10/2026** con BCR, registrada en SCRUM-32 y SCRUM-26 | BCR puede **esperar** la publicación de ventas de combustibles y molienda de soja (habitualmente días 25-27 de `t+1`); si una fuente no llega, usa una estimación propia. No hay un día de cierre rígido. | Esas variables pueden utilizar el mes `t` (rezago 0) si están disponibles. El backtest con el dato real revisado puede resultar optimista cuando BCR habría usado una estimación. |
| Reunión del **20/10/2026** con BCR, registrada en SCRUM-32 | Se necesita **un valor puntual**, no un rango como entregable principal; se prioriza poder **explicar por qué cambia la producción** sobre pequeñas diferencias de precisión o sobre la variación del IACA. | Se priorizan modelos interpretables, MAE como métrica principal y la explicación de contribuciones. La métrica del índice queda acotada en SCRUM-42; los intervalos de predicción son auxiliares. |
| Correo de BCR del **9/10/2026**, registrado en SCRUM-26 | Reconstruir las versiones históricas de los archivos de SharePoint es muy costoso y mezcla información confidencial. | Se documenta que el backtest usa las versiones actuales disponibles, no necesariamente las que existían en cada fecha de pronóstico. Se guardarán las descargas nuevas para evaluar revisiones futuras. |

## Qué se confirmó sobre log/nivel, y qué no

La **regla de selección** (menor dispersión de la variación logarítmica de D12)
y los archivos `.spc` sí están documentados. **No está confirmada la longitud
de la ventana** sobre la que BCR calcula esa dispersión. Utilizar los últimos
doce meses reproduce su elección observada (log para biodiésel, nivel para
bioetanol) y por eso `x13_bcr` usa esa variante. `x13_bcr_selcompleta`
conserva la alternativa basada en toda la serie. No presentar la ventana de
doce meses como si BCR la hubiera confirmado.

## Preguntas que siguen abiertas

- Sobre qué serie mide BCR el **acierto de signo**: producción original,
  desestacionalizada o índice.
- La ventana exacta del criterio log/nivel y las diferencias de inicio de
  entrenamiento entre `.spc` y otros modelos (detalladas en el protocolo).
- Respuestas específicas a otras consultas de SCRUM-32 que no quedaron
  confirmadas en la documentación disponible (por ejemplo, datos propios y
  eventos puntuales): no deben suponerse respondidas.

## Trazabilidad

- [SCRUM-26 – Disponibilidad temporal](https://aguformenti01.atlassian.net/browse/SCRUM-26) y [`disponibilidad_temporal.md`](disponibilidad_temporal.md).
- [SCRUM-32 – Revisión con BCR](https://aguformenti01.atlassian.net/browse/SCRUM-32).
- [SCRUM-41 – Configuración X-13](https://aguformenti01.atlassian.net/browse/SCRUM-41) y [`x13_config_bcr.md`](x13_config_bcr.md).
- [SCRUM-43 – Protocolo largo](https://aguformenti01.atlassian.net/browse/SCRUM-43) y [`protocolo_evaluacion.md`](protocolo_evaluacion.md).
- [SCRUM-42 – Error del IACA, alcance reducido](https://aguformenti01.atlassian.net/browse/SCRUM-42).

Las referencias a los correos provienen del registro realizado por el equipo
en Jira y en la documentación; para una cita textual, consultar el correo
original de BCR.
