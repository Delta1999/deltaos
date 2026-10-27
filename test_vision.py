"""Visión (fase 5.1): la lógica sin cámara — presencia con margen, gestos sostenidos, fatiga, ángulos, config.
(.venv/bin/python test_vision.py)"""
import json
import math
import os
import tempfile
from pathlib import Path

import vision

# ---------- recorte de la cara: se amplía la zona (la GoPro da 320×240) y se sabe cuántos px abarca ----------
import numpy as np
img, ancho = vision.zona_cara(np.zeros((240, 320, 3), np.uint8), [0.25, 0.1, 0.75, 0.7])
assert img.shape == (576, 640, 3) and ancho == 160, (img.shape, ancho)
base = np.zeros((240, 320, 3), np.uint8)
assert vision.zona_cara(base, None)[0] is base and vision.zona_cara(base, None)[1] == 320, "sin recorte no se toca"

# ---------- presencia: llegar rápido, irse con margen ----------
p = vision.Presencia(llega_s=2, se_va_s=120)
assert p.ver(True, 0) is None and p.ver(True, 1) is None
assert p.ver(True, 2.1) == "llega" and p.presente
assert p.ver(False, 3) is None and p.ver(False, 60) is None, "mirar el móvil un minuto no es irse"
assert p.ver(True, 61) is None and p.ver(False, 62) is None, "vuelve a verle: el reloj de irse se reinicia"
assert p.ver(False, 150) is None and p.ver(False, 182.5) == "se_va" and not p.presente
assert p.ver(False, 500) is None, "irse se dice una vez"

# ---------- gestos: sostenidos, una vez, y con descanso ----------
g = vision.Gestos(sostener_s=0.8, pausa_s=3)
assert g.ver("Open_Palm", 0.9, 0) is None and g.ver("Open_Palm", 0.9, 0.5) is None
assert g.ver("Open_Palm", 0.9, 0.9) == "Open_Palm"
assert g.ver("Open_Palm", 0.9, 2) is None, "mantenerlo no lo repite"
assert g.ver("None", 0, 2.2) is None and g.ver("Open_Palm", 0.9, 2.3) is None and g.ver("Open_Palm", 0.9, 3.2) is None, \
    "soltar y repetir dentro del descanso no cuenta"
assert g.ver("Open_Palm", 0.9, 4.5) == "Open_Palm"
g2 = vision.Gestos()
assert all(g2.ver("Thumb_Up", 0.3, t / 10) is None for t in range(30)), "con poca confianza no cuenta"
assert g2.ver("Open_Palm", 0.9, 0) is None and g2.ver("Victory", 0.9, 0.9) is None, "si cambia de gesto empieza de cero"

# ---------- fatiga ----------
f = vision.Fatiga()
for i in range(12):  # 12 parpadeos en 60 s
    f.ver(0.9, 0, i * 5)
    f.ver(0.1, 0, i * 5 + 0.2)
assert f.por_minuto() == 12, f.por_minuto()
assert f.ver(0, 0.8, 100) is None and f.ver(0, 0.8, 101.6) == "bostezo" and f.ver(0, 0.8, 103) is None

# ---------- ángulos de la cabeza ----------
I = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
assert vision.angulos(I) == (0.0, 0.0)
a = math.radians(30)  # giro de 30° alrededor del eje vertical
Ry = [[math.cos(a), 0, math.sin(a), 0], [0, 1, 0, 0], [-math.sin(a), 0, math.cos(a), 0], [0, 0, 0, 1]]
assert abs(vision.angulos(Ry)[0] - 30) < 1e-6 and abs(vision.angulos(Ry)[1]) < 1e-6

# ---------- config: por defecto la webcam; ${VAR} del entorno (contraseñas fuera del fichero) ----------
d = Path(tempfile.mkdtemp())
assert vision.cargar_config(d / "no.json")[0]["url"] == "/dev/video0"
os.environ["CLAVE_JARDIN"] = "secreta"
(d / "v.json").write_text(json.dumps({"fuentes": [{"nombre": "jardin", "url": "rtsp://admin:${CLAVE_JARDIN}@192.168.0.60/s1", "fps": 2}]}))
c = vision.cargar_config(d / "v.json")[0]
assert c["url"] == "rtsp://admin:secreta@192.168.0.60/s1" and c["fps"] == 2 and c["se_va_s"] == 120 and c["activa"]

# ---------- lado de Delta (vision_delta): lo que contesta y el modo privacidad ----------
import asyncio
import time

vision.ESTADO, vision.EVENTOS, vision.PAUSA = d / "e.json", d / "ev.jsonl", d / "pausa"  # nada de los de verdad
import acciones
import vision_delta as vd

vd.PID = d / "pid"
assert "apagada" in asyncio.run(vd.vision("estado"))
assert asyncio.run(vd.vision("nada")).startswith("Error")
vd._pid = lambda: 1  # como si vision.py estuviera en marcha
vision.ESTADO.write_text(json.dumps({"t": time.time(), "pausa": False, "fuentes": {"portatil": {
    "ok": True, "presente": True, "presente_desde": "18:40", "mirando": False, "caras": 2, "parpadeos_min": 9,
    "cabeza_hombros": 0.2}}}))
r = asyncio.run(vd.vision("estado"))
assert "18:40" in r and "2 caras" in r and "caída" in r and "sin mirar" in r, r
vision.ESTADO.write_text(json.dumps({"t": time.time() - 60, "fuentes": {}}))
assert "arrancando" in asyncio.run(vd.vision("estado")), "un estado viejo no se da por bueno"
vision.EVENTOS.write_text(json.dumps({"t": 1, "h": "18:41:00", "fuente": "portatil", "evento": "gesto", "gesto": "Open_Palm"}) + "\n")
assert "gesto=Open_Palm" in asyncio.run(vd.vision("eventos"))
acciones.ST["privacidad"] = True
vd.sincronizar_privacidad()
assert vision.PAUSA.exists(), "modo privacidad: la cámara se suelta"
acciones.ST["privacidad"] = False
vd.sincronizar_privacidad()
assert not vision.PAUSA.exists()
assert "vision" in acciones.HANDLERS and any(x.name == "vision" for x in acciones.DECLARATIONS)
print("ok")
