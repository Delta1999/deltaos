"""El mapache 3D: forma como campo de distancias con uniones suaves → malla con pelaje, luz ambiente y esqueleto.

    ~/Escritorio/WORMHOLE/.venv-cad/bin/python mascota3d/modelo.py [salida.ply]

Escribe mascota3d/mapache.npz (vértices, normales, tono, oclusión, pesos de los huesos, anclas), que es lo que
rig.py pone en pose y pinta en vivo, y, si se le pasa, un PLY con color para Blender (render.py) o la figura impresa.
Unidades = filas del sprite (panel/mapache.txt mide 43 de alto); z hacia arriba, el mapache mira a -Y.
"""
import sys
from pathlib import Path

import numpy as np
import trimesh
from skimage.measure import marching_cubes

PASO = 0.5  # vóxel; rig.py pinta 1 punto por unidad y necesita ≥ 2 vértices por punto para no dejar huecos

# ---- cotas (proporciones de panel/mapache.txt: la cabeza es media altura) ----
CABEZA = ((0, 0, 29.5), (12.5, 9.5, 9.0))
HOCICO = ((0, -7.4, 25.6), (4.4, 4.0, 3.2))
NARIZ = ((0, -11.2, 26.9), (1.8, 1.3, 1.3))
MOFLETES = [((s * 12.0, -1.6, 25.8), (4.4, 3.0, 2.8)) for s in (-1, 1)]
OREJAS = [((s * 8.4, 1.0, 35.2), (s * 10.8, 1.2, 42.0)) for s in (-1, 1)]  # base → punta
CUERPO = ((0, 0.8, 11.0), (11.0, 8.6, 9.5))
PATAS = [((s * 5.0, -1.4, 2.8), (3.6, 3.8, 3.0)) for s in (-1, 1)]
BRAZOS = [((s * 9.0, -2.0, 15.5), (s * 6.6, -7.2, 10.0)) for s in (-1, 1)]  # hombro → mano
COLA = np.array([(8.5, 6.0, 5.5), (13.0, 7.0, 7.0), (16.4, 7.0, 10.6), (17.4, 6.0, 15.0), (16.4, 5.0, 19.2)])
COLA_R = (3.0, 3.9, 4.3, 4.0, 3.2)
OJOS = [(s * 5.0, -9.0, 29.4) for s in (-1, 1)]

OSCURO, GRIS, BLANCO = 26, 138, 242  # los mismos grises que mascota.py

# ---- esqueleto: (nombre, padre, pivote). Los de lado van _i (x < 0, izquierda en pantalla) y _d ----
HUESOS = [("raiz", None, (0, 0.8, 6.0)), ("cabeza", "raiz", (0, 0, 19.5))]
for i, s in enumerate("id"):
    HUESOS += [(f"oreja_{s}", "cabeza", OREJAS[i][0]), (f"brazo_{s}", "raiz", BRAZOS[i][0]),
               (f"pata_{s}", "raiz", ((-5, 5)[i], -1.0, 6.5))]
HUESOS += [(f"cola{k + 1}", "raiz" if k == 0 else f"cola{k}", tuple(COLA[k])) for k in range(len(COLA) - 1)]
# anclas: dónde mascota.py pinta encima ojos, boca, tricornio, placa…  (hueso, punto aproximado → vértice más cercano)
ANCLAS = {"ojo_i": ("cabeza", OJOS[0]), "ojo_d": ("cabeza", OJOS[1]), "boca": ("cabeza", (0, -11, 24.4)),
          "nariz": ("cabeza", (0, -12.5, 27.0)), "coronilla": ("cabeza", (0, 0, 39)),
          "oreja_i": ("oreja_i", OREJAS[0][1]), "oreja_d": ("oreja_d", OREJAS[1][1]),
          "mano_i": ("brazo_i", (-6.6, -9.6, 9.6)), "mano_d": ("brazo_d", (6.6, -9.6, 9.6)),
          "pecho": ("raiz", (3.5, -9, 15)), "cola": ("cola4", COLA[-1] + (0, 0, 3))}


def elipsoide(p, c, r):
    q = (p - np.array(c)) / np.array(r)
    return (np.linalg.norm(q, axis=-1) - 1) * min(r)


def capsula(p, a, b, ra, rb, aplastar_y=1.0):
    a, b = np.array(a, float), np.array(b, float)
    pa, ba = p - a, b - a
    pa = pa * np.array([1, 1 / aplastar_y, 1])
    ba = ba * np.array([1, 1 / aplastar_y, 1])
    h = np.clip((pa @ ba) / (ba @ ba), 0, 1)
    return np.linalg.norm(pa - h[..., None] * ba, axis=-1) - (ra + (rb - ra) * h)


def suave(a, b, k):
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0, 1)
    return b * (1 - h) + a * h - k * h * (1 - h)


def partes(p):
    """Distancia a cada pieza, por hueso que la mueve (sin uniones suaves: para los pesos)."""
    d = {"cabeza": np.minimum.reduce([elipsoide(p, *CABEZA), elipsoide(p, *HOCICO), elipsoide(p, *NARIZ)] +
                                     [elipsoide(p, c, r) for c, r in MOFLETES]),
         "raiz": elipsoide(p, *CUERPO)}
    for i, s in enumerate("id"):
        d[f"oreja_{s}"] = capsula(p, *OREJAS[i], 4.4, 1.4, aplastar_y=0.45)
        d[f"brazo_{s}"] = capsula(p, *BRAZOS[i], 2.6, 2.3)
        d[f"pata_{s}"] = elipsoide(p, *PATAS[i])
    for k in range(len(COLA) - 1):
        d[f"cola{k + 1}"] = capsula(p, COLA[k], COLA[k + 1], COLA_R[k], COLA_R[k + 1])
    return d


def campo(p):
    d = partes(p)
    cab = elipsoide(p, *CABEZA)
    cab = suave(cab, elipsoide(p, *HOCICO), 2.0)
    for c, r in MOFLETES:
        cab = suave(cab, elipsoide(p, c, r), 1.8)
    for s in "id":
        cab = suave(cab, d[f"oreja_{s}"], 1.2)
    cab = suave(cab, elipsoide(p, *NARIZ), 0.4)
    cue = d["raiz"]
    for s in "id":
        cue = suave(cue, d[f"pata_{s}"], 1.4)
        cue = suave(cue, d[f"brazo_{s}"], 1.2)
    cola = d["cola1"]
    for k in range(2, len(COLA)):
        cola = suave(cola, d[f"cola{k}"], 0.8)
    cue = suave(cue, cola, 1.2)
    return suave(cab, cue, 2.4)  # cuello


def dentro(p, c, r):
    return (((p - np.array(c)) / np.array(r)) ** 2).sum(-1) <= 1


def pelaje(v, n):
    """Gris por vértice, calcado del sprite: antifaz grande con ojos, cejas, hocico y mofletes blancos, nariz, boca,
    orejas con borde oscuro e interior blanco, barriga, manos, pies y anillos de la cola."""
    x, y, z = v.T
    ax = np.abs(x)
    g = np.full(len(v), GRIS)
    cabeza, frente = z > 20.0, y < -2.0
    g[cabeza & frente & (z < 26.3) & (ax < 13)] = BLANCO                              # mofletes, hocico, barbilla
    g[cabeza & frente & dentro(v, HOCICO[0], np.array(HOCICO[1]) * 1.12)] = BLANCO
    g[cabeza & frente & (z > 32.0) & (z < 34.6) & (ax > 2.6) & (ax < 8.4)] = BLANCO    # cejas
    # antifaz: una elipse por ojo, inclinada hacia abajo por fuera, sin tocar el puente gris entre los ojos
    u, w, th = ax - 6.4, z - 28.6, 0.32
    u, w = u * np.cos(th) - w * np.sin(th), u * np.sin(th) + w * np.cos(th)
    g[cabeza & frente & ((u / 6.6) ** 2 + (w / 3.6) ** 2 <= 1) & (ax > 1.8)] = OSCURO
    g[cabeza & frente & (z < 27.4) & dentro(v, HOCICO[0], np.array(HOCICO[1]) * 1.12)] = BLANCO  # el hocico, por encima
    for o in OJOS:
        g[np.linalg.norm((v - np.array(o)) * (1, 0.6, 1), axis=-1) < 1.3] = BLANCO
    boca = (y < -9.0) & (ax < 2.6) & (np.abs(z - (24.6 - 0.4 * ax)) < 0.45)
    g[boca | dentro(v, NARIZ[0], np.array(NARIZ[1]) * 1.35)] = OSCURO
    # orejas: borde oscuro, cara delantera blanca
    for i in range(2):
        a, b = np.array(OREJAS[i][0]), np.array(OREJAS[i][1])
        h = np.clip(((v - a) @ (b - a)) / ((b - a) @ (b - a)), 0, 1)
        r = np.linalg.norm((v - (a + h[:, None] * (b - a))) * (1, 1 / 0.45, 1), axis=-1)
        oreja = (z > 35.6) & (h > 0.05) & (np.sign(x) == (-1, 1)[i])
        g[oreja] = OSCURO
        g[oreja & (n[:, 1] < -0.25) & (r < (4.4 + (1.4 - 4.4) * h) * 0.55)] = BLANCO
    # cuerpo
    g[~cabeza & (y < -2.5) & dentro(v, (0, -6, 12.0), (5.6, 6, 6.4))] = BLANCO          # barriga
    for h_, m in BRAZOS:  # antebrazo y mano oscuros: si no, un brazo gris sobre el cuerpo gris no se ve
        a, b = np.array(h_), np.array(m)
        h = np.clip(((v - a) @ (b - a)) / ((b - a) @ (b - a)), 0, 1)
        g[(np.linalg.norm(v - (a + h[:, None] * (b - a)), axis=-1) < 3.4) & (h > 0.45)] = OSCURO
    g[~cabeza & (z < 4.2)] = OSCURO                                                     # pies
    # cola: anillos por distancia a lo largo, punta oscura
    seg = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(COLA, axis=0), axis=1))])
    d_cola, s_cola = np.full(len(v), 1e9), np.zeros(len(v))
    for i in range(len(COLA) - 1):
        a, b = COLA[i], COLA[i + 1]
        h = np.clip(((v - a) @ (b - a)) / ((b - a) @ (b - a)), 0, 1)
        d = np.linalg.norm(v - (a + h[:, None] * (b - a)), axis=-1)
        mejor = d < d_cola
        d_cola[mejor], s_cola[mejor] = d[mejor], seg[i] + h[mejor] * (seg[i + 1] - seg[i])
    cola = (d_cola < 5.0) & (x > 7.0) & (y > 2.0)
    g[cola] = np.where((s_cola[cola] > 15.0) | ((s_cola[cola] / 2.7).astype(int) % 2 == 1), OSCURO, GRIS)
    return g


def oclusion(v, n):
    """Luz ambiente por vértice con el propio campo (oclusión de SDF): rincones, cuello y axilas más oscuros."""
    ao = np.zeros(len(v))
    for i in range(1, 6):
        h = 0.7 * i
        ao += (h - np.clip(campo(v + n * h), 0, h)) / 2 ** i
    return np.clip(1 - 1.2 * ao / 0.7, 0.25, 1)


def pesos(v, k=3, temple=0.6):
    """Hasta k huesos por vértice, más peso cuanto más cerca de su pieza (las uniones se doblan suaves)."""
    d = partes(v)
    nombres = [h[0] for h in HUESOS]
    D = np.stack([d[n] for n in nombres], 1)
    W = np.exp(-(D - D.min(1, keepdims=True)) / temple)
    idx = np.argsort(-W, 1)[:, :k]
    w = np.take_along_axis(W, idx, 1)
    return idx.astype(np.uint8), (w / w.sum(1, keepdims=True)).astype(np.float32)


def construir():
    xs, ys, zs = np.arange(-18, 24, PASO), np.arange(-15, 13, PASO), np.arange(-1, 46, PASO)
    P = np.stack(np.meshgrid(xs, ys, zs, indexing="ij"), -1).astype(np.float32)
    v, caras, _, _ = marching_cubes(campo(P), 0.0, spacing=(PASO,) * 3)
    v += np.array([xs[0], ys[0], zs[0]])
    m = trimesh.Trimesh(v, caras, process=True)
    m = max(m.split(only_watertight=False), key=lambda x: len(x.faces))  # fuera migajas degeneradas del marching cubes
    trimesh.smoothing.filter_taubin(m, iterations=8)
    return m


if __name__ == "__main__":
    m = construir()
    assert m.is_watertight, "la malla del mapache tiene agujeros"
    assert 41 < m.extents[2] < 46, m.extents  # alto ≈ sprite
    v, n = m.vertices, m.vertex_normals
    g = pelaje(v, n)
    wi, w = pesos(v)
    nombres = [h[0] for h in HUESOS]
    anclas = [(nombres.index(b), v[np.linalg.norm(v - np.array(p), axis=1).argmin()]) for b, p in ANCLAS.values()]
    np.savez_compressed(Path(__file__).with_name("mapache.npz"), v=v.astype(np.float32), n=n.astype(np.float16),
                        g=g.astype(np.uint8), ao=oclusion(v, n).astype(np.float16), wi=wi, w=w.astype(np.float16),
                        huesos=np.array(nombres), padres=np.array([-1 if p is None else nombres.index(p) for _, p, _ in HUESOS]),
                        pivotes=np.array([c for *_, c in HUESOS], np.float32),
                        anclas=np.array(list(ANCLAS)), ancla_hueso=np.array([b for b, _ in anclas]),
                        ancla_p=np.array([p for _, p in anclas], np.float32))
    if len(sys.argv) > 1:
        m.visual.vertex_colors = np.stack([g, g, g, np.full_like(g, 255)], -1).astype(np.uint8)
        m.export(sys.argv[1])
    print("vértices", len(v), "medidas", m.extents.round(1))
