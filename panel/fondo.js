// Modo espera del panel: a los 30 s de dormir sin visor tapa el panel con una escena limpia.
// Clic derecho = siguiente escena · doble clic o Esc = volver al panel 2 min · clic derecho en el mini orbe del panel = ponerlo ya · clic = el orbe 2
// · la voz fija una con la herramienta «fondo».
// Pantalla completa (clic en la tarjeta o herramienta «pantalla_completa»): impresora con todos los datos, o sistema.
//
// 2026-10-21, a petición del usuario: el ORBE es la escena por defecto, ya NO rotan solas cada X tiempo
// (se cambia a mano con el clic derecho) y la del mapache paseando está desactivada —sigue en el código y
// la voz puede pedirla, pero no entra en la rueda—. Y el orbe es el único que no se quita al hablarle a
// Delta: los demás descubren el panel en cuanto despierta.
import * as THREE from '/three.module.js';
import * as Mapache from '/mapache3d.js';
import * as Orbe from '/orbe.js';
import * as Gota from '/blob.js';
import * as Tiempo from '/tiempo.js';

const $ = i => document.getElementById(i);
const ESPERA = 30e3, PAUSA = 120e3;
let desde = null, fuera = 0, forzado = false, on = false, escena = null, manual = null, ultId = null, ultCompleta = null, full = null, D = {};
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));

const hhmm = () => new Date().toLocaleTimeString('es-ES', {hour: '2-digit', minute: '2-digit'});
const imprime = d => d.impresora && d.impresora.online && ['printing', 'paused'].includes(d.impresora.estado);
// El orbe primero: es la de por defecto. El mapache no está: desactivado (solo por voz).
const escenas = d => ['orbe', 'blob', 'reloj'].concat(d.clima ? ['tiempo'] : [], imprime(d) ? ['impresion'] : []);

function elegir(d, saltar) {
  if (full && !saltar) return full === 'impresora' ? 'impresion' : 'sistema';
  // `manual` (el clic derecho) manda sobre la escena fijada por voz: si no, la fijada volvía a
  // ponerse en el siguiente mensaje del WebSocket y el clic derecho no servía de nada (2026-10-21).
  const fija = manual || (d.fondo && d.fondo.escena !== 'auto' ? d.fondo.escena : null), lista = escenas(d);
  if (fija && !saltar) return fija === 'impresion' && !imprime(d) ? 'orbe' : fija;
  if (saltar) return lista[(lista.indexOf(escena) + 1) % lista.length];
  return lista.includes(escena) ? escena : lista[0];  // sin rotación por tiempo: la que esté puesta se queda
}

function poner(e) {
  if (e === escena) return;
  escena = e;
  for (const n of ['orbe', 'blob', 'reloj', 'mascota', 'impresion', 'tiempo', 'sistema']) $('f-' + n).classList.toggle('on', n === e);
  if (e === 'orbe') Orbe.entrar();
  if (e === 'blob') Gota.entrar();  // la gota vuelve a crecer desde una bola lisa
  if (e === 'sistema') Sis.ya();
  if (e === 'impresion') Imp.empezar();
  if (e === 'tiempo') Tiempo.entrar();
}

function mostrar(v) {
  if (v === on) return;
  on = window.FONDO_ON = v;
  $('fondo').classList.toggle('on', v);
  if (v) { escena = null; poner(elegir(D)); requestAnimationFrame(bucle); }
}

// Se llama en cada mensaje del WebSocket (≈ 0,4 s)
window.fondoEspera = d => {
  D = d;
  const nuevo = d.fondo && d.fondo.id !== ultId;
  // pedido por voz («pon el orbe»): se ve YA, también despierto. Antes solo cambiaba el fondo de cuando duerme,
  // y Delta decía «ya lo tiene» sin que saliera nada (2026-10-21). Se quita igual: doble clic, Esc o la rueda.
  if (nuevo && ultId !== null) { fuera = 0; desde = performance.now() - ESPERA; escena = null; manual = null; forzado = d.fondo.escena !== 'auto'; }
  if (d.fondo) ultId = d.fondo.id; else if (ultId === null) ultId = 0;
  const c = d.completa;  // pantalla completa pedida por voz (la del arranque no cuenta)
  if (c && c.id !== ultCompleta && ultCompleta !== null) { ultCompleta = c.id; c.que === 'salir' ? salir() : window.pantallaCompleta(c.que); return; }
  if (ultCompleta === null) ultCompleta = c ? c.id : 0;
  // el orbe y la gota son su propio sistema: puesto, se queda aunque le hables (pedido el 2026-10-21). Se quita
  // igual que siempre: doble clic, Esc o la rueda.
  const pegado = on && (escena === 'orbe' || escena === 'blob');
  const quiere = (forzado || pegado || d.estado === 'dormido') && !d.visor && !d.confirma && !document.body.classList.contains('chuleta') && !document.body.classList.contains('invisible')
    && !$('cel').classList.contains('on') && performance.now() > fuera;
  if (!quiere) desde = null; else if (desde === null) desde = performance.now();
  mostrar(quiere && (forzado || pegado || performance.now() - desde >= ESPERA));
  if (on) { poner(elegir(d)); textos(d); }
};

window.pantallaCompleta = que => { full = que; forzado = true; fuera = 0; escena = null; window.fondoEspera(D); if (on) poner(elegir(D)); };
const siguiente = e => { e.preventDefault(); full = null; $('fondo').classList.remove('full'); manual = elegir(D, true); poner(manual); };
$('fondo').addEventListener('contextmenu', siguiente);
$('miniorbe').addEventListener('contextmenu', e => { e.preventDefault(); forzado = true; fuera = 0; window.fondoEspera(D); });
// El mini orbe de la cabecera del panel (en lugar del mapache, 2026-10-21): clic = el orbe 2 en grande
window.miniOrbe = (cv, d) => Gota.mini(cv, d);
$('miniorbe').addEventListener('click', () => { full = null; manual = 'blob'; forzado = true; fuera = 0; escena = null; window.fondoEspera(D); });
const salir = () => { const era = full; full = null; manual = null; if (on) { forzado = false; fuera = era ? 0 : performance.now() + PAUSA; mostrar(false); } };
$('fondo').addEventListener('dblclick', salir);
// La rueda también lo quita: el reloj tapa el panel en cuanto Delta se duerme, que es justo cuando
// quieres subir a releer la conversación, y antes solo salía con doble clic o Escape (2026-10-20).
$('fondo').addEventListener('wheel', salir, { passive: true });
$('fondo').addEventListener('mousemove', e => {  // el mapache sigue al ratón y la gota se aparta de él
  if (escena === 'blob') { const r = $('fb-cv').getBoundingClientRect(); return Gota.raton(e.clientX - r.left, e.clientY - r.top); }
  if (escena !== 'mascota') return;
  const r = $('fm-cv').getBoundingClientRect();
  Mapache.raton(e.clientX - r.left, e.clientY - r.top, performance.now() / 1000);
});
$('fondo').addEventListener('mouseleave', () => Gota.raton(null, 0));
addEventListener('keydown', e => { if (e.key === 'Escape') salir(); });

function textos(d) {
  const w = d.clima, a = (d.avisos || [])[0];
  $('fr-hora').textContent = $('fm-hora').textContent = hhmm();
  $('fr-fecha').textContent = d.fecha || '';
  $('fr-pie').textContent = [w && `${w.temp}° · ${w.desc} · ${w.ciudad}`, a && `${a.t.slice(11, 16)} ${a.texto}`].filter(Boolean).join('   ·   ');
  $('fondo').classList.toggle('noche', new Date().getHours() < 7 && !full);
  $('fondo').classList.toggle('full', !!full);
}

function bucle(ms) {
  if (!on) return;
  const t = ms / 1000;
  if (escena === 'orbe') Orbe.pintar($('fo-cv'), D);
  if (escena === 'blob') Gota.pintar($('fb-cv'), D);
  if (escena === 'mascota') Mapache.pintar(t, $('fm-cv'));
  if (escena === 'tiempo') Tiempo.pintar(t, D);
  if (escena === 'impresion') Imp.pintar(t, $('f-impresion'), false);
  if (escena === 'impresion' && full) Imp.ficha(t);
  if (escena === 'sistema') Sis.pintar(t);
  requestAnimationFrame(bucle);
}

// la impresión también en su tarjeta del panel, a pocos fps (no gasta si no se imprime o el panel está tapado)
(function mini(ms) {
  $('imp3d').style.display = imprime(D) ? '' : 'none';
  if (!on && imprime(D) && !document.hidden && !document.body.classList.contains('visor') && !document.body.classList.contains('invisible')) Imp.pintar(ms / 1000, $('imp3d'), true);
  requestAnimationFrame(mini);
})(0);

// ---------- impresión en vivo: el G-code en 3D. Lo impreso es un cordón de plástico con luz (color del filamento),
// la capa en curso en rojo, lo que falta en líneas tenues. Un solo lienzo WebGL que va de la tarjeta al salvapantallas.
const Imp = (() => {
  let archivo = null, cargando = false, G = null, r3 = null, objetivo = 0, mostrado = 0, ultPoll = 0, ultFrame = 0, boq = null, boqObj = null;
  const ANCHO = 0.45, ROJO = new THREE.Color(0xff2d1f);

  function parsear(txt) {
    const seg = [], off = [], capas = [], zs = [];
    let x = 0, y = 0, z = 0, e = 0, absXYZ = true, absE = false, b = 0, zCapa = null;
    for (const linea of txt.split('\n')) {
      const ini = b; b += linea.length + 1;
      const c0 = linea.charCodeAt(0);
      if (c0 !== 71 && c0 !== 77) continue; // G o M
      const sin = linea.split(';')[0].trim(), p = sin.split(/\s+/), cmd = p[0];
      if (cmd === 'G90') absXYZ = true; else if (cmd === 'G91') absXYZ = false;
      else if (cmd === 'M82') absE = true; else if (cmd === 'M83') absE = false;
      else if (cmd === 'G92') { for (const q of p) if (q[0] === 'E') e = +q.slice(1); }
      else if (cmd === 'G0' || cmd === 'G1') {
        let nx = x, ny = y, nz = z, de = 0;
        for (const q of p.slice(1)) {
          const v = +q.slice(1);
          if (q[0] === 'X') nx = absXYZ ? v : x + v; else if (q[0] === 'Y') ny = absXYZ ? v : y + v;
          else if (q[0] === 'Z') nz = absXYZ ? v : z + v; else if (q[0] === 'E') { de = absE ? v - e : v; e = absE ? v : e + v; }
        }
        if (de > 0 && (nx !== x || ny !== y)) {
          if (zCapa === null || Math.abs(nz - zCapa) > 1e-3) { zCapa = nz; capas.push(off.length); zs.push(nz); }
          seg.push(x, y, z, nx, ny, nz); off.push(ini);
        }
        x = nx; y = ny; z = nz;
      }
    }
    return {seg: new Float32Array(seg), off: new Float64Array(off), capas, zs};
  }

  const hasta = (arr, v) => { let lo = 0, hi = arr.length; while (lo < hi) { const m = (lo + hi) >> 1; if (arr[m] <= v) lo = m + 1; else hi = m; } return lo; };

  // cada tramo extruido = un cilindro de 6 caras aplastado (alto de capa × ancho de línea): un InstancedMesh, ~76 B por tramo
  function cordon(g, pos, color) {
    const n = g.n, geo = new THREE.CylinderGeometry(.5, .5, 1, 6, 1, true);
    geo.rotateZ(Math.PI / 2);
    const mesh = new THREE.InstancedMesh(geo, new THREE.MeshStandardMaterial({roughness: .42, metalness: 0}), n);
    const m = new THREE.Matrix4(), q = new THREE.Quaternion(), v = new THREE.Vector3(), sc = new THREE.Vector3(), Y = new THREE.Vector3(0, 1, 0);
    let L = 0;
    for (let k = 0; k < n; k++) {
      while (L + 1 < g.capas.length && g.capas[L + 1] <= k) L++;
      const h = Math.min(.6, Math.max(.08, L ? g.zs[L] - g.zs[L - 1] : g.zs[0])), o = k * 6;
      const dx = pos[o + 3] - pos[o], dz = pos[o + 5] - pos[o + 2], lon = Math.hypot(dx, dz);
      q.setFromAxisAngle(Y, Math.atan2(-dz, dx));
      v.set((pos[o] + pos[o + 3]) / 2, pos[o + 1] - h / 2, (pos[o + 2] + pos[o + 5]) / 2);
      sc.set(lon + ANCHO * .6, h, ANCHO);
      mesh.setMatrixAt(k, m.compose(v, q, sc));
      mesh.setColorAt(k, color);
    }
    mesh.count = 0; mesh.frustumCulled = false;
    return mesh;
  }

  function montar(g, color) {
    // centro y tamaño a partir de la 2.ª capa: la línea de purga del borde no descentra la pieza
    const s = g.seg, i0 = (g.capas[1] || 0) * 6, mn = [1e9, 1e9, 1e9], mx = [-1e9, -1e9, -1e9];
    for (let i = i0 < s.length ? i0 : 0; i < s.length; i += 3) for (let k = 0; k < 3; k++) { mn[k] = Math.min(mn[k], s[i + k]); mx[k] = Math.max(mx[k], s[i + k]); }
    const cx = (mn[0] + mx[0]) / 2, cy = (mn[1] + mx[1]) / 2, tam = Math.max(mx[0] - mn[0], mx[1] - mn[1], mx[2]);
    const pos = new Float32Array(s.length);
    for (let i = 0; i < s.length; i += 3) { pos[i] = s[i] - cx; pos[i + 1] = s[i + 2]; pos[i + 2] = -(s[i + 1] - cy); }
    const n = s.length / 6;
    Object.assign(g, {n, cx, cy, tam, alto: mx[2], color, rojaDe: -1});
    if (r3.grupo) r3.escena.remove(...r3.grupo);
    const antes = r3.escena.children.length;
    const geoF = new THREE.BufferGeometry(); geoF.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    r3.escena.add(new THREE.LineSegments(geoF, new THREE.LineBasicMaterial({color: 0xf2f2f2, transparent: true, opacity: .06, depthWrite: false})));
    g.futuro = geoF;
    g.mesh = cordon(g, pos, color); r3.escena.add(g.mesh);
    // luz: cielo suave, sol blanco que marca las líneas de capa y un contraluz rojo (el acento del panel)
    r3.escena.add(new THREE.HemisphereLight(0xffffff, 0x0a0a0a, 1.1));
    const sol = new THREE.DirectionalLight(0xffffff, 2.4); sol.position.set(tam, tam * 1.7, tam * .8); r3.escena.add(sol);
    const contra = new THREE.DirectionalLight(0xff2d1f, .9); contra.position.set(-tam, tam * .3, -tam); r3.escena.add(contra);
    // cama de puntos cada 10 mm (300×300), como la trama del panel
    const cama = [];
    for (let a = 0; a <= 300; a += 10) for (let c = 0; c <= 300; c += 10) cama.push(a - cx, 0, -(c - cy));
    const gc = new THREE.BufferGeometry(); gc.setAttribute('position', new THREE.Float32BufferAttribute(cama, 3));
    r3.escena.add(new THREE.Points(gc, new THREE.PointsMaterial({color: 0x5a5a5a, size: 1.6, sizeAttenuation: false})));
    boq = new THREE.Mesh(new THREE.SphereGeometry(Math.max(.8, tam / 90), 12, 8), new THREE.MeshBasicMaterial({color: 0xff2d1f}));
    r3.escena.add(boq);
    r3.grupo = r3.escena.children.slice(antes);
    r3.escena.fog = new THREE.Fog(0x000000, tam * 1.6, tam * 4.2);
  }

  // capa en curso en rojo; la anterior vuelve al color del filamento
  function pintarCapa(g, L) {
    if (L === g.rojaDe) return;
    const tramo = (c, color) => { const a = g.capas[c] ?? g.n, b = g.capas[c + 1] ?? g.n; for (let k = a; k < b; k++) g.mesh.setColorAt(k, color); };
    if (g.rojaDe >= 0) tramo(g.rojaDe, g.color);
    tramo(L, ROJO); g.rojaDe = L; g.mesh.instanceColor.needsUpdate = true;
  }

  async function cargar(nombre, clave) {
    cargando = true;
    try {
      const [r, j] = await Promise.all([fetch('/impresora/gcode/' + encodeURIComponent(nombre)), fetch('/impresora/todo').then(r => r.json()).catch(() => ({}))]);
      if (!r.ok) throw new Error(r.status);
      const txt = new TextDecoder('latin1').decode(await r.arrayBuffer()); // 1 byte = 1 carácter: los índices son posiciones del archivo
      const hex = ((j.meta || {}).filament_colors || [])[0];
      G = parsear(txt); archivo = clave; montar(G, new THREE.Color(/^#[0-9a-f]{6}$/i.test(hex || '') ? hex : '#e6e6e6'));
      mostrado = objetivo = 0; ultPoll = 0;
    } catch (e) { G = null; $('fi-info').textContent = 'No pude leer el G-code'; }
    cargando = false;
  }

  function empezar() {
    if (!r3) {
      const cv = $('fi-cv'), ren = new THREE.WebGLRenderer({canvas: cv, antialias: true});
      ren.setPixelRatio(Math.min(devicePixelRatio || 1, 1.5)); ren.setClearColor(0x000000, 0);
      ren.toneMapping = THREE.ACESFilmicToneMapping;
      r3 = {ren, escena: new THREE.Scene(), cam: new THREE.PerspectiveCamera(32, 1, 1, 5000)};
    }
  }

  async function sondear() {
    try {
      const v = await (await fetch('/impresora/vivo')).json();
      if (v.estado === 'offline' || !G || v.archivo + '#' + (D.impresora || {}).trabajo !== archivo) return;
      objetivo = hasta(G.off, v.pos);
      boqObj = new THREE.Vector3(v.boquilla[0] - G.cx, v.boquilla[2], -(v.boquilla[1] - G.cy));
    } catch (e) {}
  }

  // sitio: el contenedor donde va el lienzo (salvapantallas o tarjeta); mini: tarjeta, 8 fps y sin textos
  function pintar(t, sitio, mini) {
    empezar();
    const p = D.impresora || {}, cv = $('fi-cv');
    if (cv.parentNode !== sitio) sitio.appendChild(cv);
    if (p.archivo && p.archivo + '#' + p.trabajo !== archivo && !cargando) cargar(p.archivo, p.archivo + '#' + p.trabajo);
    if (!G) { if (!mini) $('fi-info').textContent = cargando ? 'Leyendo el G-code…' : ''; return; }
    const ms = t * 1000;
    if (ms - ultFrame < (mini ? 125 : 33)) return; ultFrame = ms;
    if (ms - ultPoll > 1000) { ultPoll = ms; sondear(); }
    mostrado += (objetivo - mostrado) * (mini ? .4 : .12);
    const i = Math.round(mostrado), L = Math.max(0, hasta(G.capas, i) - 1);
    G.mesh.count = i; pintarCapa(G, L); G.futuro.setDrawRange(i * 2, (G.n - i) * 2);
    if (boqObj) boq.position.lerp(boqObj, mini ? .6 : .25);
    const w = cv.clientWidth, h = cv.clientHeight;
    if (!w || !h) return;
    if (cv.width !== Math.round(w * r3.ren.getPixelRatio()) || cv.height !== Math.round(h * r3.ren.getPixelRatio())) {
      r3.ren.setSize(w, h, false); r3.cam.aspect = w / h; r3.cam.updateProjectionMatrix();
    }
    const ang = t * .06, R = G.tam * (mini ? 1.75 : 2.3), zc = G.alto * .45;
    r3.cam.position.set(Math.sin(ang) * R, zc + R * .55, Math.cos(ang) * R); r3.cam.lookAt(0, zc, 0);
    r3.ren.render(r3.escena, r3.cam);
    if (mini) return;
    $('fi-pct').textContent = (p.prog ?? 0) + '%';
    $('fi-info').innerHTML = `${esc(p.archivo)}<br>capa ${L + 1} / ${G.capas.length} · z ${G.zs[L].toFixed(2)} mm` +
      (p.quedan != null ? `<br>quedan ${Math.round(p.quedan / 60)} min · fin ${new Date(Date.now() + p.quedan * 1e3).toTimeString().slice(0, 5)}` : '') +
      `<br>boquilla ${p.boquilla[0]}° · cama ${p.cama[0]}°`;
    Imp.capa = {L, total: G.capas.length, z: G.zs[L]};
  }

  // ---- pantalla completa: todo lo que sabe Moonraker ----
  let J = null, ultFicha = 0, pidiendo = false;
  const hm = s => s == null ? '—' : s < 3600 ? `${Math.round(s / 60)} min` : `${Math.floor(s / 3600)} h ${String(Math.round(s % 3600 / 60)).padStart(2, '0')} min`;
  const fila = (k, v) => `<div class="row"><span>${k}</span><span>${v}</span></div>`;
  const sec = (t, h) => `<section><span class="lbl">${t}</span>${h}</section>`;
  const bar = p => `<div class="bar" style="--p:${Math.max(0, Math.min(100, p))}%"></div>`;
  const hora = ts => new Date(ts).toTimeString().slice(0, 5);

  function curva(cv, T) {  // temperatura de los últimos 10 min en puntos; la consigna, en rojo
    if (!cv || !T || !T.temperatures) return;
    const k = devicePixelRatio || 1, w = cv.width = cv.clientWidth * k, h = cv.height = cv.clientHeight * k, x = cv.getContext('2d');
    const t = T.temperatures, o = T.targets || [], mx = Math.max(...t, ...o, 1) * 1.08, n = t.length;
    for (let i = 0; i < n; i++) {
      const px = i / (n - 1) * (w - 4 * k) + 2 * k;
      x.fillStyle = '#ff2d1f'; if (o[i]) { x.beginPath(); x.arc(px, h - o[i] / mx * h, 1 * k, 0, 7); x.fill(); }
      x.fillStyle = '#f2f2f2'; x.beginPath(); x.arc(px, h - t[i] / mx * h, 1.5 * k, 0, 7); x.fill();
    }
  }

  function ficha(t) {
    if (t * 1000 - ultFicha > 2000 && !pidiendo) {
      ultFicha = t * 1000; pidiendo = true;
      fetch('/impresora/todo').then(r => r.json()).then(j => { J = j; dibujarFicha(); }).catch(() => {}).finally(() => pidiendo = false);
    }
  }

  function dibujarFicha() {
    const j = J;
    if (!j || j.error || !j.st) { $('fi-full').innerHTML = `<section><span class="lbl">Impresora</span><div class="vacio">Sin datos: ${esc(j && j.error)}</div></section>`; return; }
    const s = j.st, ps = s.print_stats, m = j.meta || {}, ex = s.extruder || {}, cb = s.heater_bed || {}, gm = s.gcode_move || {},
      mr = s.motion_report || {}, th = s.toolhead || {}, sy = s.system_stats || {}, tot = j.tot || {}, fan = s.fan || {},
      fh = s['heater_fan ventilador_hotend'] || {}, c = Imp.capa || {}, lista = x => { try { return JSON.parse(x).join(' · '); } catch (e) { return x || '—'; } };
    const usado = ps.filament_used || 0, total = m.filament_total || 0, gramos = total ? m.filament_weight_total * usado / total : null;
    const flujo = (mr.live_extruder_velocity || 0) * Math.PI * .875 ** 2, pos = mr.live_position || th.position || [];
    const fin = j.quedan != null ? Date.now() + j.quedan * 1e3 : null, col = (m.filament_colors || [])[0];
    $('fi-full').innerHTML =
      sec('Pieza', `<img src="/impresora/miniatura?f=${encodeURIComponent(ps.filename)}" alt="" onerror="this.remove()">` +
        fila('archivo', esc(ps.filename)) + fila('laminador', `${esc(m.slicer || '—')} ${esc(m.slicer_version || '')}`) +
        fila('impresora', esc(m.printer_model || '—')) + fila('altura pieza', m.object_height ? m.object_height + ' mm' : '—') +
        fila('capa / 1.ª capa', `${m.layer_height ?? '—'} / ${m.first_layer_height ?? '—'} mm`) + fila('boquilla', `${m.nozzle_diameter ?? '—'} mm`)) +
      sec('Progreso', bar(s.virtual_sdcard ? s.virtual_sdcard.progress * 100 : 0) +
        fila('estado', esc(ps.state)) + fila('capa', c.L != null ? `${c.L + 1} / ${c.total}` : '—') +
        fila('z', c.z != null ? `${c.z.toFixed(2)} / ${m.object_height ?? '—'} mm` : '—') +
        fila('imprimiendo', hm(ps.print_duration)) + fila('total (con pausas)', hm(ps.total_duration)) +
        fila('quedan', hm(j.quedan)) + fila('acaba a las', fin ? hora(fin) : '—') +
        fila('estimación laminador', hm(m.estimated_time)) + fila('empezó', m.print_start_time ? hora(m.print_start_time * 1e3) : '—')) +
      sec('Filamento', fila('material', `${col ? `<i class="sw" style="background:${esc(col)}"></i>` : ''}${esc(lista(m.filament_type))}`) +
        fila('perfil', esc(lista(m.filament_name)).slice(0, 40)) + bar(total ? usado / total * 100 : 0) +
        fila('gastado', `${(usado / 1000).toFixed(1)} / ${(total / 1000).toFixed(1)} m`) +
        fila('peso', gramos != null ? `${gramos.toFixed(0)} / ${m.filament_weight_total} g` : '—') +
        fila('flujo ahora', `${flujo.toFixed(1)} mm³/s`)) +
      sec('Temperaturas', fila('boquilla', `${(ex.temperature ?? 0).toFixed(1)} / ${ex.target ?? 0} °C · ${Math.round((ex.power || 0) * 100)} %`) +
        '<canvas id="fc-ex"></canvas>' +
        fila('cama', `${(cb.temperature ?? 0).toFixed(1)} / ${cb.target ?? 0} °C · ${Math.round((cb.power || 0) * 100)} %`) + '<canvas id="fc-cb"></canvas>' +
        fila('últimos 10 min', '<span style="color:var(--red)">●</span> consigna')) +
      sec('Movimiento', fila('velocidad real', `${(mr.live_velocity || 0).toFixed(0)} mm/s`) +
        fila('pedida', `${((gm.speed || 0) / 60).toFixed(0)} mm/s`) +
        fila('factor velocidad', `${Math.round((gm.speed_factor ?? 1) * 100)} %`) + fila('factor flujo', `${Math.round((gm.extrude_factor ?? 1) * 100)} %`) +
        fila('posición', pos.length ? `X ${pos[0].toFixed(1)} · Y ${pos[1].toFixed(1)} · Z ${pos[2].toFixed(2)}` : '—') +
        fila('ejes con home', esc((th.homed_axes || '—').toUpperCase())) +
        fila('límites', `${th.max_velocity ?? '—'} mm/s · ${th.max_accel ?? '—'} mm/s²`)) +
      sec('Ventiladores', fila('capa', `${Math.round((fan.speed || 0) * 100)} %`) + fila('hotend', `${Math.round((fh.speed || 0) * 100)} %`)) +
      sec('Máquina', fila('Klipper', `${esc(j.info && j.info.state)} · ${esc(((j.info && j.info.software_version) || '').split('-')[0])}`) +
        fila('MCU', esc(((s.mcu && s.mcu.mcu_version) || '—').split('-')[0])) +
        fila('host', `carga ${(sy.sysload ?? 0).toFixed(2)} · ${Math.round((sy.memavail || 0) / 1024)} MB libres`) +
        fila('reposo', esc((s.idle_timeout && s.idle_timeout.state) || '—')) +
        (s.display_status && s.display_status.message ? fila('mensaje', esc(s.display_status.message)) : '')) +
      sec('Histórico', fila('trabajos', Math.round(tot.total_jobs || 0)) + fila('horas imprimiendo', Math.round((tot.total_print_time || 0) / 3600)) +
        fila('filamento', `${((tot.total_filament_used || 0) / 1e6).toFixed(2)} km`) + fila('la más larga', hm(tot.longest_print)));
    curva($('fc-ex'), (j.temps || {}).extruder); curva($('fc-cb'), (j.temps || {}).heater_bed);
  }

  return {empezar, pintar, ficha};
})();

// ---------- sistema a pantalla completa: programas por RAM y cuáles se pueden cerrar ----------
const Sis = (() => {
  let ult = 0, pidiendo = false;
  const TIPO = {no: 'no tocar', si: 'se puede cerrar', mira: 'revisar'};
  function pedir() {
    pidiendo = true;
    fetch('/sistema/procesos').then(r => r.json()).then(dibujar)
      .catch(e => { $('fs-pie').textContent = 'No se pudo leer el sistema: ' + e.message; }).finally(() => pidiendo = false);
  }
  function dibujar(j) {
    const r = j.ram, usada = r.total - r.disp, sw = j.swap.reduce((a, z) => ({mb: a.mb + z.mb, usado: a.usado + z.usado}), {mb: 0, usado: 0});
    const big = (n, v, rojo) => `<div><span class="lbl">${n}</span><b class="${rojo ? 'r' : ''}">${v}</b></div>`;
    $('fs-top').innerHTML = big('RAM', Math.round(usada / r.total * 100) + '%', usada / r.total > .9) +
      big('Swap', sw.mb ? Math.round(sw.usado / sw.mb * 100) + '%' : '—', sw.mb && sw.usado / sw.mb > .8) +
      big('CPU', (j.cpu ?? '—') + '%', j.cpu > 85) + big('Temp', j.temp != null ? j.temp + '°' : '—', j.temp >= 85) +
      big('Carga', j.carga[0].toFixed(1), j.carga[0] > j.nucleos);
    const up = j.arranque, libre = j.grupos.filter(g => g.tipo === 'si').reduce((a, g) => a + g.mb, 0);
    $('fs-pie').textContent = [`${(usada / 1024).toFixed(1)} de ${(r.total / 1024).toFixed(1)} GB en uso · ${(r.disp / 1024).toFixed(1)} GB disponibles (caché ${(r.cache / 1024).toFixed(1)} GB)`,
      sw.mb ? `swap ${(sw.usado / 1024).toFixed(1)} / ${(sw.mb / 1024).toFixed(1)} GB` : '', `${j.nproc} procesos · ${j.nucleos} núcleos`,
      `encendido ${Math.floor(up / 86400) ? Math.floor(up / 86400) + ' d ' : ''}${Math.floor(up % 86400 / 3600)} h`, `disco ${j.disco.libre} GB libres de ${j.disco.total}`,
      libre ? `cerrando lo marcado liberas ≈ ${(libre / 1024).toFixed(1)} GB` : ''].filter(Boolean).join('   ·   ');
    const max = Math.max(...j.grupos.map(g => g.mb), 1);
    $('fs-tabla').innerHTML = '<span class="h">Programa</span><span class="h">RAM real (PSS)</span><span class="h n">MB</span><span class="h n">CPU</span><span class="h n">Proc.</span><span class="h">¿Se puede cerrar?</span>' +
      j.grupos.slice(0, Math.max(6, Math.floor((innerHeight * .62) / 27))).map(g =>
        `<span class="${g.tipo}">${esc(g.nombre)}</span><div class="bar${g.tipo === 'si' ? ' r' : ''}" style="--p:${g.mb / max * 100}%"></div>` +
        `<span class="n">${g.mb}</span><span class="n">${g.cpu}%</span><span class="n">${g.n}</span><span class="${g.tipo}">${TIPO[g.tipo]}${g.por ? ' · ' + esc(g.por) : ''}</span>`).join('');
  }
  return {
    ya() { ult = performance.now(); if (!pidiendo) pedir(); },  // al abrirla, sin esperar al bucle
    pintar(t) { if (t * 1000 - ult > 3000 && !pidiendo) { ult = t * 1000; pedir(); } },
  };
})();
