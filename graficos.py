"""
Gráficos del dashboard, en Altair.

Altair viene incluido con Streamlit y renderiza SVG: se estira al ancho del
contenedor, queda nítido en cualquier pantalla y trae tooltips gratis. Están
separados de `app.py` para poder previsualizarlos sin levantar el servidor:

    python graficos.py        # escribe /tmp/preview_*.png
"""
from __future__ import annotations

import altair as alt
import pandas as pd

import config as cfg

FUENTE = "Helvetica Neue, Avenir Next, Segoe UI, Inter, sans-serif"

# Alto de cada fila del ranking, en píxeles. Altair lo usa como `Step`, así que
# el gráfico crece con el número de equipos en vez de comprimirlos.
PASO = 34


def _tema() -> dict:
    """Configuración común: fondo, tipografía y ejes recesivos."""
    return {
        "background": cfg.SUPERFICIE,
        "font": FUENTE,
        "view": {"stroke": None},
        "axis": {
            "labelFont": FUENTE, "titleFont": FUENTE,
            "labelColor": cfg.MUTED, "titleColor": cfg.TINTA2,
            "labelFontSize": 11, "titleFontSize": 11, "titleFontWeight": "normal",
            "domainColor": cfg.GRID, "tickColor": cfg.GRID,
            "gridColor": cfg.GRID, "gridWidth": 1,
            "titlePadding": 10,
        },
        "legend": {
            "labelFont": FUENTE, "titleFont": FUENTE,
            "labelColor": cfg.TINTA2, "titleColor": cfg.MUTED,
            "labelFontSize": 11, "titleFontSize": 10, "titleFontWeight": "normal",
            "symbolType": "stroke", "symbolStrokeWidth": 3, "offset": 16,
        },
        "text": {"font": FUENTE},
    }


def grafico_ranking(mejores: pd.DataFrame, metrica: str = cfg.METRICA):
    """
    Ranking horizontal: una barra por equipo, con su puesto, su nombre y su
    valor. El intervalo de confianza no se dibuja —queda en el tooltip y en la
    tabla— para que la barra sea solo la barra.
    """
    d = (mejores.sort_values(metrica, ascending=False)
         .reset_index(drop=True).copy())
    d["puesto"] = d.index + 1
    d["valor"] = d[metrica]
    d["etiqueta"] = d.puesto.astype(str) + " " + d.equipo   # clave del eje Y
    d["nombre"] = d.equipo.str.slice(0, 26)
    # El intervalo se recorta al eje: un IC que se sale de [0, 1] es ruido del
    # bootstrap, no información.
    d["lo"] = d[["ic_lo", "valor"]].min(axis=1).clip(0, 1)
    d["hi"] = d[["ic_hi", "valor"]].max(axis=1).clip(0, 1)
    d["texto"] = d.valor.map("{:.2f}".format)
    if "n_envios" not in d:
        d["n_envios"] = pd.NA
    filas = list(d.etiqueta)

    # Canal a la izquierda de 0 para el puesto y el nombre. Va dentro del
    # dominio de x —no como etiquetas de eje— para poder alinear las dos
    # columnas; al ser parte de la escala, se estira junto con el gráfico.
    # El dominio llega a 1.06 y no a 1: el 0.06 de cola es el espacio donde cabe
    # la cifra de un equipo que casi llegue al máximo sin que se corte.
    X_PUESTO, X_NOMBRE = -0.315, -0.295
    escala_x = alt.Scale(domain=[-0.36, 1.06], nice=False)
    eje_x = alt.Axis(values=[0, 0.25, 0.5, 0.75, 1], format=".2f",
                     grid=True, domain=False, ticks=False,
                     title=metrica.replace("_", " "), orient="bottom")

    def ex(campo):
        return alt.X(campo, scale=escala_x, axis=eje_x)

    y = alt.Y("etiqueta:N", sort=filas, scale=alt.Scale(domain=filas),
              title=None, axis=None)
    tips = [
        alt.Tooltip("equipo:N", title="Equipo"),
        alt.Tooltip("puesto:Q", title="Puesto"),
        alt.Tooltip("valor:Q", title=metrica.replace("_", " "), format=".3f"),
        alt.Tooltip("lo:Q", title="IC 95 % desde", format=".3f"),
        alt.Tooltip("hi:Q", title="IC 95 % hasta", format=".3f"),
        alt.Tooltip("n_envios:Q", title="Envíos"),
    ]

    base = alt.Chart(d).encode(y=y)
    # 1. la barra: desde 0 hasta el valor, y nada más.
    barra = base.mark_bar(color=cfg.AZUL, height=13, cornerRadiusEnd=3).encode(
        x=ex("valor:Q"), tooltip=tips)
    # 2. valor, pegado a la punta de su barra.
    valor = base.mark_text(align="left", dx=6, fontSize=12,
                           color=cfg.TINTA).encode(
        x=ex("valor:Q"), text="texto:N")

    # 3-4. puesto y nombre, en el canal de la izquierda.
    puesto = base.mark_text(align="right", fontSize=12, color=cfg.MUTED).encode(
        x=ex("x:Q"), text="puesto:Q").transform_calculate(x=str(X_PUESTO))
    # `limit` recorta con puntos suspensivos en vez de invadir las barras; el
    # nombre completo queda en el tooltip.
    nombre = base.mark_text(align="left", fontSize=12.5, color=cfg.TINTA2,
                            limit=180).encode(
        x=ex("x:Q"), text="nombre:N", tooltip=tips,
    ).transform_calculate(x=str(X_NOMBRE))

    return alt.layer(barra, valor, puesto, nombre).properties(
        width="container", height=alt.Step(PASO)).configure(**_tema())


def grafico_progreso(log: pd.DataFrame, metrica: str = cfg.METRICA):
    """Mejor puntaje acumulado de cada equipo a lo largo del evento."""
    d = log.sort_values("ts").copy()
    d["mejor"] = d.groupby("equipo")[metrica].cummax()
    # Orden fijo por posición final: el color sigue al equipo, no a su puesto
    # dentro de un filtro.
    orden = list(d.groupby("equipo").mejor.max()
                 .sort_values(ascending=False).index)
    escala = alt.Scale(domain=orden, range=list(cfg.SERIES[:len(orden)]))

    # Resaltado al pasar el mouse: la curva apuntada se queda opaca y el resto
    # se desvanece. Con ocho equipos superpuestos es la diferencia entre poder
    # seguir una curva y no poder.
    foco = alt.selection_point(fields=["equipo"], on="pointerover",
                               nearest=True, empty=True)
    resalte = alt.when(foco).then(alt.value(1.0)).otherwise(alt.value(0.25))

    base = alt.Chart(d).encode(
        x=alt.X("ts:T", title=None,
                axis=alt.Axis(format="%H:%M", grid=False, tickCount=8)),
        y=alt.Y("mejor:Q", title=f"{metrica.replace('_', ' ')} — mejor hasta ahora",
                scale=alt.Scale(domain=[0, min(1.0, max(0.4, d.mejor.max() * 1.15))],
                                nice=False),
                axis=alt.Axis(grid=True, domain=False, ticks=False)),
        color=alt.Color("equipo:N", scale=escala, title="Equipo",
                        # El orden de la leyenda sale del dominio de la escala,
                        # que ya viene ordenado por puesto final.
                        legend=alt.Legend(orient="right", labelLimit=180)),
    )

    linea = base.mark_line(interpolate="step-after", strokeWidth=2.5,
                           strokeCap="round").encode(opacity=resalte)
    puntos = base.mark_point(filled=True, size=55, stroke=cfg.SUPERFICIE,
                             strokeWidth=1.5).encode(
        opacity=resalte,
        tooltip=[alt.Tooltip("equipo:N", title="Equipo"),
                 alt.Tooltip("ts:T", title="Hora", format="%d %b %H:%M"),
                 alt.Tooltip(f"{metrica}:Q", title="Este envío", format=".3f"),
                 alt.Tooltip("mejor:Q", title="Mejor hasta ahí", format=".3f")],
    ).add_params(foco)

    return alt.layer(linea, puntos).properties(
        width="container", height=380).configure(**_tema())


def estilo_matriz(matriz: pd.DataFrame) -> "pd.io.formats.style.Styler":
    """
    Colorea la matriz de F1 por especie con una rampa secuencial propia.

    Reemplaza a `Styler.background_gradient(cmap="Blues")`, que exige matplotlib:
    son ~50 MB de build en Streamlit Cloud para pintar celdas, y además la rampa
    de matplotlib no es la paleta del resto del tablero.

    Un solo tono, claro→oscuro, como corresponde a una escala de magnitud. La
    mezcla se detiene en 0.75 del azul y no en el azul pleno: a plena intensidad
    el contraste con la tinta cae a 4.46:1 —bajo el mínimo AA de 4.5— y a 0.75
    sube a 6.65:1. El número se lee en todas las celdas sin invertir el color del
    texto, así que la celda nunca depende del color para ser legible.
    """
    fondo, tope = (252, 252, 251), (42, 120, 214)          # SUPERFICIE -> AZUL

    def color(v: float) -> str:
        if pd.isna(v):
            return ""
        t = min(max(float(v), 0.0), 1.0) * 0.75
        r, g, b = (round(f + (c - f) * t) for f, c in zip(fondo, tope))
        return f"background-color: #{r:02x}{g:02x}{b:02x}"

    return (matriz.style
            .map(color)
            .format("{:.2f}")
            .set_properties(**{"color": cfg.TINTA}))


if __name__ == "__main__":
    import almacen

    m = almacen.mejores_por_equipo()

    # `width="container"` solo lo entiende el navegador; para la vista previa
    # se sustituye por un ancho concreto.
    def _png(chart, ruta, ancho=900):
        import json
        import vl_convert as vlc
        spec = chart.to_dict()
        spec["width"] = ancho
        with open(ruta, "wb") as f:
            f.write(vlc.vegalite_to_png(json.dumps(spec), scale=2.0))
        print(ruta)

    _png(grafico_ranking(m), "/tmp/preview_ranking.png")
    _png(grafico_progreso(almacen.leer_log()), "/tmp/preview_progreso.png")
