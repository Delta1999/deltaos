"""Mover interfaz y mascota de pantalla por voz, y el escudo que se ve al pedirlo (.venv/bin/python test_pantallas.py)"""
import asyncio
import subprocess
import tempfile
from pathlib import Path

import acciones
import deltaos
import panel

# Portátil abajo (principal) y la ultrawide por HDMI encima, como en casa. Con colores, como lo saca kscreen-doctor.
KS = ("\x1b[01;32mOutput: \x1b[0;0m1 eDP-1 uuid\n\tenabled\n\tconnected\n\tpriority 1\n\tGeometry: 434,1080 1652x930\n"
      "Output: 2 HDMI-A-1 uuid\n\tenabled\n\tconnected\n\tpriority 2\n\tGeometry: 0,0 2520x1080\n"
      "Output: 3 DP-1 uuid\n\tdisabled\n\tdisconnected\n")
UNA = "Output: 1 eDP-1 uuid\n\tenabled\n\tconnected\n\tpriority 1\n\tGeometry: 0,0 1652x930\n"

ps = deltaos._pantallas(KS)
assert [o["n"] for o in ps] == ["eDP-1", "HDMI-A-1"], ps  # la apagada no cuenta
for donde, n in (("arriba", "HDMI-A-1"), ("abajo", "eDP-1"), ("principal", "eDP-1"), ("ultrawide", "HDMI-A-1"),
                 ("otra", "HDMI-A-1"), ("hdmi-a-1", "HDMI-A-1")):
    assert deltaos._donde(ps, "eDP-1", donde)["n"] == n, donde
assert deltaos._donde(ps, "eDP-1", "en la luna") is None

tmp = Path(tempfile.mkdtemp())
panel.PANTALLA = {k: tmp / f"delta-pantalla-{k}" for k in ("panel", "mascota")}  # no tocar los ficheros de verdad
salida = [KS]
async def falso_run(argv, cwd=None, timeout=60):
    return 0, salida[0]
deltaos._run = falso_run
run = lambda c, d="otra": asyncio.run(deltaos.mover_a_pantalla(c, d))

# Por defecto el panel va en la secundaria y la mascota en la principal: «la otra» es la contraria de cada uno.
assert run("interfaz").startswith("Hecho") and panel.PANTALLA["panel"].read_text().strip() == "eDP-1"
assert run("mascota").startswith("Hecho") and panel.PANTALLA["mascota"].read_text().strip() == "HDMI-A-1"
assert "ya estaba ahí" in run("barra", "abajo")  # barra y panel son la misma ventana
run("todo", "arriba")
assert {k: f.read_text().strip() for k, f in panel.PANTALLA.items()} == {"panel": "HDMI-A-1", "mascota": "HDMI-A-1"}
assert run("tostadora").startswith("Error")
salida[0] = UNA
assert run("interfaz").startswith("Solo hay una pantalla")

# La voz llega por la fusión «vista» y por «ventanas» (lo que Delta usaba el 21/10 y no duraba).
salida[0] = KS
assert acciones._real("vista", {"accion": "pantalla", "cual": "mascota", "donde": "abajo"}) == \
    ("mover_a_pantalla", {"cual": "mascota", "donde": "abajo"})
assert asyncio.run(acciones.ventanas("mover_pantalla", "mascota")).startswith("Hecho")
assert panel.PANTALLA["mascota"].read_text().strip() == "eDP-1"

# ventana.sh elige la misma pantalla que Python: la pedida si está encendida, si no la que no es la principal.
destino = Path("panel/ventana.sh").read_text().split("destino() {", 1)[1].split("\n}\n", 1)[0]
def sh(want):
    (tmp / "pant").write_text(want)
    script = f'kscreen-doctor() {{ printf %s "$KS"; }}\nPANT={tmp}/pant SALIDA=\ndestino() {{{destino}\n}}\ndestino'
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, env={"KS": KS, "PATH": "/usr/bin:/bin"}).stdout.split()
assert sh("eDP-1")[:5] == ["434", "1080", "1652", "930", "panel"], sh("eDP-1")
assert sh("")[:4] == ["0", "0", "2520", "1080"] and sh("DP-1")[:4] == ["0", "0", "2520", "1080"]  # apagada → la de siempre
assert sh("eDP-1")[5] == sh("")[5], "la firma es el juego de pantallas, no la elegida: si no, cambiar de pantalla resetea la vista"

# El escudo: pedirlo en modo barra pone el panel, que es donde se pinta, y el panel lo enseña ya (forzado), no al dormir.
v = panel._vista_actual()
try:
    panel.vista("invisible")
    r = asyncio.run(deltaos.fondo("delta"))
    assert panel._vista_actual() == "panel" and "pantalla completa" in r and "modo invisible" in r, r
    assert panel.S["fondo"]["escena"] == "delta"
finally:
    panel.vista(v)
assert "forzado = d.fondo.escena !== 'auto'" in Path("panel/fondo.js").read_text()

print("OK: interfaz y mascota cambian de pantalla por voz y se quedan; el escudo se ve al pedirlo")
