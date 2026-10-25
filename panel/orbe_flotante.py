#!/usr/bin/env python3
"""El orbe flotante del modo invisible: el orbe 2 solo, encima del escritorio, sin ventana a la vista.

Por qué otra ventana y no la del panel: Chromium NO sabe hacer una ventana transparente bajo Wayland
(probado el 2026-10-25 con --enable-transparent-visuals, --default-background-color=00000000 y
--ozone-platform=x11: siempre sale un cuadrado blanco detrás). GTK4 + WebKitGTK sí, y además trae
WebGL 2.0, que es lo que necesita el orbe. Así que el modo invisible pasa a ser esta ventana y el
panel de Chromium se queda minimizado.

La página es la MISMA del panel (`index.html?widget=1`): el mismo WebSocket, el mismo orbe y la misma
barra de estado, sin duplicar nada. Aquí solo está la ventana:
  · transparente y sin marco, siempre encima (la coloca ventana.sh con kdotool);
  · solo el orbe —y la barra cuando está abierta— reciben el ratón: el resto de la ventana es hueco
    y los clics caen en lo que haya debajo (región de entrada);
  · un clic enseña la barra de estado 5 s, otro clic la quita, el doble clic abre el panel entero y
    arrastrando se mueve de sitio (lo mueve el propio KWin, con begin_move).

Usa el Python del sistema (PyGObject y WebKit 6 son paquetes del sistema), no el .venv de Delta.
"""
import json
import math
import signal
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("WebKit", "6.0")
from gi.repository import Gdk, GLib, Gtk, WebKit  # noqa: E402

import cairo  # noqa: E402

URL = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:7876") + "/?widget=1"

# Las medidas van con las del CSS (body.widget en index.html): el orbe arriba a la derecha y la
# barra debajo. La ventana es grande y casi toda hueco transparente; lo que recibe clics lo decide
# la región de entrada, no el tamaño.
ORBE = 360          # tres veces el mini orbe del panel, como pidió el usuario
ANCHO, ALTO = 700, 850
TIRA_Y = 368        # dónde empieza la barra dentro de la ventana
CLIC_MS = 260       # espera antes de dar un clic por simple: si no, el doble clic abre antes la barra
ARRASTRE = 8        # px a partir de los cuales un clic es un arrastre


def region(alto_tira):
    """Lo único que recibe ratón: el círculo del orbe y, si está abierta, la barra."""
    r = cairo.Region()
    rad = ORBE / 2
    cx = ANCHO - rad          # el orbe va pegado arriba a la derecha: su centro, en la ventana
    paso = 4
    for y in range(0, ORBE, paso):
        dy = y + paso / 2 - rad
        if abs(dy) >= rad:
            continue
        semi = math.sqrt(rad * rad - dy * dy)
        r.union(cairo.RectangleInt(int(cx - semi), y, int(2 * semi), paso))
    if alto_tira > 0:
        r.union(cairo.RectangleInt(0, TIRA_Y, ANCHO, min(alto_tira, ALTO - TIRA_Y)))
    return r


class Orbe(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="es.delta.orbe")
        self.win = None
        self.vista = None
        self.alto_tira = 0
        self.mostrado = False
        self.clic_id = 0
        self.arrastrando = False

    # -------- ventana --------
    def do_activate(self):
        if self.win:
            self.win.present()
            return
        css = Gtk.CssProvider()
        css.load_from_string("window, window > *, webkitwebview { background: transparent; }")
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, 900)

        ucm = WebKit.UserContentManager()
        ucm.register_script_message_handler("orbe", None)
        ucm.connect("script-message-received::orbe", self._del_navegador)

        self.vista = WebKit.WebView(user_content_manager=ucm)
        transparente = Gdk.RGBA()
        transparente.red = transparente.green = transparente.blue = transparente.alpha = 0.0
        self.vista.set_background_color(transparente)
        self.vista.connect("load-failed", self._fallo)
        self.vista.load_uri(URL)

        self.win = Gtk.ApplicationWindow(application=self, title="Delta orbe")
        self.win.set_decorated(False)
        self.win.set_default_size(ANCHO, ALTO)
        self.win.set_child(self.vista)
        self.win.connect("realize", lambda *_: GLib.timeout_add(150, self._region))
        self._gestos()
        # Nace oculto y sin ratón: KWin lo coloca donde quiere y ventana.sh lo mueve después, y ese salto
        # se veía. ventana.sh lo muestra con SIGUSR1 cuando ya está en su sitio y lo oculta con SIGUSR2 al
        # salir del modo invisible, sin matarlo: arrancarlo de cero tarda ~10 s. Ocultar es cosa de la página
        # (clase oculto-widget y bandera orbeOculto): la ventana sigue mapeada, transparente. Ni set_opacity(0)
        # ni ocultar el WebView valen: GTK no mapea una ventana que no pinta nada y KWin deja de verla.
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, self._mostrar)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR2, self._ocultar)
        self.vista.connect("load-changed", lambda _v, ev: ev == WebKit.LoadEvent.FINISHED and self._bandera())
        self.win.present()

    def _fallo(self, _v, _ev, uri, error):
        # el panel puede tardar en levantar (o estar reiniciándose): reintentar sin ruido
        GLib.timeout_add_seconds(2, lambda: (self.vista.load_uri(URL), False)[1])
        return True

    def _bandera(self):
        # también al acabar de cargar: si la señal llegó con la página a medias, el JS se habría perdido
        o = "false" if self.mostrado else "true"
        self._js(f"window.orbeOculto={o};document.body.classList.toggle('oculto-widget',{o})")

    def _mostrar(self):
        self.mostrado = True
        self._bandera()
        self._region()
        return GLib.SOURCE_CONTINUE

    def _ocultar(self):
        self.mostrado = False
        self._cancelar_clic()
        self._bandera()
        self._region()
        return GLib.SOURCE_CONTINUE

    def _region(self):
        s = self.win.get_surface()
        if s:
            s.set_input_region(region(self.alto_tira) if self.mostrado else cairo.Region())
        return False

    # -------- lo que cuenta la página: si la barra está abierta y cuánto ocupa --------
    def _del_navegador(self, _ucm, js):
        try:
            d = json.loads(js.to_json(0)) if hasattr(js, "to_json") else {}
            if isinstance(d, str):
                d = json.loads(d)
        except Exception:
            return
        self.alto_tira = int(d.get("alto") or 0) if d.get("barra") else 0
        self._region()

    # -------- ratón: clic, doble clic y arrastre --------
    def _gestos(self):
        clic = Gtk.GestureClick()
        clic.set_button(1)
        clic.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        clic.connect("pressed", self._pulsado)
        clic.connect("released", self._soltado)
        self.win.add_controller(clic)

        arr = Gtk.GestureDrag()
        arr.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        arr.connect("drag-begin", lambda *_: setattr(self, "arrastrando", False))
        arr.connect("drag-update", self._arrastre)
        self.win.add_controller(arr)
        # en grupo: al reclamar la secuencia el clic, el WebView no se la queda y no cancela «released»
        clic.group(arr)

    def _pulsado(self, g, n, _x, _y):
        g.set_state(Gtk.EventSequenceState.CLAIMED)
        self._cancelar_clic()
        if n >= 2:                      # doble clic: el panel entero
            self._js("window.deltaWidget && window.deltaWidget.panel()")

    def _soltado(self, _g, n, _x, _y):
        # un clic es pulsar y soltar sin mover: decidirlo al pulsar abría la barra si se mantenía antes de arrastrar
        if n == 1 and not self.arrastrando:
            self.clic_id = GLib.timeout_add(CLIC_MS, self._clic_simple)

    def _clic_simple(self):
        self.clic_id = 0
        if not self.arrastrando:
            self._js("window.deltaWidget && window.deltaWidget.clic()")
        return False

    def _cancelar_clic(self):
        if self.clic_id:
            GLib.source_remove(self.clic_id)
            self.clic_id = 0

    def _arrastre(self, gesto, dx, dy):
        if self.arrastrando or math.hypot(dx, dy) < ARRASTRE:
            return
        self.arrastrando = True
        self._cancelar_clic()
        ok, ini_x, ini_y = gesto.get_start_point()
        sup = self.win.get_surface()
        if not ok or not sup:
            return
        # lo mueve KWin, no nosotros: bajo Wayland una ventana no puede colocarse sola
        sup.begin_move(gesto.get_current_event_device(), 1, ini_x, ini_y, gesto.get_current_event_time())
        gesto.set_state(Gtk.EventSequenceState.DENIED)

    def _js(self, codigo):
        self.vista.evaluate_javascript(codigo, -1, None, None, None, None, None)


if __name__ == "__main__":
    Orbe().run([])
