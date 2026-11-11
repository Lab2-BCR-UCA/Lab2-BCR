# Pipeline de estimación mensual (SCRUM-38)

Código: `scripts/pipeline.py`.
Pruebas: `scripts/test_pipeline.py`.

## 1. Qué hace

Un solo comando deja la estimación del mes, su explicación y el registro:

1. **Descargas**: producción, granos, tipo de cambio, precios regulados,
   molienda, gasoil y nafta, aceite de soja y azúcar. Si una fuente falla,
   avisa y sigue con los datos que ya había.
2. **Exportaciones de INDEC**: procesa el CSV anual hasta el mes a estimar. El
   CSV se baja a mano (`docs/exportaciones_indec.md`); si falta o es viejo,
   avisa.
3. **Base**: `build_db.py`.
4. **Registro**: completa el real de las estimaciones anteriores que ya se
   publicaron (SCRUM-44).
5. **Estimación**: el mes siguiente al último dato de producción, con el modelo
   final de cada serie (`results/comparacion_final_eleccion.csv`, SCRUM-34):
   suma contable para biodiésel y elastic net para bioetanol maíz, caña y total.
   El modelo se reentrena con todos los datos hasta el mes anterior, igual que
   en la evaluación.
6. **Contribuciones**: qué factores explican cada estimación (SCRUM-35).
7. **Registro**: agrega cada estimación con la variación del IACA que se
   publicaría (y la réplica del X-13 BCR para comparar), y sus contribuciones
   en `data/registro_contribuciones.csv`.
Salida: el registro, las contribuciones y un resumen en pantalla con la
estimación, la variación del IACA y los tres factores que más pesan en cada
serie. Los informes para la BCR (Excel y HTML) salen de lo que devuelve
`pipeline.correr()`.

Si todavía no están las ventas de gasoil o las exportaciones de INDEC del mes
a estimar, frena antes de estimar y dice cuál falta: la suma contable no puede
estimar sin ellas. Las ventas de gasoil salen los días 25-27 del mes siguiente
y las exportaciones de INDEC alrededor del día 20, así que la corrida mensual
va después del 27.

## 2. Uso

Desde la raíz del repo:

```bash
python scripts/pipeline.py                    # corrida mensual completa
python scripts/pipeline.py --sin-descargas    # con los datos que ya están
python scripts/pipeline.py --simular 2026-09  # demo con un mes ya publicado
```

`--simular` hace como si el mes no se hubiera publicado: oculta en memoria la
producción desde ese mes, estima y compara con el real. No descarga ni toca el
registro real: escribe en `results/simulacion/`.

## 3. Dónde queda cada cosa

| Archivo | Qué es | ¿Se versiona? |
|---|---|---|
| `data/registro_estimaciones.csv` | Registro de estimaciones (SCRUM-44) | Sí |
| `data/registro_contribuciones.csv` | Contribuciones de cada estimación, una fila por factor, unidas por `estimacion_id` | Sí |
| `results/simulacion/` | Simulaciones | No |

Las contribuciones siguen las mismas reglas que el registro: solo se agregan
filas y antes de escribir se controla que las anteriores no cambiaron.

En la PC de la BCR el registro vive en la carpeta `data/` del proyecto. Como
ahí no se commitea, **conviene copiar los dos CSV del registro a un lugar con
respaldo** después de cada corrida.

## 4. Verificación

`python scripts/test_pipeline.py` simula la corrida en tres meses del holdout
(noviembre 2025, julio 2026 con la exportación oculta por INDEC y septiembre
2026) y comprueba que:

- el pronóstico es el mismo de `results/modelo_final_predicciones.csv`
  (SCRUM-34);
- la variación del IACA, del modelo final y del X-13 BCR, es la misma de
  `results/iaca_holdout_detalle.csv` (SCRUM-42);
- las contribuciones suman el pronóstico y el aviso de exportación estimada
  aparece solo en julio.

También prueba que frene si faltan gasoil o exportaciones del mes, y que las
contribuciones no se repitan ni se pisen.

Probado en Linux con Python 3.13.16, pandas 3.0.5, numpy 2.5.3,
scikit-learn 1.9.1, scipy 1.18.1, statsmodels 0.15.0, openpyxl 3.1.5 y
x13binary 1.1.61. **Falta probarlo en una máquina limpia con Windows**: el
X-13 da distinto en algunos meses entre Windows y Linux
(`docs/comparacion_final.md`, sección 8), así que la variación del IACA
registrada en la BCR puede diferir de la nuestra en esos meses. Es la que la
BCR publicaría con su máquina.

## 5. Si algo falla

| Mensaje | Qué hacer |
|---|---|
| `FALLÓ <fuente>` en las descargas | Sigue con los datos anteriores de esa fuente. Si falla la producción frena, porque sin ella no se sabe qué mes estimar: reintentar más tarde o pasar el `.xlsx` a mano (`python scripts/scrape_produccion_se.py ruta.xlsx`) y correr con `--sin-descargas`. |
| `FALTA el CSV de INDEC` o `se bajó ... antes de que INDEC publicara` | Bajar el CSV del año (`docs/exportaciones_indec.md`) y volver a correr. |
| `Todavía no están los datos de <mes>` | Gasoil o exportaciones del mes no salieron. Correr después del 27. |
| `Ya está registrada` | Ese mes ya se estimó en esa misma corrida. |
