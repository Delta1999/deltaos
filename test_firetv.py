"""Comprobación de firetv.trozo: el audio del mando sale en orden y, si falta, se rellena con silencio."""
import firetv

firetv._MANDO.extend(b"\x01\x02" * 3)
assert firetv.trozo(4) == b"\x01\x02\x01\x02"
assert firetv.trozo(4) == b"\x01\x02\x00\x00"  # lo que queda + silencio
assert firetv.trozo(4) == bytes(4) and not firetv._MANDO
print("OK: trozo da el mando en orden y silencio cuando no hay")
