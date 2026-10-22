"""Valida la réplica del X-13 contra el modelo real de BCR (SCRUM-23).

BCR estima la producción con el Win X-13 y deja la corrida completa en la
planilla ``BIOCOMBUSTIBLES.xlsx`` (producción, descomposición estacional,
índice base 2013, etc.). Este script corre nuestra réplica del X-13 sobre la
misma serie de producción y compara, mes a mes, los tres componentes de la
descomposición contra los de BCR:

    - factor estacional
    - tendencia-ciclo
    - serie desestacionalizada

Confirma que la réplica reproduce el método de BCR. Resultado obtenido:
correlación >= 0.9996 y error relativo < 0.21 % en todos los componentes.

Uso:
    python scripts/comparar_bcr_x13.py ruta/a/BIOCOMBUSTIBLES.xlsx

Requiere: pip install x13binary pandas numpy matplotlib openpyxl
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from x13binary import find_x13_bin  # noqa: E402

X13 = find_x13_bin()

# Índice base 2013 = producción * factor (verificado contra la planilla).
FACTOR_INDICE = {"biodiesel": 0.00060066, "bioetanol": 0.00254033}


def descomponer(serie: pd.Series, log: bool) -> pd.DataFrame:
    """Corre X-13/X-11 y devuelve estacional (d10), tendencia (d12), desest (d11).

    Args:
        serie: Producción mensual (positiva, ordenada por fecha).
        log: Si True, transformación logarítmica (multiplicativo); si no, aditivo.

    Returns:
        DataFrame indexado por fecha con columnas ``est``, ``tend`` y ``desest``.
    """
    vals = serie.values
    primero = serie.index[0]
    start = f"{primero.year}.{primero.month}"
    data = "\n".join("  " + " ".join(f"{v:.3f}" for v in vals[i:i + 10])
                     for i in range(0, len(vals), 10))
    tr = "log" if log else "none"
    # Misma config que el .spc real de BCR (ver spc/): modelo desde
    # 2013, corrección de días hábiles y Pascua, y los órdenes del automdl.
    modelspan = "  modelspan=(2013.1, )\n" if (primero.year, primero.month) <= (2013, 1) else ""
    spec = (
        f"series{{ start={start} period=12\n{modelspan}  data=(\n{data}\n ) }}\n"
        f"transform{{ function={tr} }}\n"
        "regression{ aictest=(td easter) }\n"
        "automdl{ maxdiff=(2 1) maxorder=(4 2) }\n"
        "x11{ save=(d10 d11 d12) }\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "run"
        base.with_suffix(".spc").write_text(spec)
        subprocess.run([X13, str(base)], cwd=tmp,
                       capture_output=True, text=True, timeout=120)

        def leer(ext: str) -> pd.Series:
            df = pd.read_csv(base.with_suffix(ext), sep="\t",
                             skiprows=2, names=["d", "v"])
            df["d"] = pd.to_datetime(df["d"].astype(int).astype(str), format="%Y%m")
            return df.set_index("d")["v"]

        out = pd.concat([leer(".d10"), leer(".d12"), leer(".d11")], axis=1)
        out.columns = ["est", "tend", "desest"]
        return out


def leer_modelo_bcr(xlsx: Path) -> pd.DataFrame:
    """Extrae de BIOCOMBUSTIBLES.xlsx la producción y descomposición de BCR."""
    import openpyxl
    rows = list(openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
                ["BIOCOMBUSTIBLES"].iter_rows(values_only=True))

    def num(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return np.nan

    recs = []
    for i, r in enumerate(rows):
        if i < 3 or not hasattr(r[0], "year"):
            continue
        recs.append({
            "fecha": pd.Timestamp(r[0]),
            "bd_prod": num(r[1]), "bd_est": num(r[5]), "bd_tend": num(r[7]),
            "bd_desest": num(r[8]),
            "be_prod": num(r[14]), "be_est": num(r[18]), "be_tend": num(r[20]),
            "be_desest": num(r[21]),
        })
    return pd.DataFrame(recs).set_index("fecha")


def comparar(c: pd.DataFrame, comp: str) -> dict:
    """Correlación y error relativo medio entre mi réplica y BCR para un componente."""
    a, b = c[f"mi_{comp}"], c[f"bcr_{comp}"]
    rel = (a - b).abs() / b.abs().replace(0, np.nan)
    return {"corr": round(a.corr(b), 4), "err_rel_%": round(rel.mean() * 100, 3)}


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("Uso: python scripts/comparar_bcr_x13.py ruta/a/BIOCOMBUSTIBLES.xlsx")
    bcr = leer_modelo_bcr(Path(sys.argv[1]))
    raiz = Path(__file__).resolve().parent.parent
    out = raiz / "results"
    out.mkdir(exist_ok=True)

    cfg = [("biodiesel", True), ("bioetanol", False)]
    tabla = []
    for nom, log in cfg:
        fac = FACTOR_INDICE[nom]
        s = bcr[f"{nom[:2]}_prod" if False else ("bd_prod" if nom == "biodiesel" else "be_prod")].dropna()
        s = s[s > 0]
        pre = "bd" if nom == "biodiesel" else "be"
        mio = descomponer(s, log)
        j = bcr.loc[s.index]

        c = pd.DataFrame(index=s.index)
        # estacional: ratio (log) va directo; aditivo se lleva a índice base 2013
        c["bcr_est"] = j[f"{pre}_est"]
        c["mi_est"] = mio["est"] if log else mio["est"] * fac
        c["bcr_tend"] = j[f"{pre}_tend"]
        c["mi_tend"] = mio["tend"] * fac
        c["bcr_desest"] = j[f"{pre}_desest"]
        c["mi_desest"] = mio["desest"] * fac
        c = c.dropna()
        c.to_csv(out / f"validacion_bcr_{nom}.csv")

        for comp in ["est", "tend", "desest"]:
            tabla.append({"serie": nom, "componente": comp, "n": len(c), **comparar(c, comp)})

        fig, ax = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
        for k, (comp, tit) in enumerate([("est", "Factor estacional"),
                                         ("tend", "Tendencia-ciclo"),
                                         ("desest", "Desestacionalizada")]):
            ax[k].plot(c.index, c[f"bcr_{comp}"], lw=3.2, alpha=.45, label="BCR (Win X-13)")
            ax[k].plot(c.index, c[f"mi_{comp}"], lw=1, color="crimson", label="Mi réplica")
            ax[k].set_title(tit)
            ax[k].legend(loc="upper left", fontsize=8)
        fig.suptitle(f"{nom.upper()} — mi réplica X-13 vs modelo de BCR", fontsize=13)
        fig.tight_layout()
        fig.savefig(out / f"validacion_bcr_{nom}.png", dpi=110)
        plt.close(fig)

    resumen = pd.DataFrame(tabla)
    resumen.to_csv(out / "validacion_bcr_resumen.csv", index=False)
    print(resumen.to_string(index=False))
    print(f"\nGuardado en {out}/validacion_bcr_*")


if __name__ == "__main__":
    main()
