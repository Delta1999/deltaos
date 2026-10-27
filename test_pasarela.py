"""Comprobación de la pasarela: el estado del PC que ve el móvil según lo que conteste /movil."""
import sys

sys.path.insert(0, "pasarela")
from pasarela import PARTE, _crc_mpeg, arreglar_pat, estado_de, lista_hls, trozos_de, resumen_impresora  # noqa: E402

assert estado_de(None) == "apagado"       # sin conexión: portátil apagado
assert estado_de(502) == "delta_parado"   # tailscale serve sin Delta detrás
assert estado_de(200) == "encendido"
assert estado_de(403) == "encendido"      # contesta, aunque no nos deje pasar: el PC está encendido

# la cámara: solo salen la lista y los trozos del flujo, nada del resto de la GoPro
assert not PARTE.match("../etc/passwd") and not PARTE.match("amba.m3u8/../x") and not PARTE.match("DCIM/100GOPRO/x.mp4")
assert not PARTE.match("amba.ts?x=1")
assert PARTE.match("amba.m3u8") and PARTE.match("42.ts") and not PARTE.match("amba_hls-1.ts")
camara = "#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:5808\n#EXTINF:0.26693,\namba_hls-15.ts\n#EXTINF:0.26693,\namba_hls-0.ts\n"
assert trozos_de(camara) == [(5808, 0.26693, "amba_hls-15.ts"), (5809, 0.26693, "amba_hls-0.ts")]
mia = lista_hls([(7, 0.27, True), (8, 0.27, False)]).splitlines()
assert mia[3] == "#EXT-X-MEDIA-SEQUENCE:7" and mia[4:6] == ["#EXT-X-DISCONTINUITY", "#EXTINF:0.27000,"] and mia[-1] == "8.ts"
assert lista_hls([]) is None

# el PAT de la GoPro (real): sin el «programa 0», con un CRC válido (el de una sección sana da siempre 0)
pat = bytes.fromhex("00b0110000c100000000e01f0001e100235aab82")
assert _crc_mpeg(pat[:-4]) == int.from_bytes(pat[-4:], "big")   # mi CRC reproduce el de la cámara
paquete = bytes([0x47, 0x40, 0x00, 0x10, 0x00]) + pat + b"\xff" * (188 - 5 - len(pat))
arreglado = arreglar_pat(paquete * 2)
assert len(arreglado) == 376 and arreglado[:188] == arreglado[188:]
sec = arreglado[5:5 + 3 + ((arreglado[6] & 0xF) << 8 | arreglado[7])]
assert sec[8:12] == bytes.fromhex("0001e100") and len(sec) == 3 + 13 and _crc_mpeg(sec) == 0
assert arreglar_pat(arreglado) == arreglado   # ya arreglado: no se toca

# la impresora, de lo que contesta Moonraker
def moonraker(estado, progreso, hecho, capas=(None, None)):
    return {"print_stats": {"state": estado, "filename": "a.gcode", "print_duration": hecho,
                            "info": {"current_layer": capas[0], "total_layer": capas[1]}},
            "virtual_sdcard": {"progress": progreso}, "extruder": {"temperature": 209.6, "target": 210.0},
            "heater_bed": {"temperature": 59.9, "target": 60.0}}

r = resumen_impresora(moonraker("printing", 0.25, 600, (10, 40)))
assert r["estado"] == "printing" and r["restante"] == 1800 and r["capa"] == [10, 40]
assert r["boquilla"] == [210, 210] and r["cama"] == [60, 60]
assert resumen_impresora(moonraker("standby", 0, 0))["restante"] is None   # sin progreso no se inventa un tiempo
assert resumen_impresora(moonraker("complete", 1.0, 1822))["capa"] is None
print("ok")
