"""Logo de DeltaOS → rejilla de puntos para el panel.

    .venv/bin/python trazar_logo.py panel/logo_fuente.jpeg 104 panel/logo.json [-v] [--giro G]

Solo hay que volver a pasarlo si cambia el logotipo. El -v imprime el resultado en texto para
ver de un vistazo que el perro se sigue reconociendo. El --giro endereza la cabeza, que en el
logotipo viene inclinada: 4° es lo que la pone a plomo, y es el valor por defecto.

El logo es un dibujo de líneas claras sobre un disco oscuro. Se muestrea en celdas cuadradas:
cada celda que pisa una línea se vuelve un punto, con la intensidad que le toca. El ojo va
aparte porque es rojo oscuro y por gris no pasaría el corte.
"""
import json
import sys
import numpy as np
from PIL import Image

src, W, dest = sys.argv[1], int(sys.argv[2]), sys.argv[3]
im = Image.open(src).convert("RGB")
giro = float(sys.argv[sys.argv.index("--giro") + 1]) if "--giro" in sys.argv else 4.0
if giro:  # alrededor del centro del disco, que es lo que luego se recorta
    im = im.rotate(giro, resample=Image.BICUBIC, center=(595.0, 374.0), fillcolor=(0, 0, 0))
a = np.asarray(im).astype(np.float32)
g = a.mean(2)
h, w = g.shape
yy, xx = np.mgrid[0:h, 0:w]
# radio 288 y no 318: el anillo del borde del disco no es parte del perro, y a esta
# resolución se convertía en una circunferencia de puntos que se comía el dibujo
dentro = np.hypot(xx - 595.0, yy - 374.0) < 288.0
linea = dentro & (g > 120)                       # fondo 63, líneas 160-168: el corte es ancho
ojo = dentro & (a[:, :, 0] > 120) & (a[:, :, 1] < 80) & (a[:, :, 2] < 80)

ys, xs = np.nonzero(linea)
x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
paso = (x1 - x0) / W
H = int(round((y1 - y0) / paso))

pts, rojos = [], []
for j in range(H):
    for i in range(W):
        cx0, cx1 = int(x0 + i * paso), int(x0 + (i + 1) * paso)
        cy0, cy1 = int(y0 + j * paso), int(y0 + (j + 1) * paso)
        if ojo[cy0:cy1, cx0:cx1].mean() > 0.2:
            rojos.append([i, j, 1])
            continue
        celda = linea[cy0:cy1, cx0:cx1]
        if not celda.size:
            continue
        v = celda.mean()
        if v < 0.16:                             # por debajo es ruido del jpeg, no línea
            continue
        # las trazas de circuito se cortan en seco contra el borde del disco; apagarlas hacia
        # fuera hace que parezcan desvanecerse en vez de estar recortadas
        r = np.hypot((cx0 + cx1) / 2 - 595.0, (cy0 + cy1) / 2 - 374.0) / 288.0
        pts.append([i, j, round(min(1.0, v / 0.5) * min(1.0, max(0.12, (1 - r) / 0.25)), 2)])

print(f"recorte {x1-x0}x{y1-y0} px → rejilla {W}x{H} (paso {paso:.1f} px): {len(pts)} puntos, {len(rojos)} del ojo")
json.dump({"w": W, "h": H, "pts": pts, "ojo": rojos}, open(dest, "w"), separators=(",", ":"))

if "-v" in sys.argv:
    ras = [[" "] * W for _ in range(H)]
    for i, j, v in pts:
        ras[j][i] = "·:*#"[min(3, int(v * 4))]
    for i, j, v in rojos:
        ras[j][i] = "O"
    print("\n".join("".join(f) for f in ras))
