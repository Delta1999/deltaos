#!/usr/bin/env python3
"""Puente entre DeltaOS y Antigravity (Plan B de mejoras y peticiones).

Cuando Claude Code se queda sin tokens o cuando el usuario pide usar Antigravity
(«dile a Antigravity que...», «mejora esto con Antigravity»), las peticiones
se canalizan aquí.

Registra las tareas en `antigravity_pendientes.md` (y `antigravity_pendientes.txt`)
y, desde `lanzar`, las ejecuta de verdad con `agy -p` en segundo plano: foto git antes y
después (refs/delta/…), entrada en CAMBIOS_DELTA.md y una línea por encargo en
`antigravity_uso.jsonl` (modelo, tokens, duración, resultado).
"""
import argparse
import asyncio
import json
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
USO = AQUI / "antigravity_uso.jsonl"
CMD_AGY = ["agy", "--dangerously-skip-permissions"]
EJECUTAR = True  # False (tests): `lanzar` solo registra, no ejecuta agy
MAX_S = 900      # s que se le dan a agy antes de cortarlo
_tarea = None

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


def ocupado():
    return bool(_tarea and not _tarea.done())


async def _foto():
    """Instantánea del árbol de trabajo sin tocarlo (git stash create); vale HEAD si no hay cambios."""
    import acciones
    c, h = await acciones._run(["git", "-C", str(AQUI), "stash", "create"], timeout=30)
    if c or not h.strip():
        _, h = await acciones._run(["git", "-C", str(AQUI), "rev-parse", "HEAD"], timeout=30)
    return h.strip()


async def ejecutar_con_agy(peticion):
    """Ejecuta una petición con el CLI `agy` y deja foto git, registro y línea de uso. Devuelve el resumen de agy."""
    import acciones
    prompt = (
        f"[PETICIÓN DESDE DELTA · Plan B Antigravity] "
        f"Trabaja SOLO en este repositorio (~/gemini-live-assistant), sobre sus archivos reales. "
        f"Lee CLAUDE.md antes y respeta sus reglas. No reinicies Delta (morirías con él) ni hagas commits. "
        f"Al terminar resume en dos frases qué has cambiado y si hace falta reiniciar Delta o basta recargar el panel.\n\n"
        f"Petición: {peticion}"
    )
    antes = await _foto()
    t0 = time.time()
    print(f"\n🚀 Lanzando agy para Antigravity: {peticion[:60]}...")
    proc = await asyncio.create_subprocess_exec(
        *CMD_AGY, "-p", prompt, "--output-format", "json",
        cwd=str(AQUI), stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), MAX_S)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        stdout, stderr = b"", f"cortado a los {MAX_S} s".encode()
    salida = stdout.decode("utf-8", errors="replace").strip()
    error = stderr.decode("utf-8", errors="replace").strip()
    datos = {}
    try:
        datos = json.loads(salida)
    except ValueError:
        pass
    ok = proc.returncode == 0 and datos.get("status", "SUCCESS") == "SUCCESS"
    resumen = (datos.get("response") or salida or error or "sin salida").strip()

    despues = await _foto()
    marca = time.strftime("%Y%m%d-%H%M%S")
    for n, h in (("antes", antes), ("despues", despues)):  # refs: que git no borre las fotos
        await acciones._run(["git", "-C", str(AQUI), "update-ref", f"refs/delta/{marca}/{n}", h], timeout=30)
    _, stat = await acciones._run(["git", "-C", str(AQUI), "diff", "--stat", antes, despues], timeout=30)
    with REGISTRO.open("a", encoding="utf-8") as f:
        f.write(f"\n## {time.strftime('%Y-%m-%d %H:%M')} · vía Delta (Plan B → Antigravity)\n\n"
                f"**Petición:** {peticion}\n\n**Antigravity ({'ok' if ok else 'FALLÓ'}):** {resumen[-800:]}\n\n"
                f"```\n{stat.strip() or '(sin cambios en archivos con seguimiento)'}\n```\n"
                f"\nVer: `git diff refs/delta/{marca}/antes refs/delta/{marca}/despues` · "
                f"Deshacer: `git diff refs/delta/{marca}/antes refs/delta/{marca}/despues | git apply -R`\n")
    uso = datos.get("usage") or {}
    with USO.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"t": int(t0), "ok": ok, "s": round(time.time() - t0, 1), "tokens": uso.get("total_tokens"),
                            "peticion": peticion[:200]}, ensure_ascii=False) + "\n")
    if ok:
        marcar_completada(peticion[:30])
        print(f"✓ Antigravity terminó: {resumen[-300:]}")
        return resumen
    print(f"✗ Antigravity falló (código {proc.returncode}): {error or resumen}")
    return f"Error ejecutando agy: {(error or resumen)[:200]}"


async def _y_avisar(peticion):
    import acciones
    try:
        res = await ejecutar_con_agy(peticion)
        await acciones.avisar(f"Antigravity ha terminado: {res[:300]}")
    except Exception as e:  # una tarea suelta nunca debe tumbar a Delta
        print(f"Plan B Antigravity: {e}")


async def lanzar(peticion, origen="DeltaOS"):
    """Plan B real: registra la petición y la ejecuta con agy en segundo plano (si EJECUTAR y agy está libre)."""
    global _tarea
    import acciones
    texto = await registrar_mejora(peticion, origen)
    if not EJECUTAR:
        return texto
    if ocupado():
        return ("Antigravity sigue ocupado con otro encargo; esta petición queda anotada en antigravity_pendientes.md. "
                "Díselo así al usuario.")
    _tarea = acciones.tarea(_y_avisar(peticion))
    return ("Antigravity (Plan B) ya está trabajando en ello sobre el propio repositorio de Delta; queda registrado en "
            "CAMBIOS_DELTA.md y te aviso al terminar. Díselo así al usuario.")


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
