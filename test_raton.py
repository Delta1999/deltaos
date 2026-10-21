"""Botones del ratón: Meta = escuchar, Ctrl = privacidad, solo al pulsar (.venv/bin/python test_raton.py)"""
import raton

E = raton.EVENTO.pack
datos = (E(0, 0, 4, 4, 0x700e3) + E(0, 0, 1, 125, 1) + E(0, 0, 0, 0, 0)  # MSC_SCAN + Meta pulsado + SYN
         + E(0, 0, 1, 125, 2) + E(0, 0, 1, 125, 0)                        # repetición y soltar: nada
         + E(0, 0, 1, 29, 1) + E(0, 0, 1, 29, 0)                          # Ctrl
         + E(0, 0, 1, 30, 1))                                             # otra tecla: nada
assert raton.ordenes(datos) == ["escuchar", "privacidad"], raton.ordenes(datos)
assert raton.ordenes(datos[:-5]) == ["escuchar", "privacidad"]  # trozo cortado: se ignora el resto
print("OK: ventanas = escuchar, ZOOM = privacidad")
