"""Animaciones del gato 3D: las hace Blender (gato/blender/acciones.py → montar.py → hornear.py) y aquí solo se leen de
gato/animaciones.npz. Mismos nombres que mascota3d/poses.py, porque mascota.py elige por nombre.

ANIM[nombre] = (f(t) → pose, dur): pose en la convención de mascota3d/rig.py; dur = None si va en bucle, o los
segundos que dura si es de una vez (pasado el final se queda en el último fotograma). Entre fotograma y fotograma
horneado se interpola.
"""
from pathlib import Path

import numpy as np

DATOS = Path(__file__).with_name("animaciones.npz")
ANIM = {}


def cargar(ruta=DATOS):
    d = np.load(ruta)
    huesos, fps = [str(h) for h in d["_huesos"]], float(d["_fps"])
    for nombre, dur, ciclo in zip(d["_nombres"], d["_dur"], d["_ciclo"]):
        ANIM[str(nombre)] = animacion(d[str(nombre)].astype(np.float64), huesos, fps, float(dur), bool(ciclo))


def animacion(c, huesos, fps, dur, ciclo):
    n = len(c) - 1

    def f(t):
        x = (t * fps) % n if ciclo else min(max(t * fps, 0), n)
        i = min(int(x), n - 1)
        q = c[i] + (c[i + 1] - c[i]) * (x - i)
        return {h: {"r": tuple(q[j, :3]), "t": tuple(q[j, 3:6]), "s": tuple(q[j, 6:])} for j, h in enumerate(huesos)}
    return f, (None if ciclo else dur)


cargar()

if __name__ == "__main__":
    f, dur = ANIM["reposo"]
    assert dur is None and set(f(0.0)) == set(f(123.4))
    print(len(ANIM), "animaciones:", " ".join(sorted(ANIM)))
