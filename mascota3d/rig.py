"""Pone en pose el mapache 3D (mapache.npz, de modelo.py) y lo pinta como rejilla de puntos, en vivo y solo con numpy.

    m = Mapache()
    puntos = m.pintar(pose, yaw)   # → gris por celda (0 = vacío), profundidad y anclas visibles

Pose = {hueso: {"r": (rx, ry, rz) grados, "t": (dx, dy, dz), "s": (sx, sy, sz)}}, cada cosa opcional; giran sobre el
pivote del hueso, en los ejes del padre. Los huesos van en poses.py. yaw = grados que se gira hacia su izquierda.
"""
from pathlib import Path

import numpy as np

DATOS = Path(__file__).with_name("mapache.npz")
TAM = 64                    # celdas de la rejilla; 1 celda = 1 fila del sprite
CENTRO = (3.0, 26.0)        # (x, z) del modelo en el centro de la rejilla
ELEVA = np.radians(8)       # la cámara mira un poco desde arriba
OSCURO, GRIS, BLANCO = 26, 138, 242


def rot(rx, ry, rz):
    a, b, c = np.radians((rx, ry, rz))
    X = np.array([[1, 0, 0], [0, np.cos(a), -np.sin(a)], [0, np.sin(a), np.cos(a)]])
    Y = np.array([[np.cos(b), 0, np.sin(b)], [0, 1, 0], [-np.sin(b), 0, np.cos(b)]])
    Z = np.array([[np.cos(c), -np.sin(c), 0], [np.sin(c), np.cos(c), 0], [0, 0, 1]])
    return Z @ Y @ X


class Mapache:
    def __init__(self, ruta=DATOS):
        d = np.load(ruta)
        self.v, self.n, self.g, self.ao = d["v"], d["n"].astype(np.float32), d["g"], d["ao"].astype(np.float32)
        self.wi, self.w = d["wi"], d["w"].astype(np.float32)
        self.huesos, self.padres, self.pivotes = list(d["huesos"]), d["padres"], d["pivotes"]
        self.anclas = {n: (b, p) for n, b, p in zip(d["anclas"], d["ancla_hueso"], d["ancla_p"])}

    def matrices(self, pose):
        """Matriz 3×4 de cada hueso en el mundo (los padres van antes que los hijos en la lista)."""
        M = np.zeros((len(self.huesos), 4, 4))
        for i, (h, p) in enumerate(zip(self.huesos, self.pivotes)):
            q = pose.get(h, {})
            L = np.eye(4)
            L[:3, :3] = rot(*q.get("r", (0, 0, 0))) * np.array(q.get("s", (1, 1, 1)))
            L[:3, 3] = p - L[:3, :3] @ p + np.array(q.get("t", (0, 0, 0)))
            M[i] = L if self.padres[i] < 0 else M[self.padres[i]] @ L
        return M[:, :3]

    def posar(self, pose):
        M = self.matrices(pose)
        R = M[:, :, :3].transpose(0, 2, 1).astype(np.float32)
        Vb, Nb = self.v @ R + M[:, None, :, 3].astype(np.float32), self.n @ R  # todos los vértices con cada hueso
        todos = np.arange(len(self.v))
        v = sum(self.w[:, k, None] * Vb[self.wi[:, k], todos] for k in range(self.wi.shape[1]))  # skinning lineal
        n = sum(self.w[:, k, None] * Nb[self.wi[:, k], todos] for k in range(self.wi.shape[1]))
        return v, n / np.linalg.norm(n, axis=1, keepdims=True), M

    def pintar(self, pose, yaw=0.0, contorno=True):
        """→ (gris TAM×TAM uint8, 0 = vacío; profundidad TAM×TAM; {ancla: (col, fila) o None si está tapada})."""
        v, n, M = self.posar(pose)
        a = np.radians(yaw)
        Rz = np.array([[np.cos(a), np.sin(a), 0], [-np.sin(a), np.cos(a), 0], [0, 0, 1]])
        der, arriba, fondo = np.array([1, 0, 0]), np.array([0, np.sin(ELEVA), np.cos(ELEVA)]), np.array([0, np.cos(ELEVA), -np.sin(ELEVA)])
        V = np.stack([der, arriba, fondo]) @ Rz  # mundo → cámara (x pantalla, arriba, profundidad)
        pc, nc = (v - (CENTRO[0], 0, CENTRO[1])) @ V.T, n @ V.T
        col = np.floor(pc[:, 0] + TAM / 2).astype(int)
        fil = np.floor(TAM / 2 - pc[:, 1]).astype(int)
        ok = (col >= 0) & (col < TAM) & (fil >= 0) & (fil < TAM)
        idx = np.flatnonzero(ok)
        idx = idx[np.argsort(-pc[idx, 2])]  # de lejos a cerca: en cada celda se queda el último escrito, el más cercano
        dueño = np.full(TAM * TAM, -1)
        dueño[fil[idx] * TAM + col[idx]] = idx
        celdas = np.flatnonzero(dueño >= 0)
        cerca = dueño[celdas]
        luz = np.clip(nc[cerca] @ np.array([-0.45, 0.6, -0.66]), 0, 1)  # luz de arriba a la izquierda, por delante
        tono = self.g[cerca].astype(np.float32)
        ao = 0.55 + 0.45 * self.ao[cerca]
        gris = tono * ao * (0.78 + 0.42 * luz)
        gris = np.where(tono == OSCURO, 16 + 34 * luz * ao, np.clip(gris, 40, 255))
        G, Z = np.zeros(TAM * TAM, np.uint8), np.full(TAM * TAM, 1e4)
        G[celdas], Z[celdas] = gris, pc[cerca, 2]
        G, Z = G.reshape(TAM, TAM), Z.reshape(TAM, TAM)
        if contorno:  # silueta y bordes de lo que tapa a algo lejano (un brazo sobre la barriga) en oscuro
            Zp = np.pad(Z, 1, constant_values=1e4)
            vecino = np.max([Zp[:-2, 1:-1], Zp[2:, 1:-1], Zp[1:-1, :-2], Zp[1:-1, 2:]], 0)
            G[(G > 0) & (vecino - Z > 3.0)] = OSCURO
        anclas = {}
        for nombre, (b, p) in self.anclas.items():
            q = (M[b, :, :3] @ p + M[b, :, 3] - (CENTRO[0], 0, CENTRO[1])) @ V.T
            c, f = int(q[0] + TAM / 2), int(TAM / 2 - q[1])
            vis = 0 <= c < TAM and 0 <= f < TAM and q[2] <= Z[f, c] + 1.2
            anclas[nombre] = (q[0] + TAM / 2, TAM / 2 - q[1]) if vis else None
        return G, Z, anclas


if __name__ == "__main__":
    import time
    m = Mapache()
    G, Z, A = m.pintar({}, 0)
    assert 900 < (G > 0).sum() < 2200, (G > 0).sum()
    assert A["ojo_i"] and A["ojo_d"] and A["boca"], A          # de frente se ven los ojos y la boca
    assert m.pintar({}, 180)[2]["ojo_i"] is None                # de espaldas, no
    t = time.perf_counter()
    for i in range(20):
        m.pintar({"brazo_d": {"r": (-90, 0, 0)}}, i * 18)
    print("puntos", (G > 0).sum(), "ms por fotograma", round((time.perf_counter() - t) * 50, 1))
