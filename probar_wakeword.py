"""Comprobación de la palabra clave con voz sintética (espeak-ng + sox): .venv/bin/python probar_wakeword.py"""
import subprocess, sys
sys.argv=["x"]; sys.path.insert(0, ".")
import assistant as a
frases = {"Delta": 1, "Delta, pon música": 1, "Oye Delta, qué tal la impresora": 1,
          "dentro de la casa": 0, "con todo detalle": 0, "es muy delgado": 0,
          "y ahora las noticias del día, el gobierno ha dicho que dentro de poco": 0, "el delta del Ebro": 0}
for f, esperado in frases.items():
    pcm = subprocess.run(f"espeak-ng -v es -s 150 --stdout '{f}' | sox -t wav - -t raw -r 16000 -c 1 -b 16 -e signed - pad 0.2 1.5", shell=True, capture_output=True).stdout
    rec = a.load_wakeword()
    hit = any(a.wake_heard(rec, pcm[i:i+a.AUDIO_CHUNK]) for i in range(0, len(pcm), a.AUDIO_CHUNK))
    print("OK " if hit == bool(esperado) else "MAL", hit, "·", f)
