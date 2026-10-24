"""Modo estudiante: clase grabada → tema en PDF anotado (subrayado, margen, mnemotecnias y esquemas).

El trabajo pesado está en estudio_clase.py (horas de audio): aquí solo se lanza en segundo plano.
"""
import sys
from pathlib import Path

import acciones
from acciones import _fn, _s
import visor_delta  # noqa: F401  (visor y editor de apuntes manos libres)

AQUI = Path(__file__).parent


async def clase_a_apuntes(url="", tema="", audio="", profe=""):
    # async: atender() hace await; síncrona devolvía «str can't be awaited» y Gemini decía que había fallado aunque el trabajo arrancaba
    # Gemini a veces la llama varias veces seguidas: dos trabajos bajarían y procesarían la misma clase a la vez
    en_curso = [n for n, e in acciones.ST["trabajos"].items() if n.startswith("apuntes-") and e == "en curso"]
    if en_curso:
        return f"Ya estoy pasando una clase a apuntes (trabajo «{en_curso[0]}»): no lanzo otra. Te aviso al terminar."
    from estudio_clase import VIDEO_ACADEMIA
    if not VIDEO_ACADEMIA.search(url):
        url = ""  # lo que Gemini lee de la pantalla suele salir cortado («app.procivil.es»): mejor el historial de Chrome
    detectada = ""
    argv = [sys.executable, str(AQUI / "estudio_clase.py"), "--abrir"]
    if tema.strip():
        n = "".join(c for c in tema if c.isdigit())
        if not n:
            return f"Error: «{tema}» no es un número de tema (1-23)."
        argv += ["--tema", n]
    if audio.strip():
        f = Path(audio).expanduser()
        if not f.exists():
            return f"Error: no existe {f}"
        argv += ["--audio", str(f)]
    else:
        if not url.strip():
            from estudio_clase import clase_abierta
            abierta = clase_abierta()
            if abierta:
                url, titulo = abierta
                detectada = f"Clase detectada en Chrome: «{titulo}». "
            else:
                detectada = "No veo ninguna clase abierta en Chrome; cojo lo último que bajó la extensión de Vimeo. "
        if url.strip():
            argv += ["--url", url.strip()]
    if profe.strip():
        argv += ["--profe", profe.strip()]
    r = acciones.lanzar("apuntes", argv, cwd=str(AQUI), timeout=6 * 3600)
    return (detectada + r + " Tarda entre 15 y 40 minutos por clase (transcribir, analizar al profesor y montar el PDF);"
            " si el tema ya tenía clases, la junto con ellas en el mismo PDF. Va a Temario_Guardia_Civil/DeltaOs/"
            " (la versión anterior queda en «Versiones anteriores») y lo abro en Okular.")


acciones.registrar([
    _fn("clase_a_apuntes",
        "Modo estudiante (oposición Guardia Civil): baja el audio de la clase que el usuario está viendo, la transcribe, "
        "analiza qué recalca el profesor y genera el tema en PDF anotado a mano: subrayados, notas al margen, "
        "preguntas fijas, mnemotecnias y esquemas. «Aplica esta clase al PDF», «descárgate el audio de esta clase», "
        "«pásala a apuntes». Llámala DIRECTAMENTE sin parámetros: la clase abierta en Chrome la detecta ella sola "
        "(NO uses mirar_detalle ni le pidas la URL), y el tema y el profesor salen del título de la clase. "
        "Dile en voz alta qué clase ha detectado. No digas que estás procesando nada si esta herramienta no lo ha lanzado. "
        "Si el tema ya tiene clases (de este u otro profesor), esta se AÑADE al mismo PDF, no lo sustituye; "
        "si es una clase ya procesada, solo rehace el PDF sin repetirla.",
        {"url": _s("dirección de la página del vídeo, solo si el usuario la dicta (si no, se detecta sola)"),
         "tema": _s("número del tema del temario (1-23), si se sabe"),
         "profe": _s("nombre del profesor de la clase (p. ej. «Paco Arriola»), si lo dice"),
         "audio": _s("ruta de un audio/vídeo ya descargado, si lo dice")}),
], [clase_a_apuntes])
acciones.ETIQUETAS.update(clase_a_apuntes="Paso la clase a apuntes")
