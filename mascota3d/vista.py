"""Hoja animada (GIF) con todas las animaciones de poses.py, para revisarlas de un vistazo.

    .venv/bin/python mascota3d/vista.py <salida.gif> [yaw] [nombre ...]
"""
import sys

from PIL import Image, ImageDraw

from poses import ANIM
from puntos import pintar
from rig import TAM, Mapache

FPS, SEG, COLS = 12, 4, 8
PERFIL = {"anda": 70, "corre": 70, "salto_sube": 50, "salto_cae": 50, "tumbado": 20}  # mejor de lado

if __name__ == "__main__":
    salida, yaw = sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 30
    nombres = sys.argv[3:] or list(ANIM)
    m, recorte = Mapache(), (2, TAM - 2, 0, TAM)
    cuadros = []
    for i in range(FPS * SEG):
        t = i / FPS
        celdas = []
        for n in nombres:
            f, dur = ANIM[n]
            G = m.pintar(f(t % (dur + 0.6) if dur else t), PERFIL.get(n, yaw))[0]
            im = pintar(G, recorte)
            ImageDraw.Draw(im).text((6, 4), n, fill=(230, 230, 230))
            celdas.append(im)
        w, h = celdas[0].size
        cols = min(COLS, len(celdas))
        hoja = Image.new("RGB", (w * cols, h * -(-len(celdas) // cols)), (30, 60, 90))
        for j, im in enumerate(celdas):
            hoja.paste(im, ((j % cols) * w, (j // cols) * h))
        cuadros.append(hoja.resize((hoja.width // 2, hoja.height // 2), Image.LANCZOS))
    cuadros[0].save(salida, save_all=True, append_images=cuadros[1:], duration=1000 // FPS, loop=0, optimize=True)
    print(len(cuadros), "fotogramas", cuadros[0].size)
