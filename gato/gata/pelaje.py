"""Pinta el pelaje de la gata carey de gato/origen/ sobre las UV de la gata de Jonas Dichelle (malla_uv.npz, de
exportar_malla.py) → pelaje.png. Del pelaje original (tex_original.png) solo se queda el detalle fino de los pelos.

    .venv/bin/python gato/gata/pelaje.py

Carey «diluida»: manchas grandes gris pardo oscuro y melocotón apagado, mezcladas a motas; blancos la lista de la
nariz, el hocico y la barbilla, el babero y el pecho, la barriga y los calcetines; nariz y dentro de las orejas
rosas; punta de la cola melocotón rosado. Coordenadas de la malla en reposo: mira a -Y, z arriba, pies en z ≈ -2.7.
"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

AQUI = Path(__file__).resolve().parent
LADO = 1536

OSCURO, GRIS, MELOCOTON = (34, 27, 25), (78, 66, 60), (200, 140, 96)
CANELA, BLANCO, ROSA = (150, 98, 66), (240, 230, 216), (214, 140, 138)


def paso(a, b, x):
    """0 en a, 1 en b, suave entre medias (a > b vale)."""
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def ruido(p, semilla, escala, ondas=7):
    """Manchas suaves: suma de ondas en 3D con el espacio algo retorcido; de -1 a 1 aprox."""
    r = np.random.default_rng(semilla)
    q = p * escala
    q = q + 0.6 * np.sin(q[:, [1, 2, 0]] * 1.3 + r.uniform(0, 6, 3))
    s = np.zeros(len(p))
    for _ in range(ondas):
        k = r.normal(size=3)
        s += np.sin(q @ (k / np.linalg.norm(k)) * r.uniform(0.7, 1.4) + r.uniform(0, 2 * np.pi))
    return s / np.sqrt(ondas / 2)


def rasterizar(d):
    """Posición y normal en reposo de cada texel (por baricéntricas en cada triángulo UV); máscara de los usados."""
    P, N, usado = np.zeros((LADO, LADO, 3)), np.zeros((LADO, LADO, 3)), np.zeros((LADO, LADO), bool)
    v, n = d["v"], d["n"]
    for t, uv in zip(d["tri"], d["tuv"]):
        a = uv * LADO
        a[:, 1] = LADO - a[:, 1]  # v de abajo arriba → filas de arriba abajo
        x0, y0 = np.floor(a.min(0)).astype(int)
        x1, y1 = np.ceil(a.max(0)).astype(int)
        xs, ys = np.meshgrid(np.arange(max(x0, 0), min(x1 + 1, LADO)), np.arange(max(y0, 0), min(y1 + 1, LADO)))
        q = np.stack([xs + 0.5, ys + 0.5], -1).reshape(-1, 2)
        T = np.array([a[1] - a[0], a[2] - a[0]]).T
        if abs(np.linalg.det(T)) < 1e-9:
            continue
        l12 = (q - a[0]) @ np.linalg.inv(T).T
        w = np.c_[1 - l12.sum(1), l12]
        ok = (w >= -0.02).all(1)
        f, c = ys.ravel()[ok], xs.ravel()[ok]
        P[f, c], N[f, c], usado[f, c] = w[ok] @ v[t], w[ok] @ n[t], True
    N /= np.maximum(np.linalg.norm(N, axis=-1, keepdims=True), 1e-6)
    return P, N, usado


def colores(p, n):
    x, y, z = p.T
    ax, ny, nz = np.abs(x), n[:, 1], n[:, 2]
    # base carey: manchas grandes melocotón sobre gris pardo, con motas oscuras y vetas canela
    grande, medio, fino = ruido(p, 1, 0.55), ruido(p, 2, 1.3), ruido(p, 3, 3.2)
    mel = paso(0.45, 0.9, grande + 0.35 * medio + 0.3 * fino)  # bordes moteados, como en la carey de verdad
    osc = paso(-0.3, 0.3, -grande + 0.45 * medio) * (1 - mel)
    c = np.array(GRIS) * (1 - osc[:, None]) + np.array(OSCURO) * osc[:, None]
    c = c * (1 - mel[:, None]) + np.array(MELOCOTON) * mel[:, None]
    can = paso(0.35, 0.8, fino) * paso(0.2, 0.5, mel) * (1 - paso(0.6, 0.95, mel))
    c = c * (1 - 0.6 * can[:, None]) + np.array(CANELA) * 0.6 * can[:, None]
    c *= (0.92 + 0.1 * fino)[:, None]  # motas
    mota = paso(0.5, 1.1, ruido(p, 4, 7.0, 9)) * (1 - mel) * 0.55   # atigrado fino melocotón dentro de lo oscuro
    c = c * (1 - mota[:, None]) + np.array(MELOCOTON) * mota[:, None]
    mota = paso(0.6, 1.2, ruido(p, 5, 6.0, 9)) * mel * 0.45          # y motas oscuras dentro de lo melocotón
    c = c * (1 - mota[:, None]) + np.array(GRIS) * mota[:, None]
    # cola: más oscura, con la punta melocotón rosado
    cola = paso(3.4, 3.8, y) * paso(2.6, 3.0, z)
    c = c * (1 - 0.45 * cola[:, None]) + np.array(OSCURO) * 0.45 * cola[:, None]
    punta = paso(5.2, 5.9, z) * cola
    c = c * (1 - punta[:, None]) + np.array((214, 156, 140)) * punta[:, None]
    # blancos (difuminados)
    cara = paso(-3.7, -4.1, y)
    hocico = cara * paso(2.95, 2.7, z) * paso(0.0, -0.5, ny)                       # hocico, bigoteras y barbilla
    hocico = np.maximum(hocico, cara * paso(2.75, 2.45, z))                          # barbilla por debajo
    lista = cara * paso(0.2, 0.08, ax + 0.06 * np.clip(z - 2.9, 0, 1)) * paso(3.75, 3.5, z) * paso(-0.2, -0.6, ny)
    babero = paso(-1.6, -2.4, y) * paso(2.7, 2.2, z) * paso(1.05, 0.7, ax) * paso(0.25, -0.15, ny)
    babero = np.maximum(babero, paso(-1.2, -2.0, y) * paso(-0.2, -0.6, nz) * paso(2.3, 1.6, z))  # garganta y pecho
    barriga = paso(-0.35, -0.7, nz) * paso(1.4, 0.9, z) * paso(3.0, 2.0, y)
    calcetin = paso(-2.0, -2.35, z)
    calcetin = np.maximum(calcetin, paso(-1.4, -1.8, z) * paso(-1.0, -1.4, y) * paso(0.3, -0.1, ny))  # delanteras
    b = np.max([hocico, lista, babero, barriga, calcetin], 0)
    c = c * (1 - b[:, None]) + np.array(BLANCO) * b[:, None]
    c = cara_de_la_gata(p, n, c, medio)
    # rosas: nariz y dentro de las orejas
    nariz = paso(0.22, 0.12, np.linalg.norm(p - (0, -4.86, 2.68), axis=1))
    oreja = paso(3.75, 4.0, z) * paso(-3.4, -3.8, y) * paso(-0.1, -0.5, ny) * paso(0.35, 0.55, ax) * paso(4.5, 4.3, z)
    for m, col in ((oreja * 0.8, ROSA), (nariz, ROSA)):
        c = c * (1 - m[:, None]) + np.array(col) * m[:, None]
    return c


def cara_de_la_gata(p, n, c, medio):
    """La cara, copiada de la foto de la gata (no al azar): frente melocotón, lista corta crema de entre los ojos a la
    nariz, cejas oscuras sobre cada ojo y rayitas bajo ellos, su lado derecho (x < 0) con la mejilla y la oreja gris
    pardo, coronilla oscura entre las orejas, bigoteras blancas y barbilla oscura."""
    x, y, z = p.T
    ax, ny = np.abs(x), n[:, 1]
    cab = paso(-3.0, -3.45, y) * paso(1.95, 2.3, z)              # la cabeza entera (sin el cuello ni la gola)
    e = 0.06 * medio                                            # bordes algo irregulares
    h = np.tile(np.array((214, 168, 126), float), (len(p), 1))  # melocotón más pálido que el del cuerpo, como en la foto
    oscuro = np.max([
        paso(-0.22, -0.45, x + e) * paso(3.3, 3.0, z + e) * paso(2.35, 2.5, z),  # su mejilla derecha, hasta el ojo
        paso(-0.35, -0.6, x + e) * paso(3.5, 3.75, z),           # su oreja derecha
        paso(-3.75, -3.35, y + e) * paso(3.45, 3.75, z) * paso(0.75, 0.45, ax),  # coronilla entre las orejas
        0.85 * paso(1.0, 0.6, np.hypot((ax - 0.36) / 0.13, (z - 3.36 - 0.3 * (ax - 0.36)) / 0.05)) * paso(-3.8, -4.0, y),  # cejas
        paso(1.0, 0.7, np.hypot((ax - 0.27) / 0.06, (z - 2.88) / 0.14)) * paso(-3.9, -4.1, y),    # rayitas bajo los ojos
        paso(2.42, 2.25, z) * paso(-3.95, -4.2, y),             # barbilla
    ], 0)
    h = h * (1 - oscuro[:, None]) + np.array((72, 62, 58)) * oscuro[:, None]
    crema = np.max([
        paso(0.13, 0.05, ax + 0.05 * np.clip(z - 2.85, 0, 1)) * paso(3.25, 3.05, z) * paso(-4.0, -4.3, y),  # lista
        paso(1.0, 0.75, np.hypot((ax - 0.2) / 0.24, (z - 2.55) / 0.17)) * paso(-4.35, -4.6, y),          # bigoteras
    ], 0) * (1 - paso(2.42, 2.3, z))
    h = h * (1 - crema[:, None]) + np.array((240, 226, 210)) * crema[:, None]
    c = c * (1 - cab[:, None]) + h * cab[:, None]
    # de perfil (foto 2): la gola blanca sube por el cuello por detrás de la mandíbula hasta debajo de la oreja y baja
    # al pecho; encima, el antifaz oscuro sale del ojo y cruza la mejilla hacia atrás hasta debajo de la oreja
    tope = np.interp(y, (-3.95, -3.7, -3.3, -2.9, -2.3), (2.3, 2.55, 2.78, 2.75, 2.45)) + e
    gola = paso(-3.95, -3.75, y) * paso(-2.1, -2.4, y) * paso(tope + 0.05, tope - 0.1, z)
    c = c * (1 - gola[:, None]) + np.array(BLANCO) * gola[:, None]
    t = np.clip(((y + 4.1) * 0.95 - (z - 3.1) * 0.25) / 0.97, 0, 1)            # a lo largo, del ojo (-4.1, 3.1) a
    dist = np.hypot(y - (-4.1 + 0.95 * t), z - (3.1 - 0.25 * t))                # debajo de la oreja (-3.15, 2.85)
    lado = np.where(x < 0, paso(0.25, 0.45, ax), 0.85 * paso(0.42, 0.6, ax))  # el izquierdo, de frente, apenas se ve
    antifaz = paso(0.26 + 0.04 * t, 0.06, dist + 2 * e) * lado * (1 - 0.4 * paso(0.6, 1.0, t))  # se apaga hacia la nuca
    return c * (1 - antifaz[:, None]) + np.array((74, 64, 60)) * antifaz[:, None]


def ojo(lado=512):
    """Iris de la foto: verde grisáceo pálido, más amarillo junto a la pupila, que es redonda (la original era una
    rendija de reptil); las fibras salen de la textura original. Misma composición que la original (iris = imagen)."""
    yy, xx = (np.mgrid[:lado, :lado] + 0.5) / lado * 2 - 1
    r = np.hypot(xx, yy)
    orig = np.asarray(Image.open(AQUI / "ojo_original.png").convert("L").resize((lado, lado)), float)
    fibra = (orig - np.asarray(Image.fromarray(orig.astype(np.uint8)).filter(ImageFilter.GaussianBlur(4)), float)) / 40
    fibra *= paso(0.5, 0.6, r)  # sin el borde de la rendija original
    t = np.clip((r - 0.4) / 0.55, 0, 1)[..., None]
    iris = np.array((190, 196, 128)) * (1 - t) + np.array((150, 168, 146)) * t
    iris = iris * (1 + np.clip(fibra, -0.4, 0.4)[..., None]) * (1 - 0.55 * paso(0.85, 1.0, r))[..., None]  # aro oscuro
    pupila = paso(0.42, 0.38, r)[..., None]
    im = iris * (1 - pupila) + np.array((8, 8, 10)) * pupila
    Image.fromarray(np.clip(im, 0, 255).astype(np.uint8)).save(AQUI / "ojo.png")


def dilatar(img, usado, pasos=12):
    """Rellena unos texels alrededor de cada isla UV con el color del borde (sin costuras al filtrar)."""
    img, usado = img.copy(), usado.copy()
    for _ in range(pasos):
        suma, cuenta = np.zeros_like(img), np.zeros(usado.shape)
        for df, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            u = np.roll(usado, (df, dc), (0, 1))
            suma += np.roll(img, (df, dc), (0, 1)) * u[..., None]
            cuenta += u
        nuevo = ~usado & (cuenta > 0)
        img[nuevo] = suma[nuevo] / cuenta[nuevo, None]
        usado |= nuevo
    return img


if __name__ == "__main__":
    d = np.load(AQUI / "malla_uv.npz")
    P, N, usado = rasterizar(d)
    img = np.zeros((LADO, LADO, 3))
    img[usado] = colores(P[usado], N[usado])
    # detalle de pelos del pelaje original: su paso alto (la luz de cada mechón, sin sus manchas)
    orig = Image.open(AQUI / "tex_original.png").convert("L").resize((LADO, LADO))
    det = np.asarray(orig, float) - np.asarray(orig.filter(ImageFilter.GaussianBlur(6)), float)
    img = np.clip(img * (1 + np.clip(det, -60, 60)[..., None] / 160), 0, 255)
    img = dilatar(img, usado)
    Image.fromarray(img.astype(np.uint8)).save(AQUI / "pelaje.png")
    assert usado.mean() > 0.3, usado.mean()
    ojo()
    print("pelaje.png", LADO, "px, texels usados", round(usado.mean() * 100), "%")
