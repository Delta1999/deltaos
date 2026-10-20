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
        self.f = d["f"] if "f" in d else None  # triángulos (solo el gato; los usa el dibujo fino)
        self.wi, self.w = d["wi"], d["w"].astype(np.float32)
        self.huesos, self.padres, self.pivotes = list(d["huesos"]), d["padres"], d["pivotes"]
        self.W = np.zeros((len(self.v), len(self.huesos)), np.float32)  # pesos en denso: el skinning es un solo producto
        np.add.at(self.W, (np.arange(len(self.v))[:, None], self.wi), self.w)
        self.anclas = {n: (b, p) for n, b, p in zip(d["anclas"], d["ancla_hueso"], d["ancla_p"])}
        self.centro = tuple(d["centro"]) if "centro" in d else CENTRO  # el gato (gato/modelo.py) va centrado en x = 0

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
        Mv = (self.W @ M.reshape(len(M), 12).astype(np.float32)).reshape(-1, 3, 4)  # skinning lineal: matriz mezclada por vértice
        v = np.einsum("vij,vj->vi", Mv[:, :, :3], self.v) + Mv[:, :, 3]
        n = np.einsum("vij,vj->vi", Mv[:, :, :3], self.n)
        return v, n / np.linalg.norm(n, axis=1, keepdims=True), M

    def pintar(self, pose, yaw=0.0, contorno=True, todas=False, fino=1):
        """→ (gris TAM×TAM uint8, 0 = vacío; profundidad TAM×TAM; {ancla: (col, fila) o None si está tapada}).
        Con pelaje de color (g de N×3, el gato): TAM×TAM×3 en vez del gris, todo 0 = vacío.
        fino: celdas por celda de lado (rejilla fino·TAM, con los huecos entre vértices rellenos); las anclas siguen
        en celdas de TAM.
        todas: {ancla: (col, fila, visible)}, también las tapadas (el tricornio va sobre la coronilla, que nunca se ve)."""
        v, n, M = self.posar(pose)
        a = np.radians(yaw)
        Rz = np.array([[np.cos(a), np.sin(a), 0], [-np.sin(a), np.cos(a), 0], [0, 0, 1]])
        der, arriba, fondo = np.array([1, 0, 0]), np.array([0, np.sin(ELEVA), np.cos(ELEVA)]), np.array([0, np.cos(ELEVA), -np.sin(ELEVA)])
        V = np.stack([der, arriba, fondo]) @ Rz  # mundo → cámara (x pantalla, arriba, profundidad)
        pc, nc = (v - (self.centro[0], 0, self.centro[1])) @ V.T, n @ V.T
        T = TAM * fino
        x, y = (pc[:, 0] + TAM / 2) * fino, (TAM / 2 - pc[:, 1]) * fino
        if fino > 1:  # cada vértice tapa las 2×2 celdas de su alrededor (en fino hay ~1 vértice por celda) y sin las
            delante = nc[:, 2] < 0.25  # caras de espaldas, que asomarían por los pliegues en motas oscuras
            if self.f is not None:  # mejor el centro de cada triángulo: hay el doble y, donde la piel se estira, no se
                a, b, c = self.f[delante[self.f[:, 0]]].T  # separan tanto como los vértices (se vería el fondo)
                sx, sy, sz, de = (x[a] + x[b] + x[c]) / 3, (y[a] + y[b] + y[c]) / 3, (pc[a, 2] + pc[b, 2] + pc[c, 2]) / 3, a
            else:
                vis = np.flatnonzero(delante)
                sx, sy, sz, de = x[vis], y[vis], pc[vis, 2], vis
            o = np.argsort(-sz)  # de lejos a cerca: en cada celda se queda el último, el más cercano
            W = T + 4  # rejilla con un marco de 2 celdas donde caen (y se tiran) las muestras que se salen
            c0 = np.clip(np.floor(sx[o] + 1.5), 0, T + 2).astype(np.int32)  # celda de arriba a la izquierda de las 2×2
            i0 = np.clip(np.floor(sy[o] + 1.5), 0, T + 2).astype(np.int32) * W + c0
            i = np.stack([i0, i0 + 1, i0 + W, i0 + W + 1], 1).ravel()  # las 4 de cada muestra, seguidas: sigue
            du, z = np.full(W * W, -1), np.full(W * W, np.inf)        # ordenado de lejos a cerca
            du[i], z[i] = np.repeat(de[o], 4), np.repeat(sz[o], 4)
            dueño, zc = du.reshape(W, W)[2:-2, 2:-2].ravel(), z.reshape(W, W)[2:-2, 2:-2].ravel()
        else:
            col, fil, de, prof = np.floor(x).astype(int), np.floor(y).astype(int), np.arange(len(v)), pc[:, 2]
            o = np.argsort(-prof, kind="stable")
            col, fil, de, prof = col[o], fil[o], de[o], prof[o]
            ok = (col >= 0) & (col < T) & (fil >= 0) & (fil < T)
            i = fil[ok] * T + col[ok]
            dueño, zc = np.full(T * T, -1), np.full(T * T, np.inf)
            dueño[i], zc[i] = de[ok], prof[ok]
        if fino > 1:  # algún hueco suelto: si 3 de los 4 vecinos están bastante más cerca, se queda con el más cercano
            D = np.pad(dueño.reshape(T, T), 1, constant_values=-1)
            Zc = np.pad(zc.reshape(T, T), 1, constant_values=np.inf)
            vec = np.stack([D[:-2, 1:-1], D[2:, 1:-1], D[1:-1, :-2], D[1:-1, 2:]]).reshape(4, -1)
            z = np.stack([Zc[:-2, 1:-1], Zc[2:, 1:-1], Zc[1:-1, :-2], Zc[1:-1, 2:]]).reshape(4, -1)
            hueco = (z < zc - 1.5).sum(0) >= 3
            k = z.argmin(0)
            dueño[hueco], zc[hueco] = vec[k, np.arange(T * T)][hueco], z[k, np.arange(T * T)][hueco]
        celdas = np.flatnonzero(dueño >= 0)
        cerca = dueño[celdas]
        luz = np.clip(nc[cerca] @ np.array([-0.45, 0.6, -0.66]), 0, 1)  # luz de arriba a la izquierda, por delante
        tono = self.g[cerca].astype(np.float32)
        ao = 0.55 + 0.45 * self.ao[cerca]
        if tono.ndim == 2:  # en color: misma luz, sin el truco del negro
            gris = np.clip(tono * ((0.6 + 0.4 * ao) * (0.8 + 0.35 * luz))[:, None], 12, 255)
        else:
            gris = tono * ao * (0.78 + 0.42 * luz)
            gris = np.where(tono == OSCURO, 16 + 34 * luz * ao, np.clip(gris, 40, 255))
        G, Z = np.zeros((T * T, *tono.shape[1:]), np.uint8), np.full(T * T, 1e4)
        G[celdas], Z[celdas] = gris, zc[celdas]
        G, Z = G.reshape(T, T, *tono.shape[1:]), Z.reshape(T, T)
        if contorno:  # silueta y bordes de lo que tapa a algo lejano (un brazo sobre la barriga) en oscuro
            Zp = np.pad(Z, 1, constant_values=1e4)
            vecino = np.max([Zp[:-2, 1:-1], Zp[2:, 1:-1], Zp[1:-1, :-2], Zp[1:-1, 2:]], 0)
            borde = (Z < 1e4) & (vecino - Z > 3.0)
            if G.ndim == 3:  # el color, oscurecido: el contorno sigue siendo naranja o pardo; por dentro (una pata sobre
                fuera = borde & (vecino >= 1e4)  # la barriga), solo una sombra: oscuro, sobre blanco sale una raya sucia
                G[borde] = G[borde] * np.where(fuera[borde], 0.45, 0.8)[:, None]
            else:
                G[borde] = OSCURO
        anclas = {}
        for nombre, (b, p) in self.anclas.items():
            q = (M[b, :, :3] @ p + M[b, :, 3] - (self.centro[0], 0, self.centro[1])) @ V.T
            c, f = int((q[0] + TAM / 2) * fino), int((TAM / 2 - q[1]) * fino)
            vis = 0 <= c < T and 0 <= f < T and q[2] <= Z[f, c] + 1.2
            xy = (q[0] + TAM / 2, TAM / 2 - q[1])
            anclas[nombre] = (*xy, vis) if todas else xy if vis else None
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
