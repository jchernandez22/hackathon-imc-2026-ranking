"""Parámetros de operación del ranking. Es el único archivo que se toca en vivo."""
import os
import pathlib

RAIZ = pathlib.Path(__file__).parent


def st_secret(nombre: str) -> str | None:
    """
    Lee un secreto de Streamlit sin exigir que Streamlit esté corriendo.

    `config.py` también lo importan `simular.py` y los scripts de consola, donde
    `st.secrets` no existe y lanza excepción. Devuelve None en vez de explotar.
    """
    try:
        import streamlit as st
        return st.secrets.get(nombre)
    except Exception:
        return None

# --- Datos -------------------------------------------------------------------
# Las grabaciones sobre las que se puntúa, con su ground truth.
DIR_PUBLICO = RAIZ / "datos" / "publico"

DIR_ENVIOS = RAIZ / "envios"
ARCHIVO_LOG = DIR_ENVIOS / "log.csv"
DIR_ARCHIVOS = DIR_ENVIOS / "archivos"
ARCHIVO_EQUIPOS = RAIZ / "equipos.json"

# --- Reglas del ranking ------------------------------------------------------
NIVEL = "segmento"          # "segmento" (exigente) o "presencia"
METRICA = "f1_micro"        # ver README § "Por qué micro y no macro"
ENVIOS_POR_DIA = 5          # cuota por equipo; frena el sondeo del leaderboard
BOOTSTRAP_N = 2000          # remuestreos para el intervalo de confianza

# --- Evento ------------------------------------------------------------------
NOMBRE_EVENTO = "Hackathon IMC 2026"
INICIO = "2026-08-03 11:00"   # lunes 11:00
CIERRE = "2026-08-04 11:00"   # martes 11:00

# Contraseña del panel de organización. Sin valor por defecto a propósito: este
# archivo va al repo, así que cualquier default es una contraseña publicada.
#
#   local        export CLAVE_ADMIN='...'   antes de lanzar streamlit
#   Streamlit    Settings -> Secrets:  CLAVE_ADMIN = "..."
#
# Si falta, el panel de organización queda cerrado y el resto del ranking sigue
# funcionando: preferimos perder el panel a dejarlo abierto con una clave que
# está en GitHub.
CLAVE_ADMIN = os.environ.get("CLAVE_ADMIN") or st_secret("CLAVE_ADMIN")


def _param(nombre: str) -> str | None:
    return os.environ.get(nombre) or st_secret(nombre)


# --- Señales de revisión -----------------------------------------------------
# El panel de admin marca envíos que conviene revisar. **Qué** se marca no va en
# el código: este repo es público, y escribirlo aquí es entregarle a los equipos
# la receta para no ser detectados —basta filtrar las especies que uno nombre—.
# Va por entorno/secrets, igual que la clave.
#
#   ESPECIES_DELATORAS  Especies separadas por coma que un modelo honesto no
#                       debería emitir sobre este audio. Vacío = no se destacan;
#                       la alerta genérica de «especies fuera del ground truth»
#                       funciona igual, porque esa se deduce del propio GT.
#   UMBRAL_SOSPECHA     Puntaje por sobre el cual mirar el código. Sin definir,
#                       esa alerta queda apagada y el panel lo dice.
ESPECIES_DELATORAS = [e.strip() for e in (_param("ESPECIES_DELATORAS") or "").split(",")
                      if e.strip()]
UMBRAL_SOSPECHA = float(_param("UMBRAL_SOSPECHA")) if _param("UMBRAL_SOSPECHA") else None

# --- Paleta (validada para daltonismo) ---------------------------------------
AZUL, NARANJA, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
TINTA, TINTA2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, SUPERFICIE = "#e1e0d9", "#fcfcfb"

# Serie categórica para las curvas de progreso, en orden fijo (nunca ciclado).
# Peor par adyacente: ΔE 9.1 en protanopía, 19.6 en visión normal. Aqua, amarillo
# y magenta quedan bajo 3:1 contra el fondo, así que las curvas van SIEMPRE con
# etiqueta directa: el color nunca es lo único que identifica al equipo.
SERIES = (AZUL, NARANJA, AQUA, "#eda100", "#e87ba4",
          "#008300", "#4a3aa7", "#e34948")

for _d in (DIR_ENVIOS, DIR_ARCHIVOS, DIR_PUBLICO):
    _d.mkdir(parents=True, exist_ok=True)
