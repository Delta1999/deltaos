"""Modo estudiante: clase grabada → tema en PDF anotado (subrayado, margen, mnemotecnias y esquemas).

El trabajo pesado está en estudio_clase.py (horas de audio): aquí solo se lanza en segundo plano.
"""
import sys
from pathlib import Path

import acciones
from acciones import _fn, _s

AQUI = Path(__file__).parent


def clase_a_apuntes(url="", tema="", audio=""):
    argv = [sys.executable, str(AQUI / "estudio_clase.py"), "--abrir"]
    if tema.strip():
        n = "".join(c for c in tema if c.isdigit())
        if not n:
            return f"Error: «{tema}» no es un número de tema (0-23)."
        argv += ["--tema", n]
    if audio.strip():
        f = Path(audio).expanduser()
        if not f.exists():
            return f"Error: no existe {f}"
        argv += ["--audio", str(f)]
    elif url.strip():
        argv += ["--url", url.strip()]
    r = acciones.lanzar("apuntes", argv, cwd=str(AQUI), timeout=6 * 3600)
    return (r + " Tarda entre 15 y 40 minutos por clase (transcribir, analizar al profesor y montar el PDF);"
            " el resultado va a Temario_Guardia_Civil/Editados por mi/ y lo abro en Okular.")


acciones.registrar([
    _fn("clase_a_apuntes",
        "Modo estudiante (oposición Guardia Civil): baja el audio de la clase que el usuario está viendo, la transcribe, "
        "analiza qué recalca el profesor y genera el tema en PDF anotado a mano: subrayados, notas al margen, "
        "preguntas fijas, mnemotecnias y esquemas. «Descárgate el audio de esta clase y pásalo a apuntes». "
        "Si está viendo el vídeo en el navegador, lee antes la URL de la barra con mirar_detalle y pásala. "
        "Sin URL ni audio usa lo último que bajó con la extensión Vimeo Media Downloader. "
        "El tema lo saca del nombre del vídeo («T1_…»); si no está claro, pregúntaselo.",
        {"url": _s("dirección de la página donde está el vídeo de la clase"),
         "tema": _s("número del tema del temario (0-23), si se sabe"),
         "audio": _s("ruta de un audio/vídeo ya descargado, si lo dice")}),
], [clase_a_apuntes])
acciones.ETIQUETAS.update(clase_a_apuntes="Paso la clase a apuntes")
