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
Cuerpo: el mapache 3D con esqueleto de mascota3d/ (malla + 13 huesos, rig.py) en la pose de la animación que toque
(poses.py: escucha, habla, trabaja, permiso, agobio, calor, duerme, anda, saltos, aterrizajes, ratos ociosos…),
pintado como rejilla de puntos y girado hacia donde mira; al cambiar de animación se funden. Encima, en sus anclas:
ojos (parpadean, rojos al escuchar), boca (habla con la voz, grita, sonríe al andar, se preocupa, ronca).
Patrulla: con Delta en espera y tú delante, ronda con tricornio, placa y porra; a veces se para y da el alto.
Gato (2026-10-19): con «gato» en mascota_elegida.txt, en vez del mapache sale el gato carey 3D de gato/ (su malla en
color y su esqueleto en gato.npz, sus poses de gato en gato/poses.py con los mismos nombres) con los mismos estados,
iconos y paseos; al cambiar el archivo se reinicia.
"""
import glob
import html
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

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")  # el skinning es un producto pequeño: con un hilo por núcleo, OpenBLAS
import numpy as np  # noqa: E402                      # se queda girando en espera y se come 6 núcleos
from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, QUrl
from PyQt6.QtGui import QColor, QFontDatabase, QImage, QPainter, QPixmap, QRegion
from PyQt6.QtWebSockets import QWebSocket
from PyQt6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QToolTip, QVBoxLayout, QWidget

from mascota3d.rig import TAM, Mapache

PANEL = "127.0.0.1:7876"
ELEGIDA = Path(__file__).with_name("mascota_elegida.txt")  # «mapache» o «gato» (lo escribe deltaos.elegir_mascota)


def especie():
    try:
        return "gato" if ELEGIDA.read_text().strip() == "gato" else "mapache"
    except OSError:
        return "mapache"


ESPECIE = especie()
if ESPECIE == "gato":
    from gato.poses import ANIM
else:
    from mascota3d.poses import ANIM
CELDA, R = 5, 2.1                     # px entre puntos (1 celda de la rejilla del rig) y radio del punto
C0 = 0 if ESPECIE == "gato" else 8    # primera columna de la rejilla que cabe en la caja (el gato tumbado es más ancho)
GRIS = {"#": 26, "+": 138, "o": 242}
ROJO = QColor(255, 45, 31)
NARANJA = QColor(255, 140, 0)
INACTIVO = 300          # s sin teclado ni ratón: se acurruca a dormir
PAUSA = 50 * 60         # s de actividad seguida: saca un café
CPU_ALTA, RAM_ALTA, CALOR, BAT_BAJA = 85, 92, 85, 20  # %, % (8 GB: el 86 % es lo normal), °C, %
ICONOS_X = (TAM - 2 * C0) * CELDA + 2  # columna de iconos, a la derecha del mapache
SW, SH = ICONOS_X + 36, TAM * CELDA    # caja del mapache: la rejilla del rig (64×64) y los iconos
PIES = 59 * CELDA               # de lo alto de la caja a la punta de las patas (fila 58 de la rejilla, de pie)
OREJAS = 12 * CELDA             # de lo alto de la caja a la punta de las orejas
VEL, GRAV = 70, 2200            # px/s andando, px/s² en saltos y caídas
PASEO = (25, 90)                # s quieto entre paseo y paseo
PERCHA = 0.4                    # probabilidad de subirse a la ventana activa en vez de andar por el suelo
VGIRO, ANDAR = 240, 70          # °/s al girarse sobre sí mismo; ° de perfil al andar (0 = de frente)
MIRAR = 7                       # s de media entre vistazos a un lado y otro cuando está quieto
OCIO = 30                       # s de media entre ratos ociosos (estirarse, bostezar, rascarse…) cuando está quieto
BOCADILLO = 300                 # px de ancho del bocadillo de permiso
OCIOS = {"estira": 2.5, "bosteza": 2.0, "rasca": 2.5, "saluda": 2.0, "curioso": 3.0}  # animación: s que dura
MEZCLA = 0.25                   # s que tarda en fundirse una animación con la siguiente
FPS_CUERPO = 10                 # poses por segundo (cada una cuesta ~10 ms de numpy, el gato fino ~20); la posición va a 20
FINO = 2                        # el gato se pinta en una rejilla 2× más fina y suavizado, no a puntos
ALTO = 2.6                      # s que dura el «¡alto!» de la patrulla
DAR_ALTO = 0.35                 # probabilidad de dar el alto al acabar una ronda
PORRA = 7                       # celdas de largo
LENGUA, ORO = QColor(214, 96, 104), QColor(232, 182, 48)
MAPACHE = Mapache(Path(__file__).with_name("gato") / "gato.npz") if ESPECIE == "gato" else Mapache()
SELLOS = {}                     # color → QPixmap del punto (ver Mascota.sello)
# Iconos de puntos a su derecha (# = punto)
BATERIA = ["#######.", "#.....##", "#.....##", "#######."]
WIFI = [".#####.", "#.....#", "..###..", ".#...#.", "...#..."]
CAFE = ["#####..", "#####.#", "#####.#", "#####..", ".###..."]
PAPELERA = ["..##..", "######", ".#..#.", ".#..#.", ".#..#.", ".####."]
IMPRESORA = {"printing": "imprimiendo", "standby": "en espera", "complete": "terminada", "paused": "en pausa",
             "error": "ERROR", "cancelled": "cancelada"}


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


def mezcla(a, b, k):
    """Pose entre a y b (k de 0 a 1): al cambiar de animación no pega un salto."""
    if k >= 1:
        return b
    neutro = {"r": (0, 0, 0), "t": (0, 0, 0), "s": (1, 1, 1)}
    return {h: {c: tuple(x + (y - x) * k for x, y in zip(a.get(h, {}).get(c, n), b.get(h, {}).get(c, n)))
                for c, n in neutro.items()} for h in a.keys() | b.keys()}


FUENTE = dict(zip("ALTOGURDICV!¡ ", (
    ("###", "#.#", "###", "#.#", "#.#"), ("#..", "#..", "#..", "#..", "###"), ("###", ".#.", ".#.", ".#.", ".#."),
    ("###", "#.#", "#.#", "#.#", "###"), ("###", "#..", "#.#", "#.#", "###"), ("#.#", "#.#", "#.#", "#.#", "###"),
    ("##.", "#.#", "##.", "#.#", "#.#"), ("##.", "#.#", "#.#", "#.#", "##."), ("###", ".#.", ".#.", ".#.", "###"),
    ("###", "#..", "#..", "#..", "###"), ("#.#", "#.#", "#.#", "#.#", ".#."), ("#", "#", "#", ".", "#"),
    ("#", ".", "#", "#", "#"), ("..", "..", "..", "..", ".."))))


def rotulo(texto):
    """Filas de puntos («#») del texto en letra de 3x5."""
    return [".".join(FUENTE[ch][f] for ch in texto) for f in range(5)]


# Tricornio visto de frente (# charol, o brillo, + canto del ala); la última fila se apoya sobre la cabeza
TRICORNIO = [".......#####.......", "....###########....", "...#############...", "..###o###########..",
             "..##oo###########..", ".#################.", "+++++++++++++++++++"]
PLACA = [(-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1), (0, 2)]  # (col, fila) desde el centro
assert rotulo("¡ALTO!")[0] == "#.###.#...###.###.#" and rotulo("¡ALTO!")[3] == "#.#.#.#....#..#.#.."


def tono(g, apagado, agobio):
    g = round(g * apagado)
    return QColor(g + 70, g // 3, g // 4) if agobio and g < 60 else QColor(g, g, g)

HUD_FIN = 600                   # s que la barra sigue enseñando un trabajo ya acabado, con su ✓ o ✗
HUD_PASOS = 4                   # herramientas en la barra (las repetidas seguidas cuentan como una, con ×N)
ESTILO_HUD = ("background:rgba(0,0,0,215);color:#f2f2f2;border:1px solid #262626;border-radius:10px;padding:8px 14px;"
              "font-family:'IBM Plex Mono',monospace;font-size:12px")
ESTILO_BARRA = ("#hud{background:rgba(0,0,0,235);border:1px solid #262626;border-radius:10px}"
                "QLabel{color:#f2f2f2;font-family:'IBM Plex Mono',monospace;font-size:12px;background:transparent}"
                "#raya{background:#262626}")
GRIS_HUD, ROJO_HUD, LINEA_HUD = "#6e6e6e", "#ff2d1f", "#262626"


def barra(pct, n=12, color="#f2f2f2"):
    """Barra de progreso maciza: lo hecho en `color`, lo que falta en gris oscuro."""
    k = round(n * max(0, min(100, pct)) / 100)
    return f"<span style='color:{color}'>{'█' * k}</span><span style='color:#333333'>{'█' * (n - k)}</span>"


def reloj(s):
    s = int(s)
    return f"{s // 60}:{s % 60:02d}" if s < 3600 else f"{s // 3600} h {s // 60 % 60:02d}"


def corto(t, n):
    return t if len(t) <= n else t[:n - 1] + "…"


def trabajos_hud(d, ahora):
    """[(nombre, estado, progreso)] en curso o acabados hace menos de HUD_FIN, del más viejo al más nuevo."""
    tr, pg = d.get("trabajos") or {}, d.get("progreso") or {}
    return [(n, tr.get(n, ""), g) for n, g in sorted(pg.items(), key=lambda x: x[1].get("ini") or 0)
            if tr.get(n) == "en curso" or (g.get("fin") and ahora - g["fin"] < HUD_FIN)]


def pasos_hud(pasos):
    """Últimas herramientas, la más nueva arriba; las iguales seguidas se juntan: [(paso más reciente, veces)]."""
    junto = []
    for p in pasos or []:
        if junto and (junto[-1][0].get("t"), junto[-1][0].get("e")) == (p.get("t"), p.get("e")):
            junto[-1][1] += 1
            junto[-1][0] = p
        else:
            junto.append([p, 1])
    return [tuple(x) for x in junto[::-1][:HUD_PASOS]]


def hud(d, ahora):
    """Columnas de la barra (como claude-hud), en HTML, solo con datos medidos por el código, nunca con lo que diga
    Gemini: DELTA (estado, contexto y gasto de Gemini, Claude Code) · TRABAJOS en segundo plano con etapa, % y tiempo
    (salen de su log) · ÚLTIMOS PASOS (herramientas con su resultado real). Sin Delta, una sola."""
    e = html.escape
    rojo = lambda t: f"<span style='color:{ROJO_HUD}'>{t}</span>"
    gris = lambda t: f"<span style='color:{GRIS_HUD}'>{t}</span>"
    titulo = lambda t: f"<span style='color:{GRIS_HUD};font-size:10px'>{t}</span>"
    if not d:
        return [f"<b>DELTA</b> · {rojo('no está en marcha')}"]
    est, u, cl = d.get("estado", ""), d.get("uso") or {}, d.get("claude") or {}
    clave = lambda k: gris(k.ljust(7).replace(" ", "&nbsp;"))  # letra fija: las claves alinean los valores

    delta = [titulo("DELTA"), clave("") + (rojo("●") if est in ("escuchando", "trabajando") else "●") + f" <b>{e(est.upper())}</b>"]
    if est != "dormido" and d.get("conexion") not in (None, "conectado"):
        delta.append(clave("") + rojo(e(d["conexion"])))
    if u:
        tok = f"{u['tok'] / 1e6:.2f}M" if u.get("tok", 0) >= 1e6 else f"{u.get('tok', 0) / 1000:.1f}K"
        ctx = u.get("ctx", 0)
        delta.append(clave("Gemini") + barra(ctx, 8, ROJO_HUD if ctx >= 80 else "#f2f2f2") + f" {ctx:.0f}% ctx")
        delta.append(clave("") + gris(f"{tok} tok · ≈{u.get('usd', 0):.2f} $".replace(".", ",")))
    ce = cl.get("estado", "libre")
    delta.append(clave("Claude") + (rojo(e(ce)) if ce == "esperando permiso" else gris("libre") if ce == "libre" else e(ce)))
    if ce == "trabajando" and cl.get("pasos"):
        delta.append(clave("") + gris(e(corto(cl["pasos"][-1].get("t", ""), 30))))

    tra = [titulo("TRABAJOS")]
    for n, estado, g in trabajos_hud(d, ahora):
        n = e(re.sub(r"-\d+$", "", n))
        if estado == "en curso":
            pct = g.get("pct")
            tra.append(rojo("▶") + f" <b>{n}</b> " + (f"{barra(pct, 12, ROJO_HUD)} {pct:d}%" if pct is not None else ""))
            tra.append("&nbsp;&nbsp;" + e(corto(g.get("etapa") or "arrancando…", 44)) + " · " +
                       gris(reloj(ahora - (g.get("ini") or ahora))))
        else:
            ok = estado.startswith("terminó bien")
            tra.append(("✓" if ok else rojo("✗")) + f" <b>{n}</b> " +
                       gris(e(estado) + " · " + time.strftime("%H:%M", time.localtime(g["fin"]))))
            if not ok and g.get("etapa"):
                tra.append("&nbsp;&nbsp;" + rojo(e(corto(g["etapa"], 44))))
    if len(tra) == 1:
        tra.append(gris("ninguno"))

    marca = {"hecho": "✓", "falló": rojo("✗")}
    pas = [titulo("ÚLTIMOS PASOS")] + [f"{marca.get(p.get('e'), rojo('●'))} {gris(p.get('h', '')[:5])} "
                                       f"{e(corto(p.get('t', ''), 38))}" + (gris(f" ×{k}") if k > 1 else "")
                                       for p, k in pasos_hud(d.get("pasos"))]
    if len(pas) == 1:
        pas.append(gris("sin herramientas todavía"))
    return ["<br>".join(c) for c in (delta, tra, pas)]


def globo(d, ahora):
    """Lo que dice el mapache en su globo mientras hay un trabajo en curso: etapa y %."""
    for n, estado, g in trabajos_hud(d, ahora):
        if estado == "en curso":
            pct = g.get("pct")
            return (f"{re.sub(r'-\d+$', '', n)} · " + (f"{pct} % · " if pct is not None else "") +
                    corto(g.get("etapa") or "arrancando…", 70))
    return ""


class Barra(QFrame):
    """La barra de arriba: hasta tres columnas de hud() separadas por una raya fina."""
    def __init__(self, padre):
        super().__init__(padre)
        self.setObjectName("hud")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)  # sin esto el fondo no se pinta y se lee lo de detrás
        self.setStyleSheet(ESTILO_BARRA)
        fila = QHBoxLayout(self)
        fila.setContentsMargins(14, 8, 14, 8)
        fila.setSpacing(16)
        self.cols, self.rayas = [], []
        for i in range(3):
            if i:
                r = QFrame(self, objectName="raya")
                r.setFixedWidth(1)
                fila.addWidget(r)
                self.rayas.append(r)
            c = QLabel(self, textFormat=Qt.TextFormat.RichText, alignment=Qt.AlignmentFlag.AlignTop)
            fila.addWidget(c)
            self.cols.append(c)
        self.textos = None

    def poner(self, cols):
        if cols == self.textos:
            return False
        self.textos = cols
        for i, c in enumerate(self.cols):
            c.setText(cols[i] if i < len(cols) else "")
            c.setVisible(i < len(cols))
        for i, r in enumerate(self.rayas):
            r.setVisible(i + 1 < len(cols))
        self.adjustSize()
        return True


class Bocadillo(QFrame):
    """Pide permiso (2026-10-19): qué quiere hacer Delta, en corto, y Sí / No encima de la cabeza del mapache."""
    def __init__(self, padre, responder):
        super().__init__(padre)
        self.setObjectName("bocadillo")
        self.setStyleSheet("#bocadillo{background:#000;border:1px solid #ff2d1f;border-radius:10px}"
                           "QLabel{color:#f2f2f2;font-family:'IBM Plex Mono',monospace;font-size:12px}"
                           "QPushButton{font-family:'IBM Plex Mono',monospace;font-size:13px;padding:6px 0;border-radius:6px;"
                           "border:1px solid #f2f2f2;color:#f2f2f2;background:#000}QPushButton:hover{background:#262626}"
                           "QPushButton#si{background:#f2f2f2;color:#000}QPushButton#si:hover{background:#ff2d1f;border-color:#ff2d1f}")
        self.setFixedWidth(BOCADILLO)
        self.texto = QLabel(wordWrap=True, textFormat=Qt.TextFormat.PlainText)  # el texto lo escribe Gemini: nada de HTML
        botones = QHBoxLayout()
        for nombre, rotulo, cmd in (("si", "Sí", "permitir"), ("no", "No", "denegar")):
            b = QPushButton(rotulo, objectName=nombre, focusPolicy=Qt.FocusPolicy.NoFocus)
            b.clicked.connect(lambda _, c=cmd: self.contestar(responder, c))
            botones.addWidget(b)
        caja = QVBoxLayout(self)
        caja.setContentsMargins(12, 10, 12, 10)
        caja.addWidget(self.texto)
        caja.addLayout(botones)
        self.pregunta = self.contestada = None
        self.hide()

    def contestar(self, responder, cmd):
        self.contestada = self.pregunta  # no volver a sacarlo mientras el panel recibe la respuesta (~0,4 s)
        self.hide()
        responder(cmd)

    def poner(self, texto):
        self.pregunta = texto
        texto = "Delta quiere " + (texto if len(texto) <= 180 else texto[:179] + "…")
        if texto != self.texto.text():
            self.texto.setText(texto)
            self.adjustSize()


class Mascota(QWidget):
    def __init__(self):
        super().__init__(flags=Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool |
                         Qt.WindowType.WindowDoesNotAcceptFocus)  # capa de pantalla entera: el teclado, nunca
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(SW, SH)
        self.resize(SW, SH)
        self.d, self.t0, self.parpadeo = {}, time.monotonic(), 0.0
        ahora = time.monotonic()
        # paseo (fase 4): posición del mapache dentro de la capa, hacia dónde mira y qué hace
        self.px = self.py = self.vx = self.vy = 0.0
        self.dir, self.modo, self.meta, self.salto = 1, "quieto", (0.0, 0.0), None
        self.yaw, self.mira, self.parado = 0.0, 0.0, False  # ° girado (0 de frente, + mira a la derecha), adónde mira quieto
        # cuerpo: animación en curso (desde cuándo y desde qué pose se funde), evento de una vez (nombre, hasta cuándo),
        # boca (cuánto abre con la voz) y el último fotograma pintado
        self.anim, self.t_anim, self.pose0, self.pose = "reposo", ahora, {}, {}
        self.evento, self.abre, self.foto, self.t_foto = None, 0.0, None, 0.0
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
        self.bocadillo = Bocadillo(self, lambda c: self.ws.sendTextMessage(json.dumps({"cmd": c})))
        # barra fija arriba (estilo claude-hud) y globo del mapache con la etapa del trabajo: fuera de la máscara, el
        # ratón los atraviesa
        self.barra = Barra(self)
        self.globo = QLabel(self, textFormat=Qt.TextFormat.PlainText, styleSheet=ESTILO_HUD.replace("#262626", "#ff2d1f"))
        self.globo.hide()
        self.mascara = QRegion()
        reloj = QTimer(self, interval=50)
        reloj.timeout.connect(self.tic)
        reloj.start()

    def sensores(self):
        if especie() != ESPECIE:  # han elegido la otra mascota: se vuelve a arrancar con ella (la caja cambia de ancho)
            os.execv(sys.executable, [sys.executable, *sys.argv])
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
        if self.evento and (ahora > self.evento[1] or (parado and self.evento[0] in OCIOS)):
            self.evento = None
        self.patrulla = ESPECIE == "mapache" and est == "dormido" and self.s["inactivo"] <= INACTIVO  # el gato no es guardia
        self.mover(dt, ahora, parado)
        caja = QRect(round(self.px), round(self.py), SW, SH)
        mascara = QRegion(caja)
        b = self.bocadillo
        if not self.d.get("confirma"):
            b.contestada = None
        if self.d.get("confirma") and self.d["confirma"] != b.contestada:  # el bocadillo, sobre las orejas y sin salirse de la pantalla
            b.poner(self.d["confirma"])
            b.move(round(min(max(self.px + SW / 2 - b.width() / 2, 8), self.width() - b.width() - 8)),
                   round(max(self.py + OREJAS - b.height() - 30, 8)))  # 30: deja ver el «!» rojo
            b.show()
            mascara = mascara.united(QRegion(b.geometry()))
        else:
            b.hide()
        self.pintar_hud(b.isVisible())
        if mascara != self.mascara and self.windowHandle():
            self.windowHandle().setMask(mascara)  # solo el mapache (y el bocadillo) reciben el ratón; el resto lo deja pasar
            self.mascara = mascara
        self.update(caja.united(self.caja or caja).adjusted(-12, -12, 12, 12))  # solo su recuadro: repintar la capa entera costaría
        self.caja = caja

    def pintar_hud(self, permiso):
        ahora = time.time()
        self.barra.poner(hud(self.d, ahora))
        self.barra.move((self.width() - self.barra.width()) // 2, 6)
        g = "" if permiso else globo(self.d, ahora)  # el bocadillo de permiso manda
        if g != self.globo.text():
            self.globo.setText(g)
            self.globo.adjustSize()
        self.globo.setVisible(bool(g))
        if g:
            self.globo.move(round(min(max(self.px + SW / 2 - self.globo.width() / 2, 8), self.width() - self.globo.width() - 8)),
                            round(max(self.py + OREJAS - self.globo.height() - 26, 8)))

    def mover(self, dt, ahora, parado):
        suelo = self.height() - SH
        self.yaw += max(min(self.objetivo() - self.yaw, VGIRO * dt), -VGIRO * dt)
        if self.modo == "cae":
            self.vy += GRAV * dt
            self.px += self.vx * dt
            self.py += self.vy * dt
            if self.vy > 0 and self.py >= self.meta[1]:
                golpe = "aplastado" if self.vy > 1400 and not self.salto else "aterriza"  # soltado desde arriba: plof
                self.evento = (golpe, ahora + ANIM[golpe][1])
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
        elif self.modo == "quieto" and not parado and not self.evento and random.random() < dt / OCIO:
            nombre = random.choice(list(OCIOS))  # se estira, bosteza, se rasca, saluda o curiosea
            self.evento = (nombre, ahora + OCIOS[nombre])
        if self.modo in ("quieto", "anda"):
            self.py = suelo
        self.px, self.py = min(max(self.px, 0), max(self.width() - SW, 0)), min(self.py, suelo)

    def elegir(self, est, permiso, dormido, agobio, calor, alto):
        """Animación de poses.py que toca ahora; las del estado de Delta mandan sobre las del paseo."""
        if self.modo == "arrastre":
            return "arrastre"
        if self.modo == "cae":
            return "salto_sube" if self.vy < 0 else "salto_cae" if self.salto else "cae"
        if self.evento and self.evento[0] not in OCIOS:  # aterrizajes
            return self.evento[0]
        estado = ("duerme" if dormido else "permiso" if permiso else "agobio" if agobio else
                  {"escuchando": "escucha", "hablando": "habla", "trabajando": "trabaja"}.get(est) or
                  ("calor" if calor else "alto" if alto else None))
        if estado:
            return estado
        if self.modo == "anda":
            return "anda"
        if self.evento:
            return self.evento[0]
        if self.modo == "posado":
            return "sentado"
        return "come" if self.s.get("cafe") else "reposo"

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
        ahora = time.monotonic()
        t = ahora - self.t0
        est = self.d.get("estado", "desconectado")
        permiso, voz = bool(self.d.get("confirma")), self.d.get("nivel", 0) or 0
        S, si = self.s, self.d.get("sistema") or {}
        # Delta dormido con el usuario delante: ojos abiertos y tranquilo; se duerme si no tocas nada en 5 min
        dormido = est == "desconectado" or (est == "dormido" and S["inactivo"] > INACTIVO)
        agobio = (si.get("cpu") or 0) >= CPU_ALTA or (si.get("ram") or 0) >= RAM_ALTA
        calor = (si.get("temp") or 0) >= CALOR
        bat = S.get("bat")
        bat_baja = bat and bat[1] == "Discharging" and bat[0] <= BAT_BAJA
        alto = self.alto > ahora and not self.parado
        apagado = (0.55 if est == "desconectado" else 0.8 if dormido else 1.0) * (0.8 if bat_baja else 1.0)

        nombre = self.elegir(est, permiso, dormido, agobio, calor, alto)
        if nombre != self.anim:
            self.anim, self.t_anim, self.pose0 = nombre, ahora, self.pose
        if self.foto is None or ahora - self.t_foto >= 1 / FPS_CUERPO:  # la pose, a 10 por segundo: cuesta ~10 ms
            dtp, self.t_foto = min(ahora - self.t_foto, 0.2), ahora
            if t > self.parpadeo + 0.15 and random.random() < 0.08:
                self.parpadeo = t
            self.abre += ((voz if est == "hablando" else 0) - self.abre) * min(1.0, dtp * 18)
            f, dur = ANIM[nombre]
            ta = ahora - self.t_anim
            self.pose = mezcla(self.pose0, f(min(ta, dur) if dur else ta), ta / MEZCLA)
            ojos = (QColor(GRIS["#"], GRIS["#"], GRIS["#"]) if dormido or t - self.parpadeo < 0.15 else
                    (ROJO if int(t * 4) % 2 else QColor(60, 10, 8)) if permiso else ROJO if est == "escuchando" else None)
            self.foto = self.fotograma(self.pose, ojos, self.boca(t, est, permiso, dormido, agobio, calor, alto),
                                       apagado, agobio, alto, t)

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.translate(self.px, self.py)
        img, A = self.foto
        p.drawPixmap(0, 0, img)
        xy = lambda k, dc=0, df=0: QPointF((A[k][0] + dc - C0) * CELDA, (A[k][1] + df) * CELDA)  # ancla → px de la caja
        if est == "trabajando":  # cometa de puntos rojos alrededor de la cabeza
            c = xy("nariz", 0, -4)
            for i in range(7):
                a = t * 3.2 - i * 0.22
                p.setBrush(QColor(255, 45, 31, 255 - i * 34))
                p.drawEllipse(c + QPointF(82 * math.cos(a), 70 * math.sin(a)), R, R)
        if dormido:  # zetas de puntos que suben y se desvanecen
            c = xy("coronilla", 12, -4)
            for k in range(2):
                s = (t / 3 + k / 2) % 1
                self.zeta(p, c.x() + s * 18, c.y() - s * 30, int(220 * (1 - s) * apagado))
        if calor:  # gotas de sudor naranjas que caen de la frente
            p.setBrush(NARANJA)
            for k in range(2):
                s = (t / 1.4 + k / 2) % 1
                p.drawEllipse(xy("coronilla", 9 + 2 * k, 3 + 2 * k) + QPointF(0, s * 30), R * 1.4 * (1 - s * 0.4), R * 1.4 * (1 - s * 0.4))
        if alto:  # bocadillo del alto
            queda = self.alto - ahora
            if queda < ALTO - 0.6:
                fil = rotulo("GUARDIA CIVIL")
                self.sprite(p, fil, SW / 2 - len(fil[0]) * 2.2, OREJAS - 8, QColor(70, 170, 90))
            fil = rotulo("¡ALTO!")
            self.sprite(p, fil, SW / 2 - len(fil[0]) * 2.2, OREJAS - 38, ROJO)
        self.iconos(p, t, bat, bat_baja)
        if permiso and int(t * 4) % 2:
            p.setBrush(ROJO)
            c = xy("coronilla", 0, -14)
            for f in (0, 1, 2, 4):
                p.drawEllipse(c + QPointF(0, f * CELDA), R, R)
        p.end()

    def boca(self, t, est, permiso, dormido, agobio, calor, alto):
        """Puntos de la boca: [(col, fila desde el ancla «boca», «#»/«o» o color)]."""
        n = 2 if alto else round(min(self.abre, 1.0) * 2)
        if n:  # habla: se abre con la voz; muy abierta, enseña la lengua
            return [(c, 0, "#") for c in range(-1 - (n > 1), 2 + (n > 1))] + \
                ([(-1, 1, "#"), (0, 1, LENGUA), (1, 1, "#")] if n > 1 else [])
        if permiso:  # sorpresa
            return [(-1, 0, "#"), (0, 0, "#"), (1, 0, "#"), (0, 1, "#")]
        if agobio or calor:  # morros: las comisuras bajan
            return [(-2, -1, "o"), (2, -1, "o"), (-2, 0, "#"), (2, 0, "#")]
        if dormido:  # ronca
            return [(0, 0, "#")] if math.sin(t * 2 * math.pi / 6) > 0.5 else []
        if est == "trabajando":  # lengua fuera, concentrado
            return [(1, 0, LENGUA)]
        if self.modo in ("anda", "posado"):  # contento
            return [(-1, 0, "#"), (0, 0, LENGUA), (1, 0, "#")]
        return []

    def fotograma(self, pose, ojos, boca, apagado, agobio, alto, t):
        """(QPixmap de la caja con el mapache en `pose`, anclas): la rejilla del rig, con ojos y boca encima y, de
        patrulla, tricornio, placa y porra."""
        if ESPECIE == "gato":
            return self.fotograma_fino(pose, ojos, boca, apagado, agobio)
        G, _, A = MAPACHE.pintar(pose, -self.yaw, todas=True)  # el rig gira al revés: + es hacia su izquierda
        if G.ndim == 3:  # el gato viene en color: cada celda pasa a un entero 0xRRGGBB (+ 1 << 24 para no ser «vacía»)
            C = G * apagado
            if agobio:  # se pone rojo
                C = C * (0.55, 0.35, 0.3) + (110, 0, 0)
            C = (np.clip(C, 0, 255).astype(int) // 8 * 8)  # de 8 en 8: pocos sellos distintos
            G = np.where(G.any(-1), (1 << 24) | C[..., 0] << 16 | C[..., 1] << 8 | C[..., 2], 0)
            pinta, claro, radio = lambda g: QColor((g >> 16) & 255, (g >> 8) & 255, g & 255), 1, 2.25
        else:
            pinta, claro, radio = lambda g: tono(g, apagado, agobio), 150, 4
        color = {}  # (fila, col) → QColor en vez del del rig
        for k in ("ojo_i", "ojo_d"):
            x, y, vis = A[k]
            if ojos and vis:  # cerrados o rojos: los puntos claros del ojo (en el gato, todo el ojo)
                for f in range(int(y) - 2, int(y) + 3):
                    for c in range(int(x) - 2, int(x) + 3):
                        if 0 <= f < TAM and 0 <= c < TAM and G[f, c] >= claro and (c + 0.5 - x) ** 2 + (f + 0.5 - y) ** 2 <= radio:
                            color[f, c] = ojos
        x, y, vis = A["boca"]
        if vis:
            for dc, df, q in boca:
                f, c = int(y) + df, int(x) + dc
                if 0 <= f < TAM and 0 <= c < TAM:
                    G[f, c] = max(G[f, c], 1)
                    color[f, c] = q if isinstance(q, QColor) else tono(GRIS[q], apagado, False)
        img = QPixmap(round(SW * self.devicePixelRatio()), round(SH * self.devicePixelRatio()))
        img.setDevicePixelRatio(self.devicePixelRatio())
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        sellos = {g: self.sello(pinta(g)) for g in np.unique(G).tolist()}  # ~200 grises o colores, no ~1100 celdas
        d = round(CELDA / 2 - R - 1)  # de la esquina de la celda a la del sello
        for f, c in np.argwhere(G[:, C0:TAM - C0]).tolist():
            q = color.get((f, c + C0))
            p.drawPixmap(c * CELDA + d, f * CELDA + d, self.sello(q) if q else sellos[int(G[f, c + C0])])
        if self.patrulla:
            self.uniforme(p, A, apagado, alto, t)
        p.end()
        return img, A

    def fotograma_fino(self, pose, ojos, boca, apagado, agobio):
        """El gato: la rejilla fina del rig como imagen, escalada con suavizado a la caja (sin puntos); ojos cerrados
        o rojos y boca, encima como manchas suaves."""
        G, _, A = MAPACHE.pintar(pose, -self.yaw, todas=True, fino=FINO)
        lleno = G.any(-1)
        C = G * apagado
        if agobio:  # se pone rojo
            C = C * (0.55, 0.35, 0.3) + (110, 0, 0)
        rgba = np.ascontiguousarray(np.dstack([np.clip(C, 0, 255) * lleno[..., None], lleno * 255]).astype(np.uint8))
        T = len(G)
        imagen = QImage(rgba.data, T, T, 4 * T, QImage.Format.Format_RGBA8888_Premultiplied)  # alfa 0 o 255: ya va
        img = QPixmap(round(SW * self.devicePixelRatio()), round(SH * self.devicePixelRatio()))  # premultiplicado
        img.setDevicePixelRatio(self.devicePixelRatio())
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        p.drawImage(QRectF(-C0 * CELDA, 0, TAM * CELDA, TAM * CELDA), imagen)
        p.setPen(Qt.PenStyle.NoPen)
        ancho = max(0.35, abs(math.cos(math.radians(self.yaw))))  # de lado, los ojos se ven más estrechos
        for k in ("ojo_i", "ojo_d"):
            x, y, vis = A[k]
            if not (ojos and vis):
                continue
            c = QPointF((x - C0) * CELDA, y * CELDA)
            if ojos.red() > 50:  # rojos: escucha o pide permiso
                p.setBrush(ojos)
                p.drawEllipse(c, 1.9 * CELDA * ancho, 1.8 * CELDA)  # tapa el ojo verde entero
            else:  # cerrados: párpado del color del pelo de encima y una raya oscura
                f, cc = min(max(int((y - 2.2) * FINO), 0), T - 1), min(max(int(x * FINO), 0), T - 1)
                p.setBrush(QColor(*rgba[f, cc, :3].tolist()) if lleno[f, cc] else ojos)
                p.drawEllipse(c, 1.7 * CELDA * ancho, 1.6 * CELDA)
                p.setBrush(ojos)
                p.drawRoundedRect(QRectF(c.x() - 1.4 * CELDA * ancho, c.y() - 0.2 * CELDA, 2.8 * CELDA * ancho,
                                         0.45 * CELDA), 1, 1)
        x, y, vis = A["boca"]
        if vis:
            for dc, df, q in boca:
                p.setBrush(q if isinstance(q, QColor) else tono(GRIS[q], apagado, False))
                p.drawEllipse(QPointF((x + dc * ancho - C0) * CELDA, (y + df) * CELDA), 0.55 * CELDA, 0.5 * CELDA)
        p.end()
        return img, A

    def uniforme(self, p, A, apagado, alto, t):
        """Tricornio sobre la coronilla (más estrecho cuanto más de lado), placa en el pecho y porra en la mano."""
        x, y, _ = A["coronilla"]
        ancho = max(0.55, abs(math.cos(math.radians(self.yaw))))
        for f, fila in enumerate(TRICORNIO):
            for c, ch in enumerate(fila):
                if ch != ".":
                    px = (x - C0 + (c - (len(fila) - 1) / 2) * ancho) * CELDA
                    py = (y - 1 - len(TRICORNIO) + 1 + f) * CELDA  # el ala, justo encima de la coronilla
                    p.drawPixmap(QPointF(px - R - 1, py - R - 1), self.sello(tono(GRIS[ch], apagado, False)))
        x, y, vis = A["pecho"]
        if vis:
            for dc, df in PLACA:
                col = QColor(150, 100, 20) if (dc, df) == (0, 0) else ORO
                p.drawPixmap(QPointF((x + dc - C0) * CELDA - R - 1, (y + df) * CELDA - R - 1), self.sello(col))
        # porra: en alto al dar el alto; si no, cuelga y se balancea al andar
        a = math.radians(160 if alto else 20 * math.sin(t * 1.6 * 2 * math.pi) * (self.modo == "anda") - 20 * self.dir)
        dx, dy = math.sin(a), math.cos(a)
        x, y, _ = A["mano_i"]
        for i in range(-1, round(PORRA / 0.8) + 1):  # negra con un filo de brillo, dos puntos de gruesa
            cx, cy = (x - C0 + dx * i * 0.8) * CELDA, (y + dy * i * 0.8) * CELDA
            p.drawPixmap(QPointF(cx - 0.5 * CELDA - R - 1, cy - R - 1), self.sello(tono(GRIS["#"] * 1.6, apagado, False)))
            p.drawPixmap(QPointF(cx + 0.5 * CELDA - R - 1, cy - R - 1), self.sello(tono(GRIS["+"], apagado, False)))

    def sello(self, col):
        """Punto ya pintado de ese color (los oscuros con aro gris para verse sobre fondos oscuros): estampar ~1100
        pixmaps por fotograma cuesta mucho menos que dibujar otras tantas elipses."""
        clave = col.rgb()
        if clave not in SELLOS:
            dpr, lado = self.devicePixelRatio(), 2 * R + 2
            img = QPixmap(round(lado * dpr), round(lado * dpr))
            img.setDevicePixelRatio(dpr)
            img.fill(Qt.GlobalColor.transparent)
            q = QPainter(img)
            q.setRenderHint(QPainter.RenderHint.Antialiasing)
            q.setPen(Qt.PenStyle.NoPen)
            c = QPointF(lado / 2, lado / 2)
            if col.red() < 60 and col.green() < 60:
                q.setBrush(QColor(78, 78, 78))
                q.drawEllipse(c, R, R)
                q.setBrush(col)
                q.drawEllipse(c, R * 0.72, R * 0.72)
            else:
                q.setBrush(col)
                q.drawEllipse(c, R, R)
            q.end()
            SELLOS[clave] = img
        return SELLOS[clave]

    def iconos(self, p, t, bat, bat_baja):
        """Columna de iconos de puntos a la derecha, de abajo arriba: batería, wifi, café, papelera."""
        S, x, y = self.s, ICONOS_X, PIES - 14
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
        if self.bocadillo.isVisible():
            return  # la ficha taparía el Sí / No
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
    # mezcla: a mitad de camino entre dos poses; lo que falta en una cuenta como neutro; k ≥ 1 es la de llegada
    m = mezcla({"cabeza": {"r": (10, 0, 0)}}, {"cabeza": {"r": (30, 0, 0)}, "raiz": {"s": (1, 1, 3)}}, 0.5)
    assert m["cabeza"]["r"] == (20, 0, 0) and m["raiz"]["s"] == (1, 1, 2) and m["raiz"]["t"] == (0, 0, 0)
    assert all(n in ANIM for n in OCIOS) and all(ANIM[n][1] for n in ("aterriza", "aplastado"))
    # percha: ventana de 800 px de ancho a 400 px de alto en una capa de 2520×1080 que empieza en (40, 0)
    x0, x1, y = percha((540, 400, 800, 600), (40, 0), 2520, 1080 - SH)
    assert (x0, x1) == (500, 500 + 800 - SW) and y + PIES == 404
    assert percha((40, 0, 2520, 1080), (40, 0), 2520, 1080 - SH) is None   # maximizada: no cabe encima
    assert percha((540, 400, SW - 10, 600), (40, 0), 2520, 1080 - SH) is None  # más estrecha que el mapache
    # barra y globo: trabajo en curso con su etapa, acabado con ✓ / ✗, uno viejo ya no sale; nada de HTML ajeno
    d = {"estado": "trabajando", "uso": {"ctx": 12.5, "tok": 1_234_567, "usd": 0.3}, "claude": {"estado": "libre"},
         "pasos": [{"t": "Paso la clase <b>a</b> apuntes", "e": "hecho", "h": "16:33:01"}, {"t": "Mira", "e": "falló", "h": "16:34:00"}],
         "trabajos": {"apuntes-1": "en curso", "render-2": "falló (código 1)", "viejo-3": "terminó bien"},
         "progreso": {"apuntes-1": {"etapa": "Transcribiendo: 3/4 tramos", "pct": 44, "ini": 1000, "fin": None},
                      "render-2": {"etapa": "Traceback", "pct": None, "ini": 1100, "fin": 1500},
                      "viejo-3": {"etapa": "", "pct": 100, "ini": 0, "fin": 1}}}
    d["pasos"] += [{"t": "Mira", "e": "falló", "h": "16:35:00"}] * 2
    h = "".join(hud(d, 1600))
    assert "1,23M tok · ≈0,30 $" in h and "&lt;b&gt;" in h and "<b>a</b>" not in h, h
    assert "█████</span><span style='color:#333333'>███████</span> 44%" in h and "10:00" in h and "apuntes-1" not in h and "render" in h, h
    assert h.index("16:35") < h.index("16:33") and " ×3" in h and h.count("Mira") == 1, h  # la nueva arriba, juntas
    assert globo(d, 1600) == "apuntes · 44 % · Transcribiendo: 3/4 tramos" and globo({}, 0) == ""
    assert len(hud(d, 1600)) == 3 and hud({}, 0)[0].endswith("no está en marcha</span>")
    app = QApplication(sys.argv)
    for f in glob.glob(str(Path(__file__).with_name("panel") / "fonts" / "plexmono-*.ttf")):
        QFontDatabase.addApplicationFont(f)  # la del panel: sin ella la barra cae a una proporcional y se descuadra
    app.setDesktopFileName("delta-mascota")
    app.setStyleSheet("QToolTip{background:#000;color:#f2f2f2;border:1px solid #262626;padding:8px;"
                      "font-family:'IBM Plex Mono',monospace;font-size:12px}")
    m = Mascota()
    m.show()
    QTimer.singleShot(1200, colocar)
    sys.exit(app.exec())
