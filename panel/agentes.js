// Pantalla completa «Agentes»: se ve trabajar a cada agente (Delta, sesiones de Claude Code, subagentes y OmniRoute),
// qué herramienta usa, con qué modelo y de dónde viene (Claude / OmniRoute / Gemini), y cómo se pasan el trabajo.
// Dos vistas (constelación y carriles) y una barra para rebobinar los últimos 20 min. Los datos vienen de
// GET /agentes.json (agentes.py), solo se piden con la pantalla abierta. Se abre con el icono de la cabecera o por voz
// («enséñame los agentes»: pantalla_completa → fondo.js → Agentes.abrir) y se cierra con Esc, × o «quita eso».
const $ = i => document.getElementById(i);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const corto = (s, n) => { s = String(s ?? ''); return s.length > n ? s.slice(0, n - 1) + '…' : s; };
const guarda = (k, v) => { try { localStorage.setItem(k, v); } catch (e) {} };
const lee = (k, d) => { try { return localStorage.getItem(k) || d; } catch (e) { return d; } };

const ORIGEN = {claude: ['Claude', '#D97757'], omniroute: ['OmniRoute', '#5B9BF6'], gemini: ['Gemini', '#A78BFA']};
const VERDE = '#5FD38D';
const HERR = [[/^(Read|Glob|Grep|LS|NotebookRead)$/, '#5B9BF6'], [/^(Write|Edit|MultiEdit|NotebookEdit)$/, '#E8A33D'], [/^Bash/, '#5FD38D'],
              [/^(Agent|Task|SendMessage)$/, '#A78BFA'], [/^(Web|mcp__.*(search|fetch))/i, '#3CC8C8']];
const colorHerr = t => (HERR.find(([r]) => r.test(t)) || [0, '#8A8A8A'])[1];
const titulo = n => (n.tipo === 'sub' && n.tarea ? n.tarea : n.nombre);
const nombreModelo = m => String(m || '?').replace(/^claude-/, '').replace(/^anthropic\//, '');

let D = null, recvT = 0, vivo = true, Tfijo = 0, vista = lee('ag_vista', 'const'), ventana = +lee('ag_ventana', 300);
let abierto = false, timer = 0, raf = 0, sel = null, estilo = {}, rects = [], pos = {}, vistos = {}, ultLista = 0;

// ---------- DOM ----------
const css = `
#agentes{position:fixed;inset:0;z-index:20;background:var(--bg);color:var(--text-primary);display:none;flex-direction:column;font-family:var(--sans)}
body.agentes #agentes{display:flex}
#agentes .ag-top{display:flex;align-items:center;gap:14px;padding:14px 22px;border-bottom:1px solid var(--border);flex-wrap:wrap}
#agentes h2{font-size:28px;margin:0;color:var(--text-display);font-weight:600}
#agentes .ag-n{color:var(--text-secondary);font-family:var(--mono);font-size:12px;letter-spacing:.06em;text-transform:uppercase}
#agentes .ag-sp{flex:1}
#agentes .ag-leyenda{display:flex;gap:12px;font-family:var(--mono);font-size:11px;color:var(--text-secondary);text-transform:uppercase;letter-spacing:.06em}
#agentes .ag-leyenda i{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px;vertical-align:-1px}
#agentes .ag-seg{display:flex;border:1px solid var(--border-visible);border-radius:999px;overflow:hidden}
#agentes .ag-seg button,#agentes .ag-x{font-family:var(--mono);font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--text-secondary);background:transparent;border:0;padding:6px 13px;cursor:pointer}
#agentes .ag-seg button.on{background:var(--text-primary);color:var(--bg)}
#agentes .ag-x{border:1px solid var(--border-visible);border-radius:999px;color:var(--text-primary)}
#agentes .ag-cuerpo{flex:1;display:flex;min-height:0}
#agentes .ag-lienzo{flex:1;position:relative;min-width:0}
#agentes canvas{position:absolute;inset:0;width:100%;height:100%}
#agentes .ag-tip{position:absolute;pointer-events:none;background:var(--surface-raised);border:1px solid var(--border-visible);border-radius:8px;padding:7px 10px;font-size:12px;max-width:360px;display:none;z-index:2;line-height:1.35}
#agentes .ag-lista{width:330px;border-left:1px solid var(--border);overflow:auto;padding:10px 12px;display:flex;flex-direction:column;gap:8px}
#agentes .ag-c{border:1px solid var(--border);background:var(--surface);border-radius:12px;padding:9px 11px;cursor:pointer}
#agentes .ag-c.sel{border-color:var(--text-primary)}
#agentes .ag-c.off{opacity:.55}
#agentes .ag-c b{font-size:14px;font-weight:600;color:var(--text-display)}
#agentes .ag-c .l1{display:flex;align-items:center;gap:8px}
#agentes .ag-c .pt{width:8px;height:8px;border-radius:50%;flex:none;background:var(--text-disabled)}
#agentes .ag-c .pt.on{animation:agp 1s infinite}
@keyframes agp{50%{opacity:.25}}
#agentes .ag-c .ch{font-family:var(--mono);font-size:10.5px;letter-spacing:.04em;color:var(--text-secondary);margin-top:5px;display:flex;gap:6px;flex-wrap:wrap}
#agentes .ag-c .ch span{border:1px solid var(--border-visible);border-radius:999px;padding:1px 8px}
#agentes .ag-c .us{font-family:var(--mono);font-size:11.5px;color:var(--text-primary);margin-top:6px;word-break:break-word}
#agentes .ag-c .ta{font-size:12px;color:var(--text-secondary);margin-top:4px;line-height:1.3}
#agentes .ag-pie{display:flex;align-items:center;gap:14px;padding:11px 22px;border-top:1px solid var(--border)}
#agentes .ag-pie input{flex:1;accent-color:var(--text-primary)}
#agentes .ag-pie .ag-t{font-family:var(--mono);font-size:12px;color:var(--text-secondary);min-width:120px;text-align:right}
#agentes .ag-pie button{font-family:var(--mono);font-size:11px;letter-spacing:.08em;text-transform:uppercase;border:1px solid var(--border-visible);border-radius:999px;padding:6px 13px;background:transparent;color:var(--text-primary);cursor:pointer}
#agentes .ag-pie button.on{background:var(--accent);border-color:var(--accent);color:#fff}
#agentes .ag-decir{display:none;align-items:center;gap:10px;padding:9px 22px;border-top:1px solid var(--border);background:var(--surface)}
#agentes .ag-decir.on{display:flex}
#agentes .ag-decir label{font-family:var(--mono);font-size:11px;letter-spacing:.06em;color:var(--text-secondary);white-space:nowrap;max-width:260px;overflow:hidden;text-overflow:ellipsis}
#agentes .ag-decir label b{color:var(--text-primary);font-weight:600}
#agentes .ag-decir input{flex:1;min-width:0;background:var(--bg);color:var(--text-primary);border:1px solid var(--border-visible);border-radius:999px;padding:8px 14px;font-family:var(--sans);font-size:14px}
#agentes .ag-decir input:disabled{opacity:.5}
#agentes .ag-decir button{font-family:var(--mono);font-size:11px;letter-spacing:.08em;text-transform:uppercase;border:1px solid var(--accent);border-radius:999px;padding:7px 14px;background:var(--accent);color:#fff;cursor:pointer}
#agentes .ag-decir .res{font-size:12px;color:var(--text-secondary);max-width:340px}
#agentes .ag-vacio{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:var(--text-secondary);font-family:var(--mono);font-size:13px;pointer-events:none}
@media(max-width:900px){#agentes .ag-lista,#agentes .ag-leyenda{display:none}}
`;
const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);
const raiz = document.createElement('div');
raiz.id = 'agentes';
raiz.innerHTML = `
<div class="ag-top"><h2 class="dot">AGENTES</h2><span class="ag-n" id="ag-n"></span><span class="ag-sp"></span>
  <span class="ag-leyenda"><span><i style="background:${ORIGEN.claude[1]}"></i>Claude</span><span><i style="background:${ORIGEN.omniroute[1]}"></i>OmniRoute</span><span><i style="background:${ORIGEN.gemini[1]}"></i>Gemini</span></span>
  <span class="ag-seg" id="ag-vista"><button data-v="const">Constelación</button><button data-v="carriles">Carriles</button></span>
  <span class="ag-seg" id="ag-ventana" title="Ancho de la vista de carriles"><button data-w="120">2 min</button><button data-w="300">5 min</button><button data-w="1200">20 min</button></span>
  <button class="ag-x" id="ag-cerrar" title="Esc">Cerrar ✕</button></div>
<div class="ag-cuerpo"><div class="ag-lienzo" id="ag-lienzo"><canvas id="ag-cv"></canvas><div class="ag-vacio" id="ag-vacio"></div><div class="ag-tip" id="ag-tip"></div></div>
  <div class="ag-lista" id="ag-lista"></div></div>
<form class="ag-decir" id="ag-decir" autocomplete="off"><label id="ag-dl"></label><input id="ag-di" maxlength="2000"><button type="submit">Enviar</button><span class="res" id="ag-dr"></span></form>
<div class="ag-pie"><button id="ag-vivo" class="on">● En directo</button><input type="range" id="ag-rango" min="0" max="1" step="0.5" value="1"><span class="ag-t" id="ag-t"></span></div>`;
document.body.appendChild(raiz);
const cv = $('ag-cv'), ctx = cv.getContext('2d');

// ---------- datos ----------
const ahoraLive = () => D ? D.ahora + (performance.now() - recvT) / 1000 : Date.now() / 1000;
const Tver = () => vivo ? ahoraLive() : Tfijo;

async function pide() {
  try {
    const r = await fetch('/agentes.json', {cache: 'no-store'});
    D = await r.json();
    recvT = performance.now();
    for (const n of D.nodos) if (!(n.id in vistos)) vistos[n.id] = performance.now();
    const rg = $('ag-rango');
    rg.min = D.desde; rg.max = D.ahora;
    if (vivo) rg.value = D.ahora;
    const c = getComputedStyle(document.documentElement);
    estilo = {fg: c.getPropertyValue('--text-primary').trim() || '#e8e8e8', dim: c.getPropertyValue('--text-secondary').trim() || '#999',
              bg: c.getPropertyValue('--bg').trim() || '#000', sup: c.getPropertyValue('--surface-raised').trim() || '#1a1a1a',
              borde: c.getPropertyValue('--border-visible').trim() || '#333', mono: c.getPropertyValue('--mono').trim() || 'monospace',
              sans: c.getPropertyValue('--sans').trim() || 'sans-serif'};
  } catch (e) { /* sin datos: se queda lo último */ }
}

// estado de un agente en el instante t (en vivo manda el servidor; al rebobinar se deduce de sus tramos)
function estadoEn(n, t) {
  const act = n.segs.find(s => s.t0 <= t && t <= (s.abierto && vivo ? Infinity : s.t1));
  if (act) return {e: /^(Agent|Task)$/.test(act.tool) ? 'orquestando' : 'usando', seg: act};
  if (vivo) return {e: n.estado === 'usando' || n.estado === 'orquestando' ? 'pensando' : n.estado, seg: null};
  const fin = Math.max(0, ...n.segs.filter(s => s.t1 <= t).map(s => s.t1));
  if (t - fin < 6 && t <= n.t1 + 1) return {e: 'pensando', seg: null};
  return {e: n.fin && t >= n.fin ? 'hecho' : 'reposo', seg: null};
}
function visible(n, t) {
  if (n.t0 > t + 1) return false;
  if (n.tipo === 'delta') return true;
  if (n.tipo === 'router') return n.segs.some(s => s.t1 <= t + 1 && t - s.t1 < 300);
  const resto = n.fin ? n.fin + 90 : n.t1 + (n.tipo === 'sesion' ? 600 : 300);
  return t <= resto || n.segs.some(s => s.abierto && vivo);
}
const activo = e => e === 'usando' || e === 'orquestando' || e === 'pensando' || e === 'hablando';

// ---------- lista lateral ----------
function lista(t) {
  const vis = D.nodos.filter(n => visible(n, t)).map(n => ({n, s: estadoEn(n, t)}));
  vis.sort((a, b) => (activo(b.s.e) - activo(a.s.e)) || b.n.t1 - a.n.t1);
  $('ag-n').textContent = `${vis.filter(v => activo(v.s.e)).length} activos · ${vis.length} agentes`;
  $('ag-lista').innerHTML = vis.map(({n, s}) => {
    const o = ORIGEN[n.origen] || ORIGEN.claude, on = activo(s.e);
    const usa = s.seg ? `${s.seg.tool}${s.seg.det ? ': ' + s.seg.det : ''}` : '';
    return `<div class="ag-c ${n.id === sel ? 'sel' : ''} ${on ? '' : 'off'}" data-id="${esc(n.id)}"><div class="l1"><span class="pt ${on ? 'on' : ''}" style="background:${on ? o[1] : ''}"></span><b>${esc(corto(titulo(n), 30))}</b><span class="ag-n" style="margin-left:auto">${esc(s.e)}</span></div>
      <div class="ch"><span style="border-color:${o[1]};color:${o[1]}">${o[0]}</span>${n.tipo === 'sub' && n.tarea ? `<span>${esc(corto(n.nombre, 20))}</span>` : ''}<span>${esc(nombreModelo(n.modelo))}</span>${n.ruta ? `<span>${esc(corto(n.ruta, 28))}</span>` : ''}${n.tok ? `<span>${n.parcial ? '≥' : ''}${n.tok} tok</span>` : ''}</div>
      ${usa ? `<div class="us">▸ ${esc(corto(usa, 90))}</div>` : ''}${n.tarea && !(n.tipo === 'sub') ? `<div class="ta">${esc(corto(n.tarea, 110))}</div>` : ''}</div>`;
  }).join('');
  decirPon();
  $('ag-vacio').textContent = vis.length <= 1 ? 'Sin agentes trabajando ahora mismo. Rebobina la barra para ver lo de hace unos minutos.' : '';
}

// ---------- hablarle al agente ----------
let decirA = null;
function decirPon() {
  const n = sel && D.nodos.find(x => x.id === sel), f = $('ag-decir');
  f.classList.toggle('on', !!n);
  if (!n) { decirA = null; return; }
  if (decirA !== n.id) { decirA = n.id; $('ag-di').value = ''; $('ag-dr').textContent = ''; }
  const ok = n.hablable;
  $('ag-dl').innerHTML = `Decirle a <b>${esc(corto(titulo(n), 26))}</b>`;
  $('ag-di').disabled = !ok;
  $('ag-di').placeholder = ok ? 'Escríbele y pulsa Intro…' : 'Es otro proceso: desde aquí solo se puede leer';
  f.querySelector('button').style.display = ok ? '' : 'none';
}
$('ag-decir').onsubmit = e => {
  e.preventDefault();
  const t = $('ag-di').value.trim();
  if (!t || !decirA) return;
  $('ag-dr').textContent = window.enviarWS && window.enviarWS({decir: {a: decirA, texto: t}}) ? 'Enviando…' : 'Sin conexión con el panel.';
};
addEventListener('decir_res', e => {
  const r = e.detail || {};
  $('ag-dr').textContent = r.msg || '';
  if (r.ok) $('ag-di').value = '';
});

// ---------- constelación ----------
function objetivos(vis, W, H) {
  const por = new Map(vis.map(n => [n.id, n])), hijos = new Map(), raices = [];
  for (const n of vis) {
    if (n.tipo === 'router') continue;
    const p = n.padre && por.has(n.padre) && por.get(n.padre).tipo !== 'router' ? n.padre : null;
    if (p) (hijos.get(p) || hijos.set(p, []).get(p)).push(n); else raices.push(n);
  }
  const cx = W / 2, cy = H / 2, obj = {};
  const delta = raices.find(n => n.tipo === 'delta');
  const resto = raices.filter(n => n !== delta);
  const R1 = Math.min(W, H) * 0.27;
  if (delta) obj[delta.id] = [cx, cy];
  const soloRaiz = !delta && resto.length === 1;
  const cuelga = (n, x, y, ang, prof) => {
    const hs = hijos.get(n.id) || [], m = hs.length;
    if (!m) return;
    const arco = prof === 0 && soloRaiz ? 2 * Math.PI : 2.6, r = Math.max(105 - prof * 12, m * 46 / arco);
    const paso = m === 1 ? 0 : arco / (arco >= 6 ? m : m - 1);
    hs.forEach((h, j) => {
      const a = ang + (j - (m - 1) / 2) * paso, hx = x + Math.cos(a) * r, hy = y + Math.sin(a) * r;
      obj[h.id] = [hx, hy];
      cuelga(h, hx, hy, a, prof + 1);
    });
  };
  resto.forEach((n, i) => {
    const a = -Math.PI / 2 + (2 * Math.PI * i) / resto.length + (delta ? 0.3 : 0);
    const x = cx + (soloRaiz ? 0 : Math.cos(a) * R1), y = cy + (soloRaiz ? 0 : Math.sin(a) * R1);
    obj[n.id] = [x, y];
    cuelga(n, x, y, soloRaiz ? -Math.PI / 2 : a, 0);
  });
  if (delta) cuelga(delta, cx, cy, Math.PI * 0.85, 0);
  // que todo quepa
  const xs = Object.values(obj).map(p => p[0]), ys = Object.values(obj).map(p => p[1]);
  if (xs.length) {
    const ex = Math.max(cx - Math.min(...xs), Math.max(...xs) - cx) + 80, ey = Math.max(cy - Math.min(...ys), Math.max(...ys) - cy) + 80;
    const k = Math.min(1.7, (W / 2) / ex, (H / 2) / ey);
    if (k !== 1) for (const id in obj) obj[id] = [cx + (obj[id][0] - cx) * k, cy + (obj[id][1] - cy) * k];
  }
  for (const n of vis) if (n.tipo === 'router') obj[n.id] = [W * 0.86, H * 0.84];
  return obj;
}

function pintaConst(t, W, H, dt) {
  const vis = D.nodos.filter(n => visible(n, t)), por = new Map(vis.map(n => [n.id, n]));
  const obj = objetivos(vis, W, H);
  for (const n of vis) {
    const o = obj[n.id] || [W / 2, H / 2], p = pos[n.id];
    if (!p) { const pa = pos[n.padre]; pos[n.id] = {x: pa ? pa.x : o[0], y: pa ? pa.y : o[1]}; }
    const q = pos[n.id], k = 1 - Math.pow(0.0015, dt);
    q.x += (o[0] - q.x) * k; q.y += (o[1] - q.y) * k;
  }
  rects = [];
  const est = new Map(vis.map(n => [n.id, estadoEn(n, t)]));
  // aristas
  for (const n of vis) {
    const a = pos[n.padre && por.has(n.padre) ? n.padre : null], b = pos[n.id];
    if (!a || !b) continue;
    const on = activo(est.get(n.id).e), c = (ORIGEN[n.origen] || ORIGEN.claude)[1];
    ctx.strokeStyle = c; ctx.globalAlpha = on ? .75 : .22; ctx.lineWidth = on ? 2 : 1; ctx.setLineDash([]);
    ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
  }
  const rt = por.get('omniroute');  // el enrutador: línea discontinua hacia lo que sirve
  if (rt) for (const n of vis) if (n.origen === 'omniroute' && n.tipo !== 'router' && pos[n.id] && pos.omniroute) {
    ctx.strokeStyle = ORIGEN.omniroute[1]; ctx.globalAlpha = activo(est.get(n.id).e) ? .5 : .12; ctx.lineWidth = 1; ctx.setLineDash([4, 6]);
    ctx.beginPath(); ctx.moveTo(pos[n.id].x, pos[n.id].y); ctx.lineTo(pos.omniroute.x, pos.omniroute.y); ctx.stroke();
  }
  ctx.setLineDash([]); ctx.globalAlpha = 1;
  // mensajes: un punto de luz que viaja de quien encarga a quien trabaja (y vuelta con el resultado)
  for (const e of D.eventos) {
    const d = t - e.t;
    if (d < 0 || d > 2.4 || !pos[e.de] || !pos[e.a] || !por.has(e.de) || !por.has(e.a)) continue;
    const u = Math.min(1, d / 1.4), a = pos[e.de], b = pos[e.a], x = a.x + (b.x - a.x) * u, y = a.y + (b.y - a.y) * u;
    const c = e.tipo === 'resultado' ? VERDE : (ORIGEN[por.get(e.a).origen] || ORIGEN.claude)[1];
    ctx.fillStyle = c; ctx.shadowColor = c; ctx.shadowBlur = 16;
    ctx.beginPath(); ctx.arc(x, y, 5, 0, 7); ctx.fill(); ctx.shadowBlur = 0;
    ctx.globalAlpha = Math.max(0, 1 - Math.max(0, d - 1.4) / 1);
    ctx.font = `11px ${estilo.mono}`; ctx.fillStyle = estilo.fg; ctx.textAlign = 'center';
    ctx.fillText((e.tipo === 'resultado' ? '✓ ' : '→ ') + corto(e.txt, 38), x, y - 12);
    ctx.globalAlpha = 1;
  }
  // nodos
  for (const n of vis) {
    const p = pos[n.id], s = est.get(n.id), on = activo(s.e), o = ORIGEN[n.origen] || ORIGEN.claude;
    const edad = Math.min(1, (performance.now() - (vistos[n.id] || 0)) / 500);
    const r = ({delta: 34, sesion: 27, sub: 19, router: 25}[n.tipo] || 20) * (0.4 + 0.6 * edad);
    const pul = on ? 1 + 0.07 * Math.sin(performance.now() / 160) : 1;
    ctx.globalAlpha = (n.id === sel || !sel ? 1 : .45) * (s.e === 'hecho' ? .6 : 1);
    if (on) { ctx.shadowColor = o[1]; ctx.shadowBlur = 24; }
    ctx.fillStyle = estilo.sup; ctx.strokeStyle = o[1]; ctx.lineWidth = on ? 3 : 1.5;
    ctx.beginPath(); ctx.arc(p.x, p.y, r * pul, 0, 7); ctx.fill(); ctx.stroke(); ctx.shadowBlur = 0;
    if (on) {  // arco que gira: está haciendo algo
      ctx.strokeStyle = o[1]; ctx.lineWidth = 2; ctx.beginPath();
      const g = performance.now() / 500 * (s.e === 'pensando' ? .6 : 1.6);
      ctx.arc(p.x, p.y, r * pul + 7, g, g + 1.6); ctx.stroke();
    }
    ctx.fillStyle = estilo.fg; ctx.textAlign = 'center'; ctx.font = `600 ${r > 30 ? 15 : 12}px ${estilo.sans}`;
    ctx.fillText(n.tipo === 'delta' ? 'Δ' : n.tipo === 'router' ? '⇄' : s.e === 'hecho' ? '✓' : n.tipo === 'sub' ? '◦' : '●', p.x, p.y + 5);
    ctx.font = `600 12px ${estilo.sans}`; ctx.fillStyle = estilo.fg;
    ctx.fillText(corto(titulo(n), 24), p.x, p.y + r + 17);
    ctx.font = `10.5px ${estilo.mono}`; ctx.fillStyle = estilo.dim;
    ctx.fillText(corto(nombreModelo(n.modelo), 26), p.x, p.y + r + 30);
    if (s.seg) {
      const txt = corto(`${s.seg.tool}${s.seg.det ? ': ' + s.seg.det : ''}`, 34), w = ctx.measureText(txt).width + 14;
      ctx.fillStyle = colorHerr(s.seg.tool); ctx.globalAlpha *= .95;
      ctx.beginPath(); ctx.roundRect(p.x - w / 2, p.y + r + 36, w, 18, 9); ctx.fill();
      ctx.fillStyle = '#000'; ctx.fillText(txt, p.x, p.y + r + 49);
    }
    ctx.globalAlpha = 1;
    rects.push({id: n.id, x: p.x - r, y: p.y - r, w: 2 * r, h: 2 * r, circ: true, cx: p.x, cy: p.y, r});
  }
}

// ---------- carriles ----------
function pintaCarriles(t, W, H) {
  const vis = D.nodos.filter(n => visible(n, t));
  const por = new Map(vis.map(n => [n.id, n])), orden = [];
  const hijos = n => vis.filter(x => x.padre === n.id && x.tipo !== 'router').sort((a, b) => a.t0 - b.t0);
  const anade = n => { orden.push(n); hijos(n).forEach(anade); };
  vis.filter(n => (!n.padre || !por.has(n.padre)) && n.tipo !== 'router').sort((a, b) => (b.tipo === 'delta') - (a.tipo === 'delta') || a.t0 - b.t0).forEach(anade);
  const rt = por.get('omniroute'); if (rt) orden.push(rt);
  const IZQ = 190, DER = 20, TOP = 28, hFila = Math.max(34, Math.min(58, (H - TOP - 10) / Math.max(1, orden.length)));
  const w = Math.min(ventana, D.ahora - D.desde + 5), t0 = t - w, x = u => IZQ + (u - t0) / w * (W - IZQ - DER);
  rects = [];
  ctx.font = `10px ${estilo.mono}`; ctx.textAlign = 'center'; ctx.fillStyle = estilo.dim; ctx.strokeStyle = estilo.borde; ctx.lineWidth = 1;
  const paso = w <= 150 ? 15 : w <= 400 ? 60 : 180;
  for (let u = Math.ceil(t0 / paso) * paso; u < t; u += paso) {
    ctx.globalAlpha = .35; ctx.beginPath(); ctx.moveTo(x(u), TOP - 6); ctx.lineTo(x(u), H); ctx.stroke(); ctx.globalAlpha = 1;
    const d = new Date(u * 1000); ctx.fillText(d.toLocaleTimeString('es-ES', {hour: '2-digit', minute: '2-digit', second: w <= 150 ? '2-digit' : undefined}), x(u), TOP - 12);
  }
  const fy = new Map();
  orden.forEach((n, i) => {
    const y = TOP + i * hFila, mid = y + hFila / 2, o = ORIGEN[n.origen] || ORIGEN.claude, s = estadoEn(n, t), on = activo(s.e);
    fy.set(n.id, mid);
    if (n.id === sel) { ctx.fillStyle = estilo.sup; ctx.globalAlpha = .6; ctx.fillRect(0, y, W, hFila); ctx.globalAlpha = 1; }
    ctx.strokeStyle = estilo.borde; ctx.globalAlpha = .4; ctx.beginPath(); ctx.moveTo(0, y + hFila); ctx.lineTo(W, y + hFila); ctx.stroke(); ctx.globalAlpha = 1;
    const sangr = n.tipo === 'sub' ? 14 : 0;
    ctx.fillStyle = o[1]; ctx.beginPath(); ctx.arc(12 + sangr, mid - 5, 4, 0, 7); ctx.fill();
    ctx.textAlign = 'left'; ctx.fillStyle = estilo.fg; ctx.font = `600 12px ${estilo.sans}`; ctx.fillText(corto(titulo(n), 22 - sangr / 7), 22 + sangr, mid - 1);
    ctx.fillStyle = estilo.dim; ctx.font = `10px ${estilo.mono}`; ctx.fillText(corto(nombreModelo(n.modelo), 24), 22 + sangr, mid + 12);
    if (on) { ctx.fillStyle = o[1]; ctx.beginPath(); ctx.arc(IZQ - 12, mid, 3 + Math.sin(performance.now() / 150), 0, 7); ctx.fill(); }
    rects.push({id: n.id, x: 0, y, w: IZQ, h: hFila});
    for (const sg of n.segs) {
      const a = Math.max(IZQ, x(sg.t0)), b = Math.min(W - DER, x(sg.abierto && vivo ? t : sg.t1));
      if (b < IZQ || a > W - DER || sg.t0 > t) continue;
      const bw = Math.max(3, b - a);
      ctx.fillStyle = colorHerr(sg.tool); ctx.globalAlpha = sg.ok ? .9 : .45;
      ctx.beginPath(); ctx.roundRect(a, y + 7, bw, hFila - 14, 4); ctx.fill(); ctx.globalAlpha = 1;
      if (bw > 46) { ctx.fillStyle = '#000'; ctx.font = `10px ${estilo.mono}`; ctx.textAlign = 'left'; ctx.fillText(corto(sg.tool, Math.floor(bw / 6.5)), a + 4, mid + 3); }
      rects.push({id: n.id, x: a, y: y + 7, w: bw, h: hFila - 14, seg: sg});
    }
  });
  // mensajes entre agentes: flechas entre carriles
  for (const e of D.eventos) {
    if (e.t < t0 || e.t > t || !fy.has(e.de) || !fy.has(e.a)) continue;
    const xe = x(e.t), y1 = fy.get(e.de), y2 = fy.get(e.a), c = e.tipo === 'resultado' ? VERDE : (ORIGEN[(por.get(e.a) || {}).origen] || ORIGEN.claude)[1];
    ctx.strokeStyle = c; ctx.fillStyle = c; ctx.lineWidth = 1.6; ctx.globalAlpha = .9;
    ctx.beginPath(); ctx.moveTo(xe, y1); ctx.bezierCurveTo(xe + 22, y1, xe + 22, y2, xe, y2); ctx.stroke();
    const d = y2 > y1 ? 1 : -1; ctx.beginPath(); ctx.moveTo(xe, y2); ctx.lineTo(xe + 6, y2 - 7 * d); ctx.lineTo(xe - 6, y2 - 7 * d); ctx.fill(); ctx.globalAlpha = 1;
    rects.push({id: e.a, x: xe - 4, y: Math.min(y1, y2), w: 26, h: Math.abs(y2 - y1), evento: e});
  }
  ctx.strokeStyle = estilo.fg; ctx.lineWidth = 1; ctx.globalAlpha = .6; ctx.setLineDash([3, 4]);
  ctx.beginPath(); ctx.moveTo(x(t), TOP - 4); ctx.lineTo(x(t), H); ctx.stroke(); ctx.setLineDash([]); ctx.globalAlpha = 1;
}

// ---------- bucle ----------
let ult = performance.now();
function bucle(ms) {
  if (!abierto) return;
  raf = requestAnimationFrame(bucle);
  const dt = Math.min(.1, (ms - ult) / 1000); ult = ms;
  const dpr = devicePixelRatio || 1, W = cv.clientWidth, H = cv.clientHeight;
  if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, W, H);
  if (!D) return;
  const t = Tver();
  vista === 'const' ? pintaConst(t, W, H, dt) : pintaCarriles(t, W, H);
  if (performance.now() - ultLista > 500) { ultLista = performance.now(); lista(t); }
  $('ag-t').textContent = vivo ? 'en directo' : `hace ${fmt(ahoraLive() - t)}`;
  if (vivo) $('ag-rango').value = t;
}
const fmt = s => s < 60 ? `${Math.round(s)} s` : `${Math.floor(s / 60)} min ${String(Math.round(s % 60)).padStart(2, '0')} s`;

// ---------- control ----------
function pon() {
  for (const b of $('ag-vista').children) b.classList.toggle('on', b.dataset.v === vista);
  for (const b of $('ag-ventana').children) b.classList.toggle('on', +b.dataset.w === ventana);
  $('ag-ventana').style.display = vista === 'carriles' ? '' : 'none';
}
$('ag-vista').onclick = e => { const v = e.target.dataset.v; if (v) { vista = v; guarda('ag_vista', v); pon(); } };
$('ag-ventana').onclick = e => { const w = +e.target.dataset.w; if (w) { ventana = w; guarda('ag_ventana', w); pon(); } };
$('ag-cerrar').onclick = () => cerrar();
$('ag-vivo').onclick = () => { vivo = true; $('ag-vivo').classList.add('on'); };
$('ag-rango').oninput = e => { vivo = false; Tfijo = +e.target.value; $('ag-vivo').classList.remove('on'); };
$('ag-lista').onclick = e => { const c = e.target.closest('.ag-c'); if (c) { sel = sel === c.dataset.id ? null : c.dataset.id; ultLista = 0; } };

function bajo(e) {
  const r = cv.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
  for (let i = rects.length - 1; i >= 0; i--) {
    const q = rects[i];
    if (q.circ ? Math.hypot(x - q.cx, y - q.cy) <= q.r + 4 : (x >= q.x && x <= q.x + q.w && y >= q.y && y <= q.y + q.h)) return {q, x, y};
  }
  return null;
}
cv.addEventListener('mousemove', e => {
  const h = bajo(e), tip = $('ag-tip');
  if (!h) { tip.style.display = 'none'; return; }
  const n = D.nodos.find(z => z.id === h.q.id) || {};
  let html;
  if (h.q.seg) html = `<b>${esc(h.q.seg.tool)}</b> · ${esc(fmt(h.q.seg.t1 - h.q.seg.t0))}${h.q.seg.ok ? '' : ' · falló'}<br>${esc(h.q.seg.det)}`;
  else if (h.q.evento) html = `<b>${h.q.evento.tipo === 'resultado' ? 'Resultado' : 'Encargo'}</b><br>${esc(h.q.evento.txt)}`;
  else html = `<b>${esc(n.nombre)}</b> · ${esc((ORIGEN[n.origen] || [''])[0])}<br>${esc(n.modelo)}${n.ruta ? ' · ' + esc(n.ruta) : ''}<br>${esc(corto(n.tarea, 140))}`;
  tip.innerHTML = html; tip.style.display = 'block';
  tip.style.left = Math.min(h.x + 14, cv.clientWidth - 370) + 'px'; tip.style.top = Math.min(h.y + 14, cv.clientHeight - 80) + 'px';
});
cv.addEventListener('mouseleave', () => { $('ag-tip').style.display = 'none'; });
cv.addEventListener('click', e => { const h = bajo(e); sel = h && h.q.id !== sel ? h.q.id : null; ultLista = 0; });

function abrir() {
  if (abierto) return;
  abierto = true; vivo = true; sel = null; pos = {}; ult = performance.now();
  document.body.classList.add('agentes');
  pon(); $('ag-vivo').classList.add('on');
  pide(); timer = setInterval(pide, 1000);
  raf = requestAnimationFrame(bucle);
}
function cerrar() {
  if (!abierto) return;
  abierto = false; clearInterval(timer); cancelAnimationFrame(raf);
  document.body.classList.remove('agentes');
}
addEventListener('keydown', e => {
  if (e.key !== 'Escape' || !abierto) return;
  if (document.activeElement === $('ag-di')) { $('ag-di').blur(); sel = null; ultLista = 0; return; }
  cerrar();
});
window.Agentes = {abrir, cerrar, alternar: () => (abierto ? cerrar() : abrir()), abierto: () => abierto};
const btn = $('b-ag'); if (btn) btn.onclick = () => window.Agentes.alternar();
