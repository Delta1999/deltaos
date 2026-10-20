"""Una racha de <noise> caduca: no deja el micro en «mal» para siempre (.venv/bin/python test_mic.py)"""
import time

import panel

base = {"mic_t": time.monotonic(), "mic_rms": 2000, "mic_clip": 0.0, "activo": True}

# Ruido ahora mismo: el micro está mal de verdad.
assert panel._mic({**base, "ruido": 3, "ruido_t": time.monotonic()})["estado"] == "mal"

# La misma racha, de hace más de un minuto: ya no cuenta (antes se quedaba clavada en «mal»).
assert panel._mic({**base, "ruido": 3, "ruido_t": time.monotonic() - panel.RUIDO_VALE - 1})["estado"] == "ok"

# Saturación de verdad sigue mandando (mic_clip decae solo, no necesita caducidad).
assert panel._mic({**base, "mic_clip": 0.2})["estado"] == "mal"

# Sin señal del micro: mal, pase lo que pase con el ruido.
assert panel._mic({**base, "mic_t": time.monotonic() - 5})["estado"] == "mal"

print("OK: la racha de ruido caduca a los", panel.RUIDO_VALE, "s")
