"""El directo de pantalla: se apaga solo, lo bloquea la privacidad y el panel lo enciende
en REC (.venv/bin/python test_vivo.py)"""
import asyncio
import re
import time
from pathlib import Path

import acciones
import panel

import assistant as A

ST = acciones.ST
corre = lambda c: asyncio.run(c)


def limpiar():
    ST["vivo"] = 0
    ST["privacidad"] = False


# ---------- encender y apagar ----------
limpiar()
assert "5" in corre(A.ver_en_vivo("5"))
assert ST["vivo"] > time.monotonic() + 4 * 60, "quedan casi los 5 minutos"
assert "dejo de mirar" in corre(A.ver_en_vivo("")), "sin minutos, se para"
assert ST["vivo"] == 0

# Se apaga sola: lo importante es que caduque, no que alguien se acuerde de pararla.
limpiar()
corre(A.ver_en_vivo("1"))
ST["vivo"] = time.monotonic() - 1  # como si hubiera pasado el minuto
assert panel.snapshot(ST)["vivo"] is False, "caducado = REC apagado"

# ---------- límites ----------
limpiar()
for malo in ("mañana", "un rato", "x"):
    assert corre(A.ver_en_vivo(malo)).startswith("Error"), malo
for fuera in ("0.5", "31", "-3"):
    assert corre(A.ver_en_vivo(fuera)).startswith("Error"), fuera
assert ST["vivo"] == 0, "ningún error deja el directo a medio encender"
assert A.VIVO_MAX == 30 and A.VIVO_RITMO < 8, (A.VIVO_MAX, A.VIVO_RITMO)

# La privacidad manda: en ese modo no se mira la pantalla ni pidiéndolo.
limpiar()
ST["privacidad"] = True
assert corre(A.ver_en_vivo("5")).startswith("Error")
assert ST["vivo"] == 0
limpiar()

# ---------- el panel lo publica y lo pinta ----------
corre(A.ver_en_vivo("3"))
assert panel.snapshot(ST)["vivo"] is True, "el panel tiene que ver el directo para encender el REC"

h = Path("panel/index.html").read_text()
assert '<div id="rec"><i></i>REC</div>' in h, "falta el testigo"
# El blindaje null-safe del panel lo envolvió en un elRec: basta con que sea $('rec') quien
# mire d.vivo, en la misma línea.
assert re.search(r"\$\('rec'\)[^\n]*d\.vivo\?'on'", h), "el REC no está enganchado a d.vivo"
assert 'd.vivo?`<b class="r">● REC</b>`' in h, "falta el REC en la tira del modo invisible"
# Fuera de #dock-pista a propósito: un testigo de grabación no se busca con la rueda.
pista = h.split('<div id="dock-pista">')[1].split('<div id="rec">')[0]
assert "rec" not in pista, "el REC no puede estar dentro de los huecos del dock"

# ---------- el dock ----------
assert h.count('class="slot"') == 6, "la hora + 5 huecos"
assert "DOCK_N=6" in h and 'id="hora"' in h.split('class="slot"')[1][:200], "la hora es el hueco 0"
# El dock se mide por su propia altura; el blindaje null-safe lo guardó antes en una variable.
assert re.search(r"translateY\(\$\{-DK\*[^}]*clientHeight\}px\)", h), "la pista no se desliza"
assert "DK=0;dkpinta()},12000" in h, "el dock tiene que volver solo a ser un reloj"

# Sin herramienta plana nueva: el directo entra por la fusión «pantalla».
assert "en_vivo" in acciones.FUSIONES["pantalla"][2], acciones.FUSIONES["pantalla"][2].keys()

print("OK: directo de pantalla con REC, y el dock gira sobre la hora sin perderla")
