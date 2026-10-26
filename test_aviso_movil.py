"""Avisos al móvil como notificación del navegador (Web Push): avisar(movil=...) se lo manda a los móviles suscritos,
borra las suscripciones caducadas, y de las notificaciones del móvil por KDE Connect solo pasan WhatsApp y las del sistema."""
import asyncio
import tempfile
from pathlib import Path

from pywebpush import WebPushException

import acciones
import avisos_web
import movil

d = Path(tempfile.mkdtemp())
avisos_web.CLAVE, avisos_web.SUSCR = d / "clave.pem", d / "suscr.json"
enviados = []


class Resp:
    status_code = 410


def _enviar(sub, carga):
    enviados.append((sub["endpoint"], carga))
    if sub["endpoint"].endswith("muerta"):
        raise WebPushException("gone", response=Resp())


avisos_web._enviar = _enviar
acciones.ST["session"] = None
acciones.activar = lambda: None  # sin pitido en la prueba


def sub(n):
    return {"endpoint": f"https://push.ejemplo/{n}", "keys": {"p256dh": "a", "auth": "b"}}


async def main():
    assert len(avisos_web.clave_publica()) == 87 and avisos_web.CLAVE.exists()  # punto sin comprimir en base64url
    assert not avisos_web.suscribir({"endpoint": "http://malo", "keys": {"p256dh": "a", "auth": "b"}})
    assert not avisos_web.suscribir({"endpoint": "https://x"}) and not avisos_web.suscribir(None)
    assert await avisos_web.push("sin móviles") == 0 and enviados == []  # nadie suscrito: se pierde, sin romper
    assert avisos_web.suscribir(sub("viva")) and avisos_web.suscribir(sub("viva")) and avisos_web.cuantas() == 1  # sin duplicados
    await acciones.avisar("texto largo para el modelo", notificar=False, movil="Impresión terminada: pieza.gcode")
    await asyncio.sleep(0.2)
    assert len(enviados) == 1 and enviados[0][0].endswith("viva") and "Impresión terminada: pieza.gcode" in enviados[0][1], enviados
    enviados.clear()
    await acciones.avisar("sin móvil", notificar=False)  # sin «movil», nada al móvil
    await asyncio.sleep(0.1)
    assert enviados == []
    avisos_web.suscribir(sub("muerta"))
    assert await avisos_web.push("hola") == 1 and avisos_web.cuantas() == 1  # la caducada (410) se borra
    for app, ok in (("WhatsApp", True), ("Sistema Android", True), ("Batería", True), ("Gmail", False), ("Outlook", False)):
        assert movil.permitida({"appName": app}) is ok, app
    print("OK: avisos al móvil por Web Push, suscripciones limpias y solo WhatsApp/sistema en las notificaciones")


asyncio.run(main())
