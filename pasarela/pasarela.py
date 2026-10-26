"""Pasarela de Delta: corre en la caja de la impresora (siempre encendida), no en el portátil.
Sirve por tailscale serve la página «PC apagado» y, en cuanto el portátil responde, manda al móvil a la web de Delta.
Solo biblioteca estándar. No guarda nada ni manda ninguna orden: solo comprueba si el PC contesta."""
import json
import os
import socket
import ssl
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PC_IP = os.environ.get("PC_IP", "100.108.136.98")  # IP del portátil en la tailnet (no uso MagicDNS: la caja no lo acepta)
PC_HOST = os.environ.get("PC_HOST", "fedora.tail630f35.ts.net")
PUERTO = int(os.environ.get("PUERTO", "7890"))
AQUI = os.path.dirname(os.path.abspath(__file__))
TIPOS = {".html": "text/html; charset=utf-8", ".png": "image/png", ".webmanifest": "application/manifest+json"}
CACHE = {"t": 0.0, "estado": "apagado"}


def estado_de(codigo):
    """Código HTTP de /movil en el PC -> estado. 502/503/504 los pone tailscale serve cuando Delta no corre."""
    if codigo is None:
        return "apagado"
    return "delta_parado" if codigo in (502, 503, 504) else "encendido"


def comprobar():
    try:
        with socket.create_connection((PC_IP, 443), timeout=3) as s:
            with ssl.create_default_context().wrap_socket(s, server_hostname=PC_HOST) as t:
                t.settimeout(4)
                t.sendall(f"GET /movil HTTP/1.1\r\nHost: {PC_HOST}\r\nConnection: close\r\n\r\n".encode())
                codigo = int(t.recv(64).split(b"\r\n")[0].split()[1])
    except (OSError, ValueError, IndexError):
        codigo = None
    return estado_de(codigo)


def estado():
    if time.time() - CACHE["t"] > 3:  # varios móviles/pestañas a la vez no multiplican las comprobaciones
        CACHE["estado"], CACHE["t"] = comprobar(), time.time()
    return CACHE["estado"]


class Manejador(BaseHTTPRequestHandler):
    def _enviar(self, cuerpo, tipo):
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):
        ruta = self.path.split("?")[0]
        if ruta == "/estado":
            return self._enviar(json.dumps({"estado": estado(), "destino": f"https://{PC_HOST}/movil"}).encode(), "application/json")
        archivo = {"/": "index.html", "/manifest.webmanifest": "manifest.webmanifest"}.get(ruta, ruta.lstrip("/"))
        # solo index, manifest e iconos de esta carpeta; nada de subir niveles
        if ruta not in ("/", "/manifest.webmanifest") and not (ruta.startswith("/iconos/") and ".." not in ruta):
            return self.send_error(404)
        try:
            with open(os.path.join(AQUI, archivo), "rb") as f:
                self._enviar(f.read(), TIPOS.get(os.path.splitext(archivo)[1], "application/octet-stream"))
        except OSError:
            self.send_error(404)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PUERTO), Manejador).serve_forever()
