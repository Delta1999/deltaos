"""Botones del ratón: Meta = escuchar; ZOOM (Ctrl) corto = privacidad, mantenido 2 s = silencio total (.venv/bin/python test_raton.py)"""
import asyncio

import raton

E = raton.EVENTO.pack
datos = (E(0, 0, 4, 4, 0x700e3) + E(0, 0, 1, 125, 1) + E(0, 0, 0, 0, 0)  # MSC_SCAN + Meta pulsado + SYN
         + E(0, 0, 1, 125, 2) + E(0, 0, 1, 125, 0)                        # repetición y soltar: nada
         + E(0, 0, 1, 29, 1) + E(0, 0, 1, 29, 2) + E(0, 0, 1, 29, 0)      # ZOOM: pulsar, repetir (nada), soltar
         + E(0, 0, 1, 30, 1))                                             # otra tecla: nada
assert raton.ordenes(datos) == ["escuchar", "zoom_abajo", "zoom_arriba"], raton.ordenes(datos)
assert raton.ordenes(datos[:-5]) == ["escuchar", "zoom_abajo", "zoom_arriba"]  # trozo cortado: se ignora el resto

# click: 1 audible, 2 más largo; PCM s16le válido
a, b = raton._click(1), raton._click(2)
assert len(a) % 2 == 0 and max(a) > 0 and len(b) > 2 * len(a) - 1, (len(a), len(b))


async def pulsaciones():
    raton.ESPERA_SILENCIO = 0.05
    llamadas = []
    raton._alternar_silencio = lambda ST: llamadas.append("silencio") or asyncio.sleep(0)
    raton.acciones.tarea = lambda c: asyncio.ensure_future(c)
    z = {"t": None, "largo": False}
    raton._zoom_abajo({}, z)  # pulsación corta: soltar antes de tiempo
    assert raton._zoom_arriba(z) is True and not llamadas
    raton._zoom_abajo({}, z)  # pulsación larga: salta el silencio y al soltar no hay privacidad
    await asyncio.sleep(0.15)
    assert llamadas == ["silencio"], llamadas
    assert raton._zoom_arriba(z) is False
    assert raton._zoom_arriba(z) is False  # soltar sin haber pulsado: nada


asyncio.run(pulsaciones())
print("OK: ventanas = escuchar, ZOOM corto = privacidad, ZOOM 2 s = silencio total")
