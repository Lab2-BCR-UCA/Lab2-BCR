"""Pruebas de la tabla de eventos (SCRUM-53). Uso: python scripts/test_eventos.py"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evaluacion import UltimoValor, evaluar_modelo  # noqa: E402
from eventos import (  # noqa: E402
    cargar_eventos, eventos_conocidos, excluir_eventos, mascara_exclusion,
    pesos_entrenamiento,
)

EVENTOS = cargar_eventos()
IDX = pd.period_range("2019-01", "2024-12", freq="M")


def _tabla(filas):
    """Tabla de eventos de prueba escrita en un CSV temporal."""
    import tempfile
    df = pd.DataFrame(filas, columns=["nombre", "serie", "inicio", "fin", "criterio", "fuente"])
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
        df.to_csv(f, index=False)
    return cargar_eventos(f.name)


def test_tabla_del_repo():
    assert set(EVENTOS["nombre"]) == {"cotab", "regimen_2020_2021"}
    assert (EVENTOS["fuente"].str.len() > 0).all()
    cotab = EVENTOS.set_index("nombre").loc["cotab"]
    assert str(cotab["inicio_mes"]) == "2022-06" and str(cotab["fin_mes"]) == "2022-10"
    print("ok  la tabla del repo tiene fechas y fuente")


def test_evento_en_curso_no_se_usa():
    # Prediciendo agosto 2022, COTAB (termina en octubre 2022) sigue en curso.
    m = mascara_exclusion(IDX[IDX < pd.Period("2022-08", "M")], "2022-08", "biodiesel", EVENTOS)
    meses = IDX[IDX < pd.Period("2022-08", "M")][m]
    assert not any(str(x).startswith("2022") for x in meses)
    # El mismo mes en que termina tampoco alcanza: fin tiene que ser < mes predicho.
    assert "cotab" not in set(eventos_conocidos("2022-10", "biodiesel", EVENTOS)["nombre"])
    print("ok  un evento en curso (o que termina en el mes predicho) no se usa")


def test_evento_terminado_si():
    m = mascara_exclusion(IDX, "2022-11", "biodiesel", EVENTOS)
    excluidos = {str(x) for x in IDX[m]}
    cotab = {"2022-06", "2022-07", "2022-08", "2022-09", "2022-10"}
    regimen = {str(p) for p in pd.period_range("2020-08", "2021-07", freq="M")}
    assert excluidos == cotab | regimen
    print("ok  un evento terminado excluye todos los meses que toca")


def test_solo_su_serie():
    for serie in ("bioetanol_maiz", "bioetanol_cana", "bioetanol_total"):
        assert not mascara_exclusion(IDX, "2024-01", serie, EVENTOS).any()
    ev = _tabla([["x", "bioetanol", "2020-04-01", "2020-05-31", "c", "f"]])
    assert mascara_exclusion(IDX, "2021-01", "bioetanol_maiz", ev).sum() == 2
    assert not mascara_exclusion(IDX, "2021-01", "biodiesel", ev).any()
    print("ok  cada evento aplica solo a su serie")


def test_sin_fin_es_en_curso():
    ev = _tabla([["abierto", "todas", "2020-01-01", "", "c", "f"]])
    assert not mascara_exclusion(IDX, "2030-01", "biodiesel", ev).any()
    print("ok  un evento sin fin nunca se usa")


def test_validaciones():
    for fila in (["a", "otra", "2020-01-01", "2020-02-01", "c", "f"],
                 ["a", "todas", "2020-05-01", "2020-02-01", "c", "f"],
                 ["a", "todas", "2020-01-01", "2020-02-01", "c", ""]):
        try:
            _tabla([fila])
        except ValueError:
            continue
        raise AssertionError(f"debió fallar: {fila}")
    print("ok  serie desconocida, fechas invertidas o sin fuente frenan la carga")


def test_pesos():
    p = pesos_entrenamiento(IDX, "2022-11", "biodiesel", peso_evento=0.3, eventos=EVENTOS)
    m = mascara_exclusion(IDX, "2022-11", "biodiesel", EVENTOS)
    assert np.allclose(p[m], 0.3) and np.allclose(p[~m], 1.0)
    print("ok  los pesos valen 1 fuera de eventos y peso_evento dentro")


class _Registra:
    """Modelo de prueba: guarda cuántos meses le marcaron para excluir."""
    vistos = []

    def fit(self, serie, excluir=None):
        _Registra.vistos.append((serie.index[-1] + 1, int(np.sum(excluir))))
        self.v = float(serie[~excluir].iloc[-1])
        return self

    def predict(self):
        return self.v


def test_integracion_protocolo():
    serie = pd.Series(100.0, index=pd.period_range("2019-01", "2023-06", freq="M"))
    # Default: sin excluir, la salida no cambia y no aparece la columna nueva.
    det, _ = evaluar_modelo(serie, UltimoValor, "2019-01", "2022-09", "2022-12")
    assert "meses_excluidos" not in det.columns
    # Con excluir: la máscara se recalcula por iteración (COTAB entra recién en noviembre).
    _Registra.vistos = []
    det, _ = evaluar_modelo(serie, _Registra, "2019-01", "2022-09", "2022-12",
                            excluir=excluir_eventos("biodiesel", EVENTOS))
    assert (det["estado"] == "ok").all()
    por_mes = {str(m): n for m, n in _Registra.vistos}
    assert por_mes == {"2022-09": 12, "2022-10": 12, "2022-11": 17, "2022-12": 17}
    assert det["meses_excluidos"].tolist() == [12, 12, 17, 17]
    # Un modelo cuyo fit no acepta 'excluir' frena la evaluación.
    try:
        evaluar_modelo(serie, UltimoValor, "2019-01", "2022-09", "2022-12",
                       excluir=excluir_eventos("biodiesel", EVENTOS))
    except TypeError:
        pass
    else:
        raise AssertionError("debió frenar")
    print("ok  integrado al protocolo: por iteración, default sin cambios")


if __name__ == "__main__":
    test_tabla_del_repo()
    test_evento_en_curso_no_se_usa()
    test_evento_terminado_si()
    test_solo_su_serie()
    test_sin_fin_es_en_curso()
    test_validaciones()
    test_pesos()
    test_integracion_protocolo()
    print("\nTodas las pruebas de eventos pasaron.")
