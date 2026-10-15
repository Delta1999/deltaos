"""Mascota de Delta: el mapache de puntos flotando sobre el escritorio, siempre encima.

Lee el estado del panel (ws://127.0.0.1:7876/ws) y lo representa:
dormido (ojos cerrados, zetas), escuchando (orejas arriba, ojos rojos), hablando (hocico y barriga
laten con la voz), trabajando (puntos rojos orbitando), pide permiso (ojos rojos parpadeando y «!»).
Fase 2, el sistema: agobiado (CPU/RAM altas: tiembla y se pone rojo), calor (gotas naranjas), batería baja o
cargando, sin wifi, papelera con cosas, café tras 50 min seguidos y se duerme si no tocas nada en 5 min.
Fase 4, se pasea: la ventana es una capa transparente del tamaño de la pantalla (maximizada, así KWin le da el
área útil sin la barra) y solo el recuadro del mapache recibe el ratón (máscara de entrada); el resto de clics pasan
a lo de debajo. Cada rato anda por el suelo o salta encima de la ventana activa y se sienta en su borde; si esa
ventana se mueve o se cierra, se cae. Se para cuando Delta te escucha o habla y no se mueve si duerme.
Arrastrar = llevarlo (al soltarlo cae). Clic = pasar al panel completo. Ratón encima = ficha con la info general.
Cuerpo en 3D de puntos: se gira sobre sí mismo. Gestos: orejas (alerta, gachas, caídas, tics), brazos y manos (a la
oreja al escuchar, teclea si trabaja, manos arriba si pide permiso, a la cabeza si se agobia, recogidas al dormir,
gesticula al hablar) y boca (habla con la voz, grita, sonríe al andar, se preocupa, saca la lengua concentrado, ronca).
Patrulla: con Delta en espera y tú delante, ronda con tricornio, placa y porra; a veces se para y da el alto.
"""
import glob
import json
import math
import os
import select
import random
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from PyQt6.QtCore import QPoint, QPointF, QRect, Qt, QTimer, QUrl
from PyQt6.QtGui import QColor, QPainter, QPixmap, QRegion
from PyQt6.QtWebSockets import QWebSocket
from PyQt6.QtWidgets import QApplication, QToolTip, QWidget

PANEL = "127.0.0.1:7876"
# Sacado de la imagen del usuario (lo comparte el panel): # oscuro, + gris, o blanco, . vacío
MAPACHE = (Path(__file__).parent / "panel" / "mapache.txt").read_text().splitlines()
CELDA, R = 5, 2.1                     # px entre puntos y radio del punto
OX, OY = 102, 64                      # margen: a los lados cabe la cola al girarse; arriba, orejas, tricornio y bocadillo
OJOS = {(12, 9), (12, 10), (13, 9), (13, 10), (12, 19), (12, 20), (13, 19), (13, 20)}
PIVOTE_COLA = (33, 26)                # (fila, col) donde la cola se une al cuerpo
GRIS = {"#": 26, "+": 138, "o": 242}
ROJO = QColor(255, 45, 31)
NARANJA = QColor(255, 140, 0)
INACTIVO = 300          # s sin teclado ni ratón: se acurruca a dormir
PAUSA = 50 * 60         # s de actividad seguida: saca un café
CPU_ALTA, RAM_ALTA, CALOR, BAT_BAJA = 85, 92, 85, 20  # %, % (8 GB: el 86 % es lo normal), °C, %
SW, SH = 2 * OX + 30 * CELDA, 43 * CELDA + OY + 12  # caja del mapache; su centro (columna 15) es el eje del giro
PIES = OY + 42 * CELDA + 3      # de lo alto de la caja a la punta de las patas
VEL, GRAV = 70, 2200            # px/s andando, px/s² en saltos y caídas
PASEO = (25, 90)                # s quieto entre paseo y paseo
PERCHA = 0.4                    # probabilidad de subirse a la ventana activa en vez de andar por el suelo
ZANCADA, ALZA = 2.0, 2.0         # celdas que avanza y sube cada pie al andar
CICLO = 4 * ZANCADA * CELDA      # px recorridos por paso completo (los pies no patinan)
VGIRO, ANDAR = 240, 70          # °/s al girarse sobre sí mismo; ° de perfil al andar (0 = de frente)
MIRAR = 7                       # s de media entre vistazos a un lado y otro cuando está quieto
HOMBROS = ((7, 25, 4), (22, 25, 4))  # (columna, fila, z) de donde salen los brazos
PIVOTE_OREJA = ((5, 7.5), (24, 7.5))         # base de cada oreja, sobre la que giran
ALTO = 2.6                      # s que dura el «¡alto!» de la patrulla
DAR_ALTO = 0.35                 # probabilidad de dar el alto al acabar una ronda
PORRA = 7                       # celdas de largo
LENGUA, ORO = QColor(214, 96, 104), QColor(232, 182, 48)
PASO_GIRO = 5                   # ° entre vistas del cuerpo que se guardan en caché
# Iconos de puntos a su derecha (# = punto)
BATERIA = ["#######.", "#.....##", "#.....##", "#######."]
WIFI = [".#####.", "#.....#", "..###..", ".#...#.", "...#..."]
CAFE = ["#####..", "#####.#", "#####.#", "#####..", ".###..."]
PAPELERA = ["..##..", "######", ".#..#.", ".#..#.", ".#..#.", ".####."]
IMPRESORA = {"printing": "imprimiendo", "standby": "en espera", "complete": "terminada", "paused": "en pausa",
             "error": "ERROR", "cancelled": "cancelada"}


def parte(f, c):
    if (f, c) in OJOS:
        return "ojo"
    if f >= 23 and c >= 27:
        return "cola"
    if f >= 39:
        return "pata"
    if f <= 7 and (c <= 9 or c >= 20):
        return "oreja"
    if 18 <= f <= 21:
        return "hocico"
    return "barriga" if f >= 23 else "cuerpo"


def vigilar_entrada(s):
    """Hora de la última tecla o movimiento de ratón (el usuario está en el grupo input). Solo se mira que haya
    eventos, se tiran sin leerlos. ponytail: los dispositivos que se enchufen después no cuentan hasta reiniciar."""
    fds = []
    for f in {os.path.realpath(f) for f in glob.glob("/dev/input/by-*/*-event-kbd") + glob.glob("/dev/input/by-*/*-event-mouse")}:
        try:
            fds.append(os.open(f, os.O_RDONLY | os.O_NONBLOCK))
        except OSError:
            pass
    while fds:
        listos = select.select(fds, [], [], 60)[0]
        for fd in listos:
            try:
                while os.read(fd, 4096):
                    pass
            except BlockingIOError:
                pass
            except OSError:  # desenchufado
                fds.remove(fd)
        if listos:
            s["tecla"] = time.monotonic()
            time.sleep(1)  # basta resolución de 1 s; el núcleo guarda los eventos de mientras


def leer(ruta, defecto=""):
    try:
        return Path(ruta).read_text().strip()
    except OSError:
        return defecto


def kdo(*args):
    try:
        return subprocess.run(["kdotool", *args], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def geometria(w):
    """(x, y, ancho, alto) globales de una ventana de KWin, o None si ya no existe."""
    n = re.findall(r"-?\d+(?:\.\d+)?", kdo("getwindowgeometry", w).partition("}")[2])
    return tuple(round(float(v)) for v in n[:4]) if len(n) >= 4 else None


def percha(ventana, origen, ancho, suelo):
    """Dónde sentarse encima de `ventana` (globales) dentro de la capa que empieza en `origen`: (x_min, x_max, y) o None."""
    vx, vy, vw, _ = ventana
    x0, x1 = max(vx - origen[0], 0), min(vx - origen[0] + vw - SW, ancho - SW)
    y = vy - origen[1] - PIES + 4  # las patas un poco hundidas en el borde
    return (x0, x1, y) if x1 > x0 and 0 <= y < suelo - 120 else None


def vigilar_ventanas(g):
    """Cada 2 s: dónde está la capa, cuál es la ventana activa y si sigue en su sitio aquella en la que está sentado."""
    yo = None
    while True:
        yo = yo or (kdo("search", "--class", "delta-mascota").split() or [None])[0]
        geo = geometria(yo) if yo else None
        if geo:
            g["origen"] = geo[:2]
            act = kdo("getactivewindow").strip()
            g["activa"] = (act, geometria(act)) if act and act != yo else None
            if g.get("posada"):
                g["debajo"] = geometria(g["posada"])
        else:
            yo = None
        time.sleep(2)


# Las manos del dibujo (los triángulos oscuros de la barriga) se despegan del cuerpo y se mueven aparte; en su sitio,
# barriga clara hacia dentro y pelo gris hacia fuera
MANOS = [[(c, f) for f in range(28, 32) for c in rango if MAPACHE[f][c] == "#"] for rango in (range(8, 13), range(17, 22))]
PUNTOS = [(f, c, ("o" if 10 <= c <= 19 else "+") if (c, f) in MANOS[0] + MANOS[1] else ch, parte(f, c))
          for f, fila in enumerate(MAPACHE) for c, ch in enumerate(fila) if ch != "."]

# ---- cuerpo en 3D ----
# Cada punto del sprite se levanta sobre el elipsoide de su parte (x = columna, y = fila, z hacia ti, en celdas) y
# lleva un gemelo en la espalda; al girarse, el modelo rota sobre el eje vertical (columna 15) y se pinta de atrás
# adelante, así pasa por tres cuartos y perfil. De frente coincide punto por punto con el dibujo original.
FORMAS = {"cabeza": ((14.5, 13, 0), (15, 10, 9)), "cuerpo": ((14.5, 30.5, 0), (11.5, 8.5, 8)),
          "cola": ((33, 30, -9), (7, 8, 4)),      # detrás del cuerpo (y barre de lado a lado al girarse, ver cola_x)
          "pata_i": ((9.5, 40.5, 0), (3.5, 2.5, 3)), "pata_d": ((21, 40.5, 0), (3.5, 2.5, 3))}
ESPALDA = {"cabeza": "+", "cuerpo": "+", "pata_i": "#", "pata_d": "#", "cola": None}  # None: rayas también detrás
EJE = 15
LATERAL = ("cabeza", "cuerpo", "cola")  # partes con rejilla de costado
GIRO_LADO = 20                          # ° a partir de los que el costado se pinta con su propia rejilla


def malla_visible(malla, yaw):
    return malla == "frente" or (malla == "lado") == (abs(yaw) >= GIRO_LADO)


def forma(f, c, pt):
    if pt in ("cola", "oreja"):
        return pt
    if pt == "pata":
        return "pata_i" if c < EJE else "pata_d"
    return "cabeza" if f <= 22 else "cuerpo"


def superficie(fo, c, f, lado=1):
    """(z, nx, nz, h) del punto (c, f) en la cara delantera (lado 1) o trasera (-1) de una forma, hocico incluido."""
    (cx, cy, cz), (rx, ry, rz) = FORMAS[fo]
    u, v = (c - cx) / rx, (f - cy) / ry
    h = math.sqrt(max(0.04, 1 - u * u - v * v))
    nx, ny, nz = u / rx, v / ry, lado * h / rz
    m = math.sqrt(nx * nx + ny * ny + nz * nz)
    hocico = 3.5 * max(0.0, 1 - ((c - 14.5) / 5) ** 2 - ((f - 19) / 3) ** 2) if fo == "cabeza" and lado > 0 else 0
    return cz + lado * rz * h + hocico, nx / m, nz / m, h


def modelo():
    """[(x, y, z, nx, nz, ch, parte, forma, borde, malla)]: la cara delantera con el dibujo y la trasera lisa; borde =
    punto del contorno oscuro del dibujo, que al girarse deja de ser silueta y se aclara. malla: «frente» (rejilla del
    dibujo), «canto» (de esa rejilla, pero en el costado, donde se amontona) o «lado» (rejilla vista desde el costado:
    rellena los flancos al girarse, que con la de frente quedaban huecos)."""
    pts, filas = [], {}
    for f, c, ch, pt in PUNTOS:
        fo = forma(f, c, pt)
        if fo == "oreja":  # lámina fina: de perfil se ve de canto
            pts += [(c, f, 2.6, 0.0, 1.0, ch, pt, fo, False, "frente"), (c, f, 1.4, 0.0, -1.0, "#", pt, fo, False, "frente")]
            continue
        filas.setdefault(fo, set()).add(f)
        for lado in (1, -1):
            z, nx, nz, h = superficie(fo, c, f, lado)
            delante = lado > 0
            pts.append((c, f, z, nx, nz, ch if delante or not ESPALDA[fo] else ESPALDA[fo],
                        pt if delante or pt in ("cola", "pata") else "espalda", fo,
                        delante and ch == "#" and h < 0.5 and fo in ("cabeza", "cuerpo"),
                        "canto" if abs(nx) > abs(nz) and fo in LATERAL else "frente"))
    for fo in LATERAL:
        (cx, cy, cz), (rx, ry, rz) = FORMAS[fo]
        for f in sorted(filas[fo]):
            v = (f - cy) / ry
            for k in range(-int(rz), int(rz) + 1):
                w = k / rz
                r = 1 - w * w - v * v
                if r <= 0:
                    continue
                for lado in (-1, 1):
                    nx, ny, nz = lado * math.sqrt(r) / rx, v / ry, w / rz
                    m = math.sqrt(nx * nx + ny * ny + nz * nz)
                    if abs(nx) <= abs(nz):  # eso lo cubre bien la rejilla de frente
                        continue
                    x = cx + lado * rx * math.sqrt(r)
                    pts.append((x, f, cz + k, nx / m, nz / m, color_lado(fo, x - lado * 2, f), "cola" if fo == "cola" else "espalda",
                                fo, False, "lado"))
    return pts


def color_lado(fo, x, f):
    """Color del costado: la cola sigue sus rayas (de lado son anillos); la cabeza es gris con el antifaz oscuro
    que la rodea; el cuerpo, gris."""
    c = round(x)
    ch = MAPACHE[f][c] if 0 <= c < len(MAPACHE[f]) else "."
    if fo == "cola":
        return ch if ch != "." and forma(f, c, parte(f, c)) == fo else "+"
    return "#" if fo == "cabeza" and ch == "#" and 10 <= f <= 15 else "+"


def sin_amontonar(puntos):
    """[(Z, X, y, ...)] de atrás adelante, quitando los que caen casi encima de otro más cercano: de refilón la
    superficie se comprime y los puntos se fundían en rayas."""
    vistos, quedan = set(), []
    for q in sorted(puntos, key=lambda q: -q[0]):
        k = (round(q[1] / 0.8), round(q[2]))
        if k not in vistos:
            vistos.add(k)
            quedan.append(q)
    return quedan[::-1]


def girar(x, z, nx, nz, cs, sn):
    """Rota alrededor del eje vertical: (x en pantalla, profundidad hacia ti, cuánto mira hacia ti la normal)."""
    return (x - EJE) * cs + z * sn + EJE, -(x - EJE) * sn + z * cs, -nx * sn + nz * cs


def luz(nz):
    return 0.55 + 0.45 * max(nz, 0.0)  # lo que se ve de refilón, más apagado: da volumen y marca la silueta


def tapado(X, y, cs, sn):
    """¿Cae (X, y) dentro de la silueta de la cabeza o el cuerpo? Lo de detrás se vería entre los huecos de los puntos."""
    for fo in ("cabeza", "cuerpo"):
        (cx, cy, cz), (rx, ry, rz) = FORMAS[fo]
        v = (y - cy) / ry
        if v * v < 1 and abs(X - ((cx - EJE) * cs + cz * sn + EJE)) < math.hypot(rx * cs, rz * sn) * math.sqrt(1 - v * v) - 0.5:
            return True
    return False


def cola_x(yaw):
    """Desplazamiento lateral de la cola: de frente asoma a la derecha; al mirar a la derecha barre por detrás
    hasta asomar por la izquierda (la espalda), si no quedaría tapada por el cuerpo."""
    return -34 * min(max(yaw, 0), ANDAR) / ANDAR


MODELO = modelo()
MOVILES = [q for q in MODELO if q[6] in ("cola", "ojo", "pata", "oreja")]


def anillo(cx, fila, cz, rx, rz, ch, paso=0.9):
    """Puntos (x, y, z, nx, nz, ch) repartidos por una elipse horizontal, con la normal hacia fuera."""
    n = max(8, round(2 * math.pi * math.sqrt((rx * rx + rz * rz) / 2) / paso))
    return [(cx + rx * math.cos(a), fila, cz + rz * math.sin(a), math.cos(a), math.sin(a), ch)
            for a in (2 * math.pi * i / n for i in range(n))]


def tricornio():
    """Copa charolada que se estrecha hacia arriba, ala y la «teja» levantada detrás que lo hace reconocible."""
    pts = []
    for i, fila in enumerate((3.5, 2.6, 1.7, 0.8, -0.1, -1.0, -1.9)):
        r = 6.9 - 0.2 * i
        for x, y, z, nx, nz, _ in anillo(14.5, fila, 0.5, r, r * 0.8, "#"):
            brillo = i in (2, 3, 4) and nz > 0.5 and x < 13  # reflejo del charol
            pts.append((x, y, z, nx, nz, "o" if brillo else "#"))
    for x in range(10, 20):  # tapa
        for z in range(-3, 5):
            if ((x - 14.5) / 5.4) ** 2 + ((z - 0.5) / 4.3) ** 2 < 1:
                pts.append((x, -2.6, z, 0.0, 0.0, "#"))
    for r in (9.6, 8.6):  # ala de dos vueltas, con el canto claro
        pts += [(x, y, z, nx, nz, "+" if r > 9 else "#") for x, y, z, nx, nz, _ in anillo(14.5, 4.3, 0.8, r, r * 0.82, "#")]
    for x in range(6, 24):  # teja: lámina detrás, más alta en el centro
        alto = 8 - 3.5 * abs(x - 14.5) / 8.5
        for k in range(int(alto) + 1):
            pts.append((x, 3.6 - k, -6.4 - 0.3 * k, 0.0, 0.0, "#" if k < int(alto) else "+"))
    return pts


def brazo(hombro, mano, i):
    """Puntos de la mano i (su triángulo del dibujo) y, si se ha despegado de la barriga, del brazo: hombro → codo
    (se abre hacia fuera cuanto más se estira) → mano."""
    x, y, z = mano
    pts = [(x + dc, y + df, z, 0, 0, "#") for dc, df in PALMAS[i]]
    if math.dist(mano, REPOSO[i]) < 2:  # en su sitio: como en el dibujo, sin brazo
        return pts
    lado = 1 if i else -1
    codo = [(a + b) / 2 for a, b in zip(hombro, mano)]
    codo[0] += lado * max(0.0, 0.35 * (math.dist(hombro, mano) - 6))
    for a, b in ((hombro, codo), (codo, mano)):
        n = max(1, round(math.dist(a, b) / 0.8))
        for i in range(n):
            x, y, z = (a[j] + (b[j] - a[j]) * i / n for j in range(3))
            pts += [(x - 0.8, y, z - 0.2, 0, 0, "#"), (x, y, z - 0.1, 0, 0, "+"), (x + 0.8, y, z - 0.2, 0, 0, "#")]
    return pts


FUENTE = dict(zip("ALTOGURDICV!¡ ", (
    ("###", "#.#", "###", "#.#", "#.#"), ("#..", "#..", "#..", "#..", "###"), ("###", ".#.", ".#.", ".#.", ".#."),
    ("###", "#.#", "#.#", "#.#", "###"), ("###", "#..", "#.#", "#.#", "###"), ("#.#", "#.#", "#.#", "#.#", "###"),
    ("##.", "#.#", "##.", "#.#", "#.#"), ("##.", "#.#", "#.#", "#.#", "##."), ("###", ".#.", ".#.", ".#.", "###"),
    ("###", "#..", "#..", "#..", "###"), ("#.#", "#.#", "#.#", "#.#", ".#."), ("#", "#", "#", ".", "#"),
    ("#", ".", "#", "#", "#"), ("..", "..", "..", "..", ".."))))


def rotulo(texto):
    """Filas de puntos («#») del texto en letra de 3x5."""
    return [".".join(FUENTE[ch][f] for ch in texto) for f in range(5)]


SOMBRERO = tricornio()
PLACA = [(c, f) for f, cols in ((25, (9, 10, 11)), (26, (9, 10, 11)), (27, (9, 10, 11)), (28, (10,))) for c in cols]
CENTROS = [(sum(c for c, _ in m) / len(m), sum(f for _, f in m) / len(m)) for m in MANOS]
PALMAS = [[(c - cx, f - cy) for c, f in m] for m, (cx, cy) in zip(MANOS, CENTROS)]
REPOSO = tuple((cx, cy, superficie("cuerpo", cx, cy)[0] + 0.4) for cx, cy in CENTROS)  # donde están en el dibujo
assert len(MANOS[0]) == len(MANOS[1]) == 11 and all(abs(a - b) < 0.3 for a, b in zip(CENTROS[0], (9.8, 29.8)))
assert rotulo("¡ALTO!")[0] == "#.###.#...###.###.#" and rotulo("¡ALTO!")[3] == "#.#.#.#....#..#.#.."


def tono(g, ch, apagado, agobio):
    g = round(g * apagado)
    return QColor(g + 70, g // 3, g // 4) if agobio and ch == "#" else QColor(g, g, g)


def punto(p, x, y, ch, col):
    if ch == "#" and col.red() < 60:  # los puntos oscuros llevan aro para verse sobre fondos oscuros
        p.setBrush(QColor(78, 78, 78))
        p.drawEllipse(QPointF(x, y), R, R)
        p.setBrush(col)
        p.drawEllipse(QPointF(x, y), R * 0.72, R * 0.72)
    else:
        p.setBrush(col)
        p.drawEllipse(QPointF(x, y), R, R)


class Mascota(QWidget):
    def __init__(self):
        super().__init__(flags=Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool |
                         Qt.WindowType.WindowDoesNotAcceptFocus)  # capa de pantalla entera: el teclado, nunca
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(SW, SH)
        self.resize(SW, SH)
        self.d, self.t0, self.parpadeo, self.cache = {}, time.monotonic(), 0.0, {}
        ahora = time.monotonic()
        # paseo (fase 4): posición del mapache dentro de la capa, hacia dónde mira y qué hace
        self.px = self.py = self.vx = self.vy = 0.0
        self.dir, self.modo, self.meta, self.salto = 1, "quieto", (0.0, 0.0), None
        self.yaw, self.mira, self.parado = 0.0, 0.0, False  # ° girado (0 de frente, + mira a la derecha), adónde mira quieto
        self.paso, self.ritmo = 0.0, 0.0                    # fase del paso, cuánto mueve las patas
        self.orejas, self.manos, self.abre = [(0.0, 0.0)] * 2, REPOSO, 0.0  # gestos: (° hacia fuera, alza), manos, boca
        self.porra, self.tic_oreja, self.t_pint = (0.0, 1.0, 0.0), (0.0, 0), ahora
        self.patrulla, self.alto = False, 0.0  # Delta en espera y tú delante: ronda; alto = hasta cuándo da el alto
        self.pulsado = self.agarre = None
        self.colocado, self.caja, self.ultimo = False, QRect(), ahora
        self.siguiente = ahora + random.uniform(*PASEO)
        self.g = {}  # lo que ve vigilar_ventanas
        threading.Thread(target=vigilar_ventanas, args=(self.g,), daemon=True).start()
        self.s = {"tecla": ahora, "desde": ahora}  # sensores locales (fase 2)
        threading.Thread(target=vigilar_entrada, args=(self.s,), daemon=True).start()
        self.sensores()
        sens = QTimer(self, interval=2000)
        sens.timeout.connect(self.sensores)
        sens.start()
        self.ws = QWebSocket(origin=f"http://{PANEL}")
        self.ws.textMessageReceived.connect(lambda m: self.d.update(json.loads(m)))
        self.ws.disconnected.connect(lambda: (self.d.clear(), QTimer.singleShot(3000, self.conectar)))
        self.conectar()
        reloj = QTimer(self, interval=50)
        reloj.timeout.connect(self.tic)
        reloj.start()

    def sensores(self):
        s, ahora = self.s, time.monotonic()
        bat = (glob.glob("/sys/class/power_supply/BAT*") or [None])[0]
        s["bat"] = (int(leer(f"{bat}/capacity", "100")), leer(f"{bat}/status")) if bat else None
        wl = glob.glob("/sys/class/net/wl*")
        s["wifi"] = not wl or any(leer(f"{w}/operstate") == "up" for w in wl) or \
            any(leer(f"/sys/class/net/{e}/operstate") == "up" for e in os.listdir("/sys/class/net") if e.startswith(("en", "eth")))
        s["basura"] = len(os.listdir(Path.home() / ".local/share/Trash/files")) if (Path.home() / ".local/share/Trash/files").is_dir() else 0
        s["inactivo"] = ahora - s["tecla"]
        if s["inactivo"] > INACTIVO:
            s["desde"] = ahora  # el descanso cuenta: la pausa se reinicia
        s["cafe"] = ahora - s["desde"] > PAUSA

    def conectar(self):
        self.ws.open(QUrl(f"ws://{PANEL}/ws"))

    # ---- paseo ----
    def tic(self):
        ahora = time.monotonic()
        dt, self.ultimo = min(ahora - self.ultimo, 0.1), ahora
        est = self.d.get("estado", "desconectado")
        parado = est in ("escuchando", "hablando", "desconectado") or bool(self.d.get("confirma")) or \
            (est == "dormido" and self.s["inactivo"] > INACTIVO)
        self.parado = parado
        self.patrulla = est == "dormido" and self.s["inactivo"] <= INACTIVO
        self.mover(dt, ahora, parado)
        caja = QRect(round(self.px), round(self.py), SW, SH)
        if caja != self.caja and self.windowHandle():
            self.windowHandle().setMask(QRegion(caja))  # solo el mapache recibe el ratón; el resto de la capa lo deja pasar
        self.update(caja.united(self.caja or caja).adjusted(-12, -12, 12, 12))  # solo su recuadro: repintar la capa entera costaría
        self.caja = caja

    def mover(self, dt, ahora, parado):
        suelo = self.height() - SH
        self.yaw += max(min(self.objetivo() - self.yaw, VGIRO * dt), -VGIRO * dt)
        self.ritmo += max(min((self.modo == "anda" and self.girado()) - self.ritmo, 6 * dt), -6 * dt)
        if self.modo == "cae":
            self.vy += GRAV * dt
            self.px += self.vx * dt
            self.py += self.vy * dt
            if self.vy > 0 and self.py >= self.meta[1]:
                self.py, self.vx = self.meta[1], 0.0
                self.modo, self.siguiente = ("posado" if self.salto else "quieto"), ahora + random.uniform(*PASEO)
        elif self.modo == "anda":
            d = self.meta[0] - self.px
            if parado:
                self.modo, self.salto, self.g["posada"] = "quieto", None, None
            elif not self.girado():  # primero se da la vuelta
                pass
            elif abs(d) > VEL * dt:
                self.px += math.copysign(VEL * dt, d)
                self.paso += VEL * dt / CICLO * 2 * math.pi
            elif self.salto:  # ya está debajo de la ventana: salta encima
                self.px, self.modo, self.meta, self.vx = self.meta[0], "cae", (self.meta[0], self.salto[1]), 0.0
                self.vy = -math.sqrt(2 * GRAV * max(self.py - self.salto[1] + 40, 40))
            else:
                self.modo, self.siguiente, self.mira = "quieto", ahora + random.uniform(*PASEO), 0.0
                if self.patrulla and random.random() < DAR_ALTO:
                    self.alto = ahora + ALTO
        elif self.modo == "posado":
            if self.g.get("debajo") != self.salto[0] or ahora > self.siguiente:  # ventana movida o cerrada, o se aburre
                self.bajar()
        elif self.modo == "quieto" and not parado and ahora > self.siguiente:
            self.decidir(suelo)
        elif self.modo in ("quieto", "posado") and not parado and ahora > self.alto and random.random() < dt / MIRAR:
            self.mira = random.choice((-45, -20, 0, 0, 20, 45))  # echa un vistazo a un lado
        if self.modo in ("quieto", "anda"):
            self.py = suelo
        self.px, self.py = min(max(self.px, 0), max(self.width() - SW, 0)), min(self.py, suelo)

    def objetivo(self):
        """Hacia dónde quiere girarse: de perfil al andar, hacia ti si Delta te escucha o habla, si no adonde mire."""
        if self.modo == "anda":
            return ANDAR * self.dir
        if self.modo == "cae":
            return self.yaw
        return 0.0 if self.parado or self.alto > time.monotonic() else self.mira

    def girado(self):
        return abs(self.yaw - self.objetivo()) < 0.5

    def decidir(self, suelo):
        act, org = self.g.get("activa"), self.g.get("origen")
        sitio = act and act[1] and org and percha(act[1], org, self.width(), suelo)
        if sitio and random.random() < PERCHA:
            self.salto, self.g["posada"], self.g["debajo"] = (act[1], sitio[2]), act[0], act[1]
            x = random.uniform(sitio[0], sitio[1])
        else:
            self.salto, x = None, random.uniform(0, max(self.width() - SW, 0))
        self.meta, self.modo, self.dir = (x, suelo), "anda", 1 if x >= self.px else -1

    def bajar(self):
        """Del borde de la ventana al suelo con un saltito hacia un lado."""
        self.salto, self.g["posada"] = None, None
        self.dir = random.choice((-1, 1))
        self.vx, self.vy = 60.0 * self.dir, -350.0
        self.meta, self.modo = (self.px, self.height() - SH), "cae"

    def resizeEvent(self, e):
        if not self.colocado and self.width() > 2 * SW:  # recién maximizada: aparece abajo a la derecha
            self.colocado, self.px = True, float(self.width() - SW - 24)
        if self.modo == "posado":
            self.bajar()
        elif self.modo != "cae":
            self.py = float(self.height() - SH)

    # ---- dibujo ----
    def paintEvent(self, _):
        t = time.monotonic() - self.t0
        est = self.d.get("estado", "desconectado")
        permiso, voz = bool(self.d.get("confirma")), self.d.get("nivel", 0) or 0
        S, si = self.s, self.d.get("sistema") or {}
        # Delta dormido con el usuario delante: ojos abiertos y tranquilo; se duerme si no tocas nada en 5 min
        dormido = est == "desconectado" or (est == "dormido" and S["inactivo"] > INACTIVO)
        agobio = (si.get("cpu") or 0) >= CPU_ALTA or (si.get("ram") or 0) >= RAM_ALTA
        calor = (si.get("temp") or 0) >= CALOR
        bat = S.get("bat")
        bat_baja = bat and bat[1] == "Discharging" and bat[0] <= BAT_BAJA
        if t > self.parpadeo + 0.15 and random.random() < 0.012:
            self.parpadeo = t
        cerrados = dormido or t - self.parpadeo < 0.15
        resp = math.sin(t * 2 * math.pi / (6 if dormido else 3.5))
        cola = math.radians({"hablando": 8 + 16 * voz, "trabajando": 14}.get(est, 3 if dormido else 7)) * \
            math.sin(t * {"hablando": 9, "trabajando": 12}.get(est, 1.5 if dormido else 3))
        apagado = (0.55 if est == "desconectado" else 0.8 if dormido else 1.0) * (0.8 if bat_baja else 1.0)

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        bote = -abs(math.sin(self.paso)) * 3 * self.ritmo  # sube un poco en cada paso
        p.translate(self.px, self.py + bote)
        yaw = round(self.yaw / PASO_GIRO) * PASO_GIRO
        cs, sn = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
        oy = OY + resp * 1.2
        ox = OX + (math.sin(t * 47) * 0.9 if agobio else 0)  # agobiado: tiembla
        # El cuerpo quieto va en caché (pintar 1069 puntos por fotograma costaba media CPU); solo cola y ojos se mueven
        brillo = round(8 * (0.75 + 0.25 * voz if est == "hablando" else 0.9 + 0.1 * resp))
        clave = (apagado, agobio, brillo, yaw, self.patrulla)
        if clave not in self.cache:
            if len(self.cache) > 60:  # ~350 KB cada vista
                self.cache.clear()
            self.cache[clave] = self.cuerpo(*clave)
        # cola, patas, ojos, orejas, brazos, boca y uniforme se mueven: se pintan cada vez, detrás o delante del cuerpo
        # según su profundidad. Punto sin normal (0, 0) = plano: no se oculta y tiene luz fija.
        px, py = PIVOTE_COLA[1], PIVOTE_COLA[0]
        dtp, self.t_pint = min(time.monotonic() - self.t_pint, 0.1), time.monotonic()
        detras, delante = [], []
        cx_cola = cola_x(yaw)
        pts = self.gestos(t, dtp, est, voz, permiso, dormido, agobio, calor, resp)
        for x, y, z, nx, nz, ch, pt, fo, _, malla in MOVILES:
            if not malla_visible(malla, yaw):
                continue
            g, col = GRIS[ch], None
            if pt == "pata":
                x, y, z = self.pata(y, x, z)
            elif pt == "cola":
                dx, dy = x - px, y - py
                x, y = px + cx_cola + dx * math.cos(cola) - dy * math.sin(cola), py + dx * math.sin(cola) + dy * math.cos(cola)
            elif pt == "oreja":  # gira sobre su base (hacia fuera = gacha) y se alza
                i = int(x >= EJE)
                (bx, by), (a, alza) = PIVOTE_OREJA[i], self.orejas[i]
                a, dx, dy = math.radians(a if i else -a), x - bx, y - by
                x, y, nx, nz = bx + dx * math.cos(a) - dy * math.sin(a), by + dx * math.sin(a) + dy * math.cos(a) - alza, 0, 0
            elif cerrados:
                g = 26
            elif permiso:
                col = ROJO if int(t * 4) % 2 else QColor(60, 10, 8)
            elif est == "escuchando":
                col = ROJO
            pts.append((x, y, z, nx, nz, ch, g, col))
        for x, y, z, nx, nz, ch, g, col in pts:
            X, Z, NZ = girar(x, z, nx, nz, cs, sn)
            if NZ < -0.1 or (Z < 0 and tapado(X, y, cs, sn)):
                continue
            col = col or tono(round(g * (luz(NZ) if nx or nz else 0.9)), ch, apagado, agobio)
            (detras if Z < 0 else delante).append((Z, X, y, ch, col))
        for lista in (detras, None, delante):
            if lista is None:
                p.drawPixmap(QPointF(ox - OX, oy - OY), self.cache[clave])
                continue
            for Z, X, y, ch, col in sin_amontonar(lista):
                punto(p, ox + X * CELDA, oy + y * CELDA, ch, col)

        cx, cy = OX + 14 * CELDA, oy + 13 * CELDA
        if est == "trabajando":  # cometa de puntos rojos alrededor de la cabeza
            for i in range(7):
                a = t * 3.2 - i * 0.22
                p.setBrush(QColor(255, 45, 31, 255 - i * 34))
                p.drawEllipse(QPointF(cx + 82 * math.cos(a), cy + 70 * math.sin(a)), R, R)
        if dormido:  # zetas de puntos que suben y se desvanecen
            for k in range(2):
                s = (t / 3 + k / 2) % 1
                self.zeta(p, OX + 30 * CELDA + s * 18, OY + 2 * CELDA - s * 30, int(220 * (1 - s) * apagado))
        if calor:  # gotas de sudor naranjas que caen de la frente
            p.setBrush(NARANJA)
            for k in range(2):
                s = (t / 1.4 + k / 2) % 1
                p.drawEllipse(QPointF(ox + (28 + 2 * k) * CELDA, oy + (7 + 2 * k) * CELDA + s * 30), R * 1.4 * (1 - s * 0.4), R * 1.4 * (1 - s * 0.4))
        if self.alto > time.monotonic() and not self.parado:  # bocadillo del alto
            queda = self.alto - time.monotonic()
            centro = ox + 14.5 * CELDA
            if queda < ALTO - 0.6:
                fil = rotulo("GUARDIA CIVIL")
                self.sprite(p, fil, centro - len(fil[0]) * 2.2, oy - 8, QColor(70, 170, 90))
            fil = rotulo("¡ALTO!")
            self.sprite(p, fil, centro - len(fil[0]) * 2.2, oy - 38, ROJO)
        p.resetTransform()
        p.translate(self.px, self.py)
        self.iconos(p, t, bat, bat_baja)
        if permiso and int(t * 4) % 2:
            p.setBrush(ROJO)
            for f in (0, 1, 2, 4):
                p.drawEllipse(QPointF(cx, OY - 26 + f * CELDA), R, R)
        p.end()

    def pata(self, f, c, z):
        """Punto de las patas en el modelo (celdas): cada pata avanza alzada hacia donde mira (+z) y vuelve apoyada, a
        contrapaso de la otra; en el aire las encoge al subir y las abre al caer. La cadera se mueve menos que el pie."""
        w, lado = (f - 38) / 4, -1 if c < EJE else 1
        if self.modo == "cae":
            return c + lado * 0.8 * w, f + (0.7 if self.vy > 0 else -1.0) * w, z
        fase = self.paso + (0 if lado < 0 else math.pi)
        dz = -ZANCADA * math.cos(fase) * w * self.ritmo
        dy = -ALZA * max(math.sin(fase), 0) * w * self.ritmo
        return c, f + dy, z + dz

    def gestos(self, t, dt, est, voz, permiso, dormido, agobio, calor, resp):
        """Pone orejas y manos camino de la postura que toca y devuelve los puntos (x, y, z, nx, nz, ch, gris, color) de
        brazos, boca y, de patrulla, tricornio, placa y porra."""
        alto, k = self.alto > time.monotonic() and not self.parado, min(1.0, dt * 9)
        self.abre += ((voz if est == "hablando" else 0) - self.abre) * min(1.0, dt * 18)
        # orejas: (grados hacia fuera, celdas que se alzan)
        ore = ((28, 0) if dormido else (38, -0.3) if agobio else (-6, 0.8) if permiso else
               (-10, 1.2) if est == "escuchando" or alto else (18, 0) if calor else
               (3 + 10 * self.abre, 0.3 * self.abre) if est == "hablando" else (16, 0) if self.patrulla else (0, 0))
        if ore in ((0, 0), (16, 0)) and random.random() < dt / 4:  # tic de una oreja
            self.tic_oreja = (t + 0.25, random.randrange(2))
        metas = [(ore[0] + 18 * (t < self.tic_oreja[0] and self.tic_oreja[1] == i), ore[1]) for i in range(2)]
        self.orejas = [tuple(a + (b - a) * k for a, b in zip(o, m)) for o, m in zip(self.orejas, metas)]
        # manos
        porra = None
        if permiso:  # manos arriba
            s = math.sin(t * 8) * 1.2
            manos = ((1.5, 21 + s, 6), (27.5, 21 - s, 6))
        elif agobio:  # a la cabeza, temblando
            s = math.sin(t * 30) * 0.4
            manos = ((2.5, 11 + s, 3), (26.5, 11 - s, 3))
        elif est == "escuchando":  # mano a la oreja
            manos = (REPOSO[0], (28, 12, 3))
        elif est == "trabajando":  # teclea
            s = math.sin(t * 16) * 0.7
            manos = ((11, 29 + s, 10.5), (18, 29 - s, 10.5))
        elif est == "hablando":  # gesticula con la voz
            a, s = min(1.0, self.abre * 1.5), math.sin(t * 5) * self.abre
            manos = tuple((x, y - 5 * a + (-s if i else s), z + 3 * a) for i, (x, y, z) in enumerate(REPOSO))
        elif dormido:  # recogidas sobre la barriga
            manos = REPOSO
        elif alto:  # porra en alto y la otra mano: ¡alto!
            manos, porra = ((3.5, 19, 6), (26.5, 19, 9)), (-0.3, -0.95, 0.1)
        else:  # braceo al andar, a contrapaso de las patas
            sw = 1.5 * math.cos(self.paso) * self.ritmo
            manos = ((REPOSO[0][0], REPOSO[0][1], REPOSO[0][2] + sw), (REPOSO[1][0], REPOSO[1][1], REPOSO[1][2] - sw))
            th = math.radians(60 + 20 * math.cos(self.paso))  # porra hacia delante al andar, colgando parado
            porra = tuple(c + (w - c) * self.ritmo for c, w in zip((-0.35, 0.94, 0.0), (0, math.cos(th), math.sin(th))))
        self.manos = tuple(tuple(a + (b - a) * k for a, b in zip(m0, m1)) for m0, m1 in zip(self.manos, manos))
        pts = [(*q[:5], q[5], GRIS[q[5]], None) for i in (0, 1) for q in brazo(HOMBROS[i], self.manos[i], i)]
        # boca: (columna, fila, carácter o color)
        n = 2 if alto else round(min(self.abre, 1.0) * 2)
        if n:  # habla: se abre con la voz; muy abierta, enseña la lengua
            boca = [(c, 20, "#") for c in range(14 - (n > 1), 17 + (n > 1))] + \
                ([(14, 21, "#"), (15, 21, LENGUA), (16, 21, "#")] if n > 1 else [])
        elif permiso:  # sorpresa
            boca = [(14, 20, "#"), (15, 20, "#"), (16, 20, "#"), (15, 21, "#")]
        elif agobio or calor:  # morros: las comisuras bajan
            boca = [(13, 18, "o"), (17, 18, "o"), (13, 20, "#"), (17, 20, "#")]
        elif dormido:  # ronca
            boca = [(15, 20, "#")] if resp > 0.5 else []
        elif est == "trabajando":  # lengua fuera, concentrado
            boca = [(16, 20, LENGUA)]
        elif self.ritmo > 0.3 or self.modo == "posado":  # contento
            boca = [(14, 20, "#"), (15, 20, LENGUA), (16, 20, "#")]
        else:
            boca = []
        for c, f, q in boca:
            z, nx, nz, _ = superficie("cabeza", c, f)
            ch = q if isinstance(q, str) else "o"
            pts.append((c, f, z + 0.2, nx, nz, ch, GRIS[ch], None if ch is q else q))
        if self.patrulla and porra:  # tricornio y placa van en la caché del cuerpo
            self.porra = tuple(a + (b - a) * k for a, b in zip(self.porra, porra))
            m = math.sqrt(sum(c * c for c in self.porra)) or 1
            d, (hx, hy, hz) = [c / m for c in self.porra], self.manos[0]
            for i in range(-1, round(PORRA / 0.8) + 1):  # porra negra con un filo de brillo, dos puntos de gruesa
                x, y, z = hx + d[0] * i * 0.8, hy + d[1] * i * 0.8, hz + 0.4 + d[2] * i * 0.8
                pts += [(x - 0.5, y, z, 0, 0, "#", GRIS["#"] * 1.6, None), (x + 0.5, y, z + 0.1, 0, 0, "+", GRIS["+"], None)]
        return pts

    def cuerpo(self, apagado, agobio, brillo, yaw, patrulla):
        img = QPixmap(round(SW * self.devicePixelRatio()), round(SH * self.devicePixelRatio()))
        img.setDevicePixelRatio(self.devicePixelRatio())
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        cs, sn = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
        vista = []
        for x, y, z, nx, nz, ch, pt, fo, borde, malla in MODELO:
            if pt in ("cola", "ojo", "pata", "oreja") or not malla_visible(malla, yaw):
                continue
            X, Z, NZ = girar(x, z, nx, nz, cs, sn)
            if NZ < -0.1:  # cara que da la espalda: la tapa la de delante
                continue
            if borde and NZ > 0.45:  # el contorno ya no es silueta: sería una costura negra en mitad del cuerpo
                ch = "+"
            g = GRIS[ch] * brillo / 8 if ch == "o" and pt in ("hocico", "barriga") else GRIS[ch]
            vista.append((Z, X, y, ch, tono(round(g * luz(NZ)), ch, apagado, agobio)))
        if patrulla:  # uniforme: tricornio (plano = sin normal, luz fija) y placa dorada en el pecho
            for x, y, z, nx, nz, ch in SOMBRERO:
                X, Z, NZ = girar(x, z, nx, nz, cs, sn)
                if NZ >= -0.1:
                    vista.append((Z, X, y, ch, tono(round(GRIS[ch] * (luz(NZ) if nx or nz else 0.9)), ch, apagado, agobio)))
            for c, f in PLACA:
                z, nx, nz, _ = superficie("cuerpo", c, f)
                X, Z, NZ = girar(c, z + 0.3, nx, nz, cs, sn)
                if NZ >= -0.1:
                    vista.append((Z, X, f, "o", ORO if (c, f) != (10, 26) else QColor(150, 100, 20)))
        for Z, X, y, ch, col in sin_amontonar(vista):
            punto(p, OX + X * CELDA, OY + y * CELDA, ch, col)
        p.end()
        return img

    def iconos(self, p, t, bat, bat_baja):
        """Columna de iconos de puntos a la derecha, de abajo arriba: batería, wifi, café, papelera."""
        S, x, y = self.s, OX + 40 * CELDA + 2, SH - 14
        if bat and (bat_baja or bat[1] == "Charging"):
            lleno = (int(t * 2) % 6) if bat[1] == "Charging" else max(1, round(bat[0] / 20))
            relleno = ROJO if bat_baja else QColor(242, 242, 242)
            if not bat_baja or int(t * 2) % 2:
                y = self.sprite(p, BATERIA, x, y, QColor(138, 138, 138), {(f, c): relleno for f in (1, 2) for c in range(1, 1 + min(5, lleno))})
        if not S.get("wifi", True):
            y = self.sprite(p, WIFI, x, y, QColor(138, 138, 138), {(f, f + 1): ROJO for f in range(4)} | {(f, 5 - f): ROJO for f in range(4)})
        if S.get("cafe"):
            for k in range(2):  # vapor
                v = (t / 1.5 + k / 2) % 1
                p.setBrush(QColor(242, 242, 242, int(200 * (1 - v))))
                p.drawEllipse(QPointF(x + 5 + k * 9 + math.sin(t * 3 + k) * 1.5, y - 26 - v * 14), 1.7, 1.7)
            y = self.sprite(p, CAFE, x, y, QColor(242, 242, 242)) - 14
        if S.get("basura"):
            self.sprite(p, PAPELERA, x, y, QColor(138, 138, 138))

    def sprite(self, p, filas, x, y, col, extra={}):
        """Dibuja `filas` con la base en y; devuelve la y libre de encima."""
        top = y - len(filas) * 4.4
        for f, fila in enumerate(filas):
            for c, ch in enumerate(fila):
                if ch == "#" or (f, c) in extra:
                    p.setBrush(extra.get((f, c), col))
                    p.drawEllipse(QPointF(x + c * 4.4, top + f * 4.4), 1.7, 1.7)
        return top - 8

    def zeta(self, p, x, y, a):
        p.setBrush(QColor(242, 242, 242, max(0, a)))
        for f, c in ((0, 0), (0, 1), (0, 2), (1, 1), (2, 0), (2, 1), (2, 2)):
            p.drawEllipse(QPointF(x + c * 4, y + f * 4), 1.5, 1.5)

    # ---- ratón: encima muestra la ficha, arrastrar lo lleva (y al soltarlo cae), clic abre el panel ----
    def ficha(self):
        d, l = self.d, []
        if not d:
            return "Delta no está en marcha."
        l.append(f"<b>DELTA · {d.get('estado', '').upper()}</b> · {d.get('hora', '')}")
        i = d.get("impresora") or {}
        if i.get("online"):
            est = IMPRESORA.get(i.get("estado"), i.get("estado"))
            temp = f" · boquilla {i['boquilla'][0]}° · cama {i['cama'][0]}°" if i.get("boquilla") and i.get("cama") else ""
            l.append(f"Impresora: {est}" + (f" {i.get('prog')} % · {i.get('archivo', '')}" if i.get("estado") == "printing" else "") + temp)
        else:
            l.append("Impresora: sin conexión")
        s = d.get("sistema") or {}
        if s:
            l.append(f"Sistema: CPU {s.get('cpu')} % · RAM {s.get('ram')} %" + (f" · {s['temp']} °C" if s.get("temp") else ""))
        c = d.get("clima") or {}
        if c.get("temp") is not None:
            l.append(f"Tiempo: {c.get('ciudad', '')} {c['temp']}° (máx {c.get('max')} / mín {c.get('min')}) · humedad {c.get('hum')} %")
        cl, tr = (d.get("claude") or {}), [k for k, v in (d.get("trabajos") or {}).items() if v == "en curso"]
        l.append(f"Claude Code: {cl.get('estado', 'libre')}" + (f" · {len(tr)} trabajos en curso" if tr else ""))
        S = self.s
        if S.get("bat"):
            l.append(f"Batería: {S['bat'][0]} % · {dict(Charging='cargando', Discharging='descargando', Full='llena').get(S['bat'][1], S['bat'][1])}")
        if not S.get("wifi", True):
            l.append("<span style='color:#ff2d1f'>Sin red</span>")
        if S.get("basura"):
            l.append(f"Papelera: {S['basura']} elementos")
        if S.get("cafe"):
            l.append(f"Llevas {int((time.monotonic() - S['desde']) // 60)} min seguidos: toca un café")
        if d.get("confirma"):
            l.append(f"<span style='color:#ff2d1f'>Pide permiso: {d['confirma']}</span>")
        return "<br>".join(l)

    def enterEvent(self, e):
        QToolTip.showText(self.mapToGlobal(QPoint(round(self.px), round(self.py))), self.ficha(), self)

    def leaveEvent(self, e):
        QToolTip.hideText()

    def mousePressEvent(self, e):
        self.pulsado, self.agarre = e.position(), e.position() - QPointF(self.px, self.py)

    def mouseMoveEvent(self, e):
        if self.pulsado is not None and (self.modo == "arrastre" or (e.position() - self.pulsado).manhattanLength() > 4):
            self.modo, self.salto, self.g["posada"] = "arrastre", None, None
            q = e.position() - self.agarre
            self.px, self.py = q.x(), q.y()

    def mouseReleaseEvent(self, e):
        if self.modo == "arrastre":  # al soltarlo cae al suelo
            self.vx = self.vy = 0.0
            self.meta, self.modo = (self.px, self.height() - SH), "cae"
        elif self.pulsado is not None:
            self.ws.sendTextMessage('{"cmd": "vista_panel"}')
        self.pulsado = None


def colocar():
    """Wayland no deja a la app elegir su sitio: KWin la lleva a la pantalla principal (Qt en Wayland no ve bien las
    pantallas, por eso kscreen-doctor), encima de todo, y la maximiza para que la capa ocupe el área útil."""
    subprocess.Popen(["bash", "-c", r"""
W=$(kdotool search --class delta-mascota | head -1); [ -n "$W" ] || exit
kdotool windowstate --add ABOVE --add SKIP_TASKBAR --add SKIP_PAGER "$W"
read -r X Y AN AL < <(kscreen-doctor -o 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g' | awk '
  /^Output:/{en=0} /^[ \t]*enabled/{en=1} /priority/{p=$2}
  /Geometry:/ && en {split($2,xy,","); split($3,wh,"x"); g=xy[1]" "xy[2]" "wh[1]" "wh[2]; if(p==1){print g; f=1; exit}}
  END{if(!f) print g}')
kdotool windowmove "$W" $((X + 50)) $((Y + 50))
sleep 0.3
kdotool windowstate --add MAXIMIZED "$W"
"""])


if __name__ == "__main__":
    assert all(len(f) == 40 for f in MAPACHE) and len(MAPACHE) == 43
    # percha: ventana de 800 px de ancho a 400 px de alto en una capa de 2520×1080 que empieza en (40, 0)
    x0, x1, y = percha((540, 400, 800, 600), (40, 0), 2520, 1080 - SH)
    assert (x0, x1) == (500, 500 + 800 - SW) and y + PIES == 404
    assert percha((40, 0, 2520, 1080), (40, 0), 2520, 1080 - SH) is None   # maximizada: no cabe encima
    assert percha((540, 400, SW - 10, 600), (40, 0), 2520, 1080 - SH) is None  # más estrecha que el mapache
    app = QApplication(sys.argv)
    app.setDesktopFileName("delta-mascota")
    app.setStyleSheet("QToolTip{background:#000;color:#f2f2f2;border:1px solid #262626;padding:8px;"
                      "font-family:'IBM Plex Mono',monospace;font-size:12px}")
    m = Mascota()
    m.show()
    QTimer.singleShot(1200, colocar)
    sys.exit(app.exec())
