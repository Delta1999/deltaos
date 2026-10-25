"""Validación automática de robustez del frontend de DeltaOS (.venv/bin/python test_panel_frontend.py)

Comprueba:
1. Sintaxis AST de panel.py y registro de /api/error_panel.
2. Integridad del HTML: ausencia total de IDs duplicados.
3. Presencia de Error Boundary en panel/index.html.
4. Sintaxis de todos los bloques JavaScript en panel/index.html y panel/fondo.js con Node.js.
5. Presencia en el DOM de todos los IDs críticos manipulados por la interfaz.
6. Ejecución headless de pintar(d) con Node.js bajo múltiples configuraciones de estado (Nothing, iOS, invisible, panel, datos vacíos).
"""
import ast
import json
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

AQUI = Path(__file__).resolve().parent
HTML_PATH = AQUI / "panel" / "index.html"
FONDO_PATH = AQUI / "panel" / "fondo.js"
PANEL_PY = AQUI / "panel.py"


def test_python_ast():
    code = PANEL_PY.read_text(encoding="utf-8")
    ast.parse(code)
    assert "_error_panel" in code, "Falta la función _error_panel en panel.py"
    assert "/api/error_panel" in code, "Falta la ruta /api/error_panel en panel.py"
    print("✓ panel.py: AST y endpoint /api/error_panel OK")


def test_html_no_duplicate_ids():
    html = HTML_PATH.read_text(encoding="utf-8")
    # Ignorar bloques script para evitar IDs generados en plantillas de cadenas JS
    no_scripts = re.sub(r"<script(?:\s+[^>]*)?>.*?</script>", "", html, flags=re.DOTALL)
    ids = re.findall(r'id=["\']([^"\'>\s]+)["\']', no_scripts)
    counts = Counter(ids)
    dups = {k: v for k, v in counts.items() if v > 1}
    assert not dups, f"Existen IDs duplicados en el HTML de panel/index.html: {dups}"
    print(f"✓ panel/index.html: {len(ids)} IDs únicos verificados (cero duplicados)")


def test_error_boundary_present():
    html = HTML_PATH.read_text(encoding="utf-8")
    assert "window.__reportError" in html, "Falta window.__reportError en el Error Boundary"
    assert "window.onerror" in html, "Falta window.onerror en el Error Boundary"
    assert "window.onunhandledrejection" in html, "Falta window.onunhandledrejection en el Error Boundary"
    assert "panel-error-overlay" in html, "Falta el contenedor #panel-error-overlay"
    assert "/api/error_panel" in html, "Falta la llamada a /api/error_panel para registro en backend"
    print("✓ panel/index.html: Error Boundary y overlay de diagnóstico presentes")


def test_js_syntax():
    html = HTML_PATH.read_text(encoding="utf-8")
    scripts = re.findall(r"<script(?:\s+[^>]*)?>(.*?)</script>", html, re.DOTALL)
    assert len(scripts) >= 2, f"Se esperaban al menos 2 bloques script en index.html, encontrados {len(scripts)}"
    with tempfile.TemporaryDirectory() as td:
        for idx, scr in enumerate(scripts):
            tmp_f = Path(td) / f"script_{idx}.js"
            tmp_f.write_text(scr, encoding="utf-8")
            res = subprocess.run(["node", "--check", str(tmp_f)], capture_output=True, text=True)
            assert res.returncode == 0, f"Error de sintaxis en script #{idx}: {res.stderr}"
        if FONDO_PATH.exists():
            res = subprocess.run(["node", "--check", str(FONDO_PATH)], capture_output=True, text=True)
            assert res.returncode == 0, f"Error de sintaxis en fondo.js: {res.stderr}"
    print("✓ JavaScript: Sintaxis de todos los bloques script y fondo.js verificada con Node.js")


def test_required_dom_ids():
    html = HTML_PATH.read_text(encoding="utf-8")
    no_scripts = re.sub(r"<script(?:\s+[^>]*)?>.*?</script>", "", html, flags=re.DOTALL)
    existing_ids = set(re.findall(r'id=["\']([^"\'>\s]+)["\']', no_scripts))

    critical_ids = [
        "hora", "fecha", "dispos", "orbe-wrap", "miniorbe", "memoria", "ultima", "estado",
        "sub", "frases", "impd", "agenda", "sis", "clima", "uso", "k1", "k2", "k3",
        "k4", "k5", "rec", "pasos", "t-hora", "t-est", "t-sub", "t-vivo", "t-pie",
        "t-card", "p-card", "p-card-cerrar", "pegar-cerrar", "b-priv", "b-modo",
        "b-dormir", "b-si", "b-no", "b-tema", "vif", "pegar", "tdia"
    ]
    missing = [i for i in critical_ids if i not in existing_ids]
    assert not missing, f"Faltan IDs críticos en el DOM de panel/index.html: {missing}"
    print(f"✓ panel/index.html: Todos los IDs críticos ({len(critical_ids)}) existen en el DOM")


def test_ios_screensaver_styles_are_scoped():
    html = HTML_PATH.read_text(encoding="utf-8")
    assert '[data-tema="ios"] #fondo' in html
    assert '[data-tema="ios"] #f-reloj' in html
    assert '[data-tema="ios"] #f-blob' in html
    assert '[data-tema="ios"] #f-tiempo' in html
    assert '[data-tema="ios"] #f-sistema' in html
    assert 'prefers-reduced-motion' in html
    assert 'prefers-reduced-transparency' in html
    assert 'prefers-contrast: more' in html
    assert 'background:var(--ios-bg)' in html
    for selector in ('[data-tema="ios"] body', '[data-tema="ios"] header', '[data-tema="ios"] .card',
                     '[data-tema="ios"] #visor', '[data-tema="ios"] #chuleta', '[data-tema="ios"] #pegar'):
        assert selector in html, f"Falta el ámbito iOS de la interfaz principal: {selector}"
    assert '--text-display:#1c1c1e' in html and '--accent:#007aff' in html
    assert "document.documentElement.dataset.tema==='ios'" in html
    assert "ios?'#1c1c1e':'#f2f2f2'" in html
    assert "ios?'#8e8e93':'#1c1c1c'" in html
    fondo = FONDO_PATH.read_text(encoding='utf-8')
    assert "$('imp3d').addEventListener('wheel'" in fondo
    assert 'zoomMini' in fondo and 'passive: false' in fondo
    print("✓ iOS: interfaz principal y salvapantallas acotados con fondo claro y fallbacks de accesibilidad")


def test_render_headless():
    """Ejecuta pintar(d) en Node.js con un DOM mockeado para asegurar que no lanza excepciones."""
    import acciones
    import panel
    snapshot = panel.snapshot(acciones.ST)

    html = HTML_PATH.read_text(encoding="utf-8")
    no_scripts = re.sub(r"<script(?:\s+[^>]*)?>.*?</script>", "", html, flags=re.DOTALL)
    dom_ids = list(set(re.findall(r'id=["\']([^"\'>\s]+)["\']', no_scripts)))

    # Extraer el bloque de script principal
    scripts = re.findall(r"<script(?:\s+[^>]*)?>(.*?)</script>", html, re.DOTALL)
    main_script = scripts[1]  # Bloque principal de la app

    node_test_runner = f"""
    const domIds = {json.dumps(dom_ids)};
    const elements = new Map();

    function createElementMock(id) {{
      const el = {{
        clases: {{}},
        id: id,
        textContent: '',
        innerHTML: '',
        className: '',
        style: {{}},
        classList: {{
          toggle: function(c, on) {{ el.clases[c] = on === undefined ? !el.clases[c] : !!on; }},
          add: function() {{}},
          remove: function() {{}}
        }},
        querySelector: function() {{ return createElementMock('sub-' + id); }},
        querySelectorAll: function() {{ return []; }},
        addEventListener: function() {{}},
        removeEventListener: function() {{}},
        setAttribute: function() {{}},
        removeAttribute: function() {{}},
        getAttribute: function() {{ return ''; }},
        scrollTop: 0,
        scrollHeight: 100,
        clientHeight: 50,
        offsetWidth: 100,
        clientWidth: 1000,
        dataset: {{}},
        getBoundingClientRect: function() {{
          return {{ width: 1920, height: 1080, top: 0, left: 0, right: 1920, bottom: 1080 }};
        }},
        getContext: function() {{
          return {{
            clearRect: function() {{}},
            fillRect: function() {{}},
            beginPath: function() {{}},
            arc: function() {{}},
            fill: function() {{}},
            stroke: function() {{}}
          }};
        }}
      }};
      return el;
    }}

    domIds.forEach(id => {{
      elements.set(id, createElementMock(id));
    }});

    global.document = {{
      getElementById: function(id) {{
        if (!elements.has(id)) {{
          elements.set(id, createElementMock(id));
        }}
        return elements.get(id);
      }},
      documentElement: createElementMock('html'),
      body: createElementMock('body'),
      createElement: function(tag) {{ return createElementMock(tag); }}
    }};
    global.location = {{
      hash: '',
      host: '127.0.0.1:7876',
      hostname: '127.0.0.1',
      href: 'http://127.0.0.1:7876/',
      protocol: 'http:'
    }};
    global.devicePixelRatio = 1;
    global.window = {{
      _ev: 0,
      devicePixelRatio: 1,
      location: global.location,
      addEventListener: function() {{}},
      removeEventListener: function() {{}},
      __reportError: function(msg, url, l, c, err) {{
        console.error('REPORT ERROR LLAMADO:', msg);
        throw new Error('Error Boundary activado en pintar: ' + msg);
      }}
    }};
    global.addEventListener = global.window.addEventListener;
    global.removeEventListener = global.window.removeEventListener;
    global.WebSocket = function() {{
      return {{
        send: function() {{}},
        close: function() {{}},
        addEventListener: function() {{}}
      }};
    }};
    global.setInterval = function() {{ return 1; }};
    global.clearInterval = function() {{}};
    global.setTimeout = function() {{ return 1; }};
    global.clearTimeout = function() {{}};
    global.requestAnimationFrame = function(cb) {{ return 1; }};
    global.cancelAnimationFrame = function() {{}};
    global.fetch = function() {{ return Promise.resolve(); }};

    // Inyectar script principal
    {main_script}

    const testPayloads = [
      {json.dumps(snapshot)},
      Object.assign({{}}, {json.dumps(snapshot)}, {{ tema: 'ios', vista: 'invisible' }}),
      Object.assign({{}}, {json.dumps(snapshot)}, {{ tema: 'nothing', vista: 'panel' }}),
      {{
        hora: '12:00', fecha: 'Sábado 24', conexion: 'conectado', voz: 'Charon',
        dispos: [], memoria: {{ n: 0, ultima: '' }}, ultima: 0, estado: 'activo',
        salud: {{}}, mic: {{ db: 0 }}, frases: [], trabajos: {{}}, avisos: [],
        sistema: {{}}, clima: null, impresora: null, movil: null
      }}
    ];

    for (let i = 0; i < testPayloads.length; i++) {{
      try {{
        pintar(testPayloads[i]);
      }} catch (err) {{
        console.error('Fallo en test payload #' + i, err);
        process.exit(1);
      }}
    }}

    // Reposo: dormido, sin conversación, sin permiso, sin herramienta ni pasos en curso, en modo chat
    const base = Object.assign({{}}, {json.dumps(snapshot)}, {{
      estado: 'dormido', frases: [], confirma: null, herramienta: null, modo: 'chat',
      pasos: [], trabajos: {{}}, claude: null, priv: false,
      avisos: [{{ t: '2099-01-01T09:30:00', texto: 'Llamar al dentista', tipo: 'aviso' }}],
      arreglos: [{{ id: 1, t: '10:00', txt: 'Arreglar la tele', estado: 'pendiente' }}]
    }});
    const der = document.getElementById('der'), fr = document.getElementById('frases');
    const casos = [
      ['reposo', base, true],
      ['escuchando', Object.assign({{}}, base, {{ estado: 'escuchando' }}), false],
      ['con frases', Object.assign({{}}, base, {{ frases: [{{ rol: 'tú', t: 'hola', h: '12:00' }}] }}), false],
      ['permiso pendiente', Object.assign({{}}, base, {{ confirma: 'apagar' }}), false],
      ['herramienta', Object.assign({{}}, base, {{ herramienta: 'buscar' }}), false],
      ['modo alertas', Object.assign({{}}, base, {{ modo: 'alertas', notifs: [] }}), false],
      ['paso en curso', Object.assign({{}}, base, {{ pasos: [{{ h: '12:00:00', t: 'x', e: 'en curso' }}] }}), false],
      ['reposo otra vez', base, true]
    ];
    for (const [nombre, d, esperado] of casos) {{
      pintar(d);
      if (der.clases.reposo !== esperado) {{
        console.error('Reposo mal en «' + nombre + '»: esperado ' + esperado + ', hay ' + der.clases.reposo);
        process.exit(1);
      }}
      if (REPOSO !== esperado) {{ console.error('REPOSO no sigue al estado en «' + nombre + '»'); process.exit(1); }}
    }}
    pintar(base);
    if (!/Lo próximo/.test(fr.innerHTML) || !/Llamar al dentista/.test(fr.innerHTML)) {{
      console.error('La vista de reposo no enseña lo próximo de la agenda:', fr.innerHTML); process.exit(1);
    }}
    if (!/Por arreglar · 1 en cola/.test(fr.innerHTML)) {{
      console.error('La vista de reposo no enseña los arreglos en cola:', fr.innerHTML); process.exit(1);
    }}
    pintar(Object.assign({{}}, base, {{ avisos: [], arreglos: [] }}));
    if (/Lo próximo|Por arreglar/.test(fr.innerHTML)) {{
      console.error('La vista de reposo pinta bloques vacíos:', fr.innerHTML); process.exit(1);
    }}
    // Un único foco de estado: estadoOrbe(d) y el orbe de la cabecera
    const ow = document.getElementById('orbe-wrap');
    const sano = {{ enlace: 'ok', mic: 'ok', aec: 'ok', claude: 'ok', impresora: 'ok' }};
    const orbes = [
      ['dormido', {{ estado: 'dormido' }}, 'reposo'],
      ['escuchando', {{ estado: 'escuchando' }}, 'escuchando'],
      ['trabajando', {{ estado: 'trabajando' }}, 'trabajando'],
      ['hablando', {{ estado: 'hablando' }}, 'hablando'],
      ['privacidad', {{ estado: 'dormido', priv: true }}, 'privacidad'],
      ['enlace mal', {{ estado: 'escuchando', salud: Object.assign({{}}, sano, {{ enlace: 'mal' }}) }}, 'error'],
      ['mic mal', {{ estado: 'dormido', salud: Object.assign({{}}, sano, {{ mic: 'mal' }}) }}, 'error'],
      ['impresora mal no es error', {{ estado: 'dormido', salud: Object.assign({{}}, sano, {{ impresora: 'mal', aec: 'mal' }}) }}, 'reposo']
    ];
    for (const [nombre, extra, esperado] of orbes) {{
      const d = Object.assign({{}}, base, {{ salud: sano }}, extra);
      if (estadoOrbe(d) !== esperado) {{ console.error('estadoOrbe mal en «' + nombre + '»: ' + estadoOrbe(d)); process.exit(1); }}
      pintar(d);
      if (ow.dataset.estado !== esperado) {{ console.error('#orbe-wrap sin data-estado «' + esperado + '» en «' + nombre + '»'); process.exit(1); }}
    }}
    // El rojo solo para avisos reales: alerta(metrica, valor, d) con los umbrales del snapshot
    const sis = (ram, swap, temp) => Object.assign({{}}, base, {{ sistema: {{ ram, swap, cpu: 99, temp }} }});
    const quien = d => ['ram', 'swap', 'temp'].filter(m => alerta(m, d.sistema[m], d)).join('+');
    const casosAlerta = [
      ['normal (ram 91, swap 57, temp 84)', sis(91, 57, 84), ''],
      ['ram llena sin swap', sis(96, 57, 50), ''],
      ['ram 96 y swap 71', sis(96, 71, 50), 'ram+swap'],
      ['swap sola', sis(50, 71, 50), 'swap'],
      ['temp 85', sis(50, 10, 85), 'temp'],
      ['sin datos', sis(null, null, null), '']
    ];
    for (const [nombre, d, esperado] of casosAlerta) {{
      if (quien(d) !== esperado) {{ console.error('alerta() mal en «' + nombre + '»: «' + quien(d) + '» en vez de «' + esperado + '»'); process.exit(1); }}
    }}
    if (alerta('cpu', 100, sis(0, 0, 0))) {{ console.error('la CPU no debe ponerse roja'); process.exit(1); }}
    if (!base.umbrales || base.umbrales.temp !== 85) {{ console.error('el snapshot no trae los umbrales'); process.exit(1); }}
    // en la pantalla las barras de RAM/SWAP/TEMP llevan muesca y solo se ponen rojas con alerta
    pintar(sis(91, 57, 84));
    let sisHtml = document.getElementById('sis').innerHTML;
    if (/class="bar r"/.test(sisHtml) || (sisHtml.match(/class="mu"/g) || []).length !== 3) {{ console.error('#sis sin muescas o con rojo de más:', sisHtml); process.exit(1); }}
    pintar(sis(96, 71, 85));
    sisHtml = document.getElementById('sis').innerHTML;
    if ((sisHtml.match(/class="bar r"/g) || []).length !== 3) {{ console.error('#sis debería tener RAM, SWAP y TEMP en rojo:', sisHtml); process.exit(1); }}
    // Frases de ejemplo del reposo: solo órdenes de voz, ni gestos ni botones
    const nov = {json.dumps(json.loads((HTML_PATH.parent / 'novedades.json').read_text(encoding='utf-8')), ensure_ascii=False)};
    const prohibida = /^(rueda|clic|doble clic|toca|pulsa|arrastra|mant[eé]n|ctrl|bot[oó]n)\\b/i;
    const todas = new Set();
    for (const x of nov) for (const f of frasesDe(x)) todas.add(f);
    for (const az of [0, .5, .999]) for (const f of ejemplosVoz(nov, () => az)) todas.add(f);
    if (todas.size < 20) {{ console.error('el pool de frases de ejemplo es demasiado pequeño:', todas.size); process.exit(1); }}
    for (const f of todas) {{
      if (prohibida.test(f) || f.length > 90) {{ console.error('frase de ejemplo que no se puede decir:', f); process.exit(1); }}
    }}
    if (frasesDe({{ como: 'Rueda del ratón', voz: false }}).length) {{ console.error('voz:false debe dejar la entrada fuera'); process.exit(1); }}
    if (frasesDe({{ como: '«apaga el ordenador» → «¿seguro?» → «sí»' }}).join('|') !== 'apaga el ordenador') {{ console.error('las respuestas sueltas no son ejemplos'); process.exit(1); }}
    // La tira del día: eventosDelDia(d, ahora) es pura
    const chkT = (c, m) => {{ if (!c) {{ console.error('tira del día: ' + m); process.exit(1); }} }};
    const A0 = new Date(2026, 9, 25, 18, 0, 0);
    const clima0 = {{ sale: 8 * 60 + 41, pone: 18 * 60 + 6 }};
    const ev1 = eventosDelDia({{ clima: clima0, impresora: {{ estado: 'printing', quedan: 3000 }},
      avisos: [{{ t: '2026-10-25 20:00', texto: 'llamar', tipo: 'aviso' }}] }}, A0);
    chkT(ev1.map(e => e.tipo).join() === 'sol,impresion,aviso', 'orden ' + ev1.map(e => e.tipo));
    chkT(ev1[0].t.getTime() === new Date(2026, 9, 25, 18, 6).getTime() && ev1[0].texto === 'anochece 18:06', 'sol');
    chkT(ev1[1].t.getTime() === A0.getTime() + 3000e3, 'fin de impresión en 3000 s');
    const h1 = tiraDiaHtml({{ clima: clima0, impresora: {{ estado: 'printing', quedan: 3000 }},
      avisos: [{{ t: '2026-10-25 20:00', texto: 'llamar', tipo: 'aviso' }}] }}, A0, 1400);
    for (const px of [110, 183, 300]) chkT(h1.html.includes('class="td-m ') && h1.html.includes('style="left:' + px + 'px" title'), 'posición ' + px);
    chkT(h1.html.includes('class="td-ya" style="left:100px"') && h1.html.includes('>ahora<'), 'ahora');
    // lo pasado no sale; lo que está justo más allá de las 13 h tampoco
    const ev2 = eventosDelDia({{ clima: {{ sale: 8 * 60, pone: 17 * 60 }}, avisos: [
      {{ t: '2026-10-25 17:59', texto: 'pasado', tipo: 'aviso' }}, {{ t: '2026-10-26 07:01', texto: 'lejos', tipo: 'aviso' }},
      {{ t: '2026-10-26 07:00', texto: 'justo', tipo: 'alarma' }}] }}, A0);
    chkT(ev2.map(e => e.texto).join() === 'justo', 'pasado/lejos ' + ev2.map(e => e.texto));
    // cruce de medianoche y amanecer de mañana dentro de la ventana de 14 h
    const A1 = new Date(2026, 9, 25, 23, 0, 0);
    const ev3 = eventosDelDia({{ clima: {{ sale: 8 * 60 + 41, pone: 19 * 60 + 36, dias: [
      {{ f: '2026-10-25', sale: 8 * 60 + 41, pone: 19 * 60 + 36 }}, {{ f: '2026-10-26', sale: 8 * 60 + 43, pone: 19 * 60 + 34 }}] }},
      avisos: [{{ t: '2026-10-26 01:30', texto: 'madrugada', tipo: 'alarma' }}] }}, A1);
    chkT(ev3.map(e => e.texto).join() === 'madrugada,amanece 08:43', 'medianoche ' + ev3.map(e => e.texto));
    chkT(ev3[0].tipo === 'alarma', 'tipo alarma');
    const ev3b = eventosDelDia({{ clima: {{ sale: 8 * 60 + 41, pone: 19 * 60 + 36 }} }}, A1);
    chkT(ev3b.length === 1 && ev3b[0].texto === 'amanece 08:41', 'sin dias reutiliza el de hoy');
    // de noche los puntos son tenues; de día, brillantes
    chkT(tiraDiaHtml({{ clima: clima0 }}, A1, 1400).html.includes('td-p n'), 'puntos de noche');
    chkT(tiraDiaHtml({{ clima: clima0 }}, new Date(2026, 9, 25, 12, 0), 1400).html.startsWith('<i class="td-p h" '), 'puntos de día');
    // datos vacíos o ausentes: solo «ahora»
    for (const dv of [null, undefined, {{}}, {{ avisos: null, impresora: null, clima: null }}, {{ impresora: {{ estado: 'standby', quedan: 99 }} }}]) {{
      chkT(eventosDelDia(dv, A0).length === 0, 'vacío');
      const hv = tiraDiaHtml(dv, A0, 1400);
      chkT(!hv.html.includes('td-m') && hv.html.includes('>ahora<') && hv.aria.includes('sin eventos'), 'html vacío');
    }}
    chkT(eventosDelDia({{ impresora: {{ estado: 'paused', quedan: 600 }} }}, A0).length === 1, 'pausa cuenta');
    // dos hitos casi juntos: etiquetas en filas distintas; el título no rompe el atributo con comillas
    const h4 = tiraDiaHtml({{ avisos: [{{ t: '2026-10-25 20:00', texto: 'dice "hola"', tipo: 'aviso' }},
      {{ t: '2026-10-25 20:10', texto: 'otro', tipo: 'aviso' }}] }}, A0, 1400);
    chkT(/td-l lbl u"[^>]*>20:00/.test(h4.html) && /td-l lbl d"[^>]*>20:10/.test(h4.html), 'escalonado');
    chkT(h4.html.includes('&quot;hola&quot;'), 'comillas');
    // tres hitos en 15 min: dos etiquetas (una por fila) y ninguna encima de otra; el tercero conserva su marca y su título
    const h5 = tiraDiaHtml({{ avisos: [{{ t: '2026-10-25 20:00', texto: 'a', tipo: 'aviso' }}, {{ t: '2026-10-25 20:06', texto: 'b', tipo: 'alarma' }},
      {{ t: '2026-10-25 20:10', texto: 'c', tipo: 'aviso' }}] }}, A0, 807);
    chkT((h5.html.match(/class="td-m /g) || []).length === 3 && (h5.html.match(/class="td-l lbl [ud]"/g) || []).length === 3, 'tres juntos: ' + (h5.html.match(/class="td-l lbl [ud]"/g) || []).length);
    // más de 6 hitos: solo los 6 más próximos
    const muchos = Array.from({{ length: 9 }}, (_, i) => ({{ t: '2026-10-25 ' + String(19 + (i >> 1)).padStart(2, '0') + ':' + (i % 2 ? '30' : '00'), texto: 'a' + i, tipo: 'aviso' }}));
    chkT((tiraDiaHtml({{ avisos: muchos }}, A0, 1400).html.match(/class="td-m /g) || []).length === 6, 'máximo 6');
    // y pintar() con todo ello no revienta
    pintar(Object.assign({{}}, base, {{ clima: null, impresora: {{ online: true, estado: 'printing', prog: 40, quedan: 3000, archivo: 'x', boquilla: [200, 200], cama: [60, 60] }},
      avisos: [{{ t: '2026-10-25 20:00', texto: 'llamar', tipo: 'aviso' }}] }}));
    pintar(Object.assign({{}}, base, {{ avisos: undefined, impresora: undefined, clima: undefined }}));
    console.log('✓ Tira del día: eventosDelDia y su dibujo');
    console.log('✓ Headless Node.js: pintar(d) ejecutó con éxito todas las variantes de estado');
    process.exit(0);
    """

    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(node_test_runner)
        tmp_name = f.name

    try:
        res = subprocess.run(["node", tmp_name], capture_output=True, text=True)
        assert res.returncode == 0, f"Fallo al ejecutar pintar(d) en Node:\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}"
        print("✓ panel/index.html: Ejecución headless de pintar(d) completada sin errores")
    finally:
        Path(tmp_name).unlink(missing_ok=True)


if __name__ == "__main__":
    print("Iniciando suite de validación de frontend de DeltaOS...")
    test_python_ast()
    test_html_no_duplicate_ids()
    test_error_boundary_present()
    test_js_syntax()
    test_required_dom_ids()
    test_ios_screensaver_styles_are_scoped()
    test_render_headless()
    print("🎉 TODAS LAS PRUEBAS DE FRONTEND SUPERADAS CORRECTAMENTE.")
