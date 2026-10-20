"""Fase 8: la barra de estado crece en tarjeta (texto, imagen o el visor) y se encoge sola
(.venv/bin/python test_tarjeta.py)"""
import asyncio
import tempfile
import time
from pathlib import Path

import acciones
import panel

import deltaos

panel.VISTA = Path(tempfile.mkdtemp()) / "delta-vista"
corre = lambda c: asyncio.run(c)
ST = acciones.ST


def vista():
    return panel.VISTA.read_text().strip()


# ---------- solo tiene sentido con la tira puesta ----------
panel.vista("panel")
r = corre(deltaos.mostrar_en_tira("lo que sea"))
assert r.startswith("Error") and "panel entero" in r, r
assert panel._TARJETA is None, "no se pone la tarjeta si no hay tira"

# ---------- con la tira: crece ----------
panel.vista("invisible")
r = corre(deltaos.mostrar_en_tira("PETG 240\nCama 80\nVentilador 40", "LAMINADO", "30"))
assert r.startswith("Hecho") and "30" in r, r
assert vista() == "invisible-grande", "ventana.sh tiene que recibir la orden de agrandar"
tj = panel.snapshot(ST)["tarjeta"]
assert tj["titulo"] == "LAMINADO" and tj["lineas"] == ["PETG 240", "Cama 80", "Ventilador 40"], tj

# ---------- se encoge sola ----------
panel._TARJETA["hasta"] = time.monotonic() - 1
assert panel.snapshot(ST)["tarjeta"] is None, "caducada"
assert vista() == "invisible", "y la ventana vuelve a su sitio sin que nadie se lo pida"

# Si Delta se cayó con la tarjeta puesta, el primer snapshot al volver la quita: por eso la
# caducidad vive en snapshot() y no en un temporizador que muere con el proceso.
panel.vista("invisible")
corre(deltaos.mostrar_en_tira("algo", "X", "5"))
assert vista() == "invisible-grande"
panel._TARJETA["hasta"] = time.monotonic() - 999
panel.snapshot(ST)
assert vista() == "invisible" and panel._TARJETA is None

# ---------- límites ----------
panel.vista("invisible")
assert corre(deltaos.mostrar_en_tira("")).startswith("Error")
assert corre(deltaos.mostrar_en_tira("x", "t", "mañana")).startswith("Error")
# Ni se queda para siempre ni parpadea: se recorta a los topes en vez de fallar.
assert corre(deltaos.mostrar_en_tira("x", "t", "9999")).startswith("Hecho")
assert panel._TARJETA["hasta"] <= time.monotonic() + panel.TARJETA_MAX + 1
assert corre(deltaos.mostrar_en_tira("x", "t", "0")).startswith("Hecho")
assert panel._TARJETA["hasta"] > time.monotonic() + 4
# Las líneas en blanco no ocupan sitio en una tarjeta de 14 líneas.
corre(deltaos.mostrar_en_tira("a\n\n\n   \nb", "T"))
assert panel._TARJETA["lineas"] == ["a", "b"], panel._TARJETA["lineas"]
corre(deltaos.mostrar_en_tira("\n".join(f"l{i}" for i in range(40)), "T"))
assert len(panel._TARJETA["lineas"]) == 14

# ---------- imágenes: solo las que se dejan mirar ----------
panel.vista("invisible")
assert corre(deltaos.mostrar_en_tira("", "T", "", "/etc/passwd")).startswith("Error"), "ni ruta ni tipo"
assert corre(deltaos.mostrar_en_tira("", "T", "", "/etc/shadow.png")).startswith("Error"), "fuera de las carpetas"
assert corre(deltaos.mostrar_en_tira("", "T", "", str(Path.home() / "no_existe.png"))).startswith("Error")
# Una imagen de verdad en una carpeta permitida sí pasa, y basta ella sola: sin texto.
tmp = deltaos.VISIBLES[-1]; tmp.mkdir(parents=True, exist_ok=True)
foto = tmp / "_prueba_tarjeta.png"
foto.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
r = corre(deltaos.mostrar_en_tira("", "CAPTURA", "", str(foto)))
assert r.startswith("Hecho"), r
assert panel._TARJETA["img"].startswith("/archivo?p="), panel._TARJETA["img"]
assert panel.snapshot(ST)["tarjeta"]["img"] == panel._TARJETA["img"]
# Un fichero oculto, o dentro de una carpeta oculta, no se enseña aunque esté en zona permitida.
esc = tmp / ".secreta"; esc.mkdir(exist_ok=True); (esc / "x.png").write_bytes(b"\x89PNG\r\n\x1a\n")
assert corre(deltaos.mostrar_en_tira("", "T", "", str(esc / "x.png"))).startswith("Error")
# El salto fuera por «..» tampoco cuela: se resuelve antes de comparar.
assert corre(deltaos.mostrar_en_tira("", "T", "", str(tmp / ".." / ".." / ".." / "etc" / "x.png"))).startswith("Error")
foto.unlink(); (esc / "x.png").unlink(); esc.rmdir()
panel.quitar_tarjeta()

# ---------- el visor también hace crecer la barra ----------
# Antes se escribía en S y no se pintaba en ninguna parte: en modo invisible el visor estaba muerto.
panel.vista("invisible")
panel.S["visor"] = {"url": "https://example.com", "titulo": "GOOGLE · petg", "id": 1}
panel.snapshot(ST)
assert vista() == "invisible-grande", "la barra crece para meter el visor"
panel.S["visor"] = None
panel.snapshot(ST)
assert vista() == "invisible", "y se encoge al cerrarlo"

# ---------- quitar la barra a voluntad ----------
assert corre(deltaos.cambiar_vista("oculto")).startswith("Hecho")
assert vista() == "oculto"
# Con la barra quitada no hay dónde poner la tarjeta: se dice, no se escribe.
assert corre(deltaos.mostrar_en_tira("algo")).startswith("Error")
# Y el visor no la resucita: quitada es quitada.
panel.S["visor"] = {"url": "https://example.com", "titulo": "X", "id": 2}
panel.snapshot(ST)
assert vista() == "oculto"
panel.S["visor"] = None
assert corre(deltaos.cambiar_vista("invisible")).startswith("Hecho") and vista() == "invisible"
assert corre(deltaos.cambiar_vista("lo que sea")).startswith("Error")

# ---------- enchufada, y sin herramienta plana nueva ----------
assert "tarjeta" in acciones.FUSIONES["vista"][2]
assert acciones._real("vista", {"accion": "tarjeta", "texto": "a", "titulo": "T", "imagen": "f.png"}) \
    == ("mostrar_en_tira", {"texto": "a", "titulo": "T", "imagen": "f.png"})
assert acciones._real("vista", {"accion": "oculto"}) == ("cambiar_vista", {"modo": "oculto"})
acciones.fusionar()  # al arrancar lo hace assistant.py; aquí a mano, que no lo importamos
assert "mostrar_en_tira" not in [d.name for d in acciones.DECLARATIONS], "la absorbe la fusión"

# ---------- el panel la pinta, y «invisible-grande» sigue siendo invisible ----------
h = Path("panel/index.html").read_text()
assert '<div id="t-card">' in h and "card.className=tar?'on':''" in h
assert 'id="t-foto"' in h and 'id="t-web"' in h, "la foto y el visor reducido"
assert "web.className=vw?'on':''" in h
assert "iframe').removeAttribute('src')" in h, "al cerrar el visor la web tiene que morir, no quedarse detrás"
assert "(d.vista||'').startsWith('invisible')" in h, "si no, la tira desaparece al crecer"
v = Path("panel/ventana.sh").read_text()
assert "TIRA_ALTA=" in v and '[ "$3" = invisible-grande ] && H=$TIRA_ALTA' in v
assert '"${3%%-*}" = invisible' in v, "la rama tiene que aceptar el sufijo"
assert '[ "$3" = oculto ]' in v, "ventana.sh tiene que saber esconderlo todo"

print("OK: la barra crece en tarjeta (texto, imagen o visor), se encoge sola y se puede quitar")
