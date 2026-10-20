"""La escena «delta» del fondo: el logo en puntos (.venv/bin/python test_logo.py)"""
import asyncio
import json
import re
from pathlib import Path

import assistant  # noqa: F401  (registra y fusiona, igual que al arrancar)
import acciones
import deltaos
import panel

AQUI = Path(__file__).parent
j = json.loads((AQUI / "panel" / "logo.json").read_text())

# Un logo que se haya regenerado mal (recorte movido, umbral alto) deja de parecerse al perro.
# Sin ojo no hay acento rojo, y sin puntos no hay dibujo: eso sí se puede comprobar aquí.
assert 1500 < len(j["pts"]) < 6000, len(j["pts"])
assert 1 <= len(j["ojo"]) <= 40, j["ojo"]
assert 60 <= j["w"] <= 200 and 60 <= j["h"] <= 200, (j["w"], j["h"])
for i, f, v in j["pts"] + j["ojo"]:
    assert 0 <= i < j["w"] and 0 <= f < j["h"] and 0 < v <= 1, (i, f, v)
# el ojo cae en la mitad de arriba de la cara, no en una esquina perdida
oi = sum(p[0] for p in j["ojo"]) / len(j["ojo"]), sum(p[1] for p in j["ojo"]) / len(j["ojo"])
assert j["w"] * .35 < oi[0] < j["w"] * .75 and j["h"] * .2 < oi[1] < j["h"] * .6, oi

# La escena entra por la misma puerta que las demás: la fusión «vista», acción fondo.
assert "delta" in deltaos.ESCENAS
real, args = acciones._real("vista", {"accion": "fondo", "cual": "delta"})
assert (real, args) == ("fondo", {"escena": "delta"}), (real, args)
assert asyncio.run(acciones.HANDLERS[real](**args)) == "Hecho: fondo de espera delta."
assert panel.S["fondo"]["escena"] == "delta"
assert asyncio.run(acciones.HANDLERS["fondo"](escena="galaxia")).startswith("Error")

# El módulo y el logo tienen que estar entre los ficheros que sirve el panel, o la escena sale negra.
srv = re.search(r'for js in \(([^)]*)\)', (AQUI / "panel.py").read_text()).group(1)
assert '"delta.js"' in srv and '"logo.json"' in srv, srv
# y fondo.js tiene que pintarla, no solo conocerla
fjs = (AQUI / "panel" / "fondo.js").read_text()
assert "Delta.entrar()" in fjs and "Delta.pintar" in fjs


# El menú de la hora filtra por la clave «f»: una entrada con otras claves no sale y nadie se
# entera. Ayer pasó con cuatro. Aquí se queda la comprobación para que no vuelva a colarse.
nov = json.loads((AQUI / "panel" / "novedades.json").read_text(encoding="utf-8"))
for n in nov:
    assert set(n) <= {"f", "t", "como"} and n.get("f") and n.get("t"), n
assert any("logo" in n["t"] and n["f"] == "2026-10-21" for n in nov)

print("OK: el logo son puntos con su ojo rojo, y la escena «delta» se pide por voz y se sirve")
