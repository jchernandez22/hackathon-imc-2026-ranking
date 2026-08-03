"""
Dashboard del Hackathon IMC 2026.

    streamlit run app.py

Cinco pestañas: ranking, desglose por especie, progreso, envío y panel de admin.
La lógica de puntaje vive en `evaluador.py`, no aquí.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import almacen
import config as cfg
import graficos
import respaldo
from evaluador import Evaluador, ErrorDeFormato

st.set_page_config(page_title=cfg.NOMBRE_EVENTO, page_icon="🐦", layout="wide")


@st.cache_resource
def restaurar_estado() -> tuple[list[str], str | None]:
    """
    Repone desde el respaldo lo que el disco no tenga. `cache_resource` la deja
    corriendo una sola vez por contenedor, no en cada rerun.

    En Cloud el disco arranca vacío en cada reinicio, así que esto es lo que
    devuelve el log, los envíos y el ground truth. En local no hace nada: los
    archivos ya están y `restaurar()` nunca sobreescribe.
    """
    try:
        return respaldo.restaurar(), None
    except Exception as e:                                   # noqa: BLE001
        return [], str(e)


_restaurados, _error_restauracion = restaurar_estado()
if _error_restauracion:
    st.warning(
        f"No pude leer el respaldo remoto: {_error_restauracion}\n\n"
        "La app sigue con lo que haya en disco. **Revísalo antes de que la "
        "gente empiece a enviar**: si el disco está vacío, el ranking arrancaría "
        "en blanco.")


@st.cache_resource
def cargar_evaluador(directorio: str) -> Evaluador:
    return Evaluador(directorio)


try:
    ev = cargar_evaluador(str(cfg.DIR_PUBLICO))
except FileNotFoundError:
    st.error(
        f"Falta el ground truth público en `{cfg.DIR_PUBLICO}`.\n\n"
        "Copia ahí `segmentos_a_predecir.csv`, `ground_truth_segmentos.csv` y "
        "`ground_truth_presencia.csv`, o corre `python preparar_datos.py`."
    )
    st.stop()

EQUIPOS = almacen.cargar_equipos()

# Las especies que los equipos ya conocen: las de su paquete de entrenamiento.
# Todo desglose por especie que se muestre en público se limita a estas.
#
# Publicar las del ground truth —y sobre todo sus conteos— les permitiría
# calibrar cuántas predicciones emitir de cada una sin modelar nada, que es
# exactamente lo que se sacó del README cuando este repo pasó a ser público.
# Falla cerrada a propósito: si no está `etiquetas_entrenamiento.csv`, el
# desglose se apaga en vez de caer de vuelta al ground truth completo.
ESPECIES_VISIBLES = ev.especies_entregadas

st.title("🐦 " + cfg.NOMBRE_EVENTO)
st.caption(
    # Sin conteo de especies: cualquier número acá dice algo del set puntuado
    # que los equipos no pueden deducir de su propio paquete.
    f"Ranking por **{cfg.METRICA}** a nivel de **{cfg.NIVEL}** · "
    f"{len(ev.grilla):,} segmentos · "
    f"cuota de {cfg.ENVIOS_POR_DIA} envíos por equipo al día"
)

# El orden de las etiquetas es el orden en pantalla. Las tres primeras son las
# que están proyectadas casi todo el evento; enviar se usa cinco veces al día
# por equipo, así que queda al final, al lado del panel de admin.
tab_rank, tab_especies, tab_progreso, tab_enviar, tab_admin = st.tabs(
    ["🏆 Ranking", "🔍 Por especie", "📈 Progreso", "📤 Enviar", "⚙️ Admin"])


# ───────────────────────────────────────────────────────────── Ranking
with tab_rank:
    mejores = almacen.mejores_por_equipo()

    if mejores.empty:
        st.info("Todavía no hay envíos.")
    else:
        # theme=None: la configuración de color y tipografía la pone graficos.py.
        st.altair_chart(graficos.grafico_ranking(mejores),
                        width="stretch", theme=None)

        cols = ["equipo", "f1_micro", "ic_lo", "ic_hi", "f1_macro",
                "precision", "recall", "n_envios", "ultimo"]
        # La columna «no visto» solo existe si el evaluador tiene las etiquetas
        # de entrenamiento; sin ellas no se muestra en vez de salir vacía.
        if "f1_no_visto" in mejores and mejores["f1_no_visto"].notna().any():
            cols.insert(2, "f1_no_visto")
        tabla = mejores[cols].copy()
        tabla.insert(0, "#", range(1, len(tabla) + 1))
        tabla["intervalo"] = tabla.apply(
            lambda r: f"[{r.ic_lo:.2f} – {r.ic_hi:.2f}]", axis=1)

        # La tabla es la vista accesible del gráfico: mismos datos, sin depender
        # del color ni del largo de las barras.
        with st.expander("Ver la tabla completa"):
            st.dataframe(
                tabla.drop(columns=["ic_lo", "ic_hi"]),
                hide_index=True, width="stretch",
                column_config={
                    "f1_micro": st.column_config.NumberColumn("F1 micro", format="%.2f"),
                    "f1_no_visto": st.column_config.NumberColumn(
                        "F1 no visto", format="%.2f",
                        help="F1 sobre las etiquetas que NO venían en el paquete "
                             "de entrenamiento. Entregar el entrenamiento tal cual "
                             "da 0.00 acá."),
                    "f1_macro": st.column_config.NumberColumn("F1 macro", format="%.2f"),
                    "precision": st.column_config.NumberColumn("Prec.", format="%.2f"),
                    "recall": st.column_config.NumberColumn("Rec.", format="%.2f"),
                    "ultimo": st.column_config.DatetimeColumn(
                        "Último envío", format="DD/MM HH:mm"),
                })

    # Mismo patrón que la tabla: el detalle a un clic, sin quitarle la pantalla
    # al ranking. Va fuera del if/else porque sirve igual antes del primer
    # envío. Lo que dice aquí es literalmente lo que hace `evaluador.py`; si esa
    # lógica cambia, este texto cambia con ella.
    with st.expander("Cómo se calculan las métricas"):
        unidad = ("`(grabación, segmento, especie)`" if cfg.NIVEL == "segmento"
                  else "`(grabación, especie)`")
        # Cadena **cruda**: el bloque trae LaTeX, y sin la `r` cada `\` hay que
        # escribirlo doble. Se escapaban `\\mathrm` y `\\frac` pero no `\quad` ni
        # `\cdot`, que Python dejaba pasar como secuencias inválidas —salían bien
        # de casualidad, con un SyntaxWarning por cada una y con fecha de
        # vencimiento: en una versión futura `\q` pasa a ser error. Con `r` se
        # escribe LaTeX tal cual. Las llaves siguen dobles: eso es del f-string.
        st.markdown(rf"""
Tu envío y el ground truth se convierten en dos **conjuntos** de tuplas
{unidad} y se comparan entre sí. Al ser conjuntos, repetir una fila no suma nada.

| | qué es |
| --- | --- |
| **TP** | la tupla está en los dos |
| **FP** | la predijiste y no está en el ground truth |
| **FN** | está en el ground truth y no la predijiste |

$\mathrm{{precisión}} = \frac{{TP}}{{TP + FP}} \quad \quad$ 
$\mathrm{{recall}} = \frac{{TP}}{{TP + FN}} \quad \quad$ 
$F_1 = \frac{{2 \cdot \mathrm{{precisión}} \cdot \mathrm{{recall}}}}{{\mathrm{{precisión}} + \mathrm{{recall}}}}$

Si un denominador queda en cero, esa métrica vale 0 — no es un error.

**F1 micro**, el del ranking, sale de los TP, FP y FN **globales**: cada
detección pesa lo mismo, así que las especies con más segmentos mandan.
**F1 macro** es el promedio simple del F1 de cada especie, y promedia sobre las
que aparecen en el ground truth **o** en tu envío: predecir una especie que no
existe en estas grabaciones te mete un 0 en ese promedio, además del FP.

Tres cosas que sorprenden a todo el mundo la primera vez:

- **La columna `confidence` no se usa.** El evaluador no aplica ningún umbral:
  cada fila que entregas es una predicción positiva. Elegir el umbral es parte
  del problema y va antes de enviar.
- **Un segmento sin filas es una predicción**, la de «aquí no hay ave», y suele
  ser correcta. Rellenar por si acaso solo genera FP.
- **El nombre se normaliza** —espacios de sobra y mayúsculas dan lo mismo,
  `TURDUS  falcklandii ` cuenta como `Turdus falcklandii`—, pero la especie
  tiene que ser la correcta: no hay crédito parcial por acertar el género.

El **intervalo** de la tabla es un IC al 95 % por bootstrap: {cfg.BOOTSTRAP_N:,}
remuestreos **de grabaciones**, no de segmentos (los segmentos de una misma
grabación están correlacionados y remuestrearlos daría un intervalo falsamente
angosto), y se toman los percentiles 2.5 y 97.5. Sale ancho porque las unidades
independientes son pocas: **dos equipos separados por 0.02 no están separados.**

El ranking muestra el **mejor** envío de cada equipo, no el último.
""")


# ───────────────────────────────────────────────────── Por especie
with tab_especies:
    st.subheader("F1 por especie y por equipo")
    mejores = almacen.mejores_por_equipo()
    if mejores.empty:
        st.info("Sin envíos todavía.")
    elif not ESPECIES_VISIBLES:
        st.info("Falta `etiquetas_entrenamiento.csv`: el desglose por especie "
                "queda desactivado.")
    else:
        filas = []
        for _, r in mejores.iterrows():
            sub = pd.read_csv(cfg.DIR_ARCHIVOS / r.archivo)
            _, det = ev.evaluar(sub, cfg.NIVEL, por_especie=True)
            filas.append(det.set_index("scientific_name")["f1"].rename(r.equipo))
        # Solo las especies del paquete de entrenamiento, y sin el soporte del
        # ground truth: el `n` de cada especie es justamente lo que no se publica.
        matriz = pd.concat(filas, axis=1).reindex(ESPECIES_VISIBLES).fillna(0)

        st.dataframe(graficos.estilo_matriz(matriz), width="stretch")
        st.caption(
            "Se listan las especies del paquete de entrenamiento. Las tres que ahí "
            "traen 3, 2 y 1 ejemplo son prácticamente inaprendibles en 24 h: por eso "
            "el ranking usa F1 **micro** y no macro, donde esas tres decidirían el "
            "podio por azar."
        )


# ───────────────────────────────────────────────────────── Progreso
with tab_progreso:
    st.subheader("Mejor puntaje a lo largo del evento")
    log = almacen.leer_log()
    if log.empty:
        st.info("Sin envíos todavía.")
    else:
        st.altair_chart(graficos.grafico_progreso(log), width="stretch", theme=None)
        st.caption("Pasa el mouse por una curva para aislarla, o por un punto para "
                   "ver el envío.")

        st.dataframe(log.sort_values("ts", ascending=False)
                     [["ts", "equipo", "n_filas", "f1_micro", "f1_macro",
                       "precision", "recall"]],
                     hide_index=True, width="stretch")


# ───────────────────────────────────────────────────────────── Enviar
with tab_enviar:
    st.subheader("Enviar un `submission.csv`")

    col_a, col_b = st.columns([1, 1])
    equipo = col_a.selectbox("Equipo", sorted(EQUIPOS) or ["(sin equipos configurados)"])
    token = col_b.text_input("Token", type="password")

    if EQUIPOS and equipo in EQUIPOS:
        usados = almacen.envios_de_hoy(equipo)
        restantes = cfg.ENVIOS_POR_DIA - usados
        (st.warning if restantes <= 1 else st.info)(
            f"Envíos usados hoy: **{usados}/{cfg.ENVIOS_POR_DIA}** · quedan **{max(restantes, 0)}**"
        )

    archivo = st.file_uploader("Archivo CSV", type="csv")

    if st.button("Validar y puntuar", type="primary", disabled=archivo is None):
        if EQUIPOS.get(equipo) != token:
            st.error("Token incorrecto.")
            st.stop()
        if almacen.envios_de_hoy(equipo) >= cfg.ENVIOS_POR_DIA:
            st.error(f"Cuota agotada: {cfg.ENVIOS_POR_DIA} envíos por día. "
                     "Valida localmente con `evaluar()` antes del próximo.")
            st.stop()

        try:
            sub = pd.read_csv(archivo)
        except Exception as e:
            st.error(f"No se pudo leer el CSV: {e}")
            st.stop()

        problemas = ev.validar(sub)
        bloqueantes = [p for p in problemas if not p.startswith("Aviso")]
        for p in problemas:
            (st.warning if p.startswith("Aviso") else st.error)(p)
        if bloqueantes:
            st.info("Corrige los errores y vuelve a subirlo. **Este intento no "
                    "consumió cuota.**")
            st.stop()

        try:
            res, detalle = ev.evaluar(sub, cfg.NIVEL, por_especie=True)
            ic = ev.intervalo(sub, cfg.NIVEL, n=cfg.BOOTSTRAP_N)
        except ErrorDeFormato as e:
            st.error(str(e))
            st.stop()

        fila = almacen.registrar(equipo, sub, res, ic)
        st.success(f"Envío registrado · **F1 micro = {res['f1_micro']:.3f}**  "
                   f"[{ic[0]:.2f} – {ic[1]:.2f}]")
        if respaldo.activo() and not fila.get("respaldado"):
            # El envío quedó guardado igual; lo que falló es la copia durable.
            # Se avisa porque un reinicio del contenedor sí lo perdería.
            st.warning(
                "Tu envío quedó registrado y puntuado, pero **no se pudo "
                "respaldar**. Avísale a la organización. "
                f"({fila.get('error_respaldo', 'sin detalle')})")

        if "f1_no_visto" in res:
            m = st.columns(6)
            m[0].metric("F1 micro", f"{res['f1_micro']:.3f}")
            m[1].metric("F1 no visto", f"{res['f1_no_visto']:.3f}",
                        help="Solo las etiquetas que no venían en tu paquete de "
                             "entrenamiento. Entregar el paquete tal cual da 0.00 "
                             "acá. (No decimos cuántas son.)")
            resto = m[2:]
        else:
            m = st.columns(5)
            m[0].metric("F1 micro", f"{res['f1_micro']:.3f}")
            resto = m[1:]
        resto[0].metric("F1 macro", f"{res['f1_macro']:.3f}")
        resto[1].metric("Precisión", f"{res['precision']:.3f}")
        resto[2].metric("Recall", f"{res['recall']:.3f}")
        resto[3].metric("TP / FP / FN", f"{res['tp']} / {res['fp']} / {res['fn']}")

        # `n_verdad` es el conteo del ground truth por especie: no se muestra.
        # Y solo se listan las especies que el equipo ya conoce o que predijo:
        # una fila para una especie que nunca vio le revelaría que existe.
        visible = detalle[detalle.scientific_name.isin(ESPECIES_VISIBLES)
                          | detalle.n_pred.gt(0)]
        st.dataframe(visible.drop(columns=["n_verdad"]),
                     hide_index=True, width="stretch")
        if res["precision"] < res["recall"] / 2:
            st.info("Tu precisión es mucho más baja que tu recall: estás prediciendo "
                    "de más. Prueba subiendo el umbral de decisión.")
        elif res["recall"] < res["precision"] / 2:
            st.info("Tu recall es mucho más bajo que tu precisión: estás siendo "
                    "conservador. Prueba bajando el umbral.")

    with st.expander("Formato esperado"):
        st.markdown(
            "Una fila por **(segmento, especie detectada)**. Un segmento sin filas "
            "significa «no hay ave» — no rellenes, los falsos positivos penalizan."
        )
        st.code("id_grabacion,segmento,scientific_name,confidence\n"
                "grabadora-1/20240625_083000.WAV,40,Aphrastura spinicauda,0.87\n"
                "grabadora-1/20240625_083000.WAV,62,Turdus falcklandii,0.61",
                language="csv")


# ─────────────────────────────────────────────────────────── Admin
with tab_admin:
    st.subheader("Panel de administración")
    if not cfg.CLAVE_ADMIN:
        # Sin clave configurada el panel no se abre. Es deliberado: antes había
        # un valor por defecto en config.py, que va al repo — o sea, publicado.
        st.error(
            "El panel está cerrado porque no hay clave configurada. Defínela "
            "como variable de entorno `CLAVE_ADMIN` antes de lanzar la app, o "
            "en **Settings → Secrets** si corre en Streamlit Cloud. El resto "
            "del ranking funciona igual.")
        st.stop()
    if st.text_input("Clave", type="password") != cfg.CLAVE_ADMIN:
        st.stop()

    st.success("Acceso concedido.")
    log = almacen.leer_log()

    st.markdown("#### Renombrar un equipo")
    st.caption("El nombre es la clave con la que se agrupan los envíos. Esto lo "
               "cambia en `equipos.json` **y** en el log, para no dejar un equipo "
               "fantasma en el ranking. El token no cambia.")
    col_v, col_n, col_b = st.columns([2, 2, 1])
    viejo = col_v.selectbox("Equipo", sorted(EQUIPOS), key="renombrar_viejo",
                            label_visibility="collapsed")
    nuevo = col_n.text_input("Nombre nuevo", key="renombrar_nuevo",
                             placeholder="Nombre nuevo",
                             label_visibility="collapsed")
    if col_b.button("Renombrar", disabled=not nuevo.strip()):
        try:
            n = almacen.renombrar(viejo, nuevo)
        except (KeyError, ValueError) as e:
            st.error(str(e))
        else:
            st.success(f"«{viejo}» → «{nuevo}» · {n} envío(s) reasignado(s). "
                       "Recarga la página.")

    st.markdown("#### Set privado")
    if not (cfg.DIR_PRIVADO / "ground_truth_segmentos.csv").exists():
        # El texto describe el estado del disco y nada más. Cualquier afirmación
        # sobre cómo se puntúa *esta* edición iría en las notas privadas, no acá:
        # el repo es público y saber si hay o no set ciego le cambia la
        # estrategia a un equipo.
        st.info(
            f"No hay set privado cargado en `{cfg.DIR_PRIVADO}`. Para activar "
            "este botón, pon ahí un ground truth con "
            "`preparar_datos.py --destino privado`."
        )
    elif st.button("Puntuar todos los envíos contra el set privado"):
        ev_priv = Evaluador(str(cfg.DIR_PRIVADO))
        filas = []
        for _, r in almacen.mejores_por_equipo(log).iterrows():
            sub = pd.read_csv(cfg.DIR_ARCHIVOS / r.archivo)
            res = ev_priv.evaluar(sub, cfg.NIVEL)
            lo, hi = ev_priv.intervalo(sub, cfg.NIVEL, n=cfg.BOOTSTRAP_N)
            filas.append({"equipo": r.equipo, "publico": r[cfg.METRICA],
                          "privado": res[cfg.METRICA], "ic_lo": lo, "ic_hi": hi})
        final = pd.DataFrame(filas).sort_values("privado", ascending=False)
        final["caída"] = (final.privado - final.publico).round(3)
        st.dataframe(final, hide_index=True, width="stretch")
        st.caption("Una caída grande público→privado es sobreajuste al set de "
                   "desarrollo. Vale la pena comentarlo en el cierre.")

    st.markdown("#### Señales de revisión")
    if not log.empty:
        alertas = []
        for _, r in almacen.mejores_por_equipo(log).iterrows():
            sub = pd.read_csv(cfg.DIR_ARCHIVOS / r.archivo)
            col = next((c for c in ("scientific_name", "especie", "species")
                        if c in sub.columns), None)
            emitidas = set(sub[col].dropna().astype(str).str.strip()) if col else set()

            # Esta alerta no necesita configuración: se deduce del propio ground
            # truth, así que no hay nada que filtrar del código para evadirla.
            fuera = sorted(emitidas - set(ev.especies))
            if fuera:
                alertas.append({"equipo": r.equipo, "señal": "especies fuera del GT",
                                "detalle": ", ".join(fuera[:5])})

            # Las delatoras sí van en secrets: nombrarlas en un repo público
            # sería decirle a los equipos exactamente qué borrar del CSV.
            delatoras = sorted(emitidas & set(cfg.ESPECIES_DELATORAS))
            if delatoras:
                alertas.append({"equipo": r.equipo, "señal": "especies de la lista",
                                "detalle": ", ".join(delatoras)})

            if cfg.UMBRAL_SOSPECHA is not None and r[cfg.METRICA] > cfg.UMBRAL_SOSPECHA:
                alertas.append({"equipo": r.equipo, "señal": "puntaje muy alto",
                                "detalle": f"{r[cfg.METRICA]:.3f}"})
        st.dataframe(pd.DataFrame(alertas) if alertas else
                     pd.DataFrame([{"señal": "sin alertas"}]),
                     hide_index=True, width="stretch")
        st.caption(
            "Ninguna de estas señales es descalificación automática: son pistas "
            "para decidir a quién revisarle el código. **El podio se cierra con el "
            "código de los tres primeros a la vista antes de adjudicar**, y esa "
            "instancia pesa en la decisión: con intervalos de ±0.15 la tabla ordena "
            "pero no separa a los de arriba. Si dos quedan pegados, el desempate "
            "numérico es «F1 no visto», no F1 macro."
        )
        faltantes = ([] if cfg.ESPECIES_DELATORAS else ["`ESPECIES_DELATORAS`"]) + \
                    ([] if cfg.UMBRAL_SOSPECHA is not None else ["`UMBRAL_SOSPECHA`"])
        if faltantes:
            st.caption(f"⚠️ Sin configurar en *Secrets*: {', '.join(faltantes)} — "
                       "esas señales están apagadas. Los valores recomendados "
                       "están en las notas privadas de organización.")

    st.markdown("#### Segmentos disputados")
    st.caption("Segmentos donde los equipos se dividen: son los mejores candidatos "
               "a error del ground truth. Auditoría gratis.")
    if len(log) >= 2:
        votos: dict[tuple, set] = {}
        for _, r in almacen.mejores_por_equipo(log).iterrows():
            sub = pd.read_csv(cfg.DIR_ARCHIVOS / r.archivo)
            for k in ev._claves(sub, "segmento"):
                votos.setdefault(k, set()).add(r.equipo)
        n_eq = log.equipo.nunique()
        verdad = ev._claves(ev.gt_segmentos, "segmento")
        disputa = [{"id_grabacion": k[0], "segmento": k[1], "especie": k[2],
                    "equipos_que_lo_dicen": len(v), "en_ground_truth": k in verdad}
                   for k, v in votos.items()
                   if len(v) >= max(2, n_eq * 0.6) and k not in verdad]
        st.dataframe(pd.DataFrame(disputa).sort_values(
            "equipos_que_lo_dicen", ascending=False).head(40)
            if disputa else pd.DataFrame([{"info": "sin disputas"}]),
            hide_index=True, width="stretch")

    st.markdown("#### Respaldo")
    if not respaldo.activo():
        st.warning(
            "**El respaldo remoto está apagado.** Corriendo en local no importa: "
            "el estado vive en tu disco. En Streamlit Cloud sí importa, porque el "
            "disco del contenedor se borra en cada reinicio — configura "
            "`GITHUB_TOKEN` y `REPO_ESTADO` en *Settings → Secrets* (ver "
            "`respaldo.py`), o descarga el log a mano cada pocas horas.")
    else:
        _, _repo = respaldo._credenciales()
        _nota = ("restaurados al arrancar: " + ", ".join(_restaurados)
                 if _restaurados else "no hizo falta restaurar nada al arrancar")
        st.caption(f"Respaldando en `{_repo}` — {_nota}.")
        if st.button("Forzar respaldo completo"):
            # Red de seguridad: si alguna subida falló durante el evento, esto
            # la repone sin esperar al próximo envío.
            try:
                subidos = [r for r, p in respaldo._todo_lo_local().items()
                           if respaldo.subir(r, p, "respaldo manual")]
                st.success(f"{len(subidos)} archivo(s) respaldado(s).")
            except Exception as e:                           # noqa: BLE001
                st.error(f"Falló el respaldo: {e}")

    st.download_button("Descargar log completo", log.to_csv(index=False),
                       "log_envios.csv", "text/csv")
