"""
Persistencia de envíos. Log append-only en CSV: simple, auditable y suficiente
para un evento de 24 h con una decena de equipos.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import unicodedata

import pandas as pd

import config as cfg
import respaldo

COLUMNAS_LOG = ["ts", "equipo", "archivo", "n_filas", "f1_micro", "f1_macro",
                "precision", "recall", "tp", "fp", "fn", "ic_lo", "ic_hi", "sha8"]


def ahora() -> dt.datetime:
    return dt.datetime.now()


def slug(nombre: str) -> str:
    """Nombre de equipo apto para un nombre de archivo.

    Los equipos se llaman como quieren —«Envía RATA al 40400», «Gammatron 2.0»—
    y eso lleva tildes, espacios y puntos. En el log y en la interfaz se usa el
    nombre tal cual; solo el archivo en disco se normaliza."""
    plano = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()
    return re.sub(r"-{2,}", "-", re.sub(r"[^A-Za-z0-9]+", "-", plano)).strip("-").lower() or "equipo"


def cargar_equipos() -> dict[str, str]:
    """{nombre_equipo: token}."""
    if not cfg.ARCHIVO_EQUIPOS.exists():
        return {}
    return json.loads(cfg.ARCHIVO_EQUIPOS.read_text())


def leer_log() -> pd.DataFrame:
    if not cfg.ARCHIVO_LOG.exists():
        return pd.DataFrame(columns=COLUMNAS_LOG)
    d = pd.read_csv(cfg.ARCHIVO_LOG, parse_dates=["ts"])
    return d.reindex(columns=COLUMNAS_LOG)


def envios_de_hoy(equipo: str) -> int:
    log = leer_log()
    if log.empty:
        return 0
    hoy = ahora().date()
    return int(((log.equipo == equipo) & (log.ts.dt.date == hoy)).sum())


def registrar(equipo: str, submission: pd.DataFrame, resultado: dict,
              ic: tuple[float, float], ts: dt.datetime | None = None) -> dict:
    """Guarda el CSV crudo y añade una línea al log. Devuelve la fila registrada.

    `ts` solo se pasa desde el simulador, para repartir los envíos falsos a lo
    largo de las 24 h. En producción siempre es la hora real."""
    ts = ahora() if ts is None else ts
    crudo = submission.to_csv(index=False).encode()
    sha8 = hashlib.sha256(crudo).hexdigest()[:8]
    nombre = f"{ts:%Y%m%d_%H%M%S}__{slug(equipo)}__{sha8}.csv"
    (cfg.DIR_ARCHIVOS / nombre).write_bytes(crudo)

    fila = {"ts": ts, "equipo": equipo, "archivo": nombre, "n_filas": len(submission),
            "f1_micro": resultado["f1_micro"], "f1_macro": resultado["f1_macro"],
            "precision": resultado["precision"], "recall": resultado["recall"],
            "tp": resultado["tp"], "fp": resultado["fp"], "fn": resultado["fn"],
            "ic_lo": ic[0], "ic_hi": ic[1], "sha8": sha8}

    encabezado = not cfg.ARCHIVO_LOG.exists()
    pd.DataFrame([fila])[COLUMNAS_LOG].to_csv(
        cfg.ARCHIVO_LOG, mode="a", header=encabezado, index=False)

    # El envío ya está en disco: a partir de aquí nada puede hacerlo fallar. Si
    # el respaldo remoto se cae, se avisa y se sigue —la próxima subida manda el
    # log completo, así que el hueco se cierra solo. `respaldado` no es columna
    # del log: `[COLUMNAS_LOG]` de arriba ya lo descartó, viaja solo de vuelta a
    # la interfaz.
    try:
        fila["respaldado"] = respaldo.respaldar_envio(nombre)
    except Exception as e:                                   # noqa: BLE001
        fila["respaldado"] = False
        fila["error_respaldo"] = str(e)
    return fila


def renombrar(viejo: str, nuevo: str) -> int:
    """Renombra un equipo en `equipos.json` y en todos sus envíos ya registrados.

    El nombre del equipo es la clave con la que se agrupa el log, así que
    cambiarlo solo en `equipos.json` dejaría los envíos anteriores colgando como
    un equipo fantasma en el ranking. Devuelve cuántas filas del log se tocaron.
    Los archivos en disco no se renombran: el log los referencia por su nombre
    original y ese vínculo tiene que seguir funcionando."""
    equipos = cargar_equipos()
    if viejo not in equipos:
        raise KeyError(f"No existe un equipo llamado {viejo!r}.")
    nuevo = nuevo.strip()
    if not nuevo:
        raise ValueError("El nombre nuevo no puede estar vacío.")
    if nuevo != viejo and nuevo in equipos:
        raise ValueError(f"Ya hay un equipo llamado {nuevo!r}.")

    # Se conserva el token: el equipo ya lo tiene anotado.
    renombrados = {(nuevo if k == viejo else k): v for k, v in equipos.items()}
    cfg.ARCHIVO_EQUIPOS.write_text(
        json.dumps(renombrados, ensure_ascii=False, indent=2) + "\n")

    log = leer_log()
    tocadas = int((log.equipo == viejo).sum()) if not log.empty else 0
    if tocadas:
        log.loc[log.equipo == viejo, "equipo"] = nuevo
        log.to_csv(cfg.ARCHIVO_LOG, index=False)

    # Renombrar reescribe el log entero, no solo lo añade: si el contenedor se
    # reinicia antes de respaldar, vuelve el nombre viejo.
    respaldo.respaldar_equipos()
    if tocadas:
        respaldo.respaldar_log()
    return tocadas


def mejores_por_equipo(log: pd.DataFrame | None = None,
                       metrica: str = cfg.METRICA) -> pd.DataFrame:
    """Mejor envío de cada equipo, que es lo que se muestra en el ranking."""
    log = leer_log() if log is None else log
    if log.empty:
        return log
    idx = log.groupby("equipo")[metrica].idxmax()
    mejor = log.loc[idx].copy()
    conteo = log.groupby("equipo").agg(n_envios=("ts", "size"), ultimo=("ts", "max"))
    return (mejor.merge(conteo, on="equipo")
            .sort_values(metrica, ascending=False)
            .reset_index(drop=True))
