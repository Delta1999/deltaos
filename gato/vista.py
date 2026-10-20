"""Hoja con el gato 3D en varias animaciones y giros, para revisarlo de un vistazo (PNG, o GIF si acaba en .gif).

    .venv/bin/python gato/vista.py <salida.png|gif> [yaw,yaw…] [animación …]

FINO=1 en el entorno lo pinta como la rejilla de puntos de antes; por defecto, fino y suavizado como en mascota.py.
"""
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gato.poses import ANIM  # noqa: E402
from mascota3d.rig import TAM, Mapache  # noqa: E402

U, FONDO = 6, (30, 60, 90)
FINO = int(os.environ.get("FINO", 2))


def pintar(G, A=None):
    im = Image.new("RGB", (TAM * U, TAM * U), FONDO)
    d = ImageDraw.Draw(im)
    if FINO > 1:
        rgba = Image.fromarray(np.dstack([G, np.where(G.any(-1), 255, 0)]).astype(np.uint8), "RGBA")
        grande = rgba.resize(im.size, Image.BILINEAR)
        im.paste(grande, (0, 0), grande)
    else:
        for f in range(TAM):
            for c in range(TAM):
                if G[f, c].any():
                    d.ellipse((c * U + 1, f * U + 1, c * U + U - 1, f * U + U - 1), fill=tuple(int(x) for x in G[f, c]))
    for k, a in (A or {}).items():
        if a:
            d.ellipse((a[0] * U - 3, a[1] * U - 3, a[0] * U + 3, a[1] * U + 3), outline=(255, 0, 255))
    return im


def hoja(m, nombres, yaws, t, anclas=False):
    celdas = []
    for n in nombres:
        f, dur = ANIM[n]
        for y in yaws:
            G, _, A = m.pintar(f(min(t, dur) if dur else t), y, fino=FINO)
            im = pintar(G, A if anclas else None)
            ImageDraw.Draw(im).text((4, 2), f"{n} {y}", fill=(255, 255, 255))
            celdas.append(im)
    cols = len(yaws)
    out = Image.new("RGB", (TAM * U * cols, TAM * U * len(nombres)), FONDO)
    for j, im in enumerate(celdas):
        out.paste(im, ((j % cols) * TAM * U, (j // cols) * TAM * U))
    return out


if __name__ == "__main__":
    salida = sys.argv[1]
    yaws = [float(y) for y in (sys.argv[2] if len(sys.argv) > 2 else "0,35,70,180").split(",")]
    nombres = sys.argv[3:] or list(ANIM)
    m = Mapache(Path(__file__).with_name("gato.npz"))
    if salida.endswith(".gif"):
        cuadros = [hoja(m, nombres, yaws, i / 10) for i in range(30)]
        cuadros = [c.resize((c.width // 2, c.height // 2)) for c in cuadros]
        cuadros[0].save(salida, save_all=True, append_images=cuadros[1:], duration=100, loop=0)
    else:
        hoja(m, nombres, yaws, 0.3, anclas=True).save(salida)
