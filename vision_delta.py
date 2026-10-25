"""Delta ⇄ visión (vision.py corre en su propio proceso): la herramienta «vision» y el modo privacidad.

Fase de prueba (22/10/2026): la visión observa y apunta, pero todavía NO actúa sola (ni bloquea, ni pausa la
música, ni saluda). Primero se mira unos días en los eventos si acierta; las acciones vienen después.
Se enciende a mano («enciende la visión»): con ella encendida la luz de la webcam está siempre puesta.
"""
import asyncio
import json
import os
import signal
import subprocess
import time

import acciones
from acciones import ST, AQUI, _fn, _s
import vision as vis

LOG = AQUI / "vision.log"
PID = vis.RUN / "delta-vision.pid"
FRESCO = 10  # s: un estado más viejo es que vision.py no está mirando


def _pid():
    """El pid de vision.py si sigue vivo y es de verdad él (un pid viejo puede ser ya otro programa)."""
    try:
        pid = int(PID.read_text())
        if "vision.py" in open(f"/proc/{pid}/cmdline").read():
            return pid
    except (OSError, ValueError):
        pass
    return None


def encender():
    if _pid():
        return "La visión ya estaba encendida."
    with LOG.open("a") as log:
        p = subprocess.Popen([str(AQUI / ".venv" / "bin" / "python"), str(AQUI / "vision.py")], cwd=AQUI,
                             stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    PID.write_text(str(p.pid))
    return ("Visión encendida: miro por la webcam si está delante, hacia dónde mira, gestos y postura. Está en "
            "prueba: de momento solo observo y apunto, no hago nada por mi cuenta. La luz de la cámara queda encendida.")


def apagar():
    pid = _pid()
    if not pid:
        return "La visión ya estaba apagada."
    os.kill(pid, signal.SIGINT)  # SIGINT: vision.py suelta la cámara antes de salir
    PID.unlink(missing_ok=True)
    return "Visión apagada; la cámara queda libre."


def leer_estado():
    try:
        e = json.loads(vis.ESTADO.read_text())
    except (OSError, ValueError):
        return None
    return e if time.time() - e.get("t", 0) < FRESCO else None


def resumen():
    if not _pid():
        return "La visión está apagada («enciende la visión» para encenderla)."
    e = leer_estado()
    if e is None:
        return "La visión está arrancando o no le llega imagen todavía."
    if e.get("pausa"):
        return "La visión está en pausa por el modo privacidad: la cámara está soltada."
    partes = []
    for n, f in e["fuentes"].items():
        if not f.get("ok"):
            partes.append(f"{n}: sin imagen")
            continue
        if not f.get("presente"):
            partes.append(f"{n}: no hay nadie delante")
            continue
        p = [f"{n}: está delante desde las {f['presente_desde']}" if f.get("presente_desde") else f"{n}: está delante",
             "mirando la pantalla" if f.get("mirando") else "sin mirar la pantalla"]
        if f.get("caras", 0) >= 2:
            p.append(f"hay {f['caras']} caras")
        if f.get("parpadeos_min"):
            p.append(f"{f['parpadeos_min']} parpadeos en el último minuto (a 5 imágenes por segundo se escapan algunos)")
        if "cabeza_hombros" in f:
            p.append("cabeza caída hacia los hombros" if f["cabeza_hombros"] < 0.35 else "postura erguida")
        partes.append(", ".join(p))
    return ". ".join(partes) + "."


def eventos(n=12):
    try:
        lineas = vis.EVENTOS.read_text().splitlines()[-n:]
    except OSError:
        return "Todavía no hay eventos."
    ev = [json.loads(x) for x in lineas]
    return "Eventos recientes:\n" + "\n".join(
        f"- {x['h']} {x['fuente']}: {x['evento']}" + "".join(f" {k}={v}" for k, v in x.items()
                                                           if k not in ("t", "h", "fuente", "evento"))
        for x in ev)


async def vision(accion):
    a = (accion or "").strip().lower()
    hacer = {"encender": encender, "apagar": apagar, "estado": resumen, "eventos": eventos}.get(a)
    if not hacer:
        return "Error: accion debe ser encender | apagar | estado | eventos."
    return await asyncio.to_thread(hacer)


def sincronizar_privacidad():
    """Modo privacidad ⇒ la cámara se suelta (y su luz se apaga) aunque la visión siga encendida."""
    if ST.get("privacidad"):
        vis.PAUSA.touch()
    else:
        vis.PAUSA.unlink(missing_ok=True)


async def vigilar():
    while True:
        try:
            sincronizar_privacidad()
        except Exception as e:  # nunca debe tirar a Delta
            print(f"visión: {e}")
        await asyncio.sleep(2)


acciones.registrar([
    _fn("vision",
        "Tu vista por cámara (en prueba; hoy la webcam del portátil, más adelante las del jardín, el comedero del "
        "gato y la GoPro). encender/apagar: la enciende o la apaga («enciende la visión», «apaga la cámara»). "
        "estado: si el usuario está delante, si mira la pantalla, cuántas caras hay, parpadeos y postura («¿me ves?», "
        "«¿cómo estoy sentado?»). eventos: lo último que ha pasado (llegó, se fue, gestos, otra persona, bostezos). "
        "De momento solo observa: no prometas que hace algo solo al detectar algo.",
        {"accion": _s("encender | apagar | estado | eventos")}, req=["accion"]),
], [vision])
acciones.ETIQUETAS.update(vision="Visión")
