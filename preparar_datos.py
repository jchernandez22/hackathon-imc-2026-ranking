"""
Copia el ground truth a `datos/publico/`.


⚠️  **El ground truth bueno ya no lo produce el notebook.** Lo produce
`validar_oido.py --aplicar --umbral 0.16`, que aplica los veredictos a oído sobre
las dos corridas de BirdNET (12 archivos + 8 archivos = 20). La salida del
notebook, `../birdnet_ground_truth/`, es la corrida vieja a umbral 0.5 sobre 12
archivos: 117 etiquetas y 5.700 segmentos. Sirve como **entrenamiento**, no como
ground truth.

Copiar la una encima de la otra destruye el set puntuado en silencio, así que
`--origen` ya no tiene default y hay un guardia que se niega a reemplazar un
ground truth por uno más chico. Para rehacer el set puntuado:

    python ../validar_oido.py --aplicar --umbral 0.16 --destino datos/publico
"""
import argparse
import pathlib
import shutil

import pandas as pd

import config as cfg

NECESARIOS = ["segmentos_a_predecir.csv",
              "ground_truth_segmentos.csv",
              "ground_truth_presencia.csv"]

CLAVE = ["id_grabacion", "segmento", "scientific_name"]


def _guardia(nuevo: pathlib.Path, actual: pathlib.Path, forzar: bool) -> None:
    """
    Se niega a reemplazar un archivo por otro con menos filas.

    Existe porque ya pasó: la corrida vieja del notebook sobrescribió el set
    puntuado sin decir una palabra, y el ranking habría corrido contra un ground
    truth equivocado. Perder etiquetas nunca es lo que uno quiere al «preparar
    datos».
    """
    if forzar or not actual.exists():
        return
    n_nuevo, n_actual = len(pd.read_csv(nuevo)), len(pd.read_csv(actual))
    if n_nuevo < n_actual:
        raise SystemExit(
            f"\n✋ {actual.name}: el origen tiene MENOS filas que lo que ya está.\n"
            f"     ahora:  {n_actual:>6,} filas   ({actual})\n"
            f"     origen: {n_nuevo:>6,} filas   ({nuevo})\n\n"
            "   Si `--origen` apunta a ../birdnet_ground_truth, esa es la corrida\n"
            "   vieja a umbral 0.5 sobre 12 archivos: es el ENTRENAMIENTO, no el\n"
            "   ground truth. El set puntuado se rehace con:\n\n"
            "       python ../validar_oido.py --aplicar --umbral 0.16 "
            "--destino datos/publico\n\n"
            "   Si de verdad quieres achicar el set, repite con --forzar.\n"
        )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--origen", required=True,
                   help="carpeta con el ground truth a copiar. NO uses "
                        "../birdnet_ground_truth: esa es la corrida vieja de 117 "
                        "etiquetas y te sobrescribe el set puntuado.")
    p.add_argument("--entrenamiento", default="../birdnet_ground_truth/ground_truth_segmentos.csv",
                   help="etiquetas que se les entregan a los equipos; habilitan "
                        "la columna «no visto». Vacío para omitirlas.")
    p.add_argument("--forzar", action="store_true",
                   help="permite reemplazar un ground truth por uno más chico")
    args = p.parse_args()

    origen = pathlib.Path(args.origen)
    destino = cfg.DIR_PUBLICO
    destino.mkdir(parents=True, exist_ok=True)

    for nombre in NECESARIOS:
        # `segmentos_a_predecir.csv` vive en paquete_hackathon/, el resto en la raíz.
        for candidato in (origen / nombre, origen / "paquete_hackathon" / nombre):
            if candidato.exists():
                _guardia(candidato, destino / nombre, args.forzar)
                shutil.copy2(candidato, destino / nombre)
                print(f"  {nombre:<32} <- {candidato}")
                break
        else:
            raise FileNotFoundError(
                f"No encuentro '{nombre}' bajo {origen}. "
                "¿Corriste el notebook de BirdNET?"
            )

    # Las etiquetas que tienen los equipos. El evaluador las usa para la columna
    # «no visto»: quien copia el entrenamiento tal cual queda en 0.00 ahí.
    if args.entrenamiento:
        src = pathlib.Path(args.entrenamiento)
        if not src.exists():
            raise FileNotFoundError(f"No existe el entrenamiento: {src}")
        pd.read_csv(src)[CLAVE].drop_duplicates().to_csv(
            destino / "etiquetas_entrenamiento.csv", index=False)
        print(f"  {'etiquetas_entrenamiento.csv':<32} <- {src}")

    print(f"\nListo: {destino}")
    print("\nFalta la lista de ignoradas — se genera aparte, cruza `validacion/`:")
    print("    python ../preparar_ignoradas.py")


if __name__ == "__main__":
    main()
