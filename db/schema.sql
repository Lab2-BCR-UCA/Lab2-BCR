-- Base unificada del proyecto BCR (SCRUM-27).
-- La base es un derivado: scripts/build_db.py la arma desde cero leyendo los
-- archivos fechados de data/snapshots/. Ver db/README.md.
-- Las variables derivadas (SCRUM-56) se calculan en el armado a partir de las
-- crudas y se versionan igual que ellas.

PRAGMA foreign_keys = ON;

-- Fuentes de datos: un archivo CSV del repo por fuente. Las derivadas
-- cuelgan de una fuente fija, 'derivadas', que agrega el armado.
CREATE TABLE fuentes (
    fuente          TEXT PRIMARY KEY,
    archivo_origen  TEXT NOT NULL,
    descripcion     TEXT
);

-- Catálogo de series: una fila por variable mensual.
-- rezago_min se copia de data/disponibilidad_variables.csv (SCRUM-26).
-- Las crudas salen de db/series.csv y las derivadas de db/derivadas.csv; en
-- las derivadas, columna_origen es el nombre de la función que las calcula.
CREATE TABLE series (
    serie_id                TEXT PRIMARY KEY,
    fuente                  TEXT NOT NULL REFERENCES fuentes(fuente),
    columna_origen          TEXT NOT NULL,
    unidad                  TEXT NOT NULL,
    tipo                    TEXT NOT NULL CHECK (tipo IN ('objetivo', 'auxiliar', 'externa')),
    variable_disponibilidad TEXT NOT NULL,
    rezago_min              INTEGER NOT NULL CHECK (rezago_min >= 0),
    huecos_esperados        INTEGER NOT NULL CHECK (huecos_esperados IN (0, 1)),
    clase                   TEXT NOT NULL CHECK (clase IN ('cruda', 'derivada')),
    relleno                 TEXT NOT NULL CHECK (relleno IN ('ffill', 'ninguno')),
    descripcion             TEXT
);

-- Insumos de cada serie derivada.
CREATE TABLE series_insumos (
    serie_id        TEXT NOT NULL REFERENCES series(serie_id),
    insumo_serie_id TEXT NOT NULL REFERENCES series(serie_id),
    PRIMARY KEY (serie_id, insumo_serie_id)
);

-- Cada versión cargada de cada fuente. Una descarga nueva con datos
-- distintos agrega una fila; nunca se pisa una anterior.
-- Las versiones de una derivada (origen = 'derivada') no tienen archivo:
-- se recalculan en cada armado. serie_derivada dice de qué derivada son.
CREATE TABLE descargas (
    descarga_id      INTEGER PRIMARY KEY,
    fuente           TEXT NOT NULL REFERENCES fuentes(fuente),
    fecha_descarga   TEXT NOT NULL,          -- YYYY-MM-DD
    archivo_snapshot TEXT UNIQUE,            -- ruta dentro de data/snapshots/; NULL en derivadas
    hash_sha256      TEXT NOT NULL,
    filas            INTEGER NOT NULL,
    origen           TEXT NOT NULL CHECK (origen IN ('commit', 'carga', 'derivada')),
    serie_derivada   TEXT REFERENCES series(serie_id),
    CHECK ((origen = 'derivada') = (archivo_snapshot IS NULL)),
    CHECK ((origen = 'derivada') = (serie_derivada IS NOT NULL))
);

-- En las crudas un mismo contenido no se guarda dos veces. En las derivadas
-- una versión puede volver a un valor anterior, así que no aplica.
CREATE UNIQUE INDEX idx_descargas_hash ON descargas (fuente, hash_sha256)
    WHERE origen <> 'derivada';

-- Linaje: con qué versiones de los insumos se calculó cada versión de una
-- derivada.
CREATE TABLE descargas_insumos (
    descarga_id        INTEGER NOT NULL REFERENCES descargas(descarga_id),
    insumo_descarga_id INTEGER NOT NULL REFERENCES descargas(descarga_id),
    PRIMARY KEY (descarga_id, insumo_descarga_id)
);

-- Los datos, en formato largo: una fila por serie, mes y versión.
CREATE TABLE observaciones (
    serie_id    TEXT NOT NULL REFERENCES series(serie_id),
    fecha       TEXT NOT NULL,               -- primer día del mes, YYYY-MM-01
    valor       REAL NOT NULL,
    provisorio  INTEGER CHECK (provisorio IN (0, 1)),  -- solo producción
    descarga_id INTEGER NOT NULL REFERENCES descargas(descarga_id),
    PRIMARY KEY (serie_id, fecha, descarga_id)
);

CREATE INDEX idx_obs_serie_fecha ON observaciones (serie_id, fecha);

-- Registro de estimaciones (SCRUM-44). La fuente de verdad es
-- data/registro_estimaciones.csv, que se versiona en el repo: build_db.py lo
-- carga acá en cada armado y scripts/registro.py lo actualiza. Solo se
-- agregan filas; las columnas del dato real se completan una sola vez.
-- Las columnas de la variación del IACA solo se llenan en las series que
-- entran al índice (biodiesel y bioetanol total).
CREATE TABLE registro_estimaciones (
    estimacion_id              INTEGER PRIMARY KEY,
    fecha_corrida              TEXT NOT NULL,   -- YYYY-MM-DD HH:MM:SS
    serie_id                   TEXT NOT NULL REFERENCES series(serie_id),
    mes_estimado               TEXT NOT NULL,   -- YYYY-MM-01
    modelo                     TEXT NOT NULL,
    configuracion              TEXT,            -- JSON con parámetros del modelo
    pronostico                 REAL NOT NULL,
    fecha_descarga_datos       TEXT NOT NULL,   -- versión de la base usada (YYYY-MM-DD)
    -- Variación que se publicaría en el IACA con este pronóstico, y los
    -- componentes de X-13 con que se calculó (hacen falta para calcular
    -- después la variación con el dato real sin volver a correr X-13).
    variante_x13               TEXT CHECK (variante_x13 IN ('log', 'nivel')),
    factor_base_2013           REAL,
    x13_estacional             REAL,
    x13_filtrado_penultimo     REAL,
    x13_filtrado_ultimo        REAL,
    indice_pronosticado        REAL,
    variacion_pronosticada_pct REAL,
    -- Se completan cuando la Secretaría de Energía publica el dato.
    valor_real                 REAL,
    real_provisorio            INTEGER CHECK (real_provisorio IN (0, 1)),
    fecha_real                 TEXT,            -- descarga que trajo el real
    error_produccion           REAL,            -- pronostico menos valor_real
    variacion_con_real_pct     REAL,
    error_variacion_pp         REAL,            -- variación pronosticada menos variación con el real
    acierto_signo              INTEGER CHECK (acierto_signo IN (0, 1)),
    UNIQUE (serie_id, mes_estimado, modelo, fecha_corrida)
);

-- Última versión disponible de cada dato.
CREATE VIEW v_ultima_version AS
SELECT serie_id, fecha, valor, provisorio, fecha_descarga, descarga_id
FROM (
    SELECT o.serie_id, o.fecha, o.valor, o.provisorio, d.fecha_descarga, o.descarga_id,
           ROW_NUMBER() OVER (
               PARTITION BY o.serie_id, o.fecha
               ORDER BY d.fecha_descarga DESC, o.descarga_id DESC
           ) AS rn
    FROM observaciones o
    JOIN descargas d USING (descarga_id)
)
WHERE rn = 1;

-- v_dataset_mensual (una fila por mes, una columna por serie) la genera
-- build_db.py a partir del catálogo, para que una serie nueva aparezca sola.
