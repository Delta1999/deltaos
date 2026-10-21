"""El Fire TV Stick del salón por ADB (red, ya autorizado): abrir apps, teclas del mando y qué tiene puesto.

Alexa está desactivada en el stick, pero el sistema reactiva com.amazon.vizzini en cada arranque: vigilar() lo nota
por el boot_id y la vuelve a desactivar. El estado (encendida y app delante) va al panel en S["tele"].
"""
import asyncio

import acciones
import panel
from acciones import _fn, _run, _s

DIR = "192.168.0.101:5555"
# lo que el usuario dice → paquete (solo las suyas; nada de listas de canales de pago)
APPS = {"netflix": "com.netflix.ninja", "youtube": "com.amazon.firetv.youtube", "smarttube": "org.smarttube.stable",
        "twitch": "tv.twitch.android.viewer", "max": "com.hbo.hbonow", "prime video": "com.amazon.firebat",
        "mitele": "tv.accedo.mitele_xdk", "airplay": "apollo.gadgets.atv_airplay", "downloader": "com.esaba.downloader",
        "ajustes": "com.amazon.tv.settings.v2"}
ALIAS = {"hbo": "max", "prime": "prime video", "amazon": "prime video", "configuración": "ajustes", "smart tube": "smarttube"}
TECLAS = {"pausa": 85, "seguir": 85, "play": 85, "atras": 4, "inicio": 3, "arriba": 19, "abajo": 20, "izquierda": 21,
          "derecha": 22, "ok": 23, "adelantar": 90, "retroceder": 89, "siguiente": 87, "anterior": 88,
          "subir_volumen": 24, "bajar_volumen": 25, "silenciar": 164, "menu": 82, "apagar": 223, "encender": 224}
# Alexa (los 14 paquetes del 21/10 menos los 2 desinstalados): si alguno vuelve tras reiniciar, se desactiva otra vez
ALEXA = ("com.amazon.vizzini", "com.amazon.vizzini.ftvcds", "com.amazon.alexadirectivebrokerservice",
         "com.amazon.alexa.externalmediaplayer.fireos", "com.amazon.tv.alexaalerts", "com.amazon.tv.alexanotifications",
         "com.amazon.firetv.androidskillconnectioncapability", "com.amazon.comms.starktachyon",
         "com.amazon.rtcsessioncontroller", "com.amazon.whad", "com.amazon.wha.mediabrowserservice", "com.amazon.whasettings")
_boot = {"id": None}


async def _adb(cmd, timeout=10):
    """Un comando de shell en el stick; conecta antes si hace falta. (rc, salida)."""
    rc, out = await _run(["adb", "-s", DIR, "shell", cmd], timeout=timeout)
    if rc != 0 and ("not found" in out or "offline" in out or "closed" in out):
        await _run(["adb", "connect", DIR], timeout=8)
        rc, out = await _run(["adb", "-s", DIR, "shell", cmd], timeout=timeout)
    return rc, out.strip()


def _nombre(pkg):
    return next((n for n, p in APPS.items() if p == pkg), "inicio" if pkg == "com.amazon.tv.launcher" else pkg)


async def _estado():
    """{"on": bool, "app": nombre} o None si el stick no responde."""
    rc, out = await _adb("dumpsys power | grep -m1 mWakefulness=; dumpsys activity activities | grep -m1 mResumedActivity")
    if rc != 0 or "mWakefulness" not in out:
        return None
    on = "mWakefulness=Awake" in out
    pkg = out.split("u0 ", 1)[1].split("/", 1)[0] if "u0 " in out else ""
    return {"on": on, "app": _nombre(pkg) if on else ""}


async def _sin_alexa():
    """Tras cada arranque del stick: Alexa fuera otra vez."""
    rc, boot = await _adb("cat /proc/sys/kernel/random/boot_id")
    if rc != 0 or boot == _boot["id"]:
        return
    _, desact = await _adb("pm list packages -d")  # corta; la de activas pasa del recorte de _run
    for p in ALEXA:
        if f"package:{p}\n" not in desact + "\n":
            await _adb(f"pm disable-user --user 0 {p}")
            print(f"📺 Fire TV: {p} había vuelto, desactivada")
    _boot["id"] = boot


async def vigilar():
    while True:
        try:
            await _sin_alexa()
            panel.S["tele"] = await _estado()
        except Exception:
            pass
        await asyncio.sleep(30)


async def tele_salon(accion, app="", veces="1"):
    accion = accion.strip().lower().replace(" ", "_").replace("á", "a")
    if accion == "estado":
        e = panel.S["tele"] = await _estado()
        if not e:
            return "El Fire TV del salón no responde (¿desenchufado o sin wifi?)."
        return f"La tele del salón está encendida con {e['app']}." if e["on"] else "El Fire TV del salón está en reposo."
    if accion == "abrir":
        n = app.strip().lower()
        n = ALIAS.get(n, n)
        if n not in APPS:
            return f"No sé abrir «{app}» en la tele. Tengo: {', '.join(APPS)}."
        await _adb("input keyevent 224")  # si estaba en reposo, la despierta
        rc, out = await _adb(f"monkey -p {APPS[n]} -c android.intent.category.LEANBACK_LAUNCHER 1")
        return f"Abro {n} en la tele del salón." if rc == 0 and "No activities" not in out else f"No pude abrir {n}: {out[-200:]}"
    if accion not in TECLAS:
        return f"Acción no válida: estado | abrir | {' | '.join(TECLAS)}"
    try:
        n = max(1, min(int(veces or 1), 20))
    except ValueError:
        n = 1
    rc, out = await _adb("; ".join([f"input keyevent {TECLAS[accion]}"] * n))
    if rc != 0:
        return f"El Fire TV del salón no responde: {out[-200:]}"
    return "Hecho." if accion not in ("apagar", "encender") else ("Apago el Fire TV." if accion == "apagar" else "Enciendo el Fire TV.")


acciones.registrar([
    _fn("tele_salon",
        "La tele del SALÓN (Fire TV Stick): abrir Netflix, YouTube, Twitch, Max, Prime Video… y manejarla como el mando. "
        "No es poner_tele (canales en directo en el ordenador). estado: si está encendida y qué app tiene. abrir: una app. "
        "Teclas: pausa/seguir (la misma), atras, inicio, arriba/abajo/izquierda/derecha, ok, adelantar, retroceder, "
        "siguiente, anterior, subir_volumen/bajar_volumen, silenciar, menu, apagar, encender.",
        {"accion": _s("estado | abrir | " + " | ".join(TECLAS)),
         "app": _s("abrir: " + ", ".join(APPS)),
         "veces": _s("teclas: cuántas veces pulsarla (p. ej. 5 para bajar el volumen 5 puntos), por defecto 1")},
        req=["accion"]),
], [tele_salon])
acciones.ETIQUETAS.update(tele_salon="Tele del salón")
