"""Revisión independiente de un cambio hecho en Delta vía `mejorar_delta` (luz VERDE o ROJA).

Sigue la idea de agent-arena (revisar un diff concreto, sin ver el razonamiento de quien lo escribió), pero en local y sin
preguntas: no usa CLIs externos ni manda el código fuera. El revisor recibe SOLO la petición y el diff.
"""
import re

MAX_DIFF = 30000
MAX_NUEVO = 4000

REVISOR = (
    "[REVISIÓN INDEPENDIENTE · solo lectura] Eres un revisor que NO ha escrito este cambio y no ve el razonamiento de quien lo hizo. "
    "No edites ni crees nada, no hagas commits, no reinicies Delta y no mandes código a ningún servicio externo. Puedes leer "
    "ficheros de este repositorio (~/gemini-live-assistant) y mirar el estado con git para comprobar lo que dudes.\n\n"
    "Comprueba: 1) que el cambio hace lo que pide la petición y nada más; 2) fallos reales (lógica, sintaxis, nombres que no "
    "existen, casos límite); 3) que respeta las reglas de CLAUDE.md (impresora solo lectura, sin secretos, sin tocar "
    "~/.config/opencode, ~/.gemini ni ~/.agents, capacidad nueva anotada en panel/novedades.json).\n\n"
    "Responde SOLO así: la primera línea exactamente «VEREDICTO: VERDE» (cumple) o «VEREDICTO: ROJA» (no cumple); debajo, como "
    "máximo 5 viñetas con defectos concretos (fichero y qué falla) o, si es VERDE, una frase de por qué. Sin rodeos.\n\n"
)


def prompt(peticion, diff, nuevos, ver=""):
    """Texto completo para el revisor: petición, diff (recortado) y contenido de los ficheros nuevos. `ver` = comando git para el diff entero."""
    d = diff.strip()
    if len(d) > MAX_DIFF:
        d = d[:MAX_DIFF] + f"\n...[diff recortado: lee el resto con {ver or 'git diff'}]"
    partes = [REVISOR, f"PETICIÓN:\n{peticion}\n\nDIFF:\n{d or '(sin cambios en ficheros con seguimiento)'}"]
    for nombre, contenido in nuevos:
        partes.append(f"\nFICHERO NUEVO {nombre}:\n{contenido[:MAX_NUEVO]}")
    return "\n".join(partes)


def veredicto(texto):
    """('VERDE'|'ROJA'|None, resto de la respuesta). None = el revisor no siguió el formato: nunca se da por verde."""
    m = re.search(r"VEREDICTO:\s*\**\s*(VERDE|ROJA)", texto or "", re.I)
    if not m:
        return None, (texto or "").strip()
    return m.group(1).upper(), (texto[:m.start()] + texto[m.end():]).strip()
