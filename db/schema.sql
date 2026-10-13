-- Base unificada del proyecto BCR (SCRUM-27).
-- La base es un derivado: scripts/build_db.py la arma desde cero leyendo los
-- archivos fechados de data/snapshots/. Ver db/README.md.

PRAGMA foreign_keys = ON;

-- Fuentes de datos: un archivo CSV del repo por fuente.
CREATE TABLE fuentes (
    fuente          TEXT PRIMARY KEY,
    archivo_origen  TEXT NOT NULL,
    descripcion     TEXT
);

-- Catálogo de series: una fila por variable mensual.
-- rezago_min se copia de data/disponibilidad_variables.csv (SCRUM-26).
CREATE TABLE series (
    serie_id                TEXT PRIMARY KEY,
    fuente                  TEXT NOT NULL REFERENCES fuentes(fuente),
    columna_origen          TEXT NOT NULL,
    unidad                  TEXT NOT NULL,
    tipo                    TEXT NOT NULL CHECK (tipo IN ('objetivo', 'auxiliar', 'externa')),
    variable_disponibilidad TEXT NOT NULL,
    rezago_min              INTEGER NOT NULL CHECK (rezago_min >= 0),
    huecos_esperados        INTEGER NOT NULL CHECK (huecos_esperados IN (0, 1)),
    descripcion             TEXT
);

-- Cada versión cargada de cada fuente. Una descarga nueva con datos
-- distintos agrega una fila; nunca se pisa una anterior.
CREATE TABLE descargas (
    descarga_id      INTEGER PRIMARY KEY,
    fuente           TEXT NOT NULL REFERENCES fuentes(fuente),
    fecha_descarga   TEXT NOT NULL,          -- YYYY-MM-DD
    archivo_snapshot TEXT NOT NULL UNIQUE,   -- ruta dentro de data/snapshots/
    hash_sha256      TEXT NOT NULL,
    filas            INTEGER NOT NULL,
    origen           TEXT NOT NULL CHECK (origen IN ('commit', 'carga')),
    UNIQUE (fuente, hash_sha256)
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

-- Registro de estimaciones (SCRUM-44). Queda vacío hasta que el pipeline
-- (SCRUM-38) escriba en él. Solo se agregan filas.
CREATE TABLE registro_estimaciones (
    estimacion_id        INTEGER PRIMARY KEY,
    fecha_corrida        TEXT NOT NULL,      -- YYYY-MM-DD
    serie_id             TEXT NOT NULL REFERENCES series(serie_id),
    mes_estimado         TEXT NOT NULL,      -- YYYY-MM-01
    modelo               TEXT NOT NULL,
    configuracion        TEXT,               -- JSON con parámetros del modelo
    pronostico           REAL NOT NULL,
    fecha_descarga_datos TEXT NOT NULL,      -- versión de los datos usada
    valor_real           REAL,               -- se completa cuando se publica
    error                REAL,               -- pronostico menos valor_real
    fecha_real           TEXT,               -- fecha de la descarga que trajo el real
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
