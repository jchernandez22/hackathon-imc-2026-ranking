"""
Copia el ground truth generado por `birdnet_ground_truth.ipynb` a `datos/publico/`.

    python preparar_datos.py                     # set público (por defecto)
    python preparar_datos.py --destino privado   # cuando lleguen las nuevas grabaciones

El set privado se arma igual, pero apuntando `--origen` a la corrida de BirdNET
sobre las grabaciones diurnas nuevas. Esas nunca se entregan a los equipos.
"""
import argparse
import pathlib
import shutil

import config as cfg

NECESARIOS = ["segmentos_a_predecir.csv",
              "ground_truth_segmentos.csv",
              "ground_truth_presencia.csv"]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--origen", default="../birdnet_ground_truth",
                   help="carpeta de salida del notebook de BirdNET")
    p.add_argument("--destino", choices=["publico", "privado"], default="publico")
    args = p.parse_args()

    origen = pathlib.Path(args.origen)
    destino = cfg.DIR_PUBLICO if args.destino == "publico" else cfg.DIR_PRIVADO
    destino.mkdir(parents=True, exist_ok=True)

    for nombre in NECESARIOS:
        # `segmentos_a_predecir.csv` vive en paquete_hackathon/, el resto en la raíz.
        for candidato in (origen / nombre, origen / "paquete_hackathon" / nombre):
            if candidato.exists():
                shutil.copy2(candidato, destino / nombre)
                print(f"  {nombre:<32} <- {candidato}")
                break
        else:
            raise FileNotFoundError(
                f"No encuentro '{nombre}' bajo {origen}. "
                "¿Corriste el notebook de BirdNET?"
            )
    print(f"\nListo: {destino}")


if __name__ == "__main__":
    main()
