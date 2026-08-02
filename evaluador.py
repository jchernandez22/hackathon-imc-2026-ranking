"""
Evaluador oficial — Hackathon IMC 2026.

Módulo compartido: lo usa el dashboard (`app.py`), el notebook de arranque de los
equipos y cualquier script de organización. No depende de Streamlit.

    from evaluador import Evaluador
    ev = Evaluador("datos/publico")
    ev.validar(df)                      # -> lista de errores (vacía = OK)
    ev.evaluar(df, nivel="segmento")    # -> dict con f1_micro, f1_macro, ...
    ev.intervalo(df, nivel="segmento")  # -> (lo, hi) bootstrap sobre grabaciones

Dos archivos opcionales en el directorio de datos cambian qué se cuenta:

    etiquetas_ignoradas.csv      Etiquetas que no se puntúan ni a favor ni en
                                 contra: salen del ground truth y de la entrega.
                                 Son las que no podemos defender — la validación
                                 a oído contestó "¿hay un ave?", nunca "¿es esta
                                 especie?". Las genera `preparar_ignoradas.py`.

    etiquetas_entrenamiento.csv  Las que se les entregaron a los equipos.
                                 Habilitan `f1_no_visto` en el resultado.

Sin ellos el evaluador se comporta igual que antes.
"""
from __future__ import annotations

import pathlib
from collections import defaultdict

import numpy as np
import pandas as pd

# La métrica del ranking. Ver README.md § "Por qué micro y no macro".
METRICA = "f1_micro"
NIVEL_RANKING = "segmento"

COLS_ESPECIE = ("scientific_name", "especie", "species")


# --------------------------------------------------------------------------- #
# Utilidades de conteo
# --------------------------------------------------------------------------- #
def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def _capitalizar(s: pd.Series) -> pd.Series:
    """'TURDUS  falcklandii ' -> 'Turdus falcklandii'."""
    return (s.astype(str).str.strip()
            .str.replace(r"\s+", " ", regex=True)
            .str.capitalize())


class ErrorDeFormato(ValueError):
    """La entrega no se puede evaluar. El mensaje explica exactamente por qué."""


# --------------------------------------------------------------------------- #
class Evaluador:
    """Evalúa entregas contra un ground truth. Una instancia por set (público/privado)."""

    def __init__(self, dir_datos: str | pathlib.Path):
        d = pathlib.Path(dir_datos)
        if not d.exists():
            raise FileNotFoundError(f"No existe el directorio de datos: {d}")

        self.dir = d
        self.grilla = pd.read_csv(d / "segmentos_a_predecir.csv")
        self.gt_segmentos = pd.read_csv(d / "ground_truth_segmentos.csv")
        self.gt_presencia = pd.read_csv(d / "ground_truth_presencia.csv")

        self.ids_validos = set(self.grilla["id_grabacion"])
        self.segmentos_validos = set(zip(self.grilla["id_grabacion"], self.grilla["segmento"]))
        self.especies = sorted(self.gt_segmentos["scientific_name"].unique())

        # Etiquetas que no se puntúan ni a favor ni en contra, y etiquetas que se
        # entregaron como entrenamiento. Las dos son opcionales: sin ellas el
        # evaluador se comporta exactamente como antes.
        self.ignoradas = self._cargar_claves("etiquetas_ignoradas.csv")
        self.entrenamiento = self._cargar_claves("etiquetas_entrenamiento.csv")

        # Mapa archivo -> id_grabacion, para tolerar entregas que solo traigan `archivo`.
        por_archivo = self.grilla.groupby("archivo")["id_grabacion"].agg(set).to_dict()
        self._archivos_unicos = {a: next(iter(v)) for a, v in por_archivo.items() if len(v) == 1}

    # ------------------------------------------------------- claves excluidas
    def _cargar_claves(self, nombre: str) -> set[tuple]:
        """Lee un CSV auxiliar de pares (grabación, segmento, especie). Vacío si no está."""
        f = self.dir / nombre
        if not f.exists():
            return set()
        d = pd.read_csv(f)
        faltan = {"id_grabacion", "segmento", "scientific_name"} - set(d.columns)
        if faltan:
            raise ErrorDeFormato(f"A {f} le faltan columnas: {sorted(faltan)}")
        return set(zip(d["id_grabacion"].astype(str).str.strip(),
                       d["segmento"].astype(int),
                       _capitalizar(d["scientific_name"])))

    def _excluidas(self, nivel: str, extra: set[tuple] = frozenset()) -> set[tuple]:
        """
        Las claves a descontar, en la forma que corresponde al `nivel`.

        A nivel de segmento son los pares tal cual. A nivel de presencia una
        especie solo se excluye de una grabación si **todas** sus etiquetas ahí
        están excluidas: si queda una defendible, la presencia sigue siendo un
        hecho puntuable.
        """
        claves = self.ignoradas | set(extra)
        if not claves or nivel == "segmento":
            return claves

        gt = self.gt_segmentos.assign(
            _esp=_capitalizar(self.gt_segmentos["scientific_name"]))
        total = gt.groupby(["id_grabacion", "_esp"]).size()
        marcadas = pd.Series(
            [(g, s, e) in claves for g, s, e in
             zip(gt["id_grabacion"], gt["segmento"], gt["_esp"])], index=gt.index)
        excl = gt[marcadas].groupby(["id_grabacion", "_esp"]).size()
        return {k for k, n in excl.items() if n == total[k]}

    # ----------------------------------------------------------------- lectura
    def _leer(self, submission) -> pd.DataFrame:
        if isinstance(submission, (str, pathlib.Path)):
            try:
                submission = pd.read_csv(submission)
            except Exception as e:
                raise ErrorDeFormato(f"No se pudo leer el CSV: {e}") from e
        d = submission.copy()
        d.columns = [str(c).strip().lower() for c in d.columns]
        return d

    def _resolver_id(self, d: pd.DataFrame) -> pd.Series:
        if "id_grabacion" in d:
            return d["id_grabacion"].astype(str).str.strip()
        if "grabadora" in d and "archivo" in d:
            return (d["grabadora"].astype(str).str.strip() + "/"
                    + d["archivo"].astype(str).str.strip())
        if "archivo" in d:
            arch = d["archivo"].astype(str).str.strip()
            desconocidos = sorted(set(arch) - set(self._archivos_unicos) - self.ids_validos)
            if desconocidos:
                raise ErrorDeFormato(
                    f"Nombres de archivo ambiguos o desconocidos: {desconocidos[:5]}. "
                    "Usa la columna `id_grabacion` (formato `grabadora-N/ARCHIVO.WAV`)."
                )
            return arch.map(lambda a: self._archivos_unicos.get(a, a))
        raise ErrorDeFormato(
            "Falta la columna `id_grabacion`. Debe tener el formato "
            "`grabadora-1/20240625_083000.WAV`."
        )

    def _claves(self, df, nivel: str) -> set:
        d = self._leer(df)
        col = next((c for c in COLS_ESPECIE if c in d), None)
        if col is None:
            raise ErrorDeFormato(
                "Falta la columna de especie. Se acepta `scientific_name`, "
                "`especie` o `species`."
            )
        if len(d) == 0:
            return set()

        d = d.assign(_esp=_capitalizar(d[col]), _id=self._resolver_id(d))
        d = d[d["_esp"].ne("") & d["_esp"].ne("Nan") & d["_esp"].ne("None")]

        if nivel == "presencia":
            return set(zip(d["_id"], d["_esp"]))

        if "segmento" in d:
            seg = pd.to_numeric(d["segmento"], errors="coerce")
        elif "start_s" in d:
            seg = (pd.to_numeric(d["start_s"], errors="coerce") / 3).round()
        else:
            raise ErrorDeFormato(
                "A nivel de segmento hace falta la columna `segmento` "
                "(índice entero del bloque de 3 s) o `start_s`."
            )
        d = d.assign(_seg=seg).dropna(subset=["_seg"])
        return set(zip(d["_id"], d["_seg"].astype(int), d["_esp"]))

    # --------------------------------------------------------------- validación
    def validar(self, submission) -> list[str]:
        """Devuelve la lista de problemas. Vacía = la entrega es evaluable."""
        problemas: list[str] = []
        try:
            d = self._leer(submission)
        except ErrorDeFormato as e:
            return [str(e)]

        if len(d) == 0:
            return ["El archivo está vacío (0 filas). Un envío vacío puntúa F1 = 0."]
        if len(d) > 500_000:
            problemas.append(f"{len(d):,} filas es desproporcionado (la grilla tiene "
                             f"{len(self.grilla):,} segmentos). ¿Estás rellenando de más?")

        col = next((c for c in COLS_ESPECIE if c in d), None)
        if col is None:
            return ["Falta la columna de especie (`scientific_name`)."]

        try:
            ids = self._resolver_id(d)
        except ErrorDeFormato as e:
            return [str(e)]

        desconocidas = sorted(set(ids) - self.ids_validos)
        if desconocidas:
            problemas.append(
                f"{len(desconocidas)} grabación(es) no existen en la grilla, "
                f"p. ej. {desconocidas[:3]}."
            )

        if "segmento" in d:
            seg = pd.to_numeric(d["segmento"], errors="coerce")
            if seg.isna().any():
                problemas.append(f"{int(seg.isna().sum())} valores de `segmento` no son enteros.")
            pares = set(zip(ids, seg.dropna().astype(int)))
            fuera = pares - self.segmentos_validos
            if fuera:
                problemas.append(
                    f"{len(fuera)} segmento(s) fuera de rango, p. ej. {sorted(fuera)[:3]}. "
                    "Los válidos están en `segmentos_a_predecir.csv`."
                )

        dup = d.duplicated(subset=[c for c in ("id_grabacion", "segmento", col) if c in d])
        if dup.any():
            problemas.append(f"{int(dup.sum())} filas duplicadas (misma grabación, "
                             "segmento y especie).")

        esp = _capitalizar(d[col])
        raras = sorted(set(esp) - set(self.especies))
        if raras:
            problemas.append(
                f"Aviso: {len(raras)} especie(s) fuera del ground truth, p. ej. {raras[:3]}. "
                "No es un error — cuentan como falsos positivos."
            )
        return problemas

    # --------------------------------------------------------------- evaluación
    def evaluar(self, submission, nivel: str = NIVEL_RANKING,
                por_especie: bool = False):
        """F1 micro (ranking) y macro contra el ground truth."""
        ref = self.gt_presencia if nivel == "presencia" else self.gt_segmentos
        verdad = self._claves(ref, nivel)
        pred = self._claves(submission, nivel)

        # Las ignoradas salen del ground truth **y** de la entrega. Si solo
        # salieran del ground truth, el equipo que encuentre ese canto se comería
        # un falso positivo por haber acertado.
        excl = self._excluidas(nivel)
        verdad, pred = verdad - excl, pred - excl

        tp, fp, fn = len(pred & verdad), len(pred - verdad), len(verdad - pred)
        p, r, f1 = _prf(tp, fp, fn)

        filas = []
        for sp in sorted({k[-1] for k in verdad} | {k[-1] for k in pred}):
            v = {k for k in verdad if k[-1] == sp}
            q = {k for k in pred if k[-1] == sp}
            pe, re_, fe = _prf(len(q & v), len(q - v), len(v - q))
            filas.append({"scientific_name": sp, "n_verdad": len(v), "n_pred": len(q),
                          "precision": round(pe, 4), "recall": round(re_, 4),
                          "f1": round(fe, 4)})
        detalle = pd.DataFrame(filas)

        res = {
            "nivel": nivel, "tp": tp, "fp": fp, "fn": fn,
            "precision": round(p, 4), "recall": round(r, 4),
            "f1_micro": round(f1, 4),
            "f1_macro": round(float(detalle["f1"].mean()) if len(detalle) else 0.0, 4),
            "jaccard": round(tp / max(tp + fp + fn, 1), 4),
            "especies_pred": len({k[-1] for k in pred}),
            "n_ignoradas": len(excl),
        }

        # F1 sobre lo que el equipo **no** tenía: se descuentan también las
        # etiquetas de entrenamiento, de la entrega y del ground truth. Quien
        # copia el entrenamiento tal cual queda en 0.00 acá y a la vista.
        if self.entrenamiento:
            excl_nv = self._excluidas(nivel, self.entrenamiento)
            v_nv = verdad - excl_nv
            p_nv = pred - excl_nv
            _, _, f_nv = _prf(len(p_nv & v_nv), len(p_nv - v_nv), len(v_nv - p_nv))
            res["f1_no_visto"] = round(f_nv, 4)
            res["n_no_visto"] = len(v_nv)

        return (res, detalle.sort_values("f1", ascending=False).reset_index(drop=True)) \
            if por_especie else res

    # ------------------------------------------------------- intervalo (bootstrap)
    def intervalo(self, submission, nivel: str = NIVEL_RANKING,
                  n: int = 2000, semilla: int = 0) -> tuple[float, float]:
        """
        IC 95 % del F1 micro, remuestreando **grabaciones** (no segmentos).

        Los segmentos dentro de una grabación están correlacionados — un canto
        ocupa varios seguidos —, así que remuestrearlos daría un intervalo
        falsamente angosto. La unidad independiente es la grabación.
        """
        ref = self.gt_presencia if nivel == "presencia" else self.gt_segmentos
        verdad, pred = self._claves(ref, nivel), self._claves(submission, nivel)
        excl = self._excluidas(nivel)
        verdad, pred = verdad - excl, pred - excl

        cuentas: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
        for k in pred & verdad:
            cuentas[k[0]][0] += 1
        for k in pred - verdad:
            cuentas[k[0]][1] += 1
        for k in verdad - pred:
            cuentas[k[0]][2] += 1

        ids = sorted(self.ids_validos)
        m = np.array([cuentas[i] for i in ids], dtype=float)          # (n_grab, 3)
        if m.sum() == 0:
            return (0.0, 0.0)

        rng = np.random.default_rng(semilla)
        idx = rng.integers(0, len(ids), size=(n, len(ids)))
        s = m[idx].sum(axis=1)                                        # (n, 3)
        tp, fp, fn = s[:, 0], s[:, 1], s[:, 2]
        with np.errstate(divide="ignore", invalid="ignore"):
            f1 = np.nan_to_num(2 * tp / (2 * tp + fp + fn))
        return (round(float(np.percentile(f1, 2.5)), 4),
                round(float(np.percentile(f1, 97.5)), 4))

    # ---------------------------------------------------------------- baselines
    def baselines(self, nivel: str = NIVEL_RANKING) -> pd.DataFrame:
        """Puntajes de referencia. Si un equipo no les gana, no tiene nada."""
        base = self.grilla[["id_grabacion", "segmento"]]
        mas_comun = (self.gt_segmentos["scientific_name"].value_counts().index[0])

        rng = np.random.default_rng(0)
        n_azar = max(int(len(base) * 0.02), 1)
        azar = base.sample(n=n_azar, random_state=0).assign(
            scientific_name=rng.choice(self.especies, size=n_azar))

        pruebas = {
            "· nada (todo negativo)": base.iloc[:0].assign(scientific_name=""),
            f"· siempre {mas_comun.split()[0]}": base.assign(scientific_name=mas_comun),
            "· azar (2 % de segmentos)": azar,
            "· todas las especies en todo": base.merge(
                pd.DataFrame({"scientific_name": self.especies}), how="cross"),
        }
        filas = []
        for nombre, df in pruebas.items():
            r = self.evaluar(df, nivel)
            filas.append({"equipo": nombre, "f1_micro": r["f1_micro"],
                          "f1_macro": r["f1_macro"], "precision": r["precision"],
                          "recall": r["recall"], "es_baseline": True})
        return pd.DataFrame(filas).sort_values("f1_micro", ascending=False)
