"""Web Push (RFC 8030/8291/8292) para Delta móvil, solo con `cryptography` (ya en el venv; sin dependencias nuevas).

Las notificaciones viajan cifradas de extremo a extremo: el servicio de push de Chrome (FCM) no ve el texto.
"""
import base64
import json
import os
import struct
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

AQUI = Path(__file__).parent
CLAVE_F = AQUI / "movil_vapid.pem"
SUSCR_F = AQUI / "movil_suscripciones.json"
SUB = "mailto:delta@localhost"  # contacto VAPID; FCM no lo comprueba
TTL = 12 * 3600                 # s que el push espera si el móvil está sin red


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _privada():
    if not CLAVE_F.exists():
        k = ec.generate_private_key(ec.SECP256R1())
        CLAVE_F.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                            serialization.NoEncryption()))
        CLAVE_F.chmod(0o600)
    return serialization.load_pem_private_key(CLAVE_F.read_bytes(), None)


_K = _privada()
_RAW = lambda pub: pub.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
PUBLICA = _b64(_RAW(_K.public_key()))  # applicationServerKey del navegador


def suscripciones():
    try:
        return json.loads(SUSCR_F.read_text())
    except (OSError, ValueError):
        return []


def _guardar(lista):
    SUSCR_F.write_text(json.dumps(lista))
    SUSCR_F.chmod(0o600)


def suscribir(s):
    """s = PushSubscription.toJSON() del navegador. Sustituye la del mismo endpoint."""
    nueva = {"endpoint": str(s["endpoint"]), "keys": {"p256dh": str(s["keys"]["p256dh"]), "auth": str(s["keys"]["auth"])}}
    if urlparse(nueva["endpoint"]).scheme != "https":
        raise ValueError("endpoint no https")
    _guardar([x for x in suscripciones() if x["endpoint"] != nueva["endpoint"]] + [nueva])


def _hkdf(salt, ikm, info, n):
    return HKDF(hashes.SHA256(), n, salt, info).derive(ikm)


def cifrar(texto: bytes, p256dh: str, auth: str) -> bytes:
    """Cuerpo aes128gcm de RFC 8291 (un solo registro)."""
    ua = _unb64(p256dh)
    efimera = ec.generate_private_key(ec.SECP256R1())
    as_pub = _RAW(efimera.public_key())
    secreto = efimera.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua))
    ikm = _hkdf(_unb64(auth), secreto, b"WebPush: info\0" + ua + as_pub, 32)
    sal = os.urandom(16)
    cek = _hkdf(sal, ikm, b"Content-Encoding: aes128gcm\0", 16)
    nonce = _hkdf(sal, ikm, b"Content-Encoding: nonce\0", 12)
    cifrado = AESGCM(cek).encrypt(nonce, texto + b"\x02", None)
    return sal + struct.pack(">IB", 4096, len(as_pub)) + as_pub + cifrado


def _vapid(endpoint):
    u = urlparse(endpoint)
    cab = _b64(json.dumps({"typ": "JWT", "alg": "ES256"}).encode())
    datos = _b64(json.dumps({"aud": f"{u.scheme}://{u.netloc}", "exp": int(time.time()) + TTL, "sub": SUB}).encode())
    r, s = decode_dss_signature(_K.sign(f"{cab}.{datos}".encode(), ec.ECDSA(hashes.SHA256())))
    firma = _b64(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={cab}.{datos}.{firma}, k={PUBLICA}"


async def enviar(titulo, cuerpo, etiqueta="delta"):
    """Manda a todas las suscripciones; borra las caducadas (404/410). Devuelve cuántas llegaron."""
    carga = json.dumps({"titulo": titulo, "cuerpo": cuerpo, "tag": etiqueta}, ensure_ascii=False).encode()
    vivas, ok = [], 0
    async with httpx.AsyncClient(timeout=10) as c:
        for s in suscripciones():
            try:
                r = await c.post(s["endpoint"], content=cifrar(carga, s["keys"]["p256dh"], s["keys"]["auth"]), headers={
                    "Content-Encoding": "aes128gcm", "TTL": str(TTL), "Urgency": "high",
                    "Authorization": _vapid(s["endpoint"]), "Content-Type": "application/octet-stream"})
            except httpx.HTTPError as e:
                print(f"push: {e}")
                vivas.append(s)
                continue
            if r.status_code in (404, 410):
                continue  # el móvil dio de baja la suscripción
            vivas.append(s)
            ok += r.status_code < 300
            if r.status_code >= 300:
                print(f"push: {r.status_code} {r.text[:120]}")
    if len(vivas) != len(suscripciones()):
        _guardar(vivas)
    return ok


if __name__ == "__main__":  # autocomprobación del cifrado: descifra como lo haría el navegador
    ua_k = ec.generate_private_key(ec.SECP256R1())
    auth = os.urandom(16)
    cuerpo = cifrar(b"hola", _b64(_RAW(ua_k.public_key())), _b64(auth))
    sal, idlen = cuerpo[:16], cuerpo[20]
    as_pub = cuerpo[21:21 + idlen]
    secreto = ua_k.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_pub))
    ikm = _hkdf(auth, secreto, b"WebPush: info\0" + _RAW(ua_k.public_key()) + as_pub, 32)
    claro = AESGCM(_hkdf(sal, ikm, b"Content-Encoding: aes128gcm\0", 16)).decrypt(
        _hkdf(sal, ikm, b"Content-Encoding: nonce\0", 12), cuerpo[21 + idlen:], None)
    assert claro == b"hola\x02", claro
    assert _vapid("https://fcm.googleapis.com/x").startswith("vapid t=")
    print("movil_push OK")
