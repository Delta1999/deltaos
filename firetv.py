"""El Fire TV Stick del salón por ADB (red, ya autorizado): abrir apps, teclas del mando, qué tiene puesto y la
interfaz de DeltaOS en la tele (la app firetv/mic_mando, actividad Tele).

Fire OS deshace cosas por su cuenta (reactiva Alexa en cada arranque, puede dormir o desactivar apps): _blindar()
lo vuelve a dejar todo como debe estar tras cada arranque y cada 5 minutos. El estado va al panel en S["tele"].
Un clic en el botón del micro del mando (lo lee devicecontrol y sale en logcat) pasa la interfaz al salón.
"""
import asyncio
import time

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
PROPIA = "es.delta.micmando"
APK = acciones.AQUI / "firetv" / "mic_mando" / "build" / "micmando.apk"
# sin estas no hay botón del micro, ni panel en la tele, ni vuelta al inicio
NECESARIAS = (PROPIA, "com.amazon.tv.devicecontrol", "com.amazon.webview.chromium", "com.amazon.tv.launcher")
_FIJAR = "; ".join([  # idempotente: se repite entero cada vez, sin mirar antes
    "cmd appops set com.amazon.vizzini RECORD_AUDIO ignore",  # si Alexa vuelve, que siga sorda
    f"pm grant {PROPIA} android.permission.RECORD_AUDIO",
    f"cmd appops set {PROPIA} RECORD_AUDIO allow", f"cmd appops set {PROPIA} RUN_IN_BACKGROUND allow",
    f"cmd appops set {PROPIA} START_FOREGROUND allow",
    f"dumpsys deviceidle whitelist +{PROPIA}",  # que el ahorro de energía no la duerma
    "settings put secure screensaver_enabled 0"])  # sin salvapantallas de paisajes: tapaba el panel y el primer clic
CADA_BLINDAJE = 300
BOTON = "Received Key name: ALEXA, code: 319, action: 0"
DONDE = {"aqui": "portatil", "pulsado": 0.0}  # dónde está la interfaz: portatil | salon
_boot = {"id": None, "t": 0.0}


async def _adb(cmd, timeout=10):
    """Un comando de shell en el stick; conecta antes si hace falta. (rc, salida)."""
    rc, out = await _run(["adb", "-s", DIR, "shell", cmd], timeout=timeout)
    if rc != 0 and ("not found" in out or "offline" in out or "closed" in out):
        await _run(["adb", "connect", DIR], timeout=8)
        rc, out = await _run(["adb", "-s", DIR, "shell", cmd], timeout=timeout)
    return rc, out.strip()


def _nombre(pkg):
    if pkg == PROPIA:
        return "delta"
    return next((n for n, p in APPS.items() if p == pkg), "inicio" if pkg == "com.amazon.tv.launcher" else pkg)


async def _estado():
    """{"on": bool, "app": nombre} o None si el stick no responde."""
    rc, out = await _adb("dumpsys power | grep -m1 mWakefulness=; dumpsys activity activities | grep -m1 mResumedActivity")
    if rc != 0 or "mWakefulness" not in out:
        return None
    on = "mWakefulness=Awake" in out
    pkg = out.split("u0 ", 1)[1].split("/", 1)[0] if "u0 " in out else ""
    return {"on": on, "app": _nombre(pkg) if on else ""}


async def _blindar(forzar=False):
    """Tras cada arranque del stick y cada 5 min: Alexa fuera y sorda, lo nuestro instalado, activo y sin dormir."""
    rc, boot = await _adb("cat /proc/sys/kernel/random/boot_id")
    if rc != 0 or (boot == _boot["id"] and time.monotonic() - _boot["t"] < CADA_BLINDAJE and not forzar):
        return
    _, desact = await _adb("pm list packages -d")  # corta; la de activas pasa del recorte de _run
    desact = set(desact.replace("package:", "").split())
    for p in ALEXA:
        if p not in desact:
            await _adb(f"pm disable-user --user 0 {p}")
            print(f"📺 Fire TV: {p} había vuelto, desactivada")
    for p in NECESARIAS:
        if p in desact:
            await _adb(f"pm enable {p}")
            print(f"📺 Fire TV: {p} estaba desactivada, activada")
    _, hay = await _adb(f"pm list packages {PROPIA}")
    if f"package:{PROPIA}" not in hay.split() and APK.exists():
        rc2, out = await _run(["adb", "-s", DIR, "install", "-r", str(APK)], timeout=60)
        print(f"📺 Fire TV: la app de Delta no estaba, reinstalada: {out[-80:]}")
    await _adb(_FIJAR)
    _boot.update(id=boot, t=time.monotonic())


def _url():
    ip = panel.ip_para_la_tele()
    if not ip or f"http://{ip}:{panel.PORT}" not in panel.ORIGENES:
        return None  # la red cambió desde que arrancó Delta: el panel no escucha en esa IP
    return f"http://{ip}:{panel.PORT}/?t={panel.TELE_CLAVE}"


async def interfaz_salon(tapar=True):
    """La interfaz a la tele. tapar=False: si hay otra app delante (Netflix…), la deja."""
    url = _url()
    if not url:
        return "El panel no escucha en la red de casa (¿cambió la wifi?): reinicia Delta y vuelve a pedirlo."
    await _blindar()
    e = await _estado()
    if e is None:
        return "El Fire TV del salón no responde (¿desenchufado o sin wifi?)."
    DONDE["aqui"] = "salon"
    if not tapar and e["on"] and e["app"] not in ("inicio", "delta"):
        return f"Estás en el salón; dejo {e['app']} delante."
    rc, out = await _adb(f"input keyevent 224; am start -n {PROPIA}/.Tele --es url '{url}'")
    return "Paso la interfaz a la tele del salón." if rc == 0 and "Error" not in out else f"No pude: {out[-200:]}"


async def interfaz_portatil():
    DONDE["aqui"] = "portatil"
    e = await _estado()
    if e and e["app"] == "delta":
        await _adb(f"am start -n {PROPIA}/.Tele --ez salir true")
    return "La interfaz vuelve al portátil."


async def _boton():
    """Lee del logcat del stick las pulsaciones del botón del micro; cada una pasa la interfaz al salón."""
    while True:
        try:
            await _run(["adb", "connect", DIR], timeout=8)
            p = await asyncio.create_subprocess_exec(
                "adb", "-s", DIR, "shell", f"logcat -T \"$(date '+%m-%d %H:%M:%S.000')\" | grep --line-buffered '{BOTON}'",
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            async for _ in p.stdout:
                if time.monotonic() - DONDE["pulsado"] > 3:  # mantener pulsado o repetir no cuenta dos veces
                    DONDE["pulsado"] = time.monotonic()
                    print(f"📺 botón del mando: {await interfaz_salon(tapar=False)}")
            await p.wait()
        except Exception as ex:
            print(f"📺 Fire TV, botón: {ex}")
        await asyncio.sleep(15)  # stick apagado o sin red: reintenta


async def vigilar():
    acciones.tarea(_boton())
    while True:
        try:
            await _blindar()
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
    if accion in ("interfaz_tele", "volver_a_delta"):
        return await interfaz_salon()
    if accion == "interfaz_portatil":
        return await interfaz_portatil()
    if accion == "abrir":
        n = app.strip().lower()
        n = ALIAS.get(n, n)
        if n not in APPS:
            return f"No sé abrir «{app}» en la tele. Tengo: {', '.join(APPS)}."
        await _adb("input keyevent 224")  # si estaba en reposo, la despierta
        rc, out = await _adb(f"monkey -p {APPS[n]} -c android.intent.category.LEANBACK_LAUNCHER 1")
        return f"Abro {n} en la tele del salón." if rc == 0 and "No activities" not in out else f"No pude abrir {n}: {out[-200:]}"
    if accion not in TECLAS:
        return f"Acción no válida: estado | abrir | interfaz_tele | interfaz_portatil | volver_a_delta | {' | '.join(TECLAS)}"
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
        "interfaz_tele: tu interfaz (el panel de DeltaOS) a la tele del salón («pasa la interfaz a la tele», «me voy al "
        "salón»). interfaz_portatil: vuelve al portátil («pásala al portátil», «me vuelvo a la habitación»). "
        "volver_a_delta: tras Netflix u otra app, el panel otra vez en la tele («vuelve a Delta», «quita Netflix»). "
        "Teclas: pausa/seguir (la misma), atras, inicio, arriba/abajo/izquierda/derecha, ok, adelantar, retroceder, "
        "siguiente, anterior, subir_volumen/bajar_volumen, silenciar, menu, apagar, encender.",
        {"accion": _s("estado | abrir | interfaz_tele | interfaz_portatil | volver_a_delta | " + " | ".join(TECLAS)),
         "app": _s("abrir: " + ", ".join(APPS)),
         "veces": _s("teclas: cuántas veces pulsarla (p. ej. 5 para bajar el volumen 5 puntos), por defecto 1")},
        req=["accion"]),
], [tele_salon])
acciones.ETIQUETAS.update(tele_salon="Tele del salón")
