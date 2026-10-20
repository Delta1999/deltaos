"""La tele en directo: canales, cabeceras y qué stream se elige (.venv/bin/python test_tele.py)

Sin red: la parte que se equivoca no es la petición, es el filtro. Con `--red` sí la pide de verdad.
"""
import asyncio
import sys

import assistant  # noqa: F401  (registra y fusiona, igual que al arrancar)
import acciones
import tele

# ---------- canales ----------
assert tele.CANALES["cuatro"] == ("cuatro", "https://www.cuatro.com")
# El dominio no es decorativo: el CDN mira Origin y Referer, y sin ellos contesta 403 (probado).
c = tele.cabeceras("https://www.cuatro.com")
assert c["Origin"] == "https://www.cuatro.com" and c["Referer"] == "https://www.cuatro.com/", c
assert "Chrome" in c["User-Agent"], "con el User-Agent de mpv a secas, 403"

# ---------- qué stream se elige ----------
FALSO = {
    "https://caronte": {"cerbero": "https://cerbero", "bbx": "BBX",
                        "dls": [{"format": "hls", "drm": True, "stream": "https://no/drm", "lid": 1,
                                 "quality": "hd", "cdn": "akamai"},
                                {"format": "hls", "lgs": "x", "stream": "https://no/lgs", "lid": 2,
                                 "quality": "hd", "cdn": "akamai"},
                                {"format": "dash", "stream": "https://no/dash", "lid": 3,
                                 "quality": "hd", "cdn": "akamai"},
                                {"format": "hls", "stream": "https://si/sd", "lid": 4,
                                 "quality": "sd", "cdn": "akamai", "adtype": "csai"},
                                {"format": "hls", "stream": "https://si/hd", "lid": 5,
                                 "quality": "hd", "cdn": "akamai"}]},
    "https://mab": {"gbx": "GBX"},
    "https://cerbero": {"tokens": {str(i): {"cdn": f"t{i}"} for i in range(1, 6)}},
}
pedidas = []


def _falso(url, data=None, web=""):
    pedidas.append((url, data, web))
    for clave, val in FALSO.items():
        if url.startswith(clave):
            return val
    raise AssertionError(f"petición inesperada: {url}")


tele._http = _falso
tele.CANALES["prueba"] = ("prueba", "https://www.cuatro.com")
try:
    url, cab = tele.directo("prueba")
    # DRM, lgs y lo que no es hls, fuera: queda lo que sirve la web en abierto. Y el HD primero.
    assert url == "https://si/hd?t5", url
    assert tele.directo("prueba", hd=False)[0] == "https://si/sd?t4", "en sd, el que lleva anuncios"
    assert cab["Origin"] == "https://www.cuatro.com", cab
    assert pedidas[2][1] == {"bbx": "BBX", "gbx": "GBX"}, "cerbero necesita las dos cajas"
    # Sin token no vale decir «ya está»: suele ser que no hay IP española.
    FALSO["https://cerbero"] = {"tokens": {}}
    try:
        tele.directo("prueba")
        raise AssertionError("sin token tenía que quejarse")
    except RuntimeError as e:
        assert "española" in str(e), e
finally:
    del tele.CANALES["prueba"]

try:
    tele.directo("canal plus")
    raise AssertionError("un canal que no existe tenía que quejarse")
except ValueError as e:
    assert "cuatro" in str(e), "y decir cuáles tiene"

# ---------- la puerta por la que entra ----------
# Acción dentro de la fusión «musica», no herramienta nueva: el presupuesto de herramientas manda.
assert "tele" in acciones.FUSIONES["musica"][2], acciones.FUSIONES["musica"][2].keys()
assert "poner_tele" not in acciones.DECLARATIONS, "la plana se absorbe al fusionar"
real, args = acciones._real("musica", {"accion": "tele", "canal": "canal plus"})
assert (real, args) == ("poner_tele", {"canal": "canal plus"}), (real, args)
assert asyncio.run(acciones.HANDLERS[real](**args)).startswith("Error")

# Es el mismo mpv que la música, a propósito: así «para», «pausa» y «sube» siguen valiendo.
assert "MPV_SOCK" in dir(acciones) and acciones.MPV_SOCK == "/tmp/delta-mpv.sock"

if "--red" in sys.argv:  # pide el directo de verdad (hace falta IP española)
    import importlib
    importlib.reload(tele)
    u, h = tele.directo("cuatro")
    assert u.startswith("https://") and "?" in u, u
    import urllib.request
    r = urllib.request.urlopen(urllib.request.Request(u, headers=h), timeout=15)
    assert r.status == 200, r.status
    print("con red: Cuatro responde 200")

print("OK: la tele elige el stream en abierto, en HD, y entra por la fusión «musica»")
