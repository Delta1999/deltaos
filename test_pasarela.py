"""Comprobación de la pasarela: el estado del PC que ve el móvil según lo que conteste /movil."""
import sys

sys.path.insert(0, "pasarela")
from pasarela import estado_de  # noqa: E402

assert estado_de(None) == "apagado"       # sin conexión: portátil apagado
assert estado_de(502) == "delta_parado"   # tailscale serve sin Delta detrás
assert estado_de(200) == "encendido"
assert estado_de(403) == "encendido"      # contesta, aunque no nos deje pasar: el PC está encendido
print("ok")
