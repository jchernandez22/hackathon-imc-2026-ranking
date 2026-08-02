"""
Respaldo del estado privado en un repositorio privado de GitHub.

Por qué existe: en Streamlit Community Cloud el disco del contenedor es
**efímero**. Se reconstruye desde el repo en cada reinicio —un push, un reboot
manual, el límite de memoria, la inactividad— y todo lo que la app escribió se
pierde sin recuperación. `envios/log.csv` y las submissions son justamente eso:
24 h de competencia que nadie puede rehacer.

Este módulo mantiene una copia durable de lo que no puede vivir en el repo de la
app: el log, los CSV crudos de cada envío, `equipos.json` (los tokens son la
contraseña del correo de cada equipo) y el ground truth (los equipos lo leerían).

**Repositorio aparte, no un gist y no el repo de la app.** Un gist «secreto» lo
abre cualquiera que tenga la URL, y el ground truth no aguanta eso. Y tiene que
ser distinto del repo de la app porque Streamlit Cloud reinicia el contenedor en
cada push: respaldar en el mismo repo borraría lo que acaba de respaldar.

Flujo:

    arranque    repo -> disco, solo los archivos que faltan   `restaurar()`
    cada envío  disco -> repo                                 `respaldar_envio()`

El disco local es la fuente de verdad mientras el contenedor vive; el repo es un
espejo. Por eso cada subida manda el archivo **completo** y no un incremento: una
subida que falla se corrige sola en la siguiente, sin dejar huecos.

Sin `GITHUB_TOKEN` y `REPO_ESTADO` configurados todo esto es un no-op y la app se
comporta exactamente como antes. Corriendo en local no hace falta.

    python respaldo.py --crear      # crea el repo y sube el estado actual
    python respaldo.py --estado     # qué hay respaldado
    python respaldo.py --restaurar  # repo -> disco (solo lo que falta)
"""
from __future__ import annotations

import base64
import json
import os
import pathlib
import urllib.error
import urllib.request

import config as cfg

API = "https://api.github.com"
NOMBRE_POR_DEFECTO = "hackathon-imc-2026-estado"

# Los archivos sueltos que se respaldan, {ruta en el repo: ruta local}. Las dos
# carpetas variables —envíos y ground truth— se recorren aparte.
SUELTOS = {
    "envios/log.csv": cfg.ARCHIVO_LOG,
    "equipos.json": cfg.ARCHIVO_EQUIPOS,
}
DIRECTORIOS = {
    "envios/archivos": cfg.DIR_ARCHIVOS,
    "datos/publico": cfg.DIR_PUBLICO,
}


# ─────────────────────────────────────────────────────────────── configuración
def _credenciales() -> tuple[str | None, str | None]:
    """(token, "owner/repo"). Cualquiera de los dos en None desactiva el módulo."""
    tok = os.environ.get("GITHUB_TOKEN") or cfg.st_secret("GITHUB_TOKEN")
    repo = os.environ.get("REPO_ESTADO") or cfg.st_secret("REPO_ESTADO")
    return tok, repo


def activo() -> bool:
    return all(_credenciales())


# ──────────────────────────────────────────────────────────────────────── HTTP
def _api(metodo: str, ruta: str, payload: dict | None = None):
    """Llamada a la API de GitHub. Devuelve None en 404, levanta en el resto."""
    tok, _ = _credenciales()
    peticion = urllib.request.Request(
        API + ruta,
        method=metodo,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": f"Bearer {tok}",
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(peticion, timeout=30) as r:
            cuerpo = r.read()
        return json.loads(cuerpo) if cuerpo else None
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise RuntimeError(
            f"GitHub respondió {e.code} a {metodo} {ruta}: "
            f"{e.read().decode(errors='replace')[:200]}") from e


def _contenidos(ruta_repo: str):
    _, repo = _credenciales()
    return _api("GET", f"/repos/{repo}/contents/{ruta_repo}")


# ────────────────────────────────────────────────────────────────── escritura
def subir(ruta_repo: str, local: pathlib.Path, mensaje: str | None = None) -> bool:
    """
    Sube (o actualiza) un archivo. Devuelve False si el respaldo está apagado o
    si el archivo local no existe; propaga los errores de red al llamador, que
    decide si son fatales — para la app **no lo son**.

    La API de contenidos exige el `sha` del blob actual para sobreescribir, así
    que hay un GET antes de cada PUT. Son dos llamadas por envío; con 8 equipos y
    cuota de 5 al día ni se acerca al límite de 5 000 por hora.
    """
    if not activo() or not local.exists():
        return False
    _, repo = _credenciales()
    actual = _contenidos(ruta_repo)
    payload = {
        "message": mensaje or f"respaldo: {ruta_repo}",
        "content": base64.b64encode(local.read_bytes()).decode(),
    }
    if isinstance(actual, dict) and "sha" in actual:
        payload["sha"] = actual["sha"]
    _api("PUT", f"/repos/{repo}/contents/{ruta_repo}", payload)
    return True


def respaldar_log() -> bool:
    return subir("envios/log.csv", cfg.ARCHIVO_LOG, "log de envíos")


def respaldar_equipos() -> bool:
    return subir("equipos.json", cfg.ARCHIVO_EQUIPOS, "equipos")


def respaldar_envio(nombre: str) -> bool:
    """El CSV crudo de un envío, más el log que lo referencia."""
    ok = subir(f"envios/archivos/{nombre}", cfg.DIR_ARCHIVOS / nombre,
               f"envío {nombre}")
    return respaldar_log() and ok


# ───────────────────────────────────────────────────────────────── restauración
def restaurar() -> list[str]:
    """
    Trae del repo de estado todo archivo que **falte** en disco. Devuelve las
    rutas escritas.

    Nunca sobreescribe. En Cloud el contenedor arranca vacío, así que restaura
    todo; en local, donde los archivos ya están, es un no-op — que es justo lo
    que se quiere para que un respaldo viejo no pise el estado bueno del disco.
    """
    if not activo():
        return []

    pendientes = dict(SUELTOS)
    for dir_repo, dir_local in DIRECTORIOS.items():
        listado = _contenidos(dir_repo)
        for entrada in listado if isinstance(listado, list) else []:
            if entrada.get("type") == "file":
                pendientes[f"{dir_repo}/{entrada['name']}"] = dir_local / entrada["name"]

    escritos = []
    for ruta_repo, local in pendientes.items():
        if local.exists():
            continue
        info = _contenidos(ruta_repo)
        if not isinstance(info, dict) or "content" not in info:
            continue
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(base64.b64decode(info["content"]))
        escritos.append(str(local.relative_to(cfg.RAIZ)))
    return escritos


# ─────────────────────────────────────────────────────────────────────── CLI
def _todo_lo_local(con_envios: bool = True) -> dict[str, pathlib.Path]:
    """
    {ruta en el repo: ruta local} de todo lo respaldable que exista.

    `con_envios=False` deja fuera el log y las submissions. Es lo que se quiere
    al **crear** el repo de estado: si en el disco quedan envíos de prueba de
    `simular.py`, subirlos los volvería permanentes —cada reinicio en Cloud los
    restauraría— y el ranking arrancaría el evento con datos falsos.
    """
    rutas = {r: p for r, p in SUELTOS.items() if p.exists()}
    directorios = dict(DIRECTORIOS)
    if not con_envios:
        rutas.pop("envios/log.csv", None)
        directorios.pop("envios/archivos", None)
    for dir_repo, dir_local in directorios.items():
        for p in sorted(dir_local.glob("*")):
            if p.is_file() and not p.name.startswith("."):
                rutas[f"{dir_repo}/{p.name}"] = p
    return rutas


def main() -> None:
    import argparse
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--crear", action="store_true",
                   help="crea el repo privado de estado y sube lo que haya en disco")
    p.add_argument("--nombre", default=NOMBRE_POR_DEFECTO)
    p.add_argument("--estado", action="store_true", help="lista lo respaldado")
    p.add_argument("--restaurar", action="store_true", help="repo -> disco")
    p.add_argument("--subir", action="store_true", help="disco -> repo, todo")
    p.add_argument("--con-envios", action="store_true",
                   help="incluye el log y las submissions (con --crear se omiten: "
                        "suelen ser los de simular.py)")
    args = p.parse_args()

    tok, repo = _credenciales()
    if not tok:
        raise SystemExit(
            "Falta GITHUB_TOKEN.\n"
            "  export GITHUB_TOKEN=$(gh auth token)")

    if args.crear:
        import subprocess
        usuario = subprocess.run(["gh", "api", "user", "-q", ".login"],
                                 capture_output=True, text=True).stdout.strip()
        if not usuario:
            raise SystemExit("No pude leer tu usuario de GitHub. ¿`gh auth login`?")
        repo = f"{usuario}/{args.nombre}"
        if _api("GET", f"/repos/{repo}") is None:
            _api("POST", "/user/repos",
                 {"name": args.nombre, "private": True, "auto_init": True,
                  "description": "Estado en vivo del ranking. NO publicar."})
            print(f"Repo creado: {repo} (privado)")
        else:
            print(f"El repo {repo} ya existe; subo sobre él.")
        os.environ["REPO_ESTADO"] = repo
        args.subir = True

    if not repo:
        raise SystemExit("Falta REPO_ESTADO (owner/repo). Corre --crear primero.")

    if args.subir:
        locales = _todo_lo_local(con_envios=args.con_envios or not args.crear)
        for ruta_repo, local in locales.items():
            subir(ruta_repo, local, "respaldo inicial")
            print(f"  ↑ {ruta_repo:<52} {local.stat().st_size:>8,} B")
        print(f"\n{len(locales)} archivo(s) respaldado(s) en {repo}.")
        if args.crear and not args.con_envios:
            print("Sin envíos: el repo de estado arranca limpio, como debe ser "
                  "antes del evento. (`--con-envios` si de verdad los quieres.)")
        print("\nConfigura esto en Streamlit → Settings → Secrets:\n")
        print(f'  REPO_ESTADO  = "{repo}"')
        print( '  GITHUB_TOKEN = "ghp_..."   # token con scope `repo`')

    if args.restaurar:
        escritos = restaurar()
        print("\n".join(f"  ↓ {r}" for r in escritos) if escritos
              else "Nada que restaurar: el disco ya tiene todo.")

    if args.estado:
        print(f"Repo de estado: {repo}")
        for ruta_repo in SUELTOS:
            info = _contenidos(ruta_repo)
            print(f"  {ruta_repo:<52} "
                  f"{info['size']:>8,} B" if isinstance(info, dict) else
                  f"  {ruta_repo:<52}        —")
        for dir_repo in DIRECTORIOS:
            listado = _contenidos(dir_repo)
            n = len(listado) if isinstance(listado, list) else 0
            print(f"  {dir_repo + '/':<52} {n:>8,} archivo(s)")


if __name__ == "__main__":
    main()
