# Variables externas para la producción de biocombustibles

En este proyecto buscamos predecir la producción de biodiésel y bioetanol. Llamamos **variables externas** a los datos distintos de la producción que queremos pronosticar y que podrían ayudar a explicar sus cambios. Son externas a la serie objetivo, aunque provengan del mismo organismo que publica esa serie.

La molienda de soja puede aportar información sobre los insumos para elaborar biodiésel, mientras que las ventas de gasoil y nafta pueden relacionarse con la demanda de biocombustibles por su utilización en mezclas. Estas relaciones son hipótesis: su utilidad predictiva se evaluará posteriormente.

Esta tarea releva fuentes, documenta su frecuencia y cobertura histórica, implementa la descarga de las variables viables y justifica los descartes. No incorpora todavía variables a los modelos.

Relevamiento y ejecución verificados el **9 de octubre de 2026**. Los extremos del histórico reflejan los archivos consultados; pueden cambiar cuando se actualicen las fuentes.

## Fuentes y decisiones

| Variable | Fuente oficial | Frecuencia | Histórico comprobado | Unidad | Decisión |
|---|---|---|---|---|---|
| Ventas de gasoil, grados 1 a 3 | Secretaría de Energía, SESCO Downstream | Mensual | Enero 2010–agosto 2026; 200 meses sin faltantes | m³ | Viable |
| Ventas de nafta, grados 1 a 3 | Secretaría de Energía, SESCO Downstream | Mensual | Enero 2010–agosto 2026; 200 meses sin faltantes | m³ | Viable |
| Molienda de soja | SAGyP, Mercados Agropecuarios | Mensual | Enero 2015–agosto 2026; 140 meses sin faltantes | Toneladas | Viable, con discrepancias en totales anuales publicadas |
| Caña bruta molida | IPAAT | Quincenal durante zafra, con informes acumulados y anuales | Campañas publicadas 2013–2026; no se acreditó una serie mensual continua | Toneladas | Descartada para este sprint |

### Ventas de gasoil y nafta

[Página oficial de Energía](https://www.argentina.gob.ar/economia/energia/hidrocarburos/refinacion-y-comercializacion-de-petroleo-gas-y-derivados-tablas-dinamicas).

Recursos utilizados:

- [Ventas 2010–2019](http://www.energia.gob.ar/contenidos/archivos/Reorganizacion/informacion_del_mercado/mercado_hidrocarburos/tablas_dinamicas/dowstream/individuales/TD_ventas_mercado_2010_2019.zip).
- [Ventas actuales](http://www.energia.gob.ar/contenidos/archivos/Reorganizacion/informacion_del_mercado/mercado_hidrocarburos/tablas_dinamicas/dowstream/individuales/TD_ventas_mercado.zip).

Los ZIP contienen XLSX con tablas dinámicas. La hoja visible muestra un mes seleccionado; el historial completo se extrae de la caché de datos incluida en el XLSX. El script funciona sin instalar ni abrir Excel.

Se suman empresas, provincias y sectores informados, excluyendo bunker de cabotaje e internacional. La fuente ya excluye ventas a empresas del sector. Se conservan las seis series por grado y se calculan los totales de gasoil y nafta grados 1–3. No se incluyen otras categorías como «Otros Tipos de Gasoil». Estas sumas no equivalen directamente al volumen sujeto al corte obligatorio.

El script verifica estructura, unidades, dimensiones duplicadas y cantidad de registros de la caché; rechaza superposición entre los dos históricos. Conserva los ajustes negativos publicados y registra su cantidad, sin asumir su causa. En la ejecución verificada hubo dos registros negativos seleccionados en el histórico y ninguno en el archivo actual.

Los enlaces HTTPS de los ZIP fallaron con HTTP 502 durante el relevamiento; funcionaron los enlaces HTTP oficiales. Los hashes registrados identifican los archivos descargados, pero no autentican una transferencia HTTP. La extracción requiere que los XLSX sigan incluyendo la caché con el esquema esperado.

Se procesaron 4.971.431 registros del archivo histórico y 1.428.087 del actual. Se contrastaron los grados 2 y 3 de julio 2026 con los totales de la hoja visible: las diferencias de gasoil correspondieron al bunker excluido (32.257,64 m³ y 3.492,05 m³); las naftas coincidieron dentro de 0,000001 m³. El CSV conserva la precisión numérica de la caché.

Se descartó como fuente principal el CSV alternativo `ventas-mercado-producto-provincia.csv`, porque la descarga consultada llegaba solamente a marzo de 2019.

### Molienda de soja

[Tabla mensual oficial de SAGyP](https://www.magyp.gob.ar/sitio/areas/ss_mercados_agropecuarios/areas/granos/_archivos/000058_Estad%C3%ADsticas/000032_Evolucion%20de%20la%20Molienda%20%28Cereales%20y%20Oleaginosas%29/000002_Evoluci%C3%B3n%20de%20la%20Molienda%20Mensual%20-%20Oleaginosas/000002_Evoluci%C3%B3n%20de%20la%20Molienda%20Mensual%20-%20Oleaginosas.php).

El script extrae la columna SOJA del bloque GRANOS OLEAGINOSOS. No toma las columnas de aceite, pellets o expellers. Interpreta los separadores numéricos, reconoce la errata `ENER0` de enero 2017 y no convierte celdas vacías en cero.

En el control de los 12 totales anuales publicados se encontraron diferencias de 1–2 toneladas en varios años y de **1.371 toneladas en 2021** frente a la suma mensual. Se conservan los valores mensuales originales; no se ajustan artificialmente para coincidir con los totales. Antes de modelar, conviene contrastar la discrepancia de 2021 con otra publicación oficial.

Se descartó el CSV `molienda_granos.csv` como fuente para esta tarea porque la serie descargada era anual y terminaba en 2017. La molienda de soja aproxima actividad y disponibilidad de aceite, pero no determina cuánto aceite se destina a biodiésel.

### Aceite de soja y azúcar (Banco Mundial)

`descargar_aceite_soja.py` baja el Excel mensual del Banco Mundial (Pink Sheet) y escribe `aceite_soja_mensual.csv` (USD/tn, enero 1960 en adelante) y `azucar_mensual.csv`. La referencia de precio, el calendario de publicación y la evaluación del FOB oficial de SAGyP como alternativa están en [`docs/aceite_soja.md`](../docs/aceite_soja.md).

### Caña de azúcar

[Archivo histórico de IPAAT](https://www.ipaat.gov.ar/historico/produccion-quincenal-ddjj/3), [campaña 2013](https://www.ipaat.gov.ar/nota/85/produccion-quincenal-y-acumulada-2013) y [campaña 2026](https://www.ipaat.gov.ar/nota/744/produccion-quincenal-y-acumulada-zafra-2026).

La fuente publica informes quincenales y acumulados, no únicamente mensuales. El informe de la primera quincena de septiembre 2026 examinado tiene texto extraíble e incluye subtotales de Tucumán y de Jujuy/Salta, además del total Argentina.

**Motivo del descarte para este sprint:** no se acreditó continuidad mensual ni cobertura geográfica homogénea en todo el archivo. La página 2013 consultada solo ofrece un total anual, y la descripción histórica se refiere a Tucumán. Extraer un PDF aislado es posible, pero no garantiza una serie mensual comparable.

Se revisaron también [AREZ](https://analytics.zoho.com/open-view/2600469000000701635) y el acceso [API ZAFRA](https://sistemaweb.ipaat.gov.ar). El segundo abrió un formulario de usuario y contraseña; no se identificó una API pública documentada. No se verificó una exportación automatizada histórica de AREZ.

Para reconsiderar la variable: inventariar los PDF, comprobar fechas y territorio, sumar las dos quincenas completas de cada mes y contrastar con los cierres. No sumar acumulados entre sí, no duplicar subtotales y total nacional, no distribuir totales anuales entre meses ni asumir cero fuera de zafra sin verificarlo.

## Ejecutar los scripts

Requiere **Python 3.10 o superior** e internet. Ambos scripts usan solo la biblioteca estándar y deben permanecer en la misma carpeta: el de combustibles importa la función de descarga del otro.

Desde la raíz del repositorio:

```powershell
python variables_externas/descargar_variables.py --output variables_externas/data
python variables_externas/descargar_combustibles.py --output variables_externas/data
```

La carpeta `data` se crea automáticamente. Se generan:

- `soja_mensual.csv` y `combustibles_mensual.csv`, con una fila por mes.
- Metadatos JSON con URL, frecuencia, inicio, fin, cantidad de meses, faltantes, fecha de procesamiento y hashes.
- Copias de los originales necesarios para reproducir la extracción.

Ambos comandos finalizaron correctamente con descarga real el 9/10/2026. La descarga y extracción de combustibles tardó aproximadamente cinco minutos en el entorno de verificación. El tiempo depende del equipo y de la conexión.

Un error no debe interpretarse como una actualización exitosa. Conservar una copia del último resultado exitoso antes de actualizar. La fecha de procesamiento no equivale a la fecha de publicación de cada dato.

Para reprocesar originales previamente descargados:

```powershell
python variables_externas/descargar_variables.py --input variables_externas/data/soja_raw.html --output variables_externas/reproduccion
python variables_externas/descargar_combustibles.py --input-dir variables_externas/data --output variables_externas/reproduccion
```

## Alcance de la entrega

La documentación y los dos scripts cubren los criterios de aceptación de esta tarea. Los datos se generan localmente y no es obligatorio versionarlos. Al hacer el commit, seleccionar solamente estos tres archivos; revisar `git status` para evitar incluir las carpetas generadas.

Antes de usar las variables en un modelo se deben verificar sus calendarios de publicación y rezagos. El rezago informado por BCR para producción de biocombustibles no se aplica automáticamente a estas fuentes. Evaluar mejoras con el mismo protocolo temporal que los modelos sin variables externas, sin utilizar información futura.
