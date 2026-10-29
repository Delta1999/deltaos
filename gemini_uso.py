"""Registro local de cada llamada a Gemini (texto, búsqueda y voz) en gemini_uso.jsonl, una línea por llamada.

Sirve para analizar el gasto sin depender del panel de Google: qué herramienta llama, con qué modelo, si usa la
búsqueda de Google (la que tiene cuota aparte), cuántos tokens gasta y si falla (429, 402, tiempo agotado…).
Nunca debe romper una llamada: cualquier fallo al escribir se ignora.
"""
import json
import time
from pathlib import Path

RUTA = Path(__file__).with_name("gemini_uso.jsonl")
MAX = 5 * 1024 * 1024  # al pasar de aquí el fichero pasa a .1 (el .1 anterior se pierde)


def _por_modalidad(det):
    return {getattr(d.modality, "value", str(d.modality)): d.token_count for d in det or []} or None


def registrar(origen, modelo, um=None, busqueda=False, seg=None, error=None, herramienta=None):
    """um = usage_metadata de la respuesta (texto o voz); error = código o nombre de la excepción."""
    try:
        f = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "origen": origen, "modelo": modelo, "herramienta": herramienta,
             "busqueda": busqueda or None, "seg": None if seg is None else round(seg, 1), "error": error}
        if um is not None:
            f.update(entrada=um.prompt_token_count, total=um.total_token_count,
                     salida=getattr(um, "response_token_count", None) or getattr(um, "candidates_token_count", None),
                     pensando=getattr(um, "thoughts_token_count", None),
                     buscador=getattr(um, "tool_use_prompt_token_count", None),
                     entrada_mod=_por_modalidad(um.prompt_tokens_details),
                     salida_mod=_por_modalidad(getattr(um, "response_tokens_details", None)))
        if RUTA.exists() and RUTA.stat().st_size > MAX:
            RUTA.replace(RUTA.with_name(RUTA.name + ".1"))
        with RUTA.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({k: v for k, v in f.items() if v is not None}, ensure_ascii=False) + "\n")
    except Exception:
        pass
