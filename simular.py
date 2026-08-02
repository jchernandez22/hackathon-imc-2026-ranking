"""
Genera envíos falsos para probar el dashboard antes del evento.

    python simular.py            # crea 5 equipos con envíos de calidad variable
    python simular.py --limpiar  # borra todos los envíos y sale (dejar así antes del evento)

Los equipos simulados van de "casi perfecto" a "ruido puro" para verificar que el
ranking, los intervalos y los gráficos se comportan en todo el rango.
"""
from __future__ import annotations

import argparse
import datetime as dt
import shutil

import numpy as np
import pandas as pd

import almacen
import config as cfg
from evaluador import Evaluador

# Los ocho equipos reales, con rendimientos inventados que cubren todo el rango:
# de "casi lo resolvió" a "ruido puro". La asignación perfil↔equipo es arbitraria
# y solo sirve para ver cómo se comporta el tablero.
#
# (equipo, prob. de acertar un positivo, nº de falsos positivos, nº de envíos)
PERFILES = [
    ("Envía RATA al 40400",     0.85, 20,  6),
    ("IMT Based",               0.78, 30,  5),
    ("Gammatron 2.0",           0.70, 45,  5),
    ("Bogo Sort",               0.62, 60,  8),   # el que persigue el leaderboard
    ("Los Furritos futboleros", 0.55, 90,  4),
    ("Los Tue Tue",             0.40, 200, 3),
    ("Team Felipe Salamanca",   0.33, 150, 3),
    ("Equipo 8 (sin nombre)",   0.10, 400, 2),
]


def envio_sintetico(ev: Evaluador, p_acierto: float, n_fp: int,
                    rng: np.random.Generator) -> pd.DataFrame:
    verdad = ev.gt_segmentos[["id_grabacion", "segmento", "scientific_name"]]
    aciertos = verdad[rng.random(len(verdad)) < p_acierto]

    grilla, especies = ev.grilla, ev.especies
    i = rng.integers(0, len(grilla), size=n_fp)
    falsos = pd.DataFrame({
        "id_grabacion": grilla.id_grabacion.values[i],
        "segmento": grilla.segmento.values[i],
        "scientific_name": rng.choice(especies, size=n_fp),
    })

    sub = pd.concat([aciertos, falsos], ignore_index=True)
    sub = sub.drop_duplicates(["id_grabacion", "segmento", "scientific_name"])
    sub["confidence"] = rng.uniform(0.5, 1.0, len(sub)).round(3)
    return sub.sort_values(["id_grabacion", "segmento"]).reset_index(drop=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limpiar", action="store_true")
    args = ap.parse_args()

    if args.limpiar:
        if cfg.ARCHIVO_LOG.exists():
            cfg.ARCHIVO_LOG.unlink()
        shutil.rmtree(cfg.DIR_ARCHIVOS, ignore_errors=True)
        cfg.DIR_ARCHIVOS.mkdir(parents=True, exist_ok=True)
        print("Envíos borrados. El tablero queda vacío.")
        return

    ev = Evaluador(str(cfg.DIR_PUBLICO))
    rng = np.random.default_rng(42)

    # Los envíos se reparten por las 24 h del evento, entremezclados entre
    # equipos. Si se generan todos de corrido —como hacía antes— el eje de horas
    # del gráfico de progreso cubre medio segundo y no se puede revisar.
    inicio = dt.datetime.fromisoformat(cfg.INICIO)
    horas = (dt.datetime.fromisoformat(cfg.CIERRE) - inicio).total_seconds() / 3600
    eventos = []
    for equipo, p, n_fp, n_envios in PERFILES:
        # Nadie entrega en la primera hora ni deja el último para el minuto
        # final; dentro de eso cada equipo lleva su propio ritmo.
        t0 = 1.0 + rng.uniform(0, 3)
        t1 = horas - rng.uniform(0.5, 4)
        for k in range(n_envios):
            reparto = k / max(n_envios - 1, 1)
            t = t0 + (t1 - t0) * reparto + rng.normal(0, 0.35)
            eventos.append((min(max(t, 0.1), horas - 0.1), equipo, p, n_fp,
                            k, n_envios))
    eventos.sort()

    for t, equipo, p, n_fp, k, n_envios in eventos:
        # Van mejorando: el primer envío es peor que el último.
        avance = (k + 1) / n_envios
        sub = envio_sintetico(ev, p * (0.55 + 0.45 * avance),
                              int(n_fp * (1.6 - 0.6 * avance)), rng)
        problemas = [x for x in ev.validar(sub) if not x.startswith("Aviso")]
        assert not problemas, problemas

        res = ev.evaluar(sub, cfg.NIVEL)
        ic = ev.intervalo(sub, cfg.NIVEL, n=500)
        ts = inicio + dt.timedelta(hours=float(t))
        almacen.registrar(equipo, sub, res, ic, ts=ts)
        print(f"  {ts:%a %H:%M}  {equipo:<17} envío {k + 1}/{n_envios}  "
              f"F1={res['f1_micro']:.3f}  [{ic[0]:.2f}–{ic[1]:.2f}]  "
              f"({len(sub)} filas)")

    print("\nRanking resultante:")
    print(almacen.mejores_por_equipo()[
        ["equipo", "f1_micro", "ic_lo", "ic_hi", "n_envios"]].to_string(index=False))


if __name__ == "__main__":
    main()
