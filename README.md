# Ranking — Hackathon IMC 2026

Dashboard de envíos y leaderboard. Los equipos suben su `submission.csv`, lo ven
puntuado al instante, y el ranking se actualiza solo.

```bash
pip install -r requirements.txt
python ../validar_oido.py --aplicar --umbral 0.16 --destino datos/publico
python ../preparar_ignoradas.py   # marca lo que no se puntúa
streamlit run app.py
```

⚠️ **No corras `preparar_datos.py` a secas.** El ground truth bueno lo produce
`validar_oido.py --aplicar`, no el notebook: aplica los veredictos a oído sobre
las dos corridas de BirdNET (20 grabaciones). `../birdnet_ground_truth/`
es la corrida vieja a umbral 0.5 sobre 12 archivos y sirve de **entrenamiento**,
no de referencia. Copiarla encima
destruye el set puntuado. `--origen` ya es obligatorio y hay un guardia que se
niega a reemplazar un archivo por otro con menos filas, pero el orden correcto es
el de arriba.

## Archivos

| Archivo               | Qué hace                                                                                    |
| --------------------- | -------------------------------------------------------------------------------------------- |
| `app.py`            | El dashboard: ranking, por especie, progreso, envío y panel de admin                       |
| `evaluador.py`      | **La lógica de puntaje.** Sin dependencias de Streamlit; lo usan también los equipos |
| `graficos.py`       | Los dos gráficos, en Altair.`python graficos.py` los deja en `/tmp/preview_*.png`       |
| `almacen.py`        | Persistencia: log append-only en CSV + copia de cada envío                                  |
| `config.py`         | Todos los parámetros de operación. Es el único archivo que se toca en vivo                |
| `preparar_datos.py` | Copia el ground truth desde la salida del notebook de BirdNET                                |
| `simular.py`        | Genera envíos falsos para probar el tablero antes del evento                                |
| `respaldo.py`       | Espeja el estado en un repo privado aparte y lo repone al arrancar. Sin configurar, es un no-op |
| `equipos.json`      | `{equipo: token}`. **No va al repo** (está en `.gitignore`): el token de cada equipo es la contraseña de su correo |
| `equipos.ejemplo.json` | La plantilla que sí va al repo, con tokens falsos                                        |

## Antes del evento — lista de chequeo

1. **Repartir los tokens** de `equipos.json`, uno por equipo. Son la contraseña
   del correo `hackathon.imc.2026.gN@gmail.com` de cada uno, así que el archivo
   está en `.gitignore` y quien despliegue tiene que copiarlo a mano al servidor
   (partiendo de `equipos.ejemplo.json`).
2. **Exportar `CLAVE_ADMIN`** antes de lanzar la app (`export CLAVE_ADMIN='...'`,
   o *Settings → Secrets* en Streamlit Cloud). No tiene valor por defecto a
   propósito: `config.py` va al repo, así que cualquier default sería una
   contraseña publicada. Sin ella el panel de organización queda cerrado y el
   resto del ranking funciona igual.
3. Ajustar `INICIO` y `CIERRE` en `config.py`.
4. Probar con `python simular.py`, revisar que el tablero se ve bien, y limpiar
   con `python simular.py --limpiar`.
5. Verificar que `datos/` y `equipos.json` están en `.gitignore`. **Este repo es
   público: si el ground truth llega acá, se acabó la competencia**, y borrarlo
   con un commit no sirve porque queda en el historial.

## Renombrar un equipo

El octavo equipo está registrado como «Equipo 8 (sin nombre)» hasta que elija uno.
Para cambiarlo, usa **Admin → Renombrar un equipo**, no edites `equipos.json`
a mano: el nombre es la clave con la que se agrupan los envíos, así que cambiarlo
solo en el JSON dejaría los envíos anteriores colgando como un equipo fantasma en
el ranking. El botón lo cambia en los dos lados y conserva el token.

Antes de que el equipo haya enviado nada da lo mismo — el log está vacío.

## El set privado

`datos/privado/` está soportado por el panel de admin: si hay un ground truth
ahí, aparece el botón para puntuar todos los envíos contra él y comparar la caída
público→privado. Si no lo hay, el botón no aparece.

Para poblarlo se corre el notebook de BirdNET sobre las grabaciones nuevas y
después `preparar_datos.py --destino privado`. **Si el audio nuevo va en la misma
carpeta que el público, el notebook lo barre con `rglob` y se mezclan**: tiene que
ir en un directorio hermano.

## Por qué micro y no macro

La distribución de especies del ground truth es muy desbalanceada: unas pocas
concentran la mayoría de los segmentos y la cola tiene especies con uno o dos.
Esas de la cola no son aprendibles en 24 horas.

Con **F1 macro**, la especie con un solo ejemplo pesa lo mismo que la que tiene
cien: acertarla por casualidad mueve el puntaje varios puntos y decide el podio
al azar. Con **F1 micro**, el reto sigue siendo difícil pero mide lo que un
equipo puede realmente controlar.

El macro se muestra igual como columna informativa, y la pestaña «Por especie»
deja ver el detalle. Para cambiarlo, `METRICA` en `config.py`.

## El intervalo de confianza

El ranking muestra un intervalo de confianza al 95 %, calculado por bootstrap
**remuestreando grabaciones, no segmentos** (los segmentos de una misma grabación
están correlacionados: un canto ocupa varios seguidos, así que remuestrearlos
daría un intervalo falsamente angosto). No se dibuja sobre las barras —la barra
es solo la barra—: aparece en el tooltip de cada equipo y como columna en la
tabla completa.

Con este set los intervalos salen anchos — del orden de ±0.15. Lo que los
gobierna no es cuántos segmentos hay sino cuántas grabaciones aportan positivos,
y son pocas: remuestrear pocas unidades no da precisión por más segmentos que
haya dentro. **Tenlo presente al leer el ranking: dos equipos separados por 0.02
no están de verdad separados.**

Si al cierre los dos primeros siguen con los intervalos solapados, el desempate
razonable es F1 macro, y después la revisión de código.

## Cuota de envíos

`ENVIOS_POR_DIA = 5`. Es la defensa contra el sondeo del leaderboard —enviar
muchas variantes para inferir el ground truth a punta de puntajes— y tiene un
efecto pedagógico: obliga a validar localmente antes de enviar. **Un CSV que
falla la validación de formato no consume cuota**: se penaliza el sobreajuste,
no el descuido.

## Despliegue

**Streamlit Community Cloud, con el respaldo de `respaldo.py` encendido.**

El disco del contenedor es efímero: se reconstruye desde el repo en cada reinicio
—push, reboot manual, inactividad, límite de memoria— y todo lo que la app
escribió se pierde. `envios/log.csv` y las submissions son justamente eso, y
`app.py` vuelve a leer los CSV crudos en cuatro lugares (por especie, set
privado, señales, disputados), así que perderlos rompe más que el ranking.

`respaldo.py` cierra ese agujero: espeja el estado en un **repositorio privado
aparte** y lo repone al arrancar. Aparte por dos razones —un gist «secreto» lo
abre cualquiera con la URL y ahí va el ground truth; y escribir en el repo de la
app reiniciaría el contenedor en cada envío, borrando lo que acaba de guardar.

### Puesta en marcha

```bash
python simular.py --limpiar               # que el evento no arranque con datos falsos
export GITHUB_TOKEN=$(gh auth token)
python respaldo.py --crear                # crea el repo de estado y sube GT + equipos
```

Imprime las dos líneas que van en **Settings → Secrets** de Streamlit, junto con
la clave del panel:

```toml
CLAVE_ADMIN        = "..."
REPO_ESTADO        = "usuario/hackathon-imc-2026-estado"
GITHUB_TOKEN       = "github_pat_..."
ESPECIES_DELATORAS = "..."     # ver notas privadas de organización
UMBRAL_SOSPECHA    = "..."     # idem
```

El token de `gh auth token` sirve, pero caduca; para el evento conviene uno
*fine-grained* con acceso **solo** al repo de estado y permiso de contenidos
lectura/escritura. Si se filtra, no toca nada más.

**Este repositorio es público.** Todo lo competitivamente sensible —el ground
truth, los tokens, y qué mira el panel de revisión— vive fuera: en el repo de
estado, en los *secrets*, o en las notas privadas de organización. Al tocar este
repo, la pregunta es siempre «¿esto le sirve a un equipo para subir sin modelar?».

En Cloud: apuntar a este repo, branch `main`, archivo `app.py`.

### Durante el evento

- **No hagas push al repo de la app.** Cada push reinicia el contenedor. El
  estado se recupera solo, pero es un bajón innecesario a mitad de competencia.
- **Admin → Respaldo** dice dónde está respaldando y qué restauró al arrancar.
  Si una subida falló, «Forzar respaldo completo» la repone.
- Un envío que se registra pero no se respalda **se lo avisa al equipo** en
  pantalla. Si ves ese aviso, revisa el token.

### Alternativa: local con túnel

Si prefieres no depender de Cloud y el Mac se queda quieto y conectado 24 h:

```bash
export CLAVE_ADMIN='...'
streamlit run app.py --server.port 8501
cloudflared tunnel --url http://localhost:8501     # en otra terminal
caffeinate -dis                                    # que no se duerma
```

Aquí el estado vive en tu disco y `respaldo.py` sobra. El costo es el inverso: si
el túnel se cae la URL cambia y hay que avisarle a ocho equipos en vivo, así que
con `ngrok` conviene reservar el dominio estático del plan gratis.

## Señales de revisión

El panel de admin marca envíos que conviene mirar de cerca. Ninguna señal es
descalificación automática: son pistas para decidir a quién revisarle el código.
**El ranking público es provisional; el final se define tras esa revisión**, y
conviene anunciarlo desde el inicio.

Qué se marca exactamente **no está en este repositorio**, y es deliberado: es
público, así que escribirlo aquí sería entregarle a los equipos la receta para no
ser detectados. Se configura por `ESPECIES_DELATORAS` y `UMBRAL_SOSPECHA` en
*Secrets*; los valores están en las notas privadas de organización. Sin ellos
esas señales quedan apagadas y el panel lo dice en pantalla.

La alerta de **«especies fuera del ground truth»** funciona siempre, sin
configurar: se deduce del propio GT, así que no hay nada en el código que un
equipo pueda leer para evadirla.
