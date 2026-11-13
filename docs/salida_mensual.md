# Salida mensual con doble clic: Excel e informe HTML (SCRUM-64)

Código: `scripts/salida_mensual.py`, `scripts/informe_excel.py` y
`scripts/informe_html.py`. Pruebas: `scripts/test_salida_mensual.py`.

## 1. Instalación (una sola vez)

Hace falta Python (probado con 3.13 y 3.14; 3.11 o más nuevo debería andar), instalado desde python.org con la opción
"Add python.exe to PATH". Después, doble clic en **`instalar.bat`**: crea el
entorno de Python (`.venv`) e instala las librerías de `requirements.txt`.
Necesita internet y tarda unos minutos.

Para la BCR hay que confirmar dos cosas: si pueden instalar Python en la PC (o
lo hace sistemas) y si la PC tiene salida a internet hacia las fuentes de datos
(Secretaría de Energía, BCRA, CAC, SAGyP, Banco Mundial).

## 2. Cada mes

1. Bajar a mano el CSV de INDEC del año (`docs/exportaciones_indec.md`).
2. Doble clic en **`correr_estimacion.bat`**, desde el día 28 (antes no
   están las ventas de gasoil del mes).

Si se corre antes del 28, o si las ventas de gasoil o las exportaciones de
INDEC del mes todavía no salieron, la ventana dice desde cuándo volver a correr
y no arma informes. No es un error: igual se actualizan la base y los datos
reales de los meses anteriores en el registro.

La ventana muestra cada paso:

| Paso | Qué hace |
|---|---|
| 0. Respaldo | Copia fechada de la base y del registro en `resultados/respaldo/`. Se conservan las últimas 12 fechas; las más viejas se borran solas. |
| 1 a 6 | El pipeline (SCRUM-38, `docs/pipeline.md`): descargas, INDEC, base, reales publicados, estimación y registro. |
| 7. Informes | Guarda los datos del mes y arma el Excel y el HTML. |

Al terminar abre el informe HTML. Si algo falla, la ventana muestra el error y
queda abierta.

Todo lo que muestra la ventana queda también en `resultados/ultima_corrida.log`,
que se pisa en cada corrida: qué descargas anduvieron o fallaron y por qué, el
mes estimado, si se estimó o no y el código de salida. Si hay un error
inesperado, ahí queda además el detalle técnico para mandarle al equipo.

Si falla alguna descarga que no es la producción (precios, tipo de cambio,
CAC, molienda, combustibles, aceite y azúcar), la estimación sigue con el
último dato que ya estaba, y el Excel y el HTML lo avisan arriba: qué fuente
falló y de qué mes es el dato que se usó.

## 3. Qué deja

En `resultados/`, un juego por mes, sin pisar los anteriores:

| Archivo | Qué es |
|---|---|
| `IACA_biocombustibles_AAAA-MM.xlsx` | Excel para trabajar los números. Hojas: **Estimación** (número de cada serie, variación de la producción, variación del IACA del modelo y del X-13, dato publicado, error y resumen en palabras), **Factores** (del real del mes anterior a la estimación, factor por factor, con gráfico y las variables de cada factor), **Historial** (resumen del error y detalle mes a mes, modelo contra X-13; con fórmulas) y **Serie mensual** (real contra estimaciones, con gráficos). |
| `estimacion_AAAA-MM.html` | Informe para leer: texto con qué se estima y por qué, tablas, figuras con detalle al pasar el mouse y seguimiento. Un solo archivo; se abre sin internet. |
| `estimacion_AAAA-MM.json` | Los datos del mes: estimación, factores (SCRUM-35), seguimiento del registro (SCRUM-44) y métricas. El Excel y el HTML se arman los dos desde este archivo, así coinciden siempre y nada se calcula dos veces. |
| `ultima_corrida.log` | El detalle de la última corrida (lo mismo que mostró la ventana y, si hubo un error inesperado, el detalle técnico). Se pisa en cada corrida. |
| `respaldo/` | Copias fechadas de la base y del registro. |
| `simulacion/` | Las corridas con `--simular`. Sus archivos empiezan con `SIMULACION_` (por ejemplo `SIMULACION_IACA_biocombustibles_2026-09.xlsx`) para no confundirlos con una estimación real. |

Si el mes todavía no tiene dato publicado, las columnas de dato real y error
no aparecen. Si INDEC ocultó la exportación de biodiésel del mes, los dos
archivos lo avisan.

El Excel y el HTML se pueden borrar y volver a generar sin perder nada:

    .venv\Scripts\python.exe scripts\salida_mensual.py --regenerar 2026-10

Para probar con un mes ya publicado, sin tocar el registro real:

    .venv\Scripts\python.exe scripts\salida_mensual.py --simular 2026-09

En una copia nueva del repo la base no está armada: la simulación la arma
sola la primera vez (es lo mismo que correr `scripts\build_db.py`).

No se modifica ninguna planilla de la BCR: si quieren llevar los números a la
suya, se copian desde el Excel del mes.

## 4. Respaldo y cómo restaurar

El registro de estimaciones vive en `data/registro_estimaciones.csv` y
`data/registro_contribuciones.csv`; la base (`data/bcr.db`) se rearma de cero en
cada corrida a partir de las copias de `data/snapshots/`. Por eso el respaldo
guarda los dos CSV además de la base.

Para volver a una fecha, copiar `resultados/respaldo/registro_estimaciones_FECHA.csv`
sobre `data/registro_estimaciones.csv` (y lo mismo con `registro_contribuciones`).
La base no hace falta restaurarla: se vuelve a armar en la próxima corrida.

**Recomendación:** copiar la carpeta `resultados/respaldo/` a una carpeta de red
o a un drive de la BCR cada tanto, por si se rompe la PC.

## 5. Si algo falla

| Mensaje | Qué hacer |
|---|---|
| `Falta instalar el entorno` | Doble clic en `instalar.bat`. |
| `No se encontró Python` | Instalar Python desde python.org, marcando "Add python.exe to PATH". |
| `El Excel ... está abierto` | Si el mensaje dice que la estimación ya quedó guardada, cerrar el Excel y correr `--regenerar AAAA-MM` (no hace falta estimar de nuevo: el Excel sale con los números de esta corrida). Si no, cerrar el Excel y volver a correr. |
| `NO SE ESTIMÓ (no es un error): Todavía no se puede estimar <mes>` | Es antes del 28 del mes siguiente. Volver a correr desde la fecha que indica. |
| `NO SE ESTIMÓ (no es un error): Todavía no están los datos de <mes>` | Las ventas de gasoil o las exportaciones del mes no salieron todavía. Volver a correr cuando salgan. |
| `NO SE ESTIMÓ (no es un error): El sitio de la Secretaría de Energía no responde…` | No es un error del programa: el sitio está caído (ya se reintentó 3 veces) y sin la producción no se sabe qué mes estimar. Esperar unas horas y volver a correr. Si el caído es otro sitio, sigue con el dato anterior: muestra `FALLÓ <fuente>: el sitio no responde` y el Excel y el HTML avisan arriba qué fuente falló y de qué mes es el dato que se usó. Conviene volver a correr cuando el sitio vuelva. |
| `FALTA el CSV de INDEC` o `VIEJO el CSV de INDEC` | Bajarlo (de nuevo) según `docs/exportaciones_indec.md` y volver a correr. |
| `ERROR inesperado` | El detalle queda en `resultados/ultima_corrida.log`: mandárselo al equipo. |

Los demás mensajes del pipeline están en `docs/pipeline.md`, sección 5.

## 6. Verificación

`python scripts/test_salida_mensual.py` prueba, con septiembre 2026 simulado,
que la estimación, la variación del IACA y los factores coinciden entre el
Excel, el HTML y el registro, y que los factores suman la estimación; con un
mes sin publicar, que no aparecen las columnas de real ni de error; que el
Excel y el HTML se regeneran desde el JSON; que el respaldo conserva 12 fechas;
que avisa si el Excel está abierto y que en ese caso el JSON queda con la
estimación nueva; que si todavía no se puede estimar el mes termina con código
3, sin informes, y deja el detalle en `ultima_corrida.log`; que un error
inesperado deja el detalle técnico en el log; que los gráficos del Excel tienen
los ejes visibles; que los archivos de la simulación empiezan con
`SIMULACION_`; que si falla una fuente el Excel y el HTML avisan cuál y de qué
mes es el dato; y que en bioetanol total cada variable dice si es de maíz o de
caña. Probado en Linux y en Windows (Python 3.14, en una ruta con espacio y tilde):
`instalar.bat` crea el entorno e instala todo; `correr_estimacion.bat` avisa si
el sitio de Energía no responde, frena antes del 28 con la fecha para volver a
correr, y con `--simular 2026-09` arma el Excel y el HTML y abre el HTML solo;
con el Excel abierto, `--regenerar` pide cerrarlo.
