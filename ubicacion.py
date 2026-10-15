#!/usr/bin/python3
"""Posición por GeoClue (wifi cercanas → BeaconDB; si no, IP). Imprime «lat lon precisión_m».
Python del sistema a propósito: el .venv no tiene gi. Lo llama panel.py para el tiempo."""
import sys

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

G = "org.freedesktop.GeoClue2"
bus = Gio.bus_get_sync(Gio.BusType.SYSTEM)


def prop(ruta, iface, nombre):
    return bus.call_sync(G, ruta, "org.freedesktop.DBus.Properties", "Get", GLib.Variant("(ss)", (iface, nombre)),
                         None, 0, 5000, None).unpack()[0]


cliente = bus.call_sync(G, "/org/freedesktop/GeoClue2/Manager", f"{G}.Manager", "GetClient", None, None, 0, 5000, None).unpack()[0]
for nombre, valor in (("DesktopId", GLib.Variant("s", "delta")), ("RequestedAccuracyLevel", GLib.Variant("u", 8))):
    bus.call_sync(G, cliente, "org.freedesktop.DBus.Properties", "Set", GLib.Variant("(ssv)", (f"{G}.Client", nombre, valor)),
                  None, 0, 5000, None)
bus.call_sync(G, cliente, f"{G}.Client", "Start", None, None, 0, 5000, None)
ctx = GLib.MainContext.default()
fin = GLib.get_monotonic_time() + 20_000_000
while (loc := prop(cliente, f"{G}.Client", "Location")) == "/" and GLib.get_monotonic_time() < fin:
    ctx.iteration(False)
    GLib.usleep(200_000)
if loc == "/":
    sys.exit("geoclue: sin posición")
print(*(prop(loc, f"{G}.Location", p) for p in ("Latitude", "Longitude", "Accuracy")))
