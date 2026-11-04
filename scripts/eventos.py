"""Tabla de eventos y regla de uso en el entrenamiento (SCRUM-53).

Los eventos son períodos anormales (``data/eventos.csv``) en los que la
relación entre la producción y sus determinantes no es la habitual. La regla
del proyecto es **limpiar el entrenamiento**: esos meses se excluyen del ajuste
en lugar de agregar columnas al modelo (con pocos datos, una dummy más no suma;
ver ``docs/eventos.md``).

Regla anti-leakage
------------------
En cada iteración del walk-forward un evento se usa solo si **ya terminó antes
del mes que se predice** (``fin`` < mes predicho, a nivel mensual). Si el
evento sigue en curso, su fecha de fin todavía no se conoce y usarla sería
leakage, así que en esa iteración no se excluye nada por ese evento. Un evento
sin ``fin`` en la tabla se considera en curso y nunca se usa.

Un mes cuenta como afectado si el evento lo toca aunque sea un día (COTAB:
junio a octubre de 2022).

Uso
---
    from eventos import excluir_eventos
    from evaluacion import evaluar_ventanas

    evaluar_ventanas(serie, crear_modelo, inicio, ventanas,
                     excluir=excluir_eventos("biodiesel"))

El modelo recibe la máscara como ``fit(serie, excluir=mascara)``; ver
``evaluacion.evaluar_modelo``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
EVENTOS = RAIZ / "data" / "eventos.csv"
COLUMNAS = ["nombre", "serie", "inicio", "fin", "criterio", "fuente"]
SERIES_VALIDAS = {"biodiesel", "bioetanol", "todas"}


def cargar_eventos(ruta: Path | str = EVENTOS) -> pd.DataFrame:
    """Lee y valida la tabla de eventos.

    Agrega ``inicio_mes`` y ``fin_mes`` (Period mensual; ``fin_mes`` es NaT si
    el evento está en curso).
    """
    ev = pd.read_csv(ruta, dtype=str, keep_default_na=False)
    faltan = [c for c in COLUMNAS if c not in ev.columns]
    if faltan:
        raise ValueError(f"Faltan columnas en la tabla de eventos: {faltan}")
    if ev["nombre"].duplicated().any():
        raise ValueError("Hay eventos con el mismo nombre.")
    malas = set(ev["serie"]) - SERIES_VALIDAS
    if malas:
        raise ValueError(f"Serie desconocida en eventos: {sorted(malas)}")
    if (ev["fuente"].str.strip() == "").any():
        raise ValueError("Todo evento necesita una fuente.")

    ev["inicio"] = pd.to_datetime(ev["inicio"], errors="raise")
    ev["fin"] = pd.to_datetime(ev["fin"].replace("", None), errors="raise")
    cerrados = ev["fin"].notna()
    if (ev.loc[cerrados, "fin"] < ev.loc[cerrados, "inicio"]).any():
        raise ValueError("Hay eventos que terminan antes de empezar.")

    ev["inicio_mes"] = ev["inicio"].dt.to_period("M")
    ev["fin_mes"] = ev["fin"].dt.to_period("M")
    return ev


def _aplica(evento_serie: str, serie: str) -> bool:
    """``bioetanol`` aplica a bioetanol_maiz, bioetanol_cana y bioetanol_total."""
    return evento_serie == "todas" or serie.split("_")[0] == evento_serie


def eventos_conocidos(mes_predicho, serie: str,
                      eventos: pd.DataFrame | None = None) -> pd.DataFrame:
    """Eventos de ``serie`` que ya terminaron antes de ``mes_predicho``."""
    ev = cargar_eventos() if eventos is None else eventos
    mes = pd.Period(mes_predicho, freq="M")
    aplica = ev["serie"].map(lambda s: _aplica(s, serie))
    terminado = ev["fin_mes"].notna() & (ev["fin_mes"] < mes)
    return ev.loc[aplica & terminado]


def mascara_exclusion(indice, mes_predicho, serie: str,
                      eventos: pd.DataFrame | None = None) -> np.ndarray:
    """Booleano por mes de ``indice``: True = excluir del entrenamiento.

    Solo usa eventos terminados antes de ``mes_predicho`` (regla anti-leakage).
    """
    idx = indice if isinstance(indice, pd.PeriodIndex) else pd.PeriodIndex(
        pd.to_datetime(indice), freq="M")
    mascara = np.zeros(len(idx), dtype=bool)
    for _, e in eventos_conocidos(mes_predicho, serie, eventos).iterrows():
        mascara |= (idx >= e["inicio_mes"]) & (idx <= e["fin_mes"])
    return mascara


def pesos_entrenamiento(indice, mes_predicho, serie: str, peso_evento: float = 0.0,
                        eventos: pd.DataFrame | None = None) -> np.ndarray:
    """Pesos por mes: 1 fuera de eventos, ``peso_evento`` dentro (0 = excluir)."""
    if not 0.0 <= peso_evento <= 1.0:
        raise ValueError("peso_evento tiene que estar entre 0 y 1.")
    excl = mascara_exclusion(indice, mes_predicho, serie, eventos)
    return np.where(excl, peso_evento, 1.0)


def excluir_eventos(serie: str, eventos: pd.DataFrame | None = None
                    ) -> Callable[[pd.PeriodIndex, pd.Period], np.ndarray]:
    """Función para el parámetro ``excluir`` de ``evaluacion.evaluar_modelo``.

    La tabla se lee una sola vez y queda fija durante toda la evaluación.
    """
    ev = cargar_eventos() if eventos is None else eventos

    def _excluir(indice_entrenamiento, mes_predicho):
        return mascara_exclusion(indice_entrenamiento, mes_predicho, serie, ev)

    return _excluir
