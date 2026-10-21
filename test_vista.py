"""Modo invisible y scroll de los subtítulos (.venv/bin/python test_vista.py)"""
import asyncio
import tempfile
from pathlib import Path

import acciones
import deltaos
import panel

panel.VISTA = Path(tempfile.mkdtemp()) / "delta-vista"  # la de verdad no: la borraba y el panel real se quedaba sin vista

# La vista viaja en el snapshot: la página no tiene otra forma de saberla (ventana.sh también la escribe).
for modo in ("panel", "mascota", "invisible"):
    assert asyncio.run(deltaos.cambiar_vista(modo)) == f"Hecho: vista {modo}.", modo
    assert panel.snapshot(acciones.ST)["vista"] == modo, modo
assert asyncio.run(deltaos.cambiar_vista("fantasma")).startswith("Error"), "modos inventados, fuera"

# Si el fichero no existe (primer arranque), el panel se dibuja completo y no en blanco.
panel.VISTA.unlink(missing_ok=True)
assert panel._vista_actual() == "panel"

# La fusión «vista» es la única puerta: una herramienta plana más confundiría al modelo (19/10).
assert "invisible" in acciones.FUSIONES["vista"][2], acciones.FUSIONES["vista"][2].keys()

# Los subtítulos: antes solo quedaban 2 frases, así que no había historial que hacer scroll.
panel.S["frases"].clear()
for i in range(panel.FRASES + 5):
    panel.texto("usuario" if i % 2 else "delta", f"frase {i}")
f = panel.S["frases"]
assert len(f) == panel.FRASES and f[-1]["t"] == f"frase {panel.FRASES + 4}", len(f)
assert len(f[0]["h"]) == 5, f[0]  # con hora: con 40 frases hay que saber de cuándo es cada una

print("OK: modo invisible en el snapshot y 40 frases con hora en los subtítulos")
