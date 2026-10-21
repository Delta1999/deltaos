"""El móvil por KDE Connect: leer notificaciones, responder (WhatsApp y demás con respuesta rápida),
mandar SMS a un número y hacerlo sonar. Responder y SMS los confirma el usuario de viva voz (Delta pregunta antes)."""
import re

import acciones
from acciones import _fn, _run, _s, _confirmar

KDC = "org.kde.kdeconnect"
NOMBRE = "Reno14 5G"   # si cambia de móvil: nombre tal como sale en kdeconnect-cli -l
_NOTIF = "org.kde.kdeconnect.device.notifications"


async def _movil():
    """id del móvil si está accesible, o None."""
    rc, out = await _run(["kdeconnect-cli", "-a", "--id-name-only"], timeout=10)
    for l in out.splitlines():
        id_, _, nombre = l.partition(" ")
        if nombre.strip() == NOMBRE:
            return id_
    return None


async def _notificaciones(d):
    ruta = f"/modules/kdeconnect/devices/{d}/notifications"
    _, ids = await _run(["qdbus-qt6", KDC, ruta, f"{_NOTIF}.activeNotifications"], timeout=10)
    lista = []
    for nid in ids.split():
        _, props = await _run(["qdbus-qt6", KDC, f"{ruta}/{nid}", "org.freedesktop.DBus.Properties.GetAll",
                               f"{_NOTIF}.notification"], timeout=10)
        n = dict(re.findall(r"^(\w+): (.*)$", props, re.M))
        if n.get("silent") != "true" and (n.get("title") or n.get("text")):
            lista.append(n)
    return lista


async def notificaciones_movil():
    d = await _movil()
    if not d:
        return f"El móvil ({NOMBRE}) no está conectado a KDE Connect (¿wifi apagada o lejos?)."
    lista = await _notificaciones(d)
    if not lista:
        return "No hay notificaciones en el móvil."
    return "\n".join(f"- [{n.get('appName')}] {n.get('title', '')}: {n.get('text', '')[:200]}"
                     f"{' (se puede responder)' if n.get('replyId') else ''}" for n in lista)


async def responder_notificacion(quien, mensaje):
    d = await _movil()
    if not d:
        return "El móvil no está conectado."
    q = quien.lower()
    n = next((n for n in await _notificaciones(d) if n.get("replyId")
              and q in f"{n.get('appName', '')} {n.get('title', '')}".lower()), None)
    if not n:
        return f"No hay ninguna notificación que se pueda responder de «{quien}»."
    if not await _confirmar(f"responder por {n.get('appName')} a «{n.get('title')}»: «{mensaje}»", voz=True):
        return "El usuario no lo ha confirmado: no enviado."
    rc, out = await _run(["qdbus-qt6", KDC, f"/modules/kdeconnect/devices/{d}/notifications",
                          f"{_NOTIF}.sendReply", n["replyId"], mensaje], timeout=15)
    return f"Respondido a {n.get('title')}." if rc == 0 else f"Error al responder: {out}"


async def enviar_sms(numero, mensaje):
    num = re.sub(r"[\s.-]", "", numero)
    if not re.fullmatch(r"\+?\d{6,15}", num):
        return "Necesito el número de teléfono (los contactos del móvil no están sincronizados)."
    d = await _movil()
    if not d:
        return "El móvil no está conectado."
    if not await _confirmar(f"enviar SMS a {num}: «{mensaje}»", voz=True):
        return "El usuario no lo ha confirmado: no enviado."
    rc, out = await _run(["kdeconnect-cli", "-d", d, "--send-sms", mensaje, "--destination", num], timeout=15)
    return f"SMS enviado a {num}." if rc == 0 else f"Error: {out}"


async def sonar_movil():
    d = await _movil()
    if not d:
        return "El móvil no está conectado: no puedo hacerlo sonar."
    rc, out = await _run(["kdeconnect-cli", "-d", d, "--ring"], timeout=10)
    return "El móvil está sonando." if rc == 0 else f"Error: {out}"


acciones.registrar([
    _fn("notificaciones_movil", "Lee las notificaciones del móvil del usuario (WhatsApp, Telegram, correo, llamadas…)."),
    _fn("responder_notificacion",
        "Responde a una notificación del móvil que admita respuesta (WhatsApp, Telegram…). Lee el mensaje al usuario y pregúntale de viva voz si lo mandas; no la llames hasta que diga que sí.",
        {"quien": _s("contacto o app a la que responder, tal como sale en la notificación"), "mensaje": _s("texto de la respuesta")}),
    _fn("enviar_sms", "Envía un SMS desde el móvil a un NÚMERO de teléfono. Léele el texto al usuario y pregúntale de viva voz si lo mandas; no la llames hasta que diga que sí.",
        {"numero": _s("número de teléfono"), "mensaje": _s("texto")}),
    _fn("sonar_movil", "Hace sonar el móvil a todo volumen para encontrarlo."),
], [notificaciones_movil, responder_notificacion, enviar_sms, sonar_movil])
acciones.ETIQUETAS.update(notificaciones_movil="Miro el móvil", responder_notificacion="Respondo desde el móvil",
                          enviar_sms="Envío un SMS", sonar_movil="Hago sonar el móvil")
