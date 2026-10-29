"""Botones del ratón Amazon Basics (receptor MOSART 2.4G) para Delta, pedido el 21/10/2026.

El receptor manda dos de sus botones como teclas por su nodo de teclado: el de «ventanas» es Meta izquierda y el
de ZOOM es Ctrl izquierda. Delta se queda ese nodo en exclusiva (EVIOCGRAB), así KDE ya no abre la Vista general
ni hace zoom con ellos, y el Meta y el Ctrl del teclado de verdad siguen igual. Si Delta no está en marcha, los
botones vuelven a hacer lo de siempre.
  ventanas → escuchar, como si hubiera oído «Delta»; si ya escucha, a dormir (stand-by); si la interfaz está en
             el salón (firetv.py), la trae al portátil y escucha
  ZOOM     → pulsación corta: privacidad on/off (al soltar)
             mantenido 2 s: silencio total on/off (29/10/2026): Delta queda mudo y no avisa de nada hasta que se
             vuelva a mantener; suena un click al activarlo y dos al quitarlo
Solo stdlib: se lee struct input_event a pelo."""
import asyncio
import array
import fcntl
import math
import os
import random
import struct
import subprocess

import acciones
import firetv

DISPOSITIVO = "/dev/input/by-id/usb-MOSART_Semi._2.4G_RF_Keyboard___Mouse-event-kbd"
EVENTO = struct.Struct("llHHi")  # struct input_event de 64 bits: timeval, type, code, value
EVIOCGRAB = 0x40044590
EV_KEY, KEY_LEFTCTRL, KEY_LEFTMETA = 1, 29, 125
ESPERA_SILENCIO = 2.0  # segundos con ZOOM mantenido para alternar el silencio total
RATE_CLICK = 24000


def ordenes(datos: bytes) -> list:
    """Las órdenes que hay en un trozo leído del dispositivo. Meta: solo al pulsar. Ctrl (ZOOM): pulsar y soltar,
    para medir cuánto se mantiene; el repetir (value 2) no cuenta."""
    n = len(datos) // EVENTO.size * EVENTO.size
    res = []
    for _, _, tipo, code, value in EVENTO.iter_unpack(datos[:n]):
        if tipo != EV_KEY or value not in (0, 1):
            continue
        if code == KEY_LEFTMETA and value == 1:
            res.append("escuchar")
        elif code == KEY_LEFTCTRL:
            res.append("zoom_abajo" if value else "zoom_arriba")
    return res


def _click(veces):
    """Un click seco (ráfaga corta que decae); `veces` clicks seguidos. PCM s16le mono."""
    un = array.array("h", (int(14000 * math.exp(-i / 90) * (math.sin(i * 0.5) + random.uniform(-.5, .5)) / 1.5)
                           for i in range(RATE_CLICK // 30)))
    hueco = array.array("h", [0] * (RATE_CLICK // 12))
    pcm = array.array("h")
    for k in range(veces):
        pcm += un
        if k < veces - 1:
            pcm += hueco
    return pcm.tobytes()


def clic(activado):
    """Un click al activar el silencio, dos al quitarlo. Va directo a paplay: el silencio total no lo tapa."""
    try:
        p = subprocess.Popen(["paplay", "--raw", "--format=s16le", f"--rate={RATE_CLICK}", "--channels=1"],
                             stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        p.stdin.write(_click(1 if activado else 2))
        p.stdin.close()
    except Exception:
        pass


async def _alternar_silencio(ST):
    import panel
    import proactivo
    if acciones.silencio_total():
        callados = list(ST.get("silenciados", []))
        await proactivo.silencio_total("0")
        clic(False)
        panel.notificar("info", "Silencio total DESACTIVADO: vuelvo a hablar y a avisar"
                        + (f" · se callaron {len(callados)}: " + "; ".join(callados[-3:]) if callados else ""))
    else:
        await proactivo.silencio_total("")
        acciones.dormir_ahora()  # corta lo que esté diciendo; el audio nuevo lo descarta assistant.py
        clic(True)
        panel.notificar("info", "Silencio total ACTIVADO: mudo y sin avisos hasta que mantengas ZOOM 2 s")


def _hacer(ST, orden):
    import panel  # aquí y no arriba: panel arranca este módulo
    if orden == "privacidad":
        panel._cmd(ST, "privacidad")
    elif ST.get("privacidad"):
        panel.notificar("info", "Privacidad activada: pulsa ZOOM en el ratón para que vuelva a escucharte")
    elif firetv.DONDE["aqui"] == "salon":  # estás en la habitación: la interfaz y el micro vuelven al portátil
        acciones.tarea(firetv.interfaz_portatil())
        if not ST["activo"]:
            acciones.activar()
    else:
        acciones.dormir_ahora() if ST["activo"] else acciones.activar()


def _zoom_abajo(ST, zoom):
    """ZOOM pulsado: arma el temporizador de la pulsación larga."""
    if zoom["t"] is not None:
        return
    zoom["t"] = asyncio.get_running_loop().call_later(ESPERA_SILENCIO, _zoom_largo, ST, zoom)


def _zoom_largo(ST, zoom):
    zoom["t"], zoom["largo"] = None, True
    acciones.tarea(_alternar_silencio(ST))


def _zoom_arriba(zoom):
    """ZOOM soltado. True si era una pulsación corta (privacidad); False si fue larga o no había pulsación."""
    t, largo = zoom["t"], zoom["largo"]
    zoom["t"], zoom["largo"] = None, False
    if t is not None:
        t.cancel()
    return t is not None and not largo


async def vigilar(ST):
    avisado = False
    zoom = {"t": None, "largo": False}
    while True:
        try:
            fd = os.open(DISPOSITIVO, os.O_RDONLY)
        except OSError:  # receptor quitado o aún sin enumerar: se reintenta sin ruido
            await asyncio.sleep(5)
            continue
        try:
            try:
                fcntl.ioctl(fd, EVIOCGRAB, 1)
            except OSError as e:
                print(f"🖱️ ratón: no me lo puedo quedar en exclusiva ({e}); los botones harán también lo suyo")
            if not avisado:
                print("🖱️ ratón: botón de ventanas = escuchar, ZOOM = privacidad (corto) / silencio total (2 s)")
                avisado = True
            while datos := await asyncio.to_thread(os.read, fd, EVENTO.size * 64):
                for orden in ordenes(datos):
                    if orden == "zoom_abajo":
                        _zoom_abajo(ST, zoom)
                    elif orden == "zoom_arriba":
                        if _zoom_arriba(zoom):
                            _hacer(ST, "privacidad")
                    else:
                        _hacer(ST, orden)
        except OSError:  # desenchufado o suspensión: se vuelve a abrir
            pass
        finally:
            os.close(fd)
            _zoom_arriba(zoom)  # soltado a la fuerza: no deja un temporizador vivo
        await asyncio.sleep(2)
