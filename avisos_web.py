"""Avisos al móvil como notificación del navegador (Web Push), sin depender de que KDE Connect esté conectado.
La web /movil se suscribe (service worker panel/sw.js) y Delta le manda el aviso por el servicio push del navegador,
cifrado de punta a punta; llega aunque la web esté cerrada. Las suscripciones y la clave privada quedan en este
equipo (gitignored)."""
import asyncio
import base64
import json
import time

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid
from pywebpush import WebPushException, webpush

import acciones

CLAVE = acciones.AQUI / "vapid_privada.pem"          # *.pem está en .gitignore
SUSCR = acciones.AQUI / "push_suscripciones.json"    # gitignored: cada endpoint es una llave para avisar a ese móvil
TTL = 6 * 3600  # un aviso que no llega en 6 h ya no sirve: el servicio push lo tira

_V = None


def _vapid():
    global _V
    if _V is None:
        _V = Vapid()
        if CLAVE.exists():
            _V = Vapid.from_file(str(CLAVE))
        else:
            _V.generate_keys()
            _V.save_key(str(CLAVE))
            CLAVE.chmod(0o600)
    return _V


def clave_publica():
    """applicationServerKey que necesita el navegador para suscribirse (base64url del punto sin comprimir)."""
    raw = _vapid().public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _leer():
    try:
        return json.loads(SUSCR.read_text())
    except (OSError, ValueError):
        return []


def _guardar(lista):
    SUSCR.write_text(json.dumps(lista))
    SUSCR.chmod(0o600)


def suscribir(sub):
    """Guarda (o actualiza) la suscripción que manda el móvil; False si no tiene la forma de una."""
    k = sub.get("keys") if isinstance(sub, dict) else None
    if not (isinstance(k, dict) and isinstance(sub.get("endpoint"), str) and sub["endpoint"].startswith("https://")
            and isinstance(k.get("p256dh"), str) and isinstance(k.get("auth"), str)):
        return False
    lista = [s for s in _leer() if s["endpoint"] != sub["endpoint"]]
    lista.append({"endpoint": sub["endpoint"], "keys": {"p256dh": k["p256dh"], "auth": k["auth"]}})
    _guardar(lista)
    return True


def cuantas():
    return len(_leer())


def _enviar(sub, carga):
    webpush(subscription_info=sub, data=carga, vapid_private_key=str(CLAVE), ttl=TTL,
            vapid_claims={"sub": "mailto:delta@example.com"}, headers={"Urgency": "high"})


async def push(texto, titulo="Delta"):
    """Notificación en el móvil. Devuelve cuántos móviles la recibieron; las suscripciones caducadas se borran."""
    lista = _leer()
    if not lista:
        print(f"📱 aviso sin móvil suscrito, perdido: {texto}")
        return 0
    _vapid()
    carga = json.dumps({"titulo": titulo, "texto": texto[:200], "t": int(time.time())}, ensure_ascii=False)
    vivas, ok = [], 0
    for s in lista:
        try:
            await asyncio.to_thread(_enviar, s, carga)
            vivas.append(s)
            ok += 1
        except WebPushException as e:
            if e.response is not None and e.response.status_code in (404, 410):
                print("📱 suscripción caducada: se borra")  # el móvil la anuló: no vale para más avisos
            else:
                vivas.append(s)
                print(f"📱 el aviso no llegó: {e}")
        except Exception as e:
            vivas.append(s)
            print(f"📱 aviso al móvil: {e}")
    if len(vivas) != len(lista):
        _guardar(vivas)
    return ok


acciones.PUSH_MOVIL = push
