"""La puerta de la proactividad: qué merece decirse y cuándo callar (.venv/bin/python test_proactivo.py)"""
import asyncio

import acciones
import proactivo
from proactivo import mirar, puede

MEDIODIA, MADRUGADA = 13, 3


def limpiar():
    proactivo._ultimo.clear(); proactivo._pasadas.clear(); proactivo._seguidas.clear()
    acciones.ST["privacidad"] = False
    acciones.ST["no_molestar"] = 0


# ---------- qué merece decirse ----------
limpiar()
calor = {"temp": 95, "ram": 60, "swap": 0}
assert mirar(calor, None, 500) == [], "un pico no es un problema: hace falta la segunda ronda"
m = mirar(calor, None, 500)
assert [x[0] for x in m] == ["calor"] and m[0][1] is True, m  # y es urgente
assert mirar({"temp": 50}, None, 500) == [], "al bajar, se olvida"

limpiar()
# RAM llena pero swap intacta: en esta máquina el 86 % es lo normal, no se avisa.
for _ in range(3):
    assert mirar({"ram": 97, "swap": 10, "temp": 40}, None, 500) == []
limpiar()
for _ in range(2):
    m = mirar({"ram": 97, "swap": 80, "temp": 40}, None, 500)
assert [x[0] for x in m] == ["memoria"] and m[0][1] is False, m  # molesta, pero no urge

limpiar()
assert [x[0] for x in mirar({}, None, 2.0)] == ["disco"]
assert mirar({}, None, 50) == [], "con sitio de sobra, callado"
assert [x[0] for x in mirar({}, (9, "Discharging"), 500)] == ["bateria"]
assert mirar({}, (9, "Charging"), 500) == [], "enchufado no es problema"

# ---------- cuándo callar ----------
limpiar()
assert puede("calor", urgente=True, ahora=0, hora=MEDIODIA) is None
acciones.ST["privacidad"] = True
assert puede("calor", urgente=True, ahora=0, hora=MEDIODIA) == "privacidad"
acciones.ST["privacidad"] = False

limpiar()
assert puede("disco", ahora=0, hora=MADRUGADA) == "de noche", "de noche no se interrumpe por el disco"
assert puede("bateria", urgente=True, ahora=0, hora=MADRUGADA) is None, "lo urgente sí pasa de noche"

limpiar()
assert puede("disco", espera=600, ahora=0, hora=MEDIODIA) is None
assert puede("disco", espera=600, ahora=100, hora=MEDIODIA) == "ya lo ha dicho hace poco"
assert puede("disco", espera=600, ahora=700, hora=MEDIODIA) is None, "pasada la espera, vuelve"
# Ni siquiera lo urgente se repite en bucle.
limpiar()
assert puede("calor", urgente=True, espera=60, ahora=0, hora=MEDIODIA) is None
assert puede("calor", urgente=True, espera=60, ahora=10, hora=MEDIODIA) == "ya lo ha dicho hace poco"

limpiar()
for i in range(proactivo.MAX_HORA):
    assert puede(f"m{i}", ahora=i, hora=MEDIODIA) is None, i
assert puede("otro", ahora=5, hora=MEDIODIA).startswith("ya ha interrumpido"), "tope por hora"
assert puede("urge", urgente=True, ahora=5, hora=MEDIODIA) is None, "lo urgente no mira el tope"
assert puede("otro", ahora=3700, hora=MEDIODIA) is None, "a la hora siguiente, otra vez"

# ---------- «déjame en paz» ----------
limpiar()
assert "45" in asyncio.run(proactivo.no_molestar("45"))
assert puede("disco", ahora=0, hora=MEDIODIA) == "no molestar"
assert "vuelvo a avisar" in asyncio.run(proactivo.no_molestar(""))
assert puede("disco", ahora=0, hora=MEDIODIA) is None
assert asyncio.run(proactivo.no_molestar("mañana")).startswith("Error")
assert asyncio.run(proactivo.no_molestar("9999")).startswith("Error")

# ---------- la puerta vale para todo el que avise ----------
limpiar()
assert acciones.PUERTA is puede, "proactivo.py tiene que haberla enchufado al importarse"
acciones.ST["privacidad"] = True
assert asyncio.run(acciones.avisar("x", notificar=False, motivo="calor", urgente=True)) == "Callado: privacidad."
# Sin motivo es algo que pidió el usuario (alarma, recordatorio): no se filtra ni en privacidad.
assert asyncio.run(acciones.avisar("x", notificar=False)) is None
limpiar()

print("OK: Delta avisa de calor, memoria, disco y batería, y se calla cuando toca")
