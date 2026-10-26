"""Avisos al móvil: avisar(movil=...) manda un ping de KDE Connect con el texto corto, y de las notificaciones del
móvil solo pasan WhatsApp y las del sistema."""
import asyncio

import acciones
import movil

enviados = []


async def _run(argv, cwd=None, timeout=60):
    enviados.append(argv)
    return 0, ""


async def _movil():
    return "abc123"


movil._run, movil._movil = _run, _movil
acciones.ST["session"] = None
acciones.activar = lambda: None  # sin pitido en la prueba


async def main():
    await acciones.avisar("texto largo para el modelo", notificar=False, movil="Impresión terminada: pieza.gcode")
    await asyncio.sleep(0.1)
    assert enviados == [["kdeconnect-cli", "-d", "abc123", "--ping-msg", "Impresión terminada: pieza.gcode"]], enviados
    enviados.clear()
    await acciones.avisar("sin móvil", notificar=False)  # sin «movil», nada al móvil
    await asyncio.sleep(0.1)
    assert enviados == []
    for app, ok in (("WhatsApp", True), ("Sistema Android", True), ("Batería", True), ("Gmail", False), ("Outlook", False)):
        assert movil.permitida({"appName": app}) is ok, app
    print("OK: avisos al móvil por ping y solo WhatsApp/sistema en las notificaciones")


asyncio.run(main())
