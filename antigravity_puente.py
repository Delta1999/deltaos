#!/usr/bin/env python3
"""Puente entre DeltaOS y Antigravity (Plan B de mejoras y peticiones).

Cuando Claude Code se queda sin tokens o cuando el usuario pide usar Antigravity
(«dile a Antigravity que...», «mejora esto con Antigravity»), las peticiones
se canalizan aquí.

Registra las tareas en `antigravity_pendientes.md` (y `antigravity_pendientes.txt`)
para que Antigravity las recoja y procese, y ofrece soporte para ejecución directa
vía `agy -p` si se solicita.
"""
import argparse
import asyncio
import os
import re
import shlex
import subprocess
import time
from pathlib import Path

AQUI = Path(__file__).resolve().parent
MD_PENDIENTES = AQUI / "antigravity_pendientes.md"
TXT_PENDIENTES = AQUI / "antigravity_pendientes.txt"
REGISTRO = AQUI / "CAMBIOS_DELTA.md"

PLANTILLA_ENCARGO = (
    "## [{fecha}] · {estado}\n"
    "- **Petición:** {peticion}\n"
    "- **Origen:** {origen}\n"
    "- **Repositorio:** `{repo}`\n"
    "- **Instrucciones:** Modifica los archivos necesarios en `{repo}`. "
    "Comprueba la sintaxis de Python y los tests antes de darlo por bueno. "
    "Registra el resumen del cambio en `CAMBIOS_DELTA.md`.\n\n"
)


def _asegurar_md():
    if not MD_PENDIENTES.is_file():
        MD_PENDIENTES.write_text(
            "# Peticiones de mejora para Antigravity (Plan B)\n\n"
            "Este archivo recopila las mejoras y averías enviadas desde DeltaOS hacia Antigravity\n"
            "cuando Claude Code no tiene tokens o el usuario pide explícitamente usar Antigravity.\n\n"
            "---\n\n",
            encoding="utf-8"
        )


async def registrar_mejora(peticion, origen="DeltaOS"):
    """Registra una petición de mejora para Antigravity en formato Markdown y texto."""
    p = peticion.strip()
    fecha = time.strftime("%Y-%m-%d %H:%M:%S")

    # Registro en Markdown estructurado
    _asegurar_md()
    bloque = PLANTILLA_ENCARGO.format(
        fecha=fecha,
        estado="🟡 PENDIENTE",
        peticion=p,
        origen=origen,
        repo=str(AQUI)
    )
    with MD_PENDIENTES.open("a", encoding="utf-8") as f:
        f.write(bloque)

    # Registro en TXT
    linea_txt = f"[{fecha}] [Antigravity] {p}\n"
    with TXT_PENDIENTES.open("a", encoding="utf-8") as f:
        f.write(linea_txt)

    print(f"\n🪐 [PETICIÓN PARA ANTIGRAVITY - PLAN B]: {p}\n")

    try:
        import panel
        panel.notificar("info", f"Petición para Antigravity (Plan B) registrada: {p[:50]}")
    except Exception:
        pass

    return (
        "Petición registrada para Antigravity en Plan B (antigravity_pendientes.md). "
        "Dile al usuario que ya se lo has mandado a Antigravity y que lo resolverá desde su sesión o CLI."
    )


def listar_pendientes():
    """Lee y devuelve la lista de tareas pendientes."""
    if not MD_PENDIENTES.is_file():
        return []
    contenido = MD_PENDIENTES.read_text(encoding="utf-8", errors="replace")
    patron = re.compile(r"## \[(.*?)\] · (🟡 PENDIENTE|🟢 COMPLETADA)\n- \*\*Petición:\*\* (.*?)\n", re.M)
    return patron.findall(contenido)


def marcar_completada(peticion_sub):
    """Marca como completada una petición en antigravity_pendientes.md."""
    if not MD_PENDIENTES.is_file():
        return False
    txt = MD_PENDIENTES.read_text(encoding="utf-8", errors="replace")
    # Busca la sección con la petición y cambia 🟡 PENDIENTE por 🟢 COMPLETADA
    lineas = txt.splitlines(keepends=True)
    nuevas = []
    modificado = False
    bloque_idx = -1
    for i, l in enumerate(lineas):
        if l.startswith("## [") and "🟡 PENDIENTE" in l:
            bloque_idx = i
        if bloque_idx != -1 and peticion_sub.lower() in l.lower():
            lineas[bloque_idx] = lineas[bloque_idx].replace("🟡 PENDIENTE", f"🟢 COMPLETADA ({time.strftime('%Y-%m-%d %H:%M')})")
            modificado = True
            bloque_idx = -1
    if modificado:
        MD_PENDIENTES.write_text("".join(lineas), encoding="utf-8")
    return modificado


async def ejecutar_con_agy(peticion):
    """Ejecuta una petición directamente a través del CLI `agy` en segundo plano."""
    prompt = (
        f"[PETICIÓN DESDE DELTA · Plan B Antigravity] "
        f"Trabaja SOLO en este repositorio (~/gemini-live-assistant), sobre sus archivos reales. "
        f"Lee CLAUDE.md antes. No reinicies Delta ni hagas commits. "
        f"Al terminar resume qué has cambiado.\n\nPetición: {peticion}"
    )
    cmd = ["agy", "-p", prompt, "--dangerously-skip-permissions"]
    print(f"\n🚀 Lanzando agy para Antigravity: {peticion[:60]}...")
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(AQUI),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    salida = stdout.decode("utf-8", errors="replace").strip()
    error = stderr.decode("utf-8", errors="replace").strip()

    if proc.returncode == 0:
        marcar_completada(peticion[:30])
        print(f"✓ Antigravity terminó: {salida[-300:]}")
        return salida or "Tarea completada por Antigravity."
    else:
        print(f"✗ Antigravity falló (código {proc.returncode}): {error}")
        return f"Error ejecutando agy: {error[:200]}"


def main():
    parser = argparse.ArgumentParser(description="Puente DeltaOS <-> Antigravity")
    parser.add_argument("peticion", nargs="?", help="Petición de mejora a registrar")
    parser.add_argument("--listar", action="store_true", help="Listar peticiones registradas")
    parser.add_argument("--completar", type=str, help="Marcar como completada una petición")
    parser.add_argument("--ejecutar", action="store_true", help="Ejecutar la petición con agy directamente")
    args = parser.parse_args()

    if args.listar:
        tareas = listar_pendientes()
        if not tareas:
            print("No hay peticiones registradas en antigravity_pendientes.md")
        for f, est, pet in tareas:
            print(f"[{f}] {est} -> {pet}")
        return

    if args.completar:
        if marcar_completada(args.completar):
            print(f"✓ Petición marcada como completada: {args.completar}")
        else:
            print(f"No se encontró la petición: {args.completar}")
        return

    if args.peticion:
        if args.ejecutar:
            asyncio.run(registrar_mejora(args.peticion))
            res = asyncio.run(ejecutar_con_agy(args.peticion))
            print(res)
        else:
            res = asyncio.run(registrar_mejora(args.peticion))
            print(res)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
