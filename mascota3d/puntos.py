"""Pasa los renders de Blender (tono_XX + luz_XX) a la trama de puntos de la mascota y monta una hoja de vistas.

    ~/Escritorio/WORMHOLE/.venv-cad/bin/python mascota3d/puntos.py <carpeta> <hoja.png> [--sin-borde]

Cada bloque de 6×6 px del render es un punto: el tono sale del pelaje (oscuro/gris/blanco, los grises de mascota.py)
y la luz de Blender lo aclara u oscurece. Los oscuros llevan el aro gris de mascota.py para no perderse en el fondo.
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

BLOQUE, U = 6, 7          # px de render por punto · px de pantalla por punto en la hoja
TONOS = np.array([26, 138, 242])
FONDO = (30, 60, 90)


def trama(tono_png, luz_png, borde=True):
    """→ matriz de grises (0 = sin punto)."""
    t = np.asarray(Image.open(tono_png).convert("RGBA"), float)
    l = np.asarray(Image.open(luz_png).convert("RGBA"), float)
    n = t.shape[0] // BLOQUE
    bl = lambda a: a[:n * BLOQUE, :n * BLOQUE].reshape(n, BLOQUE, n, BLOQUE, -1).swapaxes(1, 2).reshape(n, n, BLOQUE * BLOQUE, -1)
    tb, lb = bl(t), bl(l)
    cubre = (tb[..., 3] > 128).mean(-1) >= 0.45
    # tono: el más votado del bloque (no la media: una frontera antifaz/blanco no debe salir gris)
    idx = np.abs(tb[..., :1] - TONOS).argmin(-1)
    votos = np.stack([(idx == k).sum(-1) for k in range(3)], -1)
    tono = TONOS[votos.argmax(-1)]
    luz = np.where(lb[..., 3] > 128, lb[..., 0], np.nan)
    luz = np.nan_to_num(np.nanmean(luz, -1) / 255, nan=0.7)
    g = np.clip(tono * (0.55 + 0.6 * luz), 0, 255)
    g = np.where(tono == 26, np.clip(18 + 30 * luz, 0, 60), g)  # el negro no se aclara a gris
    if borde:  # contorno de dibujo: puntos con algún vecino vacío → oscuros
        v = np.pad(cubre, 1)
        hueco = ~(v[:-2, 1:-1] & v[2:, 1:-1] & v[1:-1, :-2] & v[1:-1, 2:])
        g = np.where(cubre & hueco, 26, g)
    return np.where(cubre, g, 0)


def pintar(g, recorte):
    y0, y1, x0, x1 = recorte
    g = g[y0:y1, x0:x1]
    S = 4  # sobremuestreo para que los puntos salgan redondos
    im = Image.new("RGB", (g.shape[1] * U * S, g.shape[0] * U * S), FONDO)
    d = ImageDraw.Draw(im)
    r = U * S * 0.42
    for (f, c), v in np.ndenumerate(g):
        if not v:
            continue
        cx, cy = (c + 0.5) * U * S, (f + 0.5) * U * S
        if v < 60:
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(78, 78, 78))
            d.ellipse((cx - r * .72, cy - r * .72, cx + r * .72, cy + r * .72), fill=(int(v),) * 3)
        else:
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(int(v),) * 3)
    return im.resize((im.width // S, im.height // S), Image.LANCZOS)


if __name__ == "__main__":
    carpeta, hoja = Path(sys.argv[1]), sys.argv[2]
    borde = "--sin-borde" not in sys.argv
    tramas = [trama(t, carpeta / t.name.replace("tono", "luz"), borde) for t in sorted(carpeta.glob("tono_*.png"))]
    hay = np.argwhere(np.any(np.stack(tramas), 0))
    recorte = (hay[:, 0].min() - 1, hay[:, 0].max() + 2, hay[:, 1].min() - 1, hay[:, 1].max() + 2)  # mismo encuadre en todas
    ims = [pintar(g, recorte) for g in tramas]
    cols = min(6, len(ims))
    w, h = ims[0].size
    out = Image.new("RGB", (w * cols, h * ((len(ims) + cols - 1) // cols)), FONDO)
    for i, im in enumerate(ims):
        out.paste(im, ((i % cols) * w, (i // cols) * h))
    out.save(hoja)
    print("puntos por vista", int(np.mean([(g > 0).sum() for g in tramas])), "hoja", out.size)
