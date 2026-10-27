"""Pasarela de Delta: corre en la caja de la impresora (siempre encendida), no en el portátil.
Sirve por tailscale serve la página «PC apagado» y, en cuanto el portátil responde, manda al móvil a la web de Delta.
Además sirve /camara: la imagen de la GoPro y el estado de la impresora para vigilar una impresión desde fuera de casa
con el portátil apagado. Solo la cuenta dueña de la tailnet (cabecera Tailscale-User-Login); sin DUENO configurado no
deja pasar a nadie. La impresora es SOLO LECTURA (únicamente GET a Moonraker) y de la cámara solo se reenvía el flujo.
Solo biblioteca estándar. No guarda nada ni manda ninguna orden: solo comprueba si el PC contesta."""
import json
import os
import re
import socket
import ssl
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PC_IP = os.environ.get("PC_IP", "100.108.136.98")  # IP del portátil en la tailnet (no uso MagicDNS: la caja no lo acepta)
PC_HOST = os.environ.get("PC_HOST", "fedora.tail630f35.ts.net")
PUERTO = int(os.environ.get("PUERTO", "7890"))
AQUI = os.path.dirname(os.path.abspath(__file__))
TIPOS = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".png": "image/png", ".webmanifest": "application/manifest+json"}
CACHE = {"t": 0.0, "estado": "apagado"}
DUENO = os.environ.get("DUENO")  # login de Tailscale del dueño, en /etc/delta-pasarela.env (nunca en el repo)
CAMARA = os.environ.get("CAMARA", "10.5.5.9:8080")  # flujo HLS de la GoPro, por el WiFi USB de la caja
MOONRAKER = os.environ.get("MOONRAKER", "127.0.0.1:7125")
PARTE = re.compile(r"^(amba\.m3u8|\d+\.ts)$")  # la lista y los trozos que numera esta pasarela; nada más de la cámara sale
MEMORIA = 30  # trozos de ~0,27 s que se guardan: unos 8 s de colchón para el móvil
TIPOS_HLS = {"m3u8": "application/vnd.apple.mpegurl", "ts": "video/mp2t"}
CACHE_CAMARA = {"t": 0.0, "datos": None}


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


def resumen_impresora(st):
    """Respuesta de Moonraker (objects/query -> status) -> lo que pinta la página de la cámara."""
    ps, ex, cama = st["print_stats"], st["extruder"], st["heater_bed"]
    progreso = st["virtual_sdcard"]["progress"] or 0
    hecho = ps["print_duration"] or 0
    capas = ps.get("info") or {}
    return {
        "estado": ps["state"], "archivo": ps["filename"] or "", "progreso": progreso, "transcurrido": hecho,
        "restante": hecho * (1 - progreso) / progreso if progreso > 0.01 else None,
        "boquilla": [round(ex["temperature"]), round(ex["target"])], "cama": [round(cama["temperature"]), round(cama["target"])],
        "capa": [capas["current_layer"], capas["total_layer"]] if capas.get("current_layer") and capas.get("total_layer") else None,
    }


def trozos_de(lista):
    """Lista HLS de la GoPro -> [(secuencia, duración, nombre)]. Ella solo guarda 7 trozos de 0,27 s y reutiliza los
    nombres (amba_hls-0..15.ts, en anillo): el único dato fiable de cuáles son nuevos es #EXT-X-MEDIA-SEQUENCE."""
    sec = int(lista.split("#EXT-X-MEDIA-SEQUENCE:")[1].split()[0])
    salida, dur = [], None
    for linea in lista.splitlines():
        if linea.startswith("#EXTINF:"):
            dur = float(linea[8:].rstrip(",").split(",")[0])
        elif linea and not linea.startswith("#") and dur is not None:
            salida.append((sec + len(salida), dur, linea.strip()))
            dur = None
    return salida


def _crc_mpeg(datos):
    crc = 0xFFFFFFFF
    for b in datos:
        crc ^= b << 24
        for _ in range(8):
            crc = ((crc << 1) ^ 0x04C11DB7 if crc & 0x80000000 else crc << 1) & 0xFFFFFFFF
    return crc


def arreglar_pat(datos):
    """La GoPro anuncia en su PAT un «programa 0» (la red, PID 0x1F) además del programa de vídeo, y hls.js toma el
    primero como si fuera el PMT: no encuentra ni vídeo ni audio. Se quita esa entrada y se recalcula el CRC."""
    fuera = bytearray(datos)
    for i in range(0, len(fuera) - 187, 188):
        pq = fuera[i:i + 188]
        if pq[0] != 0x47 or (((pq[1] & 0x1F) << 8) | pq[2]) != 0 or not pq[1] & 0x40:
            continue
        ini = 5 + pq[4]   # tras el puntero
        largo = ((pq[ini + 1] & 0x0F) << 8) | pq[ini + 2]
        cuerpo = bytes(pq[ini + 3:ini + 3 + largo - 4])   # sin CRC
        entradas = [cuerpo[k:k + 4] for k in range(5, len(cuerpo), 4)]
        buenas = b"".join(e for e in entradas if e[:2] != b"\x00\x00")
        if len(buenas) == len(cuerpo) - 5:
            continue
        nuevo = cuerpo[:5] + buenas
        sec = bytes([0, 0xB0 | ((len(nuevo) + 4) >> 8), (len(nuevo) + 4) & 0xFF]) + nuevo
        sec += _crc_mpeg(sec).to_bytes(4, "big")
        fuera[i + ini:i + 188] = (sec + b"\xff" * 188)[:188 - ini]
    return bytes(fuera)


def lista_hls(trozos):
    """trozos: [(n, duración, hay_corte)] ya numerados -> lista HLS en directo con los trozos que guardamos."""
    if not trozos:
        return None
    cab = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-TARGETDURATION:1", f"#EXT-X-MEDIA-SEQUENCE:{trozos[0][0]}"]
    for n, dur, corte in trozos:
        cab += (["#EXT-X-DISCONTINUITY"] if corte else []) + [f"#EXTINF:{dur:.5f},", f"{n}.ts"]
    return "\n".join(cab) + "\n"


class Flujo:
    """Copia viva de lo que emite la GoPro: un hilo la lee de la cámara (por el WiFi de la caja, rápido) y guarda los
    últimos trozos con números propios que solo suben. Los móviles piden a esta copia, no a la cámara, que es lenta.
    Solo corre mientras alguien mira (pedir() lo reinicia): sin espectadores no se toca la cámara."""

    def __init__(self):
        self.trozos, self.siguiente, self.visto = {}, 0, 0.0   # n -> (duración, datos, hay_corte)
        self.cerrojo, self.hilo = threading.Lock(), None

    def pedir(self):
        self.visto = time.time()
        with self.cerrojo:
            if self.hilo is None or not self.hilo.is_alive():
                self.hilo = threading.Thread(target=self._bucle, daemon=True)
                self.hilo.start()

    def lista(self):
        with self.cerrojo:
            return lista_hls([(n, d, c) for n, (d, _, c) in sorted(self.trozos.items())])

    def trozo(self, n):
        with self.cerrojo:
            return self.trozos.get(n, (None, None))[1]

    def _guardar(self, dur, datos, corte):
        with self.cerrojo:
            self.trozos[self.siguiente] = (dur, datos, corte)
            self.siguiente += 1
            for n in sorted(self.trozos)[:-MEMORIA]:
                del self.trozos[n]

    def _bucle(self):
        ultima, corte = None, True   # última secuencia de la cámara que copié; el primer trozo empieza sin historia
        while time.time() - self.visto < 20:
            try:
                lista = urllib.request.urlopen(f"http://{CAMARA}/live/amba.m3u8", timeout=3).read().decode()
                actuales = trozos_de(lista)
                if ultima is not None and actuales and actuales[-1][0] < ultima:
                    ultima, corte = None, True   # la secuencia ha retrocedido: la cámara reinició la vista previa
                for sec, dur, nombre in actuales:
                    if ultima is not None and sec <= ultima:
                        continue
                    datos = urllib.request.urlopen(f"http://{CAMARA}/live/{nombre}", timeout=4).read()
                    corte = corte or (ultima is not None and sec > ultima + 1)   # se me escapó alguno: corte en la lista
                    self._guardar(dur, arreglar_pat(datos), corte)
                    corte, ultima = False, sec
                time.sleep(0.3)
            except (OSError, ValueError, IndexError):   # cámara sin contestar: se vuelve a intentar sin hacer ruido
                corte = True
                time.sleep(1)
        with self.cerrojo:
            self.trozos.clear()   # sin espectadores no guardo imágenes


FLUJO = Flujo()


def _impresora():
    try:
        url = f"http://{MOONRAKER}/printer/objects/query?print_stats&virtual_sdcard&extruder&heater_bed"
        return resumen_impresora(json.load(urllib.request.urlopen(url, timeout=3))["result"]["status"])
    except Exception:  # Klipper parado o Moonraker sin contestar: la página solo oculta el bloque
        return None


def _hay_imagen():
    try:
        urllib.request.urlopen(f"http://{CAMARA}/live/amba.m3u8", timeout=3).read(64)
        return True
    except OSError:
        return False


def estado_camara():
    if time.time() - CACHE_CAMARA["t"] > 3:
        with ThreadPoolExecutor(2) as pool:
            cam, imp = pool.submit(_hay_imagen), pool.submit(_impresora)
            CACHE_CAMARA["datos"] = {"camara": cam.result(), "impresora": imp.result()}
        CACHE_CAMARA["t"] = time.time()
    return CACHE_CAMARA["datos"]


class Manejador(BaseHTTPRequestHandler):
    def _enviar(self, cuerpo, tipo):
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(cuerpo)

    def _camara(self, ruta):
        if not DUENO or self.headers.get("Tailscale-User-Login") != DUENO:
            return self.send_error(403)
        if ruta == "/camara/estado":
            return self._enviar(json.dumps(estado_camara()).encode(), "application/json")
        if ruta in ("/camara", "/camara/hls.js"):  # hls.js (Apache-2.0, ver hls.LICENSE): Chrome no reproduce HLS con TS él solo
            archivo = "camara.html" if ruta == "/camara" else "hls.light.min.js"
            with open(os.path.join(AQUI, archivo), "rb") as f:
                return self._enviar(f.read(), TIPOS[os.path.splitext(archivo)[1]])
        parte = PARTE.match(ruta[len("/camara/live/"):]) if ruta.startswith("/camara/live/") else None
        if not parte:
            return self.send_error(404)
        FLUJO.pedir()
        nombre = parte.group(1)
        if nombre == "amba.m3u8":
            for _ in range(20):   # el hilo acaba de arrancar: unos segundos para tener colchón
                lista = FLUJO.lista()
                if lista and len(FLUJO.trozos) >= 8:
                    return self._enviar(lista.encode(), TIPOS_HLS["m3u8"])
                time.sleep(0.25)
            return self.send_error(503)
        datos = FLUJO.trozo(int(nombre[:-3]))
        if datos is None:
            return self.send_error(404)
        self._enviar(datos, TIPOS_HLS["ts"])

    def do_GET(self):
        ruta = self.path.split("?")[0]
        if ruta.startswith("/camara"):
            return self._camara(ruta)
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


class Servidor(ThreadingHTTPServer):
    def handle_error(self, request, client_address):  # un móvil que se va a media imagen no es un fallo
        if not isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            super().handle_error(request, client_address)


if __name__ == "__main__":
    Servidor(("127.0.0.1", PUERTO), Manejador).serve_forever()
