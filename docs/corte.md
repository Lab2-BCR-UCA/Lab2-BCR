# Corte obligatorio: nominal y efectivo (SCRUM-48)

El **corte** es el porcentaje de biocombustible que lleva el combustible que se
vende en el surtidor: biodiesel dentro del gasoil y bioetanol dentro de la
nafta. Hay dos formas de medirlo, y las dos están en la base.

| | Qué es | De dónde sale | Rezago |
|---|---|---|---|
| **Nominal** | El porcentaje que exige la norma. | Resoluciones, decretos y leyes (tabla `data/corte_tramos.csv`). | 0: la norma se conoce de antemano. |
| **Efectivo** | El porcentaje que realmente se mezcló. | Ventas al corte (Secretaría de Energía) / ventas de gasoil o nafta (SESCO). | 1: las ventas al corte vienen del mismo archivo que la producción. |

Pueden diferir: en 2020 la norma pedía 10% de biodiesel y se mezcló menos de
5%, porque el precio regulado no cubría el costo del aceite y las plantas
dejaron de entregar. El nominal dice lo que exige la ley; el efectivo, lo que
pasó.

## Series en la base

| serie_id | Clase | Qué mide |
|---|---|---|
| `corte_biodiesel_nominal_pct` | cruda | % mínimo de biodiesel en gasoil según la norma. |
| `corte_biodiesel_cotab_pct` | cruda | % adicional transitorio de 2022 (COTAB); 0 fuera de jun-oct 2022. |
| `corte_bioetanol_nominal_pct` | cruda | % mínimo de bioetanol en nafta según la norma. |
| `corte_efectivo_biodiesel` | derivada | % de biodiesel en el gasoil vendido. |
| `corte_efectivo_bioetanol` | derivada | % de bioetanol (caña + maíz) en la nafta vendida; se compara con el 12% nominal. |
| `corte_efectivo_bioetanol_maiz` | derivada | % de bioetanol de maíz en la nafta vendida. |
| `corte_efectivo_bioetanol_cana` | derivada | % de bioetanol de caña en la nafta vendida. |

Todas en %, desde 2010-01.

## Cómo se arma

**Nominal.** `data/corte_tramos.csv` tiene un renglón por cada período en que
rigió un porcentaje, con la norma, el link y la confianza.
`variables_externas/armar_corte_nominal.py` lo pasa a un valor por mes en
`data/corte_nominal_mensual.csv`, que es lo que lee `build_db.py`. Si la norma
cambia a mitad de mes, el mes toma el promedio por días (junio 2022: 15 días
al 5% y 15 al 7,5% = 6,25%).

Cuando salga una norma nueva: cerrar el tramo vigente (`fecha_hasta`), agregar
el renglón nuevo, correr el script y después `python scripts/build_db.py`.

**Efectivo.** Son variables derivadas (`scripts/derivadas.py`,
`db/derivadas.csv`): se calculan solas en cada armado a partir de series que ya
estaban en la base.

    biodiesel = ventas al corte [tn] / 0,88 [tn/m3] / ventas de gasoil [m3] × 100
    bioetanol = ventas de bioetanol [m3] / ventas de nafta [m3] × 100   (total, maíz y caña)

## Supuestos

- **Densidad del biodiesel = 0,88 tn/m3** (`DENSIDAD_BIODIESEL_TN_M3`). Las
  ventas al corte vienen en toneladas y el gasoil en m3. El rango típico es
  0,86-0,90; un error acá cambia la escala de la serie, no su forma, así que
  no afecta al modelo.
- **Las ventas de gasoil y nafta de SESCO ya incluyen el biocombustible**
  (SESCO informa lo que se vende en el surtidor, que es la mezcla). Con eso,
  en agosto 2026 el efectivo de biodiesel da 7,2% con un nominal de 7,5%. Si
  el denominador fuera solo el combustible fósil, el porcentaje real sería
  apenas menor (7,2% → 6,7%); la forma de la serie no cambia.
- **Las ventas al corte parecen incluir el COTAB.** En julio 2022 el efectivo
  de biodiesel (8,5%) supera al nominal (7,5%), lo que se explica por el
  adicional transitorio.

## Decisiones

- **No se separa el nominal de bioetanol en caña y maíz.** Desde la Ley 27.640
  (agosto 2021) la norma pide al menos 6% de caña y 6% de maíz, y eso no
  cambió nunca dentro del backtest: una serie constante no le aporta nada al
  modelo. Antes de 2021 no había un reparto fijado por norma (salía de cupos).
  Lo que sí varía es el reparto real, porque cuando la caña no llega el maíz
  completa (2023: 7,1% maíz y 3,9% caña); eso lo capturan los efectivos de maíz
  y de caña.
- **Solo se cargan el corte obligatorio y el adicional (COTAB).** El corte
  voluntario máximo de bioetanol (15% habilitado desde marzo 2026) y los
  proyectos no vigentes quedaron fuera: no obligan a nadie y no cambian lo que
  se vende.
- **COTAB en un solo lugar del modelo.** El COTAB también aparece en SCRUM-53;
  al armar el modelo usar una sola de las dos versiones para no contarlo dos
  veces.
- **Cuidado con el efectivo como predictor.** Está muy correlacionado con la
  producción del mes anterior (las ventas al corte son la mayor parte de la
  producción), así que puede aportar poco por encima del propio rezago del
  target. La prueba (sin corte / efectivo / efectivo + nominal) se hace en
  SCRUM-31.

## Verificación de los tramos

| Tramo | Norma | Confianza |
|---|---|---|
| Biodiesel 5% (ene-jul 2010) | Res. SE 7/2010 | alta |
| Biodiesel 7% (jul 2010 - mar 2013) | Res. SE 554/2010 (BO 12/7/2010), ratificada por Res. SE 56/2012 art. 4 | alta |
| Biodiesel 8% (abr - 5/8/2013) | Nota de la Secretaría de Energía a las petroleras (abril 2013) | media |
| Biodiesel 8% (6/8 - dic 2013) | Res. SE 450/2013 (6/8/2013, art. 3) | alta |
| Biodiesel 9% (ene 2014) y 10% (feb 2014 - dic 2020) | Res. SE 1125/2013; Res. MEyM 37/2016 | media / alta |
| Biodiesel 5% / 6,7% / 8,4% (ene-mar 2021) y 10% (abr-jun 2021) | Res. SE 1/2021 | alta |
| Biodiesel 5% (jul 2021 - jun 2022) | Res. SE 624/2021 (BO 1/7/2021, art. 4) y desde el 4/8/2021 Ley 27.640 | alta |
| Biodiesel 7,5% (desde 16/6/2022) | Res. SE 438/2022; confirmado por el IACA de septiembre 2026 de la BCR | alta |
| COTAB +5% (16/6 - 16/10/2022) | DNU 330/2022; prórrogas Res. SE 636, 637 y 638/2022 | alta |
| Bioetanol 5% (2010 - sep 2014) | Ley 26.093; confirmado por los considerandos de la Res. SE 44/2014 | alta |
| Bioetanol 8,5% → 10% (sep-dic 2014) | Res. SE 44/2014 | alta |
| Bioetanol 12% (desde abr 2016) | Res. MEyM 37/2016, Decreto 543/2016; Ley 27.640 | alta |

Cambios respecto de la primera versión de la tabla: se eliminó un tramo de 2%
el 30/6/2021 que no tenía norma que lo respalde (la Res. SE 624/2021 recién
rige desde el 1/7/2021, así que junio 2021 es 10% completo). El tramo actual de
biodiesel es 7,5% y no 7%.

### Tramos 2013-2014 (revisión de SCRUM-48)

Bioetanol entrena desde 2013 y usa el nominal como régimen justo en ese
período, así que estos tramos se verificaron con las normas.

**Biodiesel 2013.** El 8% tiene norma: la **Res. SE 450/2013** (6/8/2013), que
en su art. 3 sustituye el art. 4 de la Res. SE 56/2012 y fija el mínimo en 8%
en volumen. Desde esa fecha el tramo es de confianza alta. Entre abril y el
5/8/2013 el 8% surge de una nota de la Secretaría a las petroleras, sin
resolución propia (el piso escrito seguía en 7%), y queda en confianza media.
Se mantiene 8% desde abril porque es el valor que después formaliza la
Res. 450/2013 y el corte efectivo sube a 8-9% en mayo-junio 2013. La
alternativa conservadora (7% hasta el 5/8/2013) cambia solo cuatro meses,
anteriores al backtest. La serie mensual no cambia con esta revisión.

**Bioetanol 2010 - sep 2014.** El 5% es correcto y pasa a confianza alta: la
Res. SE 44/2014 parte de ese 5% como mínimo vigente y es la primera norma que
lo sube (8,5% desde su vigencia, 9%, 9,5% y 10% en dic-2014). No faltan
escalones: la suba del efectivo de ~2,7% (2012) a ~8% (2014) vino por **cupos
de volumen** asignados a cada empresa (Res. SE 698/2009, 553/2010, 1673/2010,
424/2011, 5/2012, 137/2012 y 1675/2012), sin cambiar el porcentaje mínimo.
Por eso el efectivo está por debajo del 5% hasta comienzos de 2013 (no había
oferta suficiente) y por encima desde mediados de 2013.

**Implicancia para el modelo.** En bioetanol 2012 - ago 2014 el nominal no es
la restricción que opera: la regla real eran los cupos. Ese tramo no es un
cambio de régimen por norma; para capturarlo sirve el efectivo o la brecha
efectivo − nominal, no el nominal solo. A tener en cuenta en SCRUM-31.

Pendientes menores (no cambian valores mensuales salvo por días):

- Fecha de Boletín Oficial de la Res. SE 450/2013 y de la Res. SE 44/2014
  (hoy se usa la fecha de dictado).
- Biodiesel 9% (ene-2014): confirmar la vigencia exacta de la Res. SE 1125/2013.

Fuentes de la verificación:
[Res. SE 624/2021](https://www.argentina.gob.ar/normativa/nacional/norma-351541/texto),
[Res. SE 450/2013 (InfoLEG)](https://webfs.oecd.org/TADWEB/agriculture/data/AMIS/Indicators/Sources/www.infoleg.gob.ar_infolegInternet_anexos_215000-219999_218395_norma.pdf),
[Res. SE 44/2014 (InfoLEG)](https://webfs.oecd.org/TADWEB/agriculture/data/AMIS/Indicators/Sources/Resolucion_44-2014.pdf),
[Res. SE 56/2012 (Boletín Oficial)](https://www.boletinoficial.gob.ar/pdf/aviso/primera/66837/20120316),
[Marval: Res. SE 554/2010](https://www.marval.com/publicacion/biocombustibles-5691),
[Bichos de Campo: Res. SE 1/2021](https://bichosdecampo.com/mientras-los-precios-subiran-hasta-90-en-mayo-baja-a-la-mitad-el-corte-obligatorio-del-gasoil-con-biodiesel).
El resto de los links está en la columna `fuente_url` de `data/corte_tramos.csv`.
