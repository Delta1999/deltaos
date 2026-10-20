"""Proactividad: Delta habla sin que le pregunten — y, sobre todo, sabe cuándo callarse.

Hablar solo ya se podía (`acciones.avisar`), pero sin freno: cualquier aviso sonaba a cualquier
hora y tantas veces como hiciera falta. Lo que faltaba es esto:

  - QUÉ dice por su cuenta: calor, memoria, disco y batería. Son cosas que el panel ya medía y
    el mapache ya pintaba, pero que nadie decía en voz alta.
  - CUÁNDO se calla: privacidad, «no molestar», de noche salvo urgencias, y un freno por motivo
    para que no se vuelva pesado.

La puerta vale para TODO el que avise, no solo para lo de aquí: `acciones.avisar(..., motivo=…)`
pasa por ella. Sin `motivo` (alarmas, recordatorios, trabajos terminados: cosas que el usuario
pidió expresamente) no se filtra nada, faltaría más.

El texto que se manda no es la frase que dirá Delta, sino el encargo: lo redacta él con su
personalidad (ver el apartado PROACTIVIDAD de personalidad.txt).
"""
import glob
import shutil
import time
from pathlib import Path

import acciones
import panel
from acciones import _s

RONDA = 20          # s entre rondas; los umbrales son lentos, no hace falta más
NOCHE = (23, 8)     # de 23:00 a 08:00 solo pasan las urgencias
MAX_HORA = 4        # veces que puede interrumpir por su cuenta en una hora (las urgencias no cuentan)

CALOR = 88          # °C; el mapache tiembla a 85, hablar es un escalón por encima
RAM_ALTA = 95       # % (8 GB: el 86 % es lo normal en esta máquina)
SWAP_ALTA = 70      # % — con la RAM llena pero sin swap tocada no pasa nada
DISCO_MIN = 4.0     # GB libres en casa
BAT_BAJA = 15       # %

_ultimo: dict = {}   # motivo → time.monotonic() de la última vez que se dijo
_pasadas: list = []  # monotonic de cada intervención por su cuenta (para el tope por hora)
_seguidas: dict = {} # motivo → rondas seguidas cumpliendo el umbral (un pico no es un problema)


# ---------- la puerta ----------
def puede(motivo, urgente=False, espera=0.0, ahora=None, hora=None):
    """¿Puede Delta decir esto por su cuenta? Devuelve el motivo para callarse, o None si pasa.

    Si pasa, lo apunta: esta función tiene efecto, y por eso se llama justo antes de hablar.
    """
    ahora = time.monotonic() if ahora is None else ahora
    hora = time.localtime().tm_hour if hora is None else hora
    if acciones.ST.get("privacidad"):
        return "privacidad"
    if ahora < acciones.ST.get("no_molestar", 0):
        return "no molestar"
    if not urgente:
        if hora >= NOCHE[0] or hora < NOCHE[1]:
            return "de noche"
        if espera and ahora - _ultimo.get(motivo, float("-inf")) < espera:
            return "ya lo ha dicho hace poco"
        if len([t for t in _pasadas if ahora - t < 3600]) >= MAX_HORA:
            return f"ya ha interrumpido {MAX_HORA} veces esta hora"
    elif espera and ahora - _ultimo.get(motivo, float("-inf")) < espera:
        return "ya lo ha dicho hace poco"  # urgente no es excusa para repetirse en bucle
    _ultimo[motivo] = ahora
    _pasadas.append(ahora)
    del _pasadas[:-50]
    return None


# ---------- qué merece decirse ----------
def _bateria():
    bat = (glob.glob("/sys/class/power_supply/BAT*") or [None])[0]
    if not bat:
        return None
    try:
        return int(Path(bat, "capacity").read_text()), Path(bat, "status").read_text().strip()
    except OSError:
        return None


def mirar(sistema, bateria, libres_gb):
    """Estado → lista de (motivo, urgente, espera_s, encargo). Sin efectos: así se puede probar.

    Pide dos rondas seguidas para los umbrales que pueden dar un pico (calor, memoria): un
    laminado arranca la CPU al 100 % un segundo y eso no es nada que contar.
    """
    out = []

    def sostenido(motivo, cumple):
        _seguidas[motivo] = _seguidas.get(motivo, 0) + 1 if cumple else 0
        return _seguidas[motivo] >= 2

    t = (sistema or {}).get("temp")
    if sostenido("calor", t is not None and t >= CALOR):
        out.append(("calor", True, 20 * 60,
                    f"El procesador lleva un rato a {t} grados (el límite cómodo son {CALOR}). Dile la cifra y "
                    f"ofrécele cerrar lo que más esté gastando, en una sola frase."))

    ram, swap = (sistema or {}).get("ram"), (sistema or {}).get("swap")
    if sostenido("memoria", ram is not None and ram >= RAM_ALTA and (swap or 0) >= SWAP_ALTA):
        out.append(("memoria", False, 45 * 60,
                    f"La memoria está al {ram} % y la swap al {swap} %: el ordenador va a empezar a ir a tirones. "
                    f"Dile las dos cifras y ofrécele mirar qué lo está comiendo."))

    if libres_gb is not None and libres_gb < DISCO_MIN:
        out.append(("disco", False, 12 * 3600,
                    f"Quedan {libres_gb:.1f} GB libres en el disco. Díselo y ofrécele buscar qué ocupa."))

    if bateria and bateria[1] == "Discharging" and bateria[0] <= BAT_BAJA:
        out.append(("bateria", True, 15 * 60,
                    f"Queda un {bateria[0]} % de batería y no está enchufado. Díselo en una frase, sin dramatismo."))

    return out


async def vigilar():
    """Ronda cada RONDA segundos. Es la única tarea de este módulo."""
    import asyncio
    while True:
        await asyncio.sleep(RONDA)
        try:
            libres = shutil.disk_usage(Path.home()).free / 1e9
            for motivo, urgente, espera, encargo in mirar(panel.S.get("sistema"), _bateria(), libres):
                callar = puede(motivo, urgente, espera)
                if callar:
                    continue  # no es un fallo: es que ahora no toca
                await acciones.avisar(encargo, motivo=motivo, urgente=urgente)
                break  # uno por ronda: dos avisos seguidos no son un mayordomo, son una alarma
        except Exception as e:
            print(f"🔔 proactivo: {type(e).__name__}: {e}")


# ---------- «déjame en paz» ----------
async def no_molestar(minutos=""):
    """Silencia lo que Delta diría por su cuenta. Lo que pidió el usuario (alarmas, recordatorios,
    trabajos que terminan) sigue sonando: eso no es molestar, es lo que encargó."""
    m = str(minutos).strip().replace(",", ".")
    if m in ("", "0", "fin", "ya", "basta"):
        acciones.ST["no_molestar"] = 0
        return "Hecho: vuelvo a avisar de lo que vea."
    try:
        n = float(m)
    except ValueError:
        return 'Error: minutos tiene que ser un número (o vacío para volver a avisar), p.ej. "45".'
    if not 0 < n <= 12 * 60:
        return "Error: entre 1 minuto y 12 horas."
    acciones.ST["no_molestar"] = time.monotonic() + n * 60
    return f"Hecho: no le molesto durante {n:g} minutos. Lo que me pidió expresamente sigue sonando."


acciones.PUERTA = puede  # acciones.avisar() la consulta; sin este módulo cargado, avisa como siempre
acciones.ETIQUETAS["no_molestar"] = "No molestar"
# Se registra plana pero la absorbe la fusión «avisos»: el presupuesto de herramientas está lleno.
acciones.registrar([
    acciones._fn("no_molestar",
                 "Deja de avisar por tu cuenta durante un rato («no me molestes», «déjame en paz un rato», "
                 "«silencio»). Las alarmas y los recordatorios que él te pidió siguen sonando. Sin minutos, "
                 "o con 0, vuelves a avisar.",
                 {"minutos": _s("cuántos minutos callar; vacío o 0 para volver a avisar")}),
], (no_molestar,))
