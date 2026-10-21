"""Botones del ratón Amazon Basics (receptor MOSART 2.4G) para Delta, pedido el 21/10/2026.

El receptor manda dos de sus botones como teclas por su nodo de teclado: el de «ventanas» es Meta izquierda y el
de ZOOM es Ctrl izquierda. Delta se queda ese nodo en exclusiva (EVIOCGRAB), así KDE ya no abre la Vista general
ni hace zoom con ellos, y el Meta y el Ctrl del teclado de verdad siguen igual. Si Delta no está en marcha, los
botones vuelven a hacer lo de siempre.
  ventanas → escuchar, como si hubiera oído «Delta»; si ya escucha, a dormir (stand-by)
  ZOOM     → privacidad on/off
Solo stdlib: se lee struct input_event a pelo."""
import asyncio
import fcntl
import os
import struct

import acciones

DISPOSITIVO = "/dev/input/by-id/usb-MOSART_Semi._2.4G_RF_Keyboard___Mouse-event-kbd"
EVENTO = struct.Struct("llHHi")  # struct input_event de 64 bits: timeval, type, code, value
EVIOCGRAB = 0x40044590
EV_KEY, KEY_LEFTCTRL, KEY_LEFTMETA = 1, 29, 125
ORDENES = {KEY_LEFTMETA: "escuchar", KEY_LEFTCTRL: "privacidad"}


def ordenes(datos: bytes) -> list:
    """Las órdenes que hay en un trozo leído del dispositivo; solo al pulsar (value 1), ni al soltar ni al repetir."""
    n = len(datos) // EVENTO.size * EVENTO.size
    return [ORDENES[code] for _, _, tipo, code, value in EVENTO.iter_unpack(datos[:n])
            if tipo == EV_KEY and value == 1 and code in ORDENES]


def _hacer(ST, orden):
    import panel  # aquí y no arriba: panel arranca este módulo
    if orden == "privacidad":
        panel._cmd(ST, "privacidad")
    elif ST.get("privacidad"):
        panel.notificar("info", "Privacidad activada: pulsa ZOOM en el ratón para que vuelva a escucharte")
    else:
        acciones.dormir_ahora() if ST["activo"] else acciones.activar()


async def vigilar(ST):
    avisado = False
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
                print("🖱️ ratón: botón de ventanas = escuchar, ZOOM = privacidad")
                avisado = True
            while datos := await asyncio.to_thread(os.read, fd, EVENTO.size * 64):
                for orden in ordenes(datos):
                    _hacer(ST, orden)
        except OSError:  # desenchufado o suspensión: se vuelve a abrir
            pass
        finally:
            os.close(fd)
        await asyncio.sleep(2)
