"""El móvil por KDE Connect: leer notificaciones, responder (WhatsApp y demás con respuesta rápida),
mandar SMS a un número, hacerlo sonar y enviar imágenes o capturas de pantalla. Responder y SMS los confirma el usuario de viva voz (Delta pregunta antes)."""
import os
from pathlib import Path
import re
import time

import acciones
from acciones import _fn, _run, _s, _confirmar

KDC = "org.kde.kdeconnect"
NOMBRE = "Reno14 5G"   # si cambia de móvil: nombre tal como sale en kdeconnect-cli -l
_NOTIF = "org.kde.kdeconnect.device.notifications"

# Del móvil solo importan WhatsApp y los avisos del sistema (batería baja…); correos y demás ni se enseñan ni se leen.
# Comparación por trozos del nombre de la app, sin mayúsculas ni acentos.
PERMITIDAS = ("whatsapp", "android", "sistema", "system", "bater", "battery", "kde connect")

EXTS_IMAGEN = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".bmp", ".avif"}
CARPETAS_IMAGEN = [
    Path.home() / "Imágenes" / "Capturas de pantalla",
    Path.home() / "Imágenes",
    Path.home() / "Descargas",
    Path.home() / "Escritorio",
    Path(__file__).resolve().parent / "capturas",
    Path.home() / "Documentos" / "Delta",
]


async def _movil():
    """id del móvil si está accesible, o None."""
    rc, out = await _run(["kdeconnect-cli", "-a", "--id-name-only"], timeout=10)
    for l in out.splitlines():
        id_, _, nombre = l.partition(" ")
        if nombre.strip() == NOMBRE:
            return id_
    return None


def permitida(n):
    app = f"{n.get('appName', '')}".lower().replace("í", "i").replace("é", "e")
    return any(k in app for k in PERMITIDAS)


async def push(texto):
    """Notificación en el móvil (un «ping» de KDE Connect con mensaje). Si no está a mano, se pierde: no se encola."""
    try:
        d = await _movil()
        if not d:
            print(f"📱 sin móvil a mano, aviso perdido: {texto}")
            return False
        rc, out = await _run(["kdeconnect-cli", "-d", d, "--ping-msg", texto[:200]], timeout=10)
        if rc != 0:
            print(f"📱 el aviso no llegó: {out}")
        return rc == 0
    except Exception as e:
        print(f"📱 aviso al móvil: {e}")
        return False


async def _notificaciones(d):
    ruta = f"/modules/kdeconnect/devices/{d}/notifications"
    _, ids = await _run(["qdbus-qt6", KDC, ruta, f"{_NOTIF}.activeNotifications"], timeout=10)
    lista = []
    for nid in ids.split():
        _, props = await _run(["qdbus-qt6", KDC, f"{ruta}/{nid}", "org.freedesktop.DBus.Properties.GetAll",
                               f"{_NOTIF}.notification"], timeout=10)
        n = dict(re.findall(r"^(\w+): (.*)$", props, re.M))
        if n.get("silent") != "true" and (n.get("title") or n.get("text")) and permitida(n):
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


async def _resolver_imagen(ref=""):
    """Resuelve la ruta de una imagen o toma una captura de pantalla si se solicita o viene vacío."""
    ref = str(ref or "").strip()
    # 1. Si está vacío o pide captura / pantalla actual
    if not ref or ref.lower() in ("captura", "pantalla", "monitor", "actual", "screenshot", "ahora", "captura de pantalla"):
        ahora = time.strftime("%Y%m%d_%H%M%S")
        dest_dir = Path.home() / "Imágenes" / "Capturas de pantalla"
        dest_dir.mkdir(parents=True, exist_ok=True)
        captura_path = dest_dir / f"Captura_Delta_{ahora}.png"
        rc, out = await _run(["spectacle", "-b", "-n", "-m", "-o", str(captura_path)], timeout=10)
        if rc != 0 or not captura_path.is_file():
            captura_path = Path(f"/tmp/captura_delta_{ahora}.png")
            rc, out = await _run(["spectacle", "-b", "-n", "-m", "-o", str(captura_path)], timeout=10)
            if rc != 0 or not captura_path.is_file():
                return None, f"Error al tomar captura de pantalla con spectacle: {out}"
        return captura_path, None

    # 2. Si pide la última imagen / foto tomada
    if ref.lower() in ("ultima", "última", "reciente", "la ultima", "la última", "ultima foto", "última foto",
                       "ultima captura", "última captura", "ultima imagen", "última imagen"):
        candidatos = []
        for carp in CARPETAS_IMAGEN:
            if carp.is_dir():
                try:
                    for f in carp.iterdir():
                        if f.is_file() and f.suffix.lower() in EXTS_IMAGEN:
                            candidatos.append(f)
                except Exception:
                    pass
        if not candidatos:
            return None, "No he encontrado ninguna imagen reciente en las carpetas de usuario."
        candidatos.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return candidatos[0], None

    # 3. Si es una ruta directa
    p_directa = Path(ref).expanduser()
    if p_directa.is_file():
        return p_directa, None

    # 4. Búsqueda por nombre en las carpetas habituales
    ref_clean = ref.lower().strip()
    # Coincidencia exacta de nombre o stem
    for carp in CARPETAS_IMAGEN:
        if carp.is_dir():
            try:
                for f in carp.iterdir():
                    if f.is_file() and f.suffix.lower() in EXTS_IMAGEN:
                        if f.name.lower() == ref_clean or f.stem.lower() == ref_clean:
                            return f, None
            except Exception:
                pass
    # Coincidencia por subcadena
    for carp in CARPETAS_IMAGEN:
        if carp.is_dir():
            try:
                for f in carp.iterdir():
                    if f.is_file() and f.suffix.lower() in EXTS_IMAGEN:
                        if ref_clean in f.name.lower():
                            return f, None
            except Exception:
                pass

    return None, f"No encuentro ninguna imagen que coincida con «{ref}»."


async def enviar_imagen_movil(ruta=""):
    """Envía una imagen, foto o captura de pantalla al móvil mediante KDE Connect."""
    d = await _movil()
    if not d:
        return f"El móvil ({NOMBRE}) no está conectado a KDE Connect (¿wifi apagada o lejos?)."
    img_path, err = await _resolver_imagen(ruta)
    if err:
        return err
    if not img_path or not img_path.is_file():
        return f"El archivo de imagen no existe o no es accesible: {img_path}"
    rc, out = await _run(["kdeconnect-cli", "-d", d, "--share", str(img_path)], timeout=30)
    return (f"Imagen enviada al móvil ({img_path.name}) mediante KDE Connect. Llegará a su galería o carpeta de descargas."
            if rc == 0 else f"Error al enviar la imagen al móvil: {out}")


acciones.PUSH_MOVIL = push
acciones.registrar([
    _fn("notificaciones_movil", "Lee las notificaciones del móvil del usuario (WhatsApp, Telegram, correo, llamadas…)."),
    _fn("responder_notificacion",
        "Responde a una notificación del móvil que admita respuesta (WhatsApp, Telegram…). Lee el mensaje al usuario y pregúntale de viva voz si lo mandas; no la llames hasta que diga que sí.",
        {"quien": _s("contacto o app a la que responder, tal como sale en la notificación"), "mensaje": _s("texto de la respuesta")}),
    _fn("enviar_sms", "Envía un SMS desde el móvil a un NÚMERO de teléfono. Léele el texto al usuario y pregúntale de viva voz si lo mandas; no la llames hasta que diga que sí.",
        {"numero": _s("número de teléfono"), "mensaje": _s("texto")}),
    _fn("sonar_movil", "Hace sonar el móvil a todo volumen para encontrarlo."),
    _fn("enviar_imagen_movil", "Envía una imagen, foto o captura de pantalla del monitor al móvil mediante KDE Connect.",
        {"ruta": _s("ruta o nombre de la imagen; vacío o 'captura' para capturar la pantalla actual; 'ultima' para la más reciente")}, req=[]),
], [notificaciones_movil, responder_notificacion, enviar_sms, sonar_movil, enviar_imagen_movil])
acciones.ETIQUETAS.update(notificaciones_movil="Miro el móvil", responder_notificacion="Respondo desde el móvil",
                          enviar_sms="Envío un SMS", sonar_movil="Hago sonar el móvil",
                          enviar_imagen_movil="Envío imagen al móvil")
