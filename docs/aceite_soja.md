# Precio del aceite de soja (SCRUM-49)

Serie cruda `aceite_soja_usd_tn`: precio mensual del aceite de soja en USD por
tonelada métrica. Es el insumo del margen doméstico del biodiésel
(`margen_domestico_biodiesel`, SCRUM-51), porque el aceite es el principal
costo de las plantas.

Verificado el **29 de octubre de 2026**.

## Fuente elegida

| Campo | Valor |
|---|---|
| Fuente | Banco Mundial, Commodity Markets: Excel *CMO Historical Data Monthly* (Pink Sheet), hoja "Monthly Prices", columna "Soybean oil" |
| Referencia de precio | **Soybean oil (any origin), crude, f.o.b. ex-mill Netherlands**. Es aceite crudo puesto en fábrica en Países Bajos (mercado de Rotterdam), **no CBOT** |
| Agregación | Promedio mensual que publica el Banco Mundial (no se calcula nada) |
| Unidad | USD por tonelada métrica (`$/mt` en el Excel; el script verifica la unidad y falla si cambia) |
| Rango histórico | **enero 1960 → septiembre 2026**, 801 meses, sin faltantes. Desde 2018 (ventana del modelo): 105 meses, entre 1.963 USD/tn de máximo y una mediana de 1.079 USD/tn |
| Script | `variables_externas/descargar_aceite_soja.py` (el mismo baja el azúcar, SCRUM-58) |
| CSV | `variables_externas/data/aceite_soja_mensual.csv`, columnas `fecha,aceite_soja_usd_tn`, fecha en el primer día del mes |
| Copia versionada | `data/snapshots/aceite_soja/2026-10-27.csv` |

La descripción de la referencia está en la hoja "Description" del mismo
Excel; conviene revisarla si el Banco Mundial cambia la columna.

### Calendario de publicación y rezago

El Banco Mundial actualiza el Excel en los primeros días hábiles del mes
siguiente: la edición con el dato de septiembre 2026 salió el **2/10/2026**, la
de enero el 3/2/2026, y la página anuncia la próxima para el **3/11/2026**. O
sea que el dato de `t` está disponible hacia el día 2-4 de `t+1`, mucho antes
de que la Secretaría de Energía publique la producción de `t` (principios de
`t+2`). Por eso queda **confirmado con rezago 0** en
`data/disponibilidad_variables.csv`.

## Alternativa evaluada: FOB oficial de SAGyP

La Secretaría de Agricultura publica el **precio FOB oficial** del aceite de
soja crudo (posición NCM 1507.10, puertos argentinos). Es el precio de
referencia para liquidar los derechos de exportación y está más cerca del
precio que reciben las plantas argentinas que la cotización de Rotterdam.

Qué se verificó:

- Hay una API pública que devuelve JSON:
  `https://www.magyp.gob.ar/sitio/areas/ss_mercados_agropecuarios/ws/ssma/precios_fob.php?Fecha=dd/mm/aaaa`
  (SAGyP pide usar esta URL y no la de `monitorsiogranos` por problemas
  técnicos). Hay datos desde **1993**.
- Cada registro tiene `fecha`, `circular`, `posicion`, `precio` y un período
  de embarque (`mesDesde/añoDesde` a `mesHasta/añoHasta`). Un mismo día puede
  tener varios precios para distintos meses de embarque, y el aceite aparece
  en más de una posición arancelaria (por ejemplo `15071000100Q`, crudo, y
  `15079019100G`).
- No hay precio los sábados, domingos ni feriados.

Por qué **no** se usa como serie principal:

1. **Necesita una metodología propia.** No es una serie mensual: hay que
   elegir la posición (crudo), el embarque (el más cercano), tomar el último
   precio vigente de cada día y promediar por mes. Eso ya es una serie
   calculada, con decisiones que hay que justificar y testear.
2. **Las posiciones cambian en el tiempo.** Los códigos NCM se renumeraron
   varias veces desde 1993; armar la serie larga requiere mapear códigos.
3. **Acceso.** Desde el entorno donde se corrió el armado no se pudo llegar a
   la API de SAGyP, y la propia Secretaría avisa de problemas técnicos en uno
   de los endpoints. El Excel del Banco Mundial es un único archivo estable.
4. **Para el uso actual alcanza la referencia internacional.** El margen se
   usa como señal de cuándo el precio regulado deja de cubrir el aceite
   (2020). Rotterdam y el FOB argentino se mueven juntos; lo que difiere es
   el nivel (el descuento del aceite argentino varía con la cosecha y la
   logística).

**Decisión:** la base usa el Banco Mundial (`aceite_soja_usd_tn`). El FOB
oficial queda como complemento a sumar en otro ticket si el margen resulta
útil en el modelo; el `serie_id` propuesto es `aceite_soja_fob_arg_usd_tn`.

## Limitación para el margen doméstico

Ninguna de las dos series es exactamente el costo de una planta local. El
aceite que se vende en el mercado interno se paga, aproximadamente, al FOB
menos los derechos de exportación y los gastos de puerto. Como los derechos
de exportación del aceite cambiaron varias veces, el margen calculado con un
precio internacional sobreestima el costo en pesos en un nivel que no es
constante en el tiempo. Si el margen entra al modelo, conviene evaluar una
versión neta de derechos de exportación.

## Fuentes

- [Banco Mundial, Commodity Markets](https://www.worldbank.org/en/research/commodity-markets) (enlace "Monthly prices", fecha de la última y la próxima publicación)
- [Pink Sheet 2026, ediciones mensuales](https://thedocs.worldbank.org/en/doc/74e8be41ceb20fa0da750cda2f6b9e4e-0050012026/world-bank-commodities-price-data-the-pink-sheet)
- [YCharts, Soybean Oil Price (Any Origin)](https://ycharts.com/indicators/soybean_oil_price) (reproduce la descripción del Banco Mundial)
- [SAGyP, Precios FOB oficiales](https://www.magyp.gob.ar/sitio/areas/ss_mercados_agropecuarios/fob_oficiales/)
- [SAGyP, API de precios FOB](https://www.magyp.gob.ar/sitio/areas/ss_mercados_agropecuarios/fob_oficiales/_archivos/000021_Precios%20Fob%20Api.php)
