"""La escena «orbe» del fondo: la esfera de alambre que se mueve con la voz (.venv/bin/python test_orbe.py)

Sustituye a test_logo.py: el escudo de puntos se quitó el 2026-10-21 porque no gustaba."""
import asyncio
import json
import re
import tempfile
from pathlib import Path

import assistant  # noqa: F401  (registra y fusiona, igual que al arrancar)
import acciones
import deltaos
import panel

panel.VISTA = Path(tempfile.mkdtemp()) / "delta-vista"  # fondo() escribe la vista: no la de verdad

AQUI = Path(__file__).parent

# La escena entra por la misma puerta que las demás: la fusión «vista», acción fondo.
assert "orbe" in deltaos.ESCENAS
assert "delta" not in deltaos.ESCENAS, "el escudo se quitó: que no quede una escena que pinta un lienzo que ya no existe"
real, args = acciones._real("vista", {"accion": "fondo", "cual": "orbe"})
assert (real, args) == ("fondo", {"escena": "orbe"}), (real, args)
assert asyncio.run(acciones.HANDLERS[real](**args)).startswith("Hecho: orbe a pantalla completa")
assert panel.S["fondo"]["escena"] == "orbe"
# Sin la palabra en la fusión, Delta se lo toma por una mejora pendiente y dice que no existe (pasó con el escudo).
acciones.fusionar()
assert "pon el orbe" in acciones.FUSIONES["vista"][0]
assert asyncio.run(acciones.HANDLERS["fondo"](escena="galaxia")).startswith("Error")

# El módulo tiene que estar entre los ficheros que sirve el panel, o la escena sale negra.
srv = " ".join(re.findall(r'for js in \(([^)]*)\)', (AQUI / "panel.py").read_text()))  # dos listas: con versión y sin ella
assert '"orbe.js"' in srv and '"delta.js"' not in srv, srv
assert '"logo.json"' not in (AQUI / "panel.py").read_text(), "el logo del escudo ya no se sirve"

# y fondo.js tiene que pintarla, no solo conocerla; con el lienzo que de verdad existe en el HTML
fjs = (AQUI / "panel" / "fondo.js").read_text()
html = (AQUI / "panel" / "index.html").read_text()
assert "Orbe.entrar()" in fjs and "Orbe.pintar($('fo-cv'), D)" in fjs
assert 'id="f-orbe"' in html and 'id="fo-cv"' in html
assert 'id="f-delta"' not in html and 'id="fd-cv"' not in html
assert not (AQUI / "panel" / "delta.js").exists()

# La esfera reacciona a la voz: el nivel de Delta cuando habla y el del micro cuando escucha.
ojs = (AQUI / "panel" / "orbe.js").read_text()
assert "d.nivel" in ojs and "d.mic" in ojs and "hablando" in ojs


# El menú de la hora filtra por la clave «f»: una entrada con otras claves no sale y nadie se
# entera. Pasó con cuatro. Aquí se queda la comprobación para que no vuelva a colarse.
nov = json.loads((AQUI / "panel" / "novedades.json").read_text(encoding="utf-8"))
for n in nov:
    assert set(n) <= {"f", "t", "como"} and n.get("f") and n.get("t"), n
assert any("orbe" in n["t"].lower() and n["f"] == "2026-10-21" for n in nov)

print("OK: el orbe se pide por voz, se sirve, se pinta en su lienzo y se mueve con la voz")
