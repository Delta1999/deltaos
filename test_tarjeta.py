"""Fase 8: la tira del modo invisible crece en tarjeta y se encoge sola
(.venv/bin/python test_tarjeta.py)"""
import asyncio
import tempfile
import time
from pathlib import Path

import acciones
import panel

import deltaos

panel.VISTA = Path(tempfile.mkdtemp()) / "delta-vista"
corre = lambda c: asyncio.run(c)
ST = acciones.ST


def vista():
    return panel.VISTA.read_text().strip()


# ---------- solo tiene sentido con la tira puesta ----------
panel.vista("panel")
r = corre(deltaos.mostrar_en_tira("lo que sea"))
assert r.startswith("Error") and "panel entero" in r, r
assert panel._TARJETA is None, "no se pone la tarjeta si no hay tira"

# ---------- con la tira: crece ----------
panel.vista("invisible")
r = corre(deltaos.mostrar_en_tira("PETG 240\nCama 80\nVentilador 40", "LAMINADO", "30"))
assert r.startswith("Hecho") and "30" in r, r
assert vista() == "invisible-grande", "ventana.sh tiene que recibir la orden de agrandar"
tj = panel.snapshot(ST)["tarjeta"]
assert tj["titulo"] == "LAMINADO" and tj["lineas"] == ["PETG 240", "Cama 80", "Ventilador 40"], tj

# ---------- se encoge sola ----------
panel._TARJETA["hasta"] = time.monotonic() - 1
assert panel.snapshot(ST)["tarjeta"] is None, "caducada"
assert vista() == "invisible", "y la ventana vuelve a su sitio sin que nadie se lo pida"

# Si Delta se cayó con la tarjeta puesta, el primer snapshot al volver la quita: por eso la
# caducidad vive en snapshot() y no en un temporizador que muere con el proceso.
panel.vista("invisible")
corre(deltaos.mostrar_en_tira("algo", "X", "5"))
assert vista() == "invisible-grande"
panel._TARJETA["hasta"] = time.monotonic() - 999
panel.snapshot(ST)
assert vista() == "invisible" and panel._TARJETA is None

# ---------- límites ----------
panel.vista("invisible")
assert corre(deltaos.mostrar_en_tira("")).startswith("Error")
assert corre(deltaos.mostrar_en_tira("x", "t", "mañana")).startswith("Error")
# Ni se queda para siempre ni parpadea: se recorta a los topes en vez de fallar.
assert corre(deltaos.mostrar_en_tira("x", "t", "9999")).startswith("Hecho")
assert panel._TARJETA["hasta"] <= time.monotonic() + panel.TARJETA_MAX + 1
assert corre(deltaos.mostrar_en_tira("x", "t", "0")).startswith("Hecho")
assert panel._TARJETA["hasta"] > time.monotonic() + 4
# Las líneas en blanco no ocupan sitio en una tarjeta de 14 líneas.
corre(deltaos.mostrar_en_tira("a\n\n\n   \nb", "T"))
assert panel._TARJETA["lineas"] == ["a", "b"], panel._TARJETA["lineas"]
corre(deltaos.mostrar_en_tira("\n".join(f"l{i}" for i in range(40)), "T"))
assert len(panel._TARJETA["lineas"]) == 14

# ---------- enchufada, y sin herramienta plana nueva ----------
assert "tarjeta" in acciones.FUSIONES["vista"][2]
assert acciones._real("vista", {"accion": "tarjeta", "texto": "a", "titulo": "T"}) \
    == ("mostrar_en_tira", {"texto": "a", "titulo": "T"})
acciones.fusionar()  # al arrancar lo hace assistant.py; aquí a mano, que no lo importamos
assert "mostrar_en_tira" not in [d.name for d in acciones.DECLARATIONS], "la absorbe la fusión"

# ---------- el panel la pinta, y «invisible-grande» sigue siendo invisible ----------
h = Path("panel/index.html").read_text()
assert '<div id="t-card">' in h and "card.className=tar?'on':''" in h
assert "(d.vista||'').startsWith('invisible')" in h, "si no, la tira desaparece al crecer"
v = Path("panel/ventana.sh").read_text()
assert "TIRA_ALTA=" in v and '[ "$3" = invisible-grande ] && H=$TIRA_ALTA' in v
assert '"${3%%-*}" = invisible' in v, "la rama tiene que aceptar el sufijo"

print("OK: la tira crece en tarjeta y se encoge sola")
