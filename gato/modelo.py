"""El gato 3D tricolor, la otra mascota: forma como campo de distancias → malla con pelaje de color, luz y esqueleto.

    ~/Escritorio/WORMHOLE/.venv-cad/bin/python gato/modelo.py [salida.ply]

Como mascota3d/modelo.py (el mapache), pero a cuatro patas y en color. Escribe gato/malla.npz (malla, pelaje, luz
y anclas); el esqueleto, los pesos y las animaciones los pone Blender (gato/blender/montar.py → gato.npz y
animaciones.npz, que rig.py pone en pose y pinta en vivo). Colores y manchas calcados de los dibujos de gato/origen/ (carey: blanco, naranja y pardo
oscuro, nariz y almohadillas rosas, ojos verdes). Unidades = celdas de la rejilla; z arriba, el gato mira a -Y.
Se modela en unidades «base» y se escala por ESCALA al final.
"""
import sys
from pathlib import Path

import numpy as np
import trimesh
from skimage.measure import marching_cubes

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mascota3d.modelo import capsula, dentro, elipsoide, suave  # noqa: E402

PASO = 0.4    # vóxel en unidades base (tras escalar ≈ 0.5, como el mapache: ≥ 2 vértices por punto)
ESCALA = 1.3  # base → celdas: el gato sentado mide ~44 puntos, como el mapache

# ---- cotas base: gato de pie, cuerpo a lo largo de Y ----
CUERPO = ((0, 1.5, 13.0), (6.2, 11.5, 6.0))
PECHO = ((0, -6.5, 13.5), (5.6, 5.0, 6.4))
ANCAS = ((0, 9.0, 13.0), (6.4, 5.6, 6.6))
CABEZA = ((0, -13.0, 22.0), (6.4, 5.4, 5.4))
HOCICO = ((0, -17.4, 20.0), (2.6, 2.0, 1.9))
MOFLETES = [((s * 2.1, -17.2, 19.8), (2.3, 2.0, 1.8)) for s in (-1, 1)]
NARIZ = ((0, -19.3, 21.0), (0.9, 0.6, 0.6))
OREJAS = [((s * 3.5, -12.6, 25.4), (s * 4.6, -12.4, 29.8)) for s in (-1, 1)]  # base → punta
OJOS = [(s * 2.5, -17.3, 22.6) for s in (-1, 1)]
BRAZOS = [((s * 3.4, -7.0, 10.5), (s * 3.4, -7.6, 1.4)) for s in (-1, 1)]       # hombro → mano (patas delanteras)
MANOS = [((s * 3.4, -8.4, 1.1), (1.9, 2.4, 1.1)) for s in (-1, 1)]
MUSLOS = [((s * 4.0, 9.0, 8.8), (2.7, 4.4, 4.6)) for s in (-1, 1)]
PATAS = [((s * 3.8, 10.5, 7.0), (s * 3.6, 11.2, 1.4)) for s in (-1, 1)]         # cadera → pie (traseras)
PIES = [((s * 3.6, 10.2, 1.1), (1.9, 2.6, 1.1)) for s in (-1, 1)]
COLA = np.array([(0, 13.0, 15.5), (0, 15.6, 19.5), (0, 16.4, 25.0), (0, 15.8, 30.5), (0, 14.0, 35.0)])
COLA_R = (2.0, 1.9, 1.8, 1.7, 1.4)

# colores (RGB) sacados de los dibujos
BLANCO, CREMA = (238, 232, 220), (214, 196, 170)
NARANJA, CANELA = (214, 128, 62), (176, 102, 56)
PARDO, NEGRO = (112, 80, 56), (58, 40, 30)
ROSA, VERDE, PUPILA = (226, 150, 150), (156, 176, 64), (18, 18, 18)

# ---- puntos que mascota.py necesita (ojos, boca…); el hueso que los lleva lo elige blender/montar.py ----
ANCLAS = {"ojo_i": OJOS[0], "ojo_d": OJOS[1], "boca": (0, -18.6, 18.9), "nariz": (0, -19.6, 21.0),
          "coronilla": (0, -13.0, 27.4), "oreja_i": OREJAS[0][1], "oreja_d": OREJAS[1][1],
          "mano_i": (-3.4, -9.8, 1.4), "mano_d": (3.4, -9.8, 1.4), "pecho": (0, -11.0, 13.0), "cola": COLA[-1] + (0, 0, 1.5)}


def partes(p):
    """Distancia a cada pieza (sin uniones suaves); campo() las junta."""
    d = {"cabeza": np.minimum.reduce([elipsoide(p, *CABEZA), elipsoide(p, *HOCICO), elipsoide(p, *NARIZ)] +
                                     [elipsoide(p, c, r) for c, r in MOFLETES]),
         "raiz": np.minimum.reduce([elipsoide(p, *CUERPO), elipsoide(p, *PECHO), elipsoide(p, *ANCAS)])}
    for i, s in enumerate("id"):
        d[f"oreja_{s}"] = capsula(p, *OREJAS[i], 2.3, 0.4, aplastar_y=0.4)
        d[f"brazo_{s}"] = np.minimum(capsula(p, *BRAZOS[i], 2.0, 1.5), elipsoide(p, *MANOS[i]))
        d[f"pata_{s}"] = np.minimum(capsula(p, *PATAS[i], 1.9, 1.5), elipsoide(p, *PIES[i]))
    for k in range(len(COLA) - 1):
        d[f"cola{k + 1}"] = capsula(p, COLA[k], COLA[k + 1], COLA_R[k], COLA_R[k + 1])
    return d


def campo(p):
    d = partes(p)
    cab = elipsoide(p, *CABEZA)
    cab = suave(cab, elipsoide(p, *HOCICO), 1.2)
    for c, r in MOFLETES:
        cab = suave(cab, elipsoide(p, c, r), 1.0)
    for s in "id":
        cab = suave(cab, d[f"oreja_{s}"], 0.8)
    cab = suave(cab, elipsoide(p, *NARIZ), 0.3)
    cue = suave(suave(elipsoide(p, *CUERPO), elipsoide(p, *PECHO), 2.5), elipsoide(p, *ANCAS), 2.5)
    for i, s in enumerate("id"):
        cue = suave(cue, elipsoide(p, *MUSLOS[i]), 2.0)
        cue = suave(cue, d[f"pata_{s}"], 1.2)
        cue = suave(cue, d[f"brazo_{s}"], 1.4)
    cola = d["cola1"]
    for k in range(2, len(COLA)):
        cola = suave(cola, d[f"cola{k}"], 0.6)
    cue = suave(cue, cola, 1.0)
    return suave(cab, cue, 2.6)  # cuello


def ruido(v, semilla):
    """Manchas suaves: suma de ondas en 3D, de -1 a 1 aprox."""
    r = np.random.default_rng(semilla)
    s = np.zeros(len(v))
    for _ in range(5):
        k = r.normal(size=3) * 0.22
        s += np.sin(v @ k + r.uniform(0, 2 * np.pi))
    return s / 2.2


def paso(a, b, x):
    """0 en a, 1 en b, suave entre medias (a > b vale: sube al bajar x)."""
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def pelaje(v, n):
    """Color por vértice: carey con pecho, barriga, hocico y patas blancos; cara mitad naranja mitad parda con la
    lista blanca entre los ojos; orejas pardas con el interior rosa; cola parda con naranja y punta clara."""
    x, y, z = v.T
    ax = np.abs(x)
    c = np.zeros((len(v), 3))
    # cuerpo: manchas grandes naranja / parda, con vetas oscuras (atigrado) en lo pardo
    m = ruido(v, 7)
    c[:] = np.where((m > 0.05)[:, None], NARANJA, PARDO)
    c[(m > 0.05) & (ruido(v, 3) > 0.6)] = CANELA
    raya = np.sin(y * 0.9 + 0.6 * np.sin(z * 0.7)) > 0.55
    c[(m <= 0.05) & raya] = NEGRO
    # blancos de abajo: barriga, pecho y cuello por delante, patas; con borde difuminado (un corte seco sale en
    # escalones y deja vetas sueltas de pardo y naranja en el pecho)
    babero = paso(1.15, 0.8, np.linalg.norm((v - (0, -10.5, 13.0)) / (5.4, 4.2, 7.0), axis=1)) * paso(0.35, -0.05, n[:, 1])
    barriga = paso(-0.2, -0.5, n[:, 2]) * paso(13.0, 10.5, z)
    calcetin = np.maximum(paso(4.2, 3.0, z), paso(8.3, 6.8, z) * paso(-3.0, -4.5, y) * paso(0.45, 0.15, n[:, 1]))
    brazo = paso(11.0, 9.5, z) * paso(-4.0, -5.5, y) * paso(4.6, 3.4, ax)  # delanteras: blancas por delante y por dentro
    calcetin = np.maximum(calcetin, brazo * np.maximum(paso(0.3, -0.1, n[:, 1]), paso(-0.1, -0.5, n[:, 0] * np.sign(x))))
    b = np.max([babero, barriga, calcetin], 0)[:, None]
    c = c * (1 - b) + np.array(BLANCO) * b
    # cabeza
    cab = (y < -8.5) & (z > 16.0)
    lado = np.where(x > 0, 1, -1)
    c[cab] = np.where((lado[cab] > 0)[:, None], NARANJA, PARDO)
    c[cab & (x < 0) & (np.sin(x * 1.6 + z * 0.8) > 0.4)] = NEGRO    # vetas en la mitad parda
    lista = cab & (n[:, 1] < -0.2) & (ax < 1.0 + np.clip(24.0 - z, 0, 5) * 0.5)
    c[lista] = BLANCO                                              # lista blanca que baja de la frente
    c[cab & (z < 21.0) & (n[:, 1] < -0.1)] = BLANCO                 # hocico y barbilla
    c[cab & dentro(v, HOCICO[0], np.array(HOCICO[1]) * 1.15)] = BLANCO
    for o in OJOS:
        d = np.linalg.norm((v - np.array(o)) * (1, 0.6, 1), axis=-1)
        c[cab & (d < 1.35)] = VERDE
        c[cab & (np.abs(v[:, 0] - o[0]) < 0.3) & (d < 1.2)] = PUPILA  # pupila de rendija
    c[dentro(v, NARIZ[0], np.array(NARIZ[1]) * 1.5)] = ROSA
    boca = (y < -18.0) & (ax < 1.3) & (np.abs(z - (19.1 - 0.4 * ax)) < 0.3)
    c[boca] = NEGRO
    # orejas: fuera pardas (o naranja la derecha), dentro rosa
    for i in range(2):
        a, b = np.array(OREJAS[i][0]), np.array(OREJAS[i][1])
        h = np.clip(((v - a) @ (b - a)) / ((b - a) @ (b - a)), 0, 1)
        oreja = (z > 25.0) & (h > 0.02) & (np.sign(x) == (-1, 1)[i]) & (y < -9)
        c[oreja] = (PARDO, NARANJA)[i]
        c[oreja & (n[:, 1] < -0.55) & (h > 0.15) & (h < 0.7) & (np.abs(x - (a + h[:, None] * (b - a))[:, 0]) < 1.0)] = ROSA
    # cola: base naranja, parda con anillos, punta clara
    cola = (y > 12.5) & (z > 14.0)
    c[cola] = np.where((np.sin(z[cola] * 1.1) > 0.3)[:, None], NEGRO, PARDO)
    c[cola & (z < 19.0)] = NARANJA
    c[cola & (z > 32.5)] = CREMA
    return c.astype(np.uint8)


def oclusion(v, n):
    ao = np.zeros(len(v))
    for i in range(1, 6):
        h = 0.6 * i
        ao += (h - np.clip(campo(v + n * h), 0, h)) / 2 ** i
    return np.clip(1 - 1.2 * ao / 0.6, 0.3, 1)


def construir():
    xs, ys, zs = np.arange(-9, 9, PASO), np.arange(-22, 20, PASO), np.arange(-1, 38, PASO)
    P = np.stack(np.meshgrid(xs, ys, zs, indexing="ij"), -1).astype(np.float32)
    v, caras, _, _ = marching_cubes(campo(P), 0.0, spacing=(PASO,) * 3)
    v += np.array([xs[0], ys[0], zs[0]])
    m = trimesh.Trimesh(v, caras, process=True)
    m = max(m.split(only_watertight=False), key=lambda x: len(x.faces))
    trimesh.smoothing.filter_taubin(m, iterations=8)
    return m


if __name__ == "__main__":
    m = construir()
    assert m.is_watertight, "la malla del gato tiene agujeros"
    v, n = m.vertices, m.vertex_normals
    assert v[:, 2].min() < 0.6 and 34 < m.extents[2] < 38, m.extents  # de las almohadillas a la punta de la cola
    col, ao = pelaje(v, n), oclusion(v, n)
    anclas = np.array([v[np.linalg.norm(v - np.array(p), axis=1).argmin()] for p in ANCLAS.values()])
    E = ESCALA
    np.savez_compressed(Path(__file__).with_name("malla.npz"), v=(v * E).astype(np.float32), f=m.faces.astype(np.int32),
                        n=n.astype(np.float16), g=col, ao=ao.astype(np.float16), anclas=np.array(list(ANCLAS)),
                        ancla_p=(anclas * E).astype(np.float32))
    if len(sys.argv) > 1:
        m.apply_scale(E)
        m.visual.vertex_colors = np.concatenate([col, np.full((len(col), 1), 255, np.uint8)], 1)
        m.export(sys.argv[1])
    print("vértices", len(v), "medidas", (m.extents * (1 if len(sys.argv) > 1 else E)).round(1))
