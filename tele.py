"""Televisión en directo de Mediaset (Cuatro, Telecinco, FDF…) sin pasar por la web.

El reproductor de cuatro.com no tiene la URL del directo a mano: pide a tres sitios un token
efímero y con él abre un HLS. Esto hace lo mismo y le pasa la URL a mpv, que es el que ya
reproduce la música, así que «para», «sube» y «pausa» siguen valiendo igual.

Se descartan los streams con DRM: no son para esto. Lo que queda es lo mismo que sirve la web
en abierto. Hace falta IP española, que es como está geobloqueado el canal.

El token dura 180 segundos (st→exp en la propia URL), así que no se guarda: se pide entera cada
vez que se pone la tele.
"""
import json
import urllib.request

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

# Los que sirve el mismo endpoint: nombre dicho → (id del canal, web de la que se dice venir).
# El dominio importa: el CDN mira Origin y Referer, y sin ellos responde 403 (probado).
CANALES = {"cuatro": ("cuatro", "https://www.cuatro.com"),
           "telecinco": ("telecinco", "https://www.telecinco.es"),
           "fdf": ("fdf", "https://www.mitele.es"),
           "energy": ("energy", "https://www.mitele.es"),
           "divinity": ("divinity", "https://www.divinity.es"),
           "be mad": ("bemad", "https://www.mitele.es"), "bemad": ("bemad", "https://www.mitele.es")}


def cabeceras(web):
    """Las que hay que repetir en cada petición, también en las de mpv."""
    return {"User-Agent": UA, "Origin": web, "Referer": web + "/"}


def _http(url, data=None, web="https://www.cuatro.com"):
    h = cabeceras(web)
    if data is not None:
        data = json.dumps(data).encode()
        h["Content-Type"] = "application/json;charset=UTF-8"
        h["Accept"] = "application/json, text/plain, */*"
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def directo(canal="cuatro", hd=True):
    """(URL del directo con su token, cabeceras que hay que repetir). Con red: llámala en un hilo."""
    par = CANALES.get(str(canal).strip().lower())
    if not par:
        raise ValueError(f"no sé poner «{canal}»; tengo {', '.join(sorted(set(CANALES)))}")
    c, web = par
    caronte = _http(f"https://caronte.mediaset.es/delivery/channel/mmc/{c}/multisite/", web=web)
    gbx = _http("https://mab.mediaset.es/1.0.0/get?oid=jero&eid=%2Fapi%2Fjero%2Fv3%2Fgbx%2Fmultisite%2F" + c, web=web)
    tokens = _http(caronte["cerbero"], {"bbx": caronte["bbx"], "gbx": gbx["gbx"]}, web=web)["tokens"]

    # sin drm ni lgs: lo de la web en abierto. hd primero, y akamai antes que el resto porque aguanta mejor
    dls = [d for d in caronte["dls"] if d.get("format") == "hls" and not d.get("drm") and not d.get("lgs")]
    dls.sort(key=lambda d: (d.get("quality") != "hd" if hd else d.get("adtype") != "csai",
                            d.get("cdn") != "akamai", d.get("lid", 99)))
    for d in dls:
        t = tokens.get(str(d["lid"]), {}).get("cdn")
        if t:
            return f'{d["stream"]}?{t}', cabeceras(web)
    raise RuntimeError("ningún stream devolvió token (¿sin IP española?)")


if __name__ == "__main__":  # python3 tele.py [canal] → imprime la URL (caduca en 3 min)
    import sys
    print(directo(sys.argv[1] if len(sys.argv) > 1 else "cuatro")[0])
