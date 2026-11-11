# Registro de estimaciones mensuales (SCRUM-44)

Código: `scripts/registro.py`. Pruebas: `scripts/test_registro.py` (rápida) y
`scripts/prueba_registro_holdout.py` (con X-13, contra SCRUM-42).

## 1. Para qué sirve

La producción de biodiesel y bioetanol se publica 40-45 días después del
cierre del mes, así que la BCR estima el último mes para publicar el IACA. El
registro guarda cada una de esas estimaciones y, cuando sale el dato, la
compara con el real. Así se puede seguir mes a mes cuánto se equivoca el
modelo sin hacer cuentas a mano.

Cada fila es una estimación y se llena en dos momentos:

| Momento | Qué se guarda |
|---|---|
| Al estimar (`registrar`) | Fecha de la corrida, serie, mes, modelo, configuración, pronóstico, versión de los datos y, en biodiesel y bioetanol total, la variación del IACA que se publicaría con ese pronóstico. |
| Al publicarse el dato (`completar`) | Valor real, error en producción y error en la variación del índice. |

La variación hay que guardarla en el momento de estimar: cada publicación del
IACA revisa toda la serie hacia atrás y después no se puede reconstruir qué se
habría publicado.

## 2. Cómo se calcula la variación

Igual que en SCRUM-42 (`docs/error_iaca.md`): X-13 con los `.spc` de la BCR
sobre los datos hasta el mes anterior, elección entre log y nivel con el
criterio de la BCR (últimos 12 meses), base 2013 = 100, media móvil 1-2-1,
fórmula del mes estimado y tasa en log. El registro usa las mismas funciones
de `scripts/error_iaca.py`; no hay una segunda versión del cálculo.

En cada fila se guardan los componentes de X-13 que se usaron (factor
estacional y las dos últimas observaciones filtradas). Con ellos, al llegar el
dato real se calcula "la variación que habría dado el real" sin volver a
correr X-13, con los mismos ajustes que había al estimar. Es la misma
definición de SCRUM-42.

Al registrar biodiesel o bioetanol total se agrega también una fila con el
pronóstico de la réplica del X-13 de la BCR (`x13_bcr`). Sale de la misma
corrida de X-13 que hace falta para la variación, así que no cuesta nada, y
deja en el registro la comparación de los dos modelos todos los meses.

Bioetanol de maíz y de caña se pueden registrar, pero sin variación: no entran
al IACA por separado.

## 3. Dónde vive

- **`data/registro_estimaciones.csv`** es la fuente de verdad y se versiona en
  el repo. La base `data/bcr.db` no sirve para guardarlo, porque
  `build_db.py` la borra y la arma de cero cada vez.
- `build_db.py` copia el CSV a la tabla `registro_estimaciones` en cada
  armado, y `registro.py` actualiza la tabla cada vez que escribe el CSV. Así
  se puede consultar con SQL junto con el resto de los datos.
- `results/registro_estimaciones.xlsx` es la exportación para la BCR. No se
  versiona: se genera desde el CSV.

## 4. Reglas

- **Solo se agregan filas.** Antes de escribir se controla que ninguna fila
  anterior haya cambiado ni desaparecido; si pasa, no se escribe nada.
- **El real se completa una sola vez**, con la primera versión del mes que hay
  en la base, aunque sea provisoria (queda marcado en `real_provisorio`).
  Como la base guarda todas las versiones, da lo mismo correr `completar`
  enseguida o después de que la Secretaría revise el dato: siempre toma la
  primera. Si después lo revisan, la fila no se toca.
- **Si un mes se estima más de una vez** (por ejemplo, porque se corrigieron
  datos y se volvió a correr), quedan todas las corridas, cada una con su
  fecha. Para medir el error cuenta **la última de cada mes**, que es la que se
  habría publicado: la devuelve `ultimas_estimaciones()` y es la hoja
  `ultima_por_mes` del Excel.
- **Solo se estima el mes siguiente al último dato.** Si el mes ya está
  publicado, o hay meses en el medio, frena.
- **No se registra dos veces la misma corrida** (misma serie, mes, modelo y
  fecha de corrida).
- Usa solo datos públicos.

## 5. Uso

Desde la raíz del repo, con la base armada (`python scripts/build_db.py`):

```bash
# 1. Después de actualizar los datos: completar los meses que se publicaron
python scripts/registro.py completar

# 2. Registrar la estimación del mes (tarda ~30 s por serie, corre X-13)
python scripts/registro.py registrar --serie biodiesel --mes 2026-10 --modelo modelo_final --pronostico 123456.7 --configuracion "{\"modelo_elegido\": \"suma_contable\"}"

# 3. Exportar a Excel para la BCR
python scripts/registro.py exportar
```

Desde Python, que es como lo va a llamar el pipeline (SCRUM-38):

```python
from registro import registrar, completar, exportar_excel

completar()
registrar("biodiesel", "2026-10", "modelo_final", 123456.7, {"modelo_elegido": "suma_contable"})
registrar("bioetanol_total", "2026-10", "modelo_final", 150000.0, {"modelo_elegido": "elastic_net"})
exportar_excel()
```

Orden recomendado en el pipeline: armar la base → `completar()` → estimar →
`registrar()` → `exportar_excel()` → commitear `data/registro_estimaciones.csv`.

El Excel tiene tres hojas: `ultima_por_mes`, con la última estimación de cada
mes (la que se usa para medir el error), `registro`, con todas las corridas, y
`columnas`, con qué es cada columna.

## 6. Verificación

`python scripts/prueba_registro_holdout.py` simula que el registro hubiera
andado durante el holdout (sep-2025 a sep-2026): registra cada mes el
pronóstico del modelo final con los datos hasta el mes anterior, completa los
reales y compara contra `results/iaca_holdout_detalle.csv` (SCRUM-42).
Coinciden las 52 filas (13 meses × 2 series × 2 modelos) en pronóstico,
índice, las dos variaciones, error y signo, y la elección log/nivel es la
misma del protocolo. El registro simulado queda en
`results/registro_holdout_simulado.csv`, como ejemplo de cómo se ve.

| Serie | Modelo | Meses | Error medio absoluto (pp) | Aciertos de signo |
|---|---|---:|---:|---:|
| Biodiésel | modelo final | 13 | 8,96 | 7 |
| Biodiésel | X-13 BCR | 13 | 12,26 | 7 |
| Bioetanol total | modelo final | 13 | 4,95 | 7 |
| Bioetanol total | X-13 BCR | 13 | 4,50 | 8 |

Son los mismos números de `results/iaca_holdout_metricas.csv`.

`python scripts/test_registro.py` prueba las reglas de la sección 4 (incluido
que un dato revisado no cambie el real ya publicado), la carga en la base, el
Excel y los mensajes de error, sin correr X-13.

## 7. Cambio en `error_iaca.py`

Para no duplicar el cálculo, la parte de `obtener_contexto` que arma los
componentes a partir de la salida de X-13 pasó a una función propia,
`contexto_desde_salida`, que usan los dos scripts. El resultado no cambia:
`error_iaca.py --mes 2026-08` da exactamente los mismos números que antes.
