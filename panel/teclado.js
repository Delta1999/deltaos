// Modo teclado de DeltaOS: doble clic en la conversación abre un bocadillo para escribirle a Delta (Intro envía) y el
// modelo de OmniRoute contesta con las mismas herramientas (teclado.py). Se elige con un desplegable; el botón «OmniRoute»
// de la cabecera enseña los modelos, qué cupo gastan, cuándo se restablece y el gasto. Todo viaja por el WebSocket del panel
// (window.enviarWS): {teclado:{texto,modelo}} → teclado_res, {omni:1} → omni_res.
const $ = i => document.getElementById(i);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const guarda = (k, v) => { try { localStorage.setItem(k, v); } catch (e) {} };
const lee = (k, d) => { try { return localStorage.getItem(k) || d; } catch (e) { return d; } };
const num = n => Math.round(n).toLocaleString('es-ES');
const tok = n => n >= 1e6 ? (n / 1e6).toFixed(1).replace('.', ',') + ' M' : n >= 1e3 ? Math.round(n / 1e3) + ' k' : String(n || 0);
const usd = v => !v ? '0 $' : v < 0.01 ? '<0,01 $' : v.toFixed(2).replace('.', ',') + ' $';
const falta = s => {
  const d = s - Date.now() / 1000;
  if (d <= 0) return 'ya';
  const h = Math.floor(d / 3600), m = Math.floor(d % 3600 / 60);
  return h >= 24 ? `${Math.floor(h / 24)} d ${h % 24} h` : h ? `${h} h ${m} min` : `${Math.max(1, m)} min`;
};
const hace = s => { const d = Date.now() / 1000 - s; return d < 90 ? 'un momento' : d < 5400 ? Math.round(d / 60) + ' min' : Math.round(d / 3600) + ' h'; };
const cuando = s => new Date(s * 1000).toLocaleString('es-ES', {weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'});
const color = libre => libre == null ? '#8A8A8A' : libre < 10 ? '#E5484D' : libre < 50 ? '#E8A33D' : '#5FD38D';
const barra = libre => `<span class="om-b"><i style="width:${libre ?? 0}%;background:${color(libre)}"></i></span>`;

let INFO = null, modelo = lee('tk_modelo', ''), ocupado = false, timer = 0, ultimo = '';

const css = `
#tk{position:fixed;z-index:8;display:flex;flex-direction:column;gap:8px;padding:10px 12px;background:var(--surface-raised);border:1px solid var(--border-visible);
  border-radius:14px 14px 4px 14px;box-shadow:0 8px 28px rgba(0,0,0,.35);font-family:var(--sans)}
#tk[hidden]{display:none}
#tk .tk-top{display:flex;gap:10px;align-items:center;min-width:0}
#tk select{flex:1;min-width:0;font:12px var(--mono);color:var(--text-primary);background:transparent;border:1px solid var(--border-visible);border-radius:8px;padding:4px 6px}
#tk select option{background:var(--bg);color:var(--text-primary)}
#tk .tk-ayuda{font:10px var(--mono);letter-spacing:.06em;color:var(--text-secondary);text-transform:uppercase;white-space:nowrap}
#tk textarea{resize:none;border:0;outline:0;background:transparent;color:var(--text-display);font:17px/1.4 var(--sans);padding:2px 0;max-height:140px}
#tk textarea::placeholder{color:var(--text-secondary)}
#tk-est{font:11px var(--mono);color:var(--text-secondary);min-height:0}#tk-est:empty{display:none}
#omni{position:fixed;inset:0;z-index:20;background:var(--bg);color:var(--text-primary);display:none;flex-direction:column;font-family:var(--sans)}
#omni.on{display:flex}
#omni header{display:flex;align-items:center;gap:14px;padding:18px 28px;border-bottom:1px solid var(--border)}
#omni h2{font-size:22px;color:var(--text-display);font-weight:600}
#omni .om-sub{font:11px var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--text-secondary);flex:1}
#omni .om-x{background:none;border:1px solid var(--border-visible);border-radius:999px;color:var(--text-primary);font:12px var(--mono);padding:5px 14px;cursor:pointer}
#omni .om-c{overflow:auto;padding:22px 28px 40px;display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:26px;align-content:start}
#omni section{min-width:0}
#omni h3{font:11px var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--text-secondary);margin-bottom:10px;border-top:1px solid var(--border);padding-top:10px}
#omni .om-m{display:block;width:100%;text-align:left;background:none;border:1px solid var(--border);border-radius:10px;color:inherit;padding:9px 12px;margin-bottom:8px;cursor:pointer;font-family:var(--sans)}
#omni .om-m:hover{border-color:var(--text-display)}#omni .om-m.en{border-color:var(--text-display);background:var(--surface)}
#omni .om-m b{font-weight:600;font-size:15px;color:var(--text-display)}
#omni .om-m .om-t{font-size:13px;line-height:1.35;color:var(--text-secondary);margin-top:3px}
#omni .om-m .om-q{display:flex;align-items:center;gap:10px;margin-top:6px;font:11px var(--mono);color:var(--text-secondary)}
#omni .om-tag{font:10px var(--mono);letter-spacing:.08em;text-transform:uppercase;border:1px solid var(--border-visible);border-radius:999px;padding:1px 8px;margin-left:8px;color:var(--text-secondary);font-weight:400}
#omni .om-b{display:inline-block;width:90px;height:6px;border-radius:3px;background:var(--border);overflow:hidden;vertical-align:middle}
#omni .om-b i{display:block;height:100%}
#omni table{width:100%;border-collapse:collapse;font-size:13px}
#omni th{font:10px var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--text-secondary);text-align:left;padding:4px 8px 4px 0;font-weight:400}
#omni td{padding:6px 8px 6px 0;border-top:1px solid var(--border);vertical-align:middle}
#omni td.n,#omni th.n{text-align:right;font-variant-numeric:tabular-nums}
#omni .om-nota{font-size:12px;line-height:1.4;color:var(--text-secondary);margin-top:8px}
`;
const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);

// ---------- el bocadillo ----------
const form = document.createElement('form');
form.id = 'tk'; form.hidden = true; form.autocomplete = 'off';
form.innerHTML = `<div class="tk-top"><select id="tk-mod" aria-label="Modelo de OmniRoute"></select><span class="tk-ayuda">Intro envía · Esc cierra</span></div>
<textarea id="tk-txt" rows="1" maxlength="4000" placeholder="Escríbele a Delta…" aria-label="Mensaje para Delta"></textarea><div id="tk-est" aria-live="polite"></div>`;
document.body.appendChild(form);
const ta = $('tk-txt'), sel = $('tk-mod'), est = t => { $('tk-est').textContent = t || ''; coloca(); };

function opciones() {
  const ms = (INFO && INFO.modelos) || [{id: 'combo-fast-completion', nombre: 'Gemini 3.8 Flash · antigravity (con respaldo)', corto: 'interfaz, informes, órdenes básicas'}];
  if (!ms.some(m => m.id === modelo)) modelo = (INFO && INFO.defecto) || ms[0].id;
  sel.innerHTML = ms.map(m => `<option value="${esc(m.id)}" title="${esc(m.bueno || '')}">${esc(m.nombre)}${m.corto ? ' — ' + esc(m.corto) : ''}${m.libre === 0 ? ' (agotado)' : ''}</option>`).join('');
  sel.value = modelo;
}
function coloca() {
  const f = $('frases');
  if (!f || form.hidden) return;
  const r = f.getBoundingClientRect(), w = Math.max(280, Math.min(600, r.width - 32));
  form.style.width = w + 'px';
  form.style.left = Math.max(8, r.right - w - 16) + 'px';
  form.style.bottom = Math.max(8, innerHeight - r.bottom + 14) + 'px';
  f.style.paddingBottom = (form.offsetHeight + 24) + 'px';  // la conversación se sigue viendo por encima del bocadillo
}
function abre() {
  form.hidden = false; opciones(); coloca(); ta.focus();
  if (!INFO) window.enviarWS && window.enviarWS({omni: 1});
}
function cierra() {
  form.hidden = true;
  const f = $('frases'); if (f) f.style.paddingBottom = '';
}
function alto() { ta.style.height = 'auto'; ta.style.height = Math.min(ta.scrollHeight, 140) + 'px'; coloca(); }

$('frases').addEventListener('dblclick', e => {
  if (e.target.closest && e.target.closest('button,a,input,textarea,select')) return;
  try { getSelection().removeAllRanges(); } catch (x) {}
  if (form.hidden) abre(); else ta.focus();
});
sel.addEventListener('change', () => { modelo = sel.value; guarda('tk_modelo', modelo); });
ta.addEventListener('input', alto);
ta.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); }
  else if (e.key === 'Escape') { e.preventDefault(); cierra(); }
});
form.addEventListener('submit', e => {
  e.preventDefault();
  const t = ta.value.trim();
  if (ocupado || !t) return;
  if (!(window.enviarWS && window.enviarWS({teclado: {texto: t, modelo}}))) { est('Sin conexión con el panel.'); return; }
  ocupado = true; ultimo = t; ta.value = ''; ta.disabled = true; sel.disabled = true; alto();
  est('Pensando…');
});
addEventListener('teclado_res', e => {
  const r = e.detail || {};
  ocupado = false; ta.disabled = false; sel.disabled = false;
  if (r.devolver) ta.value = ultimo;  // no llegó a salir (ocupado o vacío): que no se pierda lo escrito
  est(r.ok ? '' : (r.msg || 'No ha salido bien.').slice(0, 160));
  alto(); if (!form.hidden) ta.focus();
});
addEventListener('resize', coloca);
addEventListener('keydown', e => { if (e.key === 'Escape' && $('omni').classList.contains('on')) cierraOmni(); });

// ---------- el panel «OmniRoute» ----------
const om = document.createElement('div');
om.id = 'omni'; om.setAttribute('role', 'dialog'); om.setAttribute('aria-label', 'OmniRoute');
om.innerHTML = `<header><h2>OmniRoute</h2><span class="om-sub" id="om-sub">modo teclado · modelos, cupos y gasto</span><button class="om-x" id="om-x">Cerrar</button></header><div class="om-c" id="om-c"></div>`;
document.body.appendChild(om);

function pintaOmni() {
  const d = INFO, c = $('om-c');
  if (!d) { c.innerHTML = '<section><div class="om-nota">Cargando…</div></section>'; return; }
  const modelos = d.modelos.map(m => `<button class="om-m${m.id === modelo ? ' en' : ''}" data-id="${esc(m.id)}">
    <b>${esc(m.nombre)}</b>${m.id === d.defecto ? '<span class="om-tag">por defecto</span>' : ''}${m.id === modelo ? '<span class="om-tag">en uso</span>' : ''}
    <div class="om-t">${esc(m.bueno)}</div>
    <div class="om-q">${m.cupo ? `${barra(m.libre)}<span>${esc(m.cupo)}: ${m.libre == null ? '—' : m.libre + ' % libre'}${m.reset ? ` · se restablece en <span data-r="${m.reset}">${falta(m.reset)}</span>` : ''}</span>`
      : '<span>Sin cupo medido (gratis o de pago por token)</span>'}</div></button>`).join('');
  const cuotas = d.cuotas.map(q => `<tr><td>${esc(q.recurso)}</td><td class="n">${q.pct ? q.usado + ' %' : num(q.usado) + ' / ' + num(q.total)}</td>
    <td>${barra(q.libre)}</td><td class="n">${q.libre == null ? '—' : q.libre + ' %'}</td>
    <td class="n">${q.reset ? `<span data-r="${q.reset}">${falta(q.reset)}</span><br><small style="color:var(--text-secondary)">${esc(cuando(q.reset))}</small>` : '—'}</td></tr>`).join('');
  const visto = Math.max(0, ...d.cuotas.map(q => q.visto || 0));  // la lectura más reciente: cada proveedor se refresca a su ritmo
  const g = d.gasto, p = d.propio;
  const gasto = g ? `<table><tr><th></th><th class="n">Peticiones</th><th class="n">Tokens</th><th class="n">Gasto</th></tr>${[['Hoy', 'hoy'], ['7 días', 'semana'], ['30 días', 'mes'], ['Total', 'total']]
      .map(([t, k]) => `<tr><td>${t}</td><td class="n">${num(g[k].n)}</td><td class="n">${tok(g[k].tok)}</td><td class="n">${usd(g[k].usd)}</td></tr>`).join('')}</table>
    <h3 style="margin-top:18px">Modelos de hoy</h3><table>${g.modelos.length ? g.modelos.map(m => `<tr><td>${esc(m.modelo)}</td><td class="n">${num(m.n)}</td><td class="n">${tok(m.tok)}</td><td class="n">${usd(m.usd)}</td></tr>`).join('')
      : '<tr><td>Nada todavía hoy.</td></tr>'}</table>`
    : '<div class="om-nota">Sin datos de gasto.</div>';
  c.innerHTML = `<section><h3>Modelos del modo teclado · toca uno para usarlo</h3>${modelos}
      <div class="om-nota">Doble clic en la conversación para escribir. Las búsquedas en Google siguen yendo por la API de Gemini.</div></section>
    <section><h3>Cupos y límites</h3><table><tr><th>Recurso</th><th class="n">Gastado</th><th></th><th class="n">Libre</th><th class="n">Se restablece</th></tr>${cuotas}</table>
      <div class="om-nota">${visto ? `Última lectura de OmniRoute hace ${hace(visto)}.` : ''} Antigravity da unas 140 peticiones al día de Gemini; cada herramienta que usa el modelo cuenta como una.</div></section>
    <section><h3>Gasto en OmniRoute (todo lo que pasa por él)</h3>${gasto}
      <div class="om-nota">Modo teclado: ${num(p.hoy)} peticiones hoy · ${num(p.semana)} en 7 días · ${tok(p.tin)} tokens enviados y ${tok(p.tout)} recibidos hoy.${d.clave ? '' : ' <b>Falta la clave de OmniRoute.</b>'}</div>
      ${d.error ? `<div class="om-nota">${esc(d.error)}</div>` : ''}</section>`;
  $('om-sub').textContent = `actualizado ${new Date(d.ahora * 1000).toLocaleTimeString('es-ES', {hour: '2-digit', minute: '2-digit', second: '2-digit'})}`;
}
function abreOmni() {
  om.classList.add('on'); pintaOmni();
  const pide = () => window.enviarWS && window.enviarWS({omni: 1});
  pide(); clearInterval(timer); timer = setInterval(() => { if (om.classList.contains('on')) pide(); }, 20000);
}
function cierraOmni() { om.classList.remove('on'); clearInterval(timer); }
addEventListener('omni_res', e => {
  INFO = e.detail; opciones();
  if (om.classList.contains('on')) pintaOmni();
});
setInterval(() => { if (om.classList.contains('on')) om.querySelectorAll('[data-r]').forEach(x => { x.textContent = falta(+x.dataset.r); }); }, 1000);
$('om-x').addEventListener('click', cierraOmni);
om.addEventListener('click', e => {
  const m = e.target.closest('.om-m');
  if (m) { modelo = m.dataset.id; guarda('tk_modelo', modelo); opciones(); pintaOmni(); }
});
const b = $('b-omni'); if (b) b.addEventListener('click', abreOmni);
