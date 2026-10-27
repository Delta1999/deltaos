"""Temporizadores, alarmas y recordatorios (sobreviven a reinicios, en avisos.json) y el buzón por el que
las sesiones de Claude Code que lanza el usuario avisan al terminar (hook Stop → aviso_claude.py)."""
import asyncio
import json
import os
import re
import subprocess
import time
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

import acciones
from acciones import _fn, _s

FICHERO = acciones.AQUI / "avisos.json"
BUZON = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "delta-avisos"
SONIDOS = Path("/usr/share/sounds/freedesktop/stereo")
MAX_ALARMA = 300            # s sonando si nadie dice «para la alarma»
RETRASO_MAX = 12 * 3600     # un aviso que venció con el PC apagado/suspendido se dice si lleva menos de esto
BUZON_CADUCA = 30 * 60      # avisos de Claude más viejos (Delta estaba parado) se descartan
_ALARMA = {"parar": None}


def _cargar():
    try:
        return json.loads(FICHERO.read_text())
    except (FileNotFoundError, ValueError):
        return []


def _guardar(lista):
    FICHERO.write_text(json.dumps(lista, ensure_ascii=False, indent=1))


_DIAS_SEM = {"lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3, "viernes": 4, "sabado": 5, "domingo": 6}


def _dia_y_hora(a, ahora):
    """«jueves 17:30», «el jueves a las 17:30», «mañana 09:00», «pasado mañana 10:00», «hoy 18:00» → instante, o None.
    Delta no sabe qué día es hoy: el día de la semana se resuelve aquí, no lo calcula el modelo. Un día de la semana es
    siempre el próximo: si hoy es jueves y la hora aún no ha pasado es hoy; si ya pasó, el de la semana que viene."""
    plano = "".join(c for c in unicodedata.normalize("NFD", a.lower()) if not unicodedata.combining(c))
    m = re.fullmatch(r"(?:el |para el |para )?(hoy|pasado manana|manana|" + "|".join(_DIAS_SEM) + r")(?: a las| a la| sobre las)? ?(\d{1,2})(?:[:.h](\d{2}))?",
                     plano.strip())
    if not m:
        return None
    nombre, h, mi = m.group(1), int(m.group(2)), int(m.group(3) or 0)
    if h > 23 or mi > 59:
        return None
    base = ahora.replace(hour=h, minute=mi, second=0, microsecond=0)
    if nombre in _DIAS_SEM:
        t = base + timedelta(days=(_DIAS_SEM[nombre] - ahora.weekday()) % 7)
        return t if t > ahora else t + timedelta(days=7)
    return base + timedelta(days={"hoy": 0, "manana": 1, "pasado manana": 2}[nombre])


def cuando(en_minutos="", a_las="", ahora=None):
    """Instante del aviso: dentro de N minutos, o a una hora (HH:MM → la próxima vez que llegue; o AAAA-MM-DD HH:MM)."""
    ahora = ahora or datetime.now()
    if str(en_minutos).strip():
        return ahora + timedelta(minutes=float(str(en_minutos).replace(",", ".")))
    a = str(a_las).strip()
    dia = _dia_y_hora(a, ahora)
    if dia:
        return dia
    for fmt in ("%Y-%m-%d %H:%M", "%H:%M", "%H.%M", "%H"):
        try:
            t = datetime.strptime(a, fmt)
            break
        except ValueError:
            pass
    else:
        raise ValueError(f"no entiendo «{a_las}»: usa en_minutos, o a_las como HH:MM o AAAA-MM-DD HH:MM")
    if fmt.startswith("%Y"):
        return t
    t = ahora.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
    return t if t > ahora else t + timedelta(days=1)


DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def _bonito(t, ahora=None):
    ahora = ahora or datetime.now()
    dia = "hoy" if t.date() == ahora.date() else "mañana" if t.date() == (ahora + timedelta(days=1)).date() \
        else f"el {DIAS[t.weekday()]} {t.day}"
    m = max(0, round((t - ahora).total_seconds() / 60))
    falta = f"{m} min" if m < 60 else f"{m // 60} h {m % 60} min"
    return f"{dia} a las {t:%H:%M} (dentro de {falta})"


# ---------- herramientas ----------
async def programar_aviso(texto, en_minutos="", a_las="", tipo="aviso", repetir=""):
    try:
        t = cuando(en_minutos, a_las)
    except ValueError as e:
        return f"Error: {e}"
    if t < datetime.now() - timedelta(minutes=1):
        return f"Error: {t:%d/%m %H:%M} ya ha pasado. Ahora son las {datetime.now():%d/%m %H:%M}."
    tipo = "alarma" if "alarm" in str(tipo).lower() else "aviso"
    diario = str(repetir).lower().startswith("diar")
    lista = _cargar()
    lista.append({"id": int(time.time() * 1000), "texto": texto.strip() or tipo, "t": t.isoformat(timespec="seconds"),
                  "tipo": tipo, "diario": diario})
    _guardar(lista)
    return f"{tipo.capitalize()} «{texto}» para {_bonito(t)}{', cada día' if diario else ''}."


def _ahora():
    """La hora de aquí, para que Gemini no diga la suya (va en UTC: decía las 18:17 a las 19:17, 26/10/2026)."""
    n = datetime.now()
    return f"Ahora (hora de España): {DIAS[n.weekday()]} {n:%d/%m/%Y, %H:%M}."


async def ver_avisos():
    lista = sorted(_cargar(), key=lambda a: a["t"])
    if not lista:
        return f"{_ahora()} No hay avisos ni alarmas."
    return f"{_ahora()}\n" + "\n".join(
        f"- {a['tipo']} «{a['texto']}»: {_bonito(datetime.fromisoformat(a['t']))}{' (cada día)' if a['diario'] else ''}"
        for a in lista)


async def cancelar_aviso(cual):
    lista = _cargar()
    c = cual.strip().lower()
    quedan = [] if c in ("todos", "todas", "todo") else [a for a in lista if c not in a["texto"].lower()]
    _guardar(quedan)
    n = len(lista) - len(quedan)
    return f"Cancelados {n}." if n else f"No hay ningún aviso que case con «{cual}». " + await ver_avisos()


async def parar_alarma():
    ev = _ALARMA["parar"]
    if ev is None or ev.is_set():
        return "No está sonando ninguna alarma."
    ev.set()
    return "Alarma parada."


# ---------- disparo ----------
def _sonar(nombre):
    if acciones.silencio_total():
        return
    subprocess.Popen(["paplay", str(SONIDOS / nombre)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def _alarma_en_bucle():
    if _ALARMA["parar"] and not _ALARMA["parar"].is_set():
        return  # ya suena una
    ev = _ALARMA["parar"] = asyncio.Event()
    fin = time.monotonic() + MAX_ALARMA
    while not ev.is_set() and time.monotonic() < fin:
        _sonar("alarm-clock-elapsed.oga")
        try:
            await asyncio.wait_for(ev.wait(), 3)
        except asyncio.TimeoutError:
            pass
    ev.set()


async def _disparar(a, retraso):
    tarde = f" (con {round(retraso / 60)} min de retraso: el ordenador estaba apagado o suspendido)" if retraso > 120 else ""
    if a["tipo"] == "alarma" and not acciones.silencio_total():
        acciones.tarea(_alarma_en_bucle())
        await acciones.avisar(f"Alarma: {a['texto']}{tarde}. Sigue sonando hasta que el usuario diga que pares (avisos accion=parar_alarma).",
                           movil=f"Alarma: {a['texto']}{tarde}")
    else:
        _sonar("complete.oga")
        await acciones.avisar(f"Recordatorio que te pidió el usuario: {a['texto']}{tarde}.",
                              movil=f"Recordatorio: {a['texto']}{tarde}")


def vencidos(lista, ahora):
    """Separa los que tocan ya; los diarios se reprograman al día siguiente. Devuelve (vencidos, lista_nueva)."""
    toca, quedan = [], []
    for a in lista:
        t = datetime.fromisoformat(a["t"])
        if t > ahora:
            quedan.append(a)
            continue
        toca.append((a, (ahora - t).total_seconds()))
        if a["diario"]:
            while t <= ahora:
                t += timedelta(days=1)
            quedan.append({**a, "t": t.isoformat(timespec="seconds")})
    return toca, quedan


async def _buzon_claude():
    BUZON.mkdir(mode=0o700, exist_ok=True)
    for f in sorted(BUZON.glob("*.json")):
        try:
            d = json.loads(f.read_text())
        except ValueError:
            d = None
        f.unlink(missing_ok=True)
        if d and time.time() - d.get("t", 0) < BUZON_CADUCA:
            await acciones.avisar(f"Ha terminado una sesión de CLAUDE CODE en la carpeta «{d.get('proyecto', '?')}» "
                                  f"(llevaba {d.get('min', '?')} min). Dilo así: ha terminado Claude Code, y en qué carpeta "
                                  f"(«gemini-live-assistant» es tu propio repositorio, DeltaOS). Resúmeselo en una frase: "
                                  f"{d.get('final', '')[:600]}",
                                  movil=f"Claude Code ha terminado en «{d.get('proyecto', '?')}» ({d.get('min', '?')} min)")


async def vigilar():
    while True:
        await asyncio.sleep(5)
        try:
            toca, quedan = vencidos(_cargar(), datetime.now())
            if toca:
                _guardar(quedan)
                for a, retraso in toca:
                    if retraso < RETRASO_MAX:
                        await _disparar(a, retraso)
            await _buzon_claude()
        except Exception as e:
            print(f"avisos: {e}")


acciones.registrar([
    _fn("programar_aviso",
        "Temporizador, recordatorio o alarma. «Avísame en 20 minutos», «recuérdame a las 18:30 llamar a Juan», "
        "«despiértame a las 8» (tipo alarma: suena en bucle hasta parar_alarma). Sobrevive a reinicios.",
        {"texto": _s("qué hay que recordar, p.ej. «sacar la pizza»"),
         "en_minutos": _s("dentro de cuántos minutos (para temporizadores), p.ej. 20 o 1.5"),
         "a_las": _s("hora HH:MM (la próxima vez que llegue), o con día: «jueves 17:30», «mañana 09:00», «pasado mañana 10:00» "
                     "(escríbelo tal cual lo dijo el usuario: tú no sabes qué día es hoy) o AAAA-MM-DD HH:MM"),
         "tipo": _s("aviso (por defecto: lo dices una vez con un sonido) | alarma (suena en bucle)"),
         "repetir": _s("vacío | diario")},
        req=["texto"]),
    _fn("ver_avisos", "Lista temporizadores, recordatorios y alarmas pendientes, y la hora actual."),
    _fn("cancelar_aviso", "Cancela los avisos/alarmas cuyo texto contenga esto, o «todos».",
        {"cual": _s("parte del texto del aviso, o «todos»")}),
    _fn("parar_alarma", "Para la alarma que está sonando."),
], [programar_aviso, ver_avisos, cancelar_aviso, parar_alarma])
acciones.ETIQUETAS.update(programar_aviso="Programo un aviso", ver_avisos="Miro los avisos",
                          cancelar_aviso="Cancelo un aviso", parar_alarma="Paro la alarma")


if __name__ == "__main__":  # comprobación: .venv/bin/python avisos.py
    n = datetime(2026, 10, 15, 22, 0)
    assert cuando("20", ahora=n) == datetime(2026, 10, 15, 22, 20)
    assert cuando(a_las="08:00", ahora=n) == datetime(2026, 10, 16, 8, 0)      # ya pasó hoy → mañana
    assert cuando(a_las="23:30", ahora=n) == datetime(2026, 10, 15, 23, 30)
    assert cuando(a_las="2026-12-24 20:00", ahora=n) == datetime(2026, 12, 24, 20, 0)
    lista = [{"t": "2026-10-15T21:59:00", "diario": True, "texto": "a"}, {"t": "2026-10-15T23:00:00", "diario": False, "texto": "b"},
             {"t": "2026-10-15T21:00:00", "diario": False, "texto": "c"}]
    toca, quedan = vencidos(lista, n)
    assert [a["texto"] for a, _ in toca] == ["a", "c"] and toca[1][1] == 3600
    assert sorted(a["t"] for a in quedan) == ["2026-10-15T23:00:00", "2026-10-16T21:59:00"]
    try:
        cuando(a_las="mañana")
        raise AssertionError
    except ValueError:
        pass
    print("avisos OK")
