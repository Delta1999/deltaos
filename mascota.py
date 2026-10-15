"""Mascota de Delta: el mapache de puntos flotando sobre el escritorio, siempre encima.

Lee el estado del panel (ws://127.0.0.1:7876/ws) y lo representa:
dormido (ojos cerrados, zetas), escuchando (orejas arriba, ojos rojos), hablando (hocico y barriga
laten con la voz), trabajando (puntos rojos orbitando), pide permiso (ojos rojos parpadeando y «!»).
Fase 2, el sistema: agobiado (CPU/RAM altas: tiembla y se pone rojo), calor (gotas naranjas), batería baja o
cargando, sin wifi, papelera con cosas, café tras 50 min seguidos y se duerme si no tocas nada en 5 min.
Arrastrar = mover. Clic = pasar al panel completo. Ratón encima = ficha con la info general.
"""
import glob
import json
import math
import os
import select
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

from PyQt6.QtCore import QPointF, Qt, QTimer, QUrl
from PyQt6.QtGui import QColor, QGuiApplication, QPainter, QPixmap
from PyQt6.QtWebSockets import QWebSocket
from PyQt6.QtWidgets import QApplication, QToolTip, QWidget

PANEL = "127.0.0.1:7876"
# Sacado de la imagen del usuario (lo comparte el panel): # oscuro, + gris, o blanco, . vacío
MAPACHE = (Path(__file__).parent / "panel" / "mapache.txt").read_text().splitlines()
CELDA, R = 5, 2.1                     # px entre puntos y radio del punto
OX, OY = 22, 34                       # margen para la cola, las orejas y las zetas
OJOS = {(12, 9), (12, 10), (13, 9), (13, 10), (12, 19), (12, 20), (13, 19), (13, 20)}
PIVOTE_COLA = (33, 26)                # (fila, col) donde la cola se une al cuerpo
GRIS = {"#": 26, "+": 138, "o": 242}
ROJO = QColor(255, 45, 31)
NARANJA = QColor(255, 140, 0)
INACTIVO = 300          # s sin teclado ni ratón: se acurruca a dormir
PAUSA = 50 * 60         # s de actividad seguida: saca un café
CPU_ALTA, RAM_ALTA, CALOR, BAT_BAJA = 85, 92, 85, 20  # %, % (8 GB: el 86 % es lo normal), °C, %
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


PUNTOS = [(f, c, ch, parte(f, c)) for f, fila in enumerate(MAPACHE) for c, ch in enumerate(fila) if ch != "."]
MOVILES = [q for q in PUNTOS if q[3] in ("cola", "ojo")]


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
        super().__init__(flags=Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(40 * CELDA + 2 * OX + 30, 43 * CELDA + OY + 12)
        self.d, self.t0, self.parpadeo, self.arrastre, self.cache = {}, time.monotonic(), 0.0, None, {}
        ahora = time.monotonic()
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
        reloj.timeout.connect(self.update)
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
        oy = OY + resp * 1.2
        ox = OX + (math.sin(t * 47) * 0.9 if agobio else 0)  # agobiado: tiembla
        # El cuerpo quieto va en caché (pintar 1069 puntos por fotograma costaba media CPU); solo cola y ojos se mueven
        brillo = round(8 * (0.75 + 0.25 * voz if est == "hablando" else 0.9 + 0.1 * resp))
        clave = (est == "escuchando", apagado, agobio, brillo)
        if clave not in self.cache:
            if len(self.cache) > 40:
                self.cache.clear()
            self.cache[clave] = self.cuerpo(*clave)
        p.drawPixmap(QPointF(ox - OX, oy - OY), self.cache[clave])
        px, py = ox + PIVOTE_COLA[1] * CELDA, oy + PIVOTE_COLA[0] * CELDA
        for f, c, ch, pt in MOVILES:
            x, y = ox + c * CELDA, oy + f * CELDA
            g, col = GRIS[ch], None
            if pt == "cola":
                dx, dy = x - px, y - py
                x, y = px + dx * math.cos(cola) - dy * math.sin(cola), py + dx * math.sin(cola) + dy * math.cos(cola)
            elif cerrados:
                g = 26
            elif permiso:
                col = ROJO if int(t * 4) % 2 else QColor(60, 10, 8)
            elif est == "escuchando":
                col = ROJO
            punto(p, x, y, ch, col or tono(g, ch, apagado, agobio))

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
        self.iconos(p, t, bat, bat_baja)
        if permiso and int(t * 4) % 2:
            p.setBrush(ROJO)
            for f in (0, 1, 2, 4):
                p.drawEllipse(QPointF(cx, OY - 26 + f * CELDA), R, R)
        p.end()

    def cuerpo(self, escucha, apagado, agobio, brillo):
        img = QPixmap(self.size() * self.devicePixelRatio())
        img.setDevicePixelRatio(self.devicePixelRatio())
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        for f, c, ch, pt in PUNTOS:
            if pt in ("cola", "ojo"):
                continue
            g = round(GRIS[ch] * brillo / 8) if ch == "o" and pt in ("hocico", "barriga") else GRIS[ch]
            punto(p, OX + c * CELDA, OY + (f - (pt == "oreja" and escucha)) * CELDA, ch, tono(g, ch, apagado, agobio))
        p.end()
        return img

    def iconos(self, p, t, bat, bat_baja):
        """Columna de iconos de puntos a la derecha, de abajo arriba: batería, wifi, café, papelera."""
        S, x, y = self.s, OX + 40 * CELDA + 2, self.height() - 14
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

    # ---- ratón: encima muestra la ficha, arrastrar mueve, clic abre el panel ----
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
        QToolTip.showText(self.mapToGlobal(self.rect().topLeft()), self.ficha(), self)

    def leaveEvent(self, e):
        QToolTip.hideText()

    def mousePressEvent(self, e):
        self.arrastre = e.position()

    def mouseMoveEvent(self, e):
        if self.arrastre is not None and (e.position() - self.arrastre).manhattanLength() > 4:
            self.arrastre = None
            self.windowHandle().startSystemMove()

    def mouseReleaseEvent(self, e):
        if self.arrastre is not None:
            self.ws.sendTextMessage('{"cmd": "vista_panel"}')
        self.arrastre = None


def colocar(w):
    """Wayland no deja a la app elegir su sitio: KWin la pone encima de todo, abajo a la derecha de la pantalla
    principal (Qt en Wayland no ve bien las pantallas, por eso kscreen-doctor)."""
    subprocess.Popen(["bash", "-c", r"""
W=$(kdotool search --class delta-mascota | head -1); [ -n "$W" ] || exit
kdotool windowstate --add ABOVE --add SKIP_TASKBAR --add SKIP_PAGER "$W"
read -r X Y AN AL < <(kscreen-doctor -o 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g' | awk '
  /^Output:/{en=0} /^[ \t]*enabled/{en=1} /priority/{p=$2}
  /Geometry:/ && en {split($2,xy,","); split($3,wh,"x"); g=xy[1]" "xy[2]" "wh[1]" "wh[2]; if(p==1){print g; f=1; exit}}
  END{if(!f) print g}')
kdotool windowmove "$W" $((X + AN - %d - 24)) $((Y + AL - %d - 56))""" % (w.width(), w.height())])


if __name__ == "__main__":
    assert all(len(f) == 40 for f in MAPACHE) and len(MAPACHE) == 43
    app = QApplication(sys.argv)
    app.setDesktopFileName("delta-mascota")
    app.setStyleSheet("QToolTip{background:#000;color:#f2f2f2;border:1px solid #262626;padding:8px;"
                      "font-family:'IBM Plex Mono',monospace;font-size:12px}")
    m = Mascota()
    m.show()
    QTimer.singleShot(1200, lambda: colocar(m))
    sys.exit(app.exec())
