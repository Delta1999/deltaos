// Pantalla completa «Agentes»: se ve trabajar a cada agente (Delta, sesiones de Claude Code, subagentes y OmniRoute),
// qué herramienta usa, con qué modelo y de dónde viene (Claude / OmniRoute / Gemini), y cómo se pasan el trabajo.
// Tres vistas (constelación, carriles y sala de control: un panel por agente con sus pasos en vivo, agrupados por sesión) y una barra para rebobinar los últimos 20 min. Los datos vienen de
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
const glifo = t => /^(Read|Glob|Grep|LS|NotebookRead)$/.test(t) ? 'R' : /^(Write|Edit|MultiEdit|NotebookEdit)$/.test(t) ? 'E' : /^Bash/.test(t) ? '$'
  : /^(Agent|Task|SendMessage)$/.test(t) ? '⇆' : /^(Web|mcp__.*(search|fetch))/i.test(t) ? '⌕' : /^mcp__/.test(t) ? 'M' : '·';
const nomHerr = t => String(t).replace(/^mcp__/, '').split('__').pop();
const RADIO = {delta: 34, sesion: 27, sub: 19, router: 25};
const sats = {};  // «agente|inicio» -> {a, rad}: posición suavizada de cada herramienta que orbita a su agente
const titulo = n => (n.tipo === 'sub' && n.tarea ? n.tarea : n.nombre);
const nombreModelo = m => String(m || '?').replace(/^claude-/, '').replace(/^anthropic\//, '');

let D = null, recvT = 0, vivo = true, Tfijo = 0, vista = lee('ag_vista', 'const'), ventana = +lee('ag_ventana', 300);
let ocultos = new Set(JSON.parse(lee('ag_ocultos', '[]'))), abierto = false, timer = 0, raf = 0, sel = null, estilo = {}, rects = [], pos = {}, vistos = {}, ultLista = 0;
let cam = {x: 0, y: 0, z: 1}, drag = null, fijados = {}, giroDelta = 0;
const hexRgb = h => {
  const m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(h || '');
  return m ? `${parseInt(m[1], 16)},${parseInt(m[2], 16)},${parseInt(m[3], 16)}` : '217,119,87';
};

// ---------- DOM ----------
const css = `
#agentes{position:fixed;inset:0;z-index:20;background:radial-gradient(circle at 50% 44%,rgba(255,255,255,.028) 0%,transparent 68%),var(--bg);color:var(--text-primary);display:none;flex-direction:column;font-family:var(--sans)}
body.agentes #agentes{display:flex}
#agentes .ag-top{display:flex;align-items:center;gap:14px;padding:14px 22px;border-bottom:1px solid var(--border);background:color-mix(in srgb,var(--surface) 78%,transparent);backdrop-filter:blur(22px) saturate(160%);-webkit-backdrop-filter:blur(22px) saturate(160%);flex-wrap:wrap;z-index:4}
#agentes h2{font-size:28px;margin:0;color:var(--text-display);font-weight:600}
#agentes .ag-n{color:var(--text-secondary);font-family:var(--mono);font-size:12px;letter-spacing:.06em;text-transform:uppercase}
#agentes .ag-sp{flex:1}
#agentes .ag-leyenda{display:flex;gap:12px;font-family:var(--mono);font-size:11px;color:var(--text-secondary);text-transform:uppercase;letter-spacing:.06em}
#agentes .ag-leyenda i{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px;vertical-align:-1px;box-shadow:0 0 8px currentColor}
#agentes .ag-seg{display:flex;border:1px solid var(--border-visible);border-radius:999px;overflow:hidden;background:color-mix(in srgb,var(--bg) 50%,transparent)}
#agentes .ag-seg button,#agentes .ag-x{font-family:var(--mono);font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--text-secondary);background:transparent;border:0;padding:6px 13px;cursor:pointer;transition:background .16s ease,color .16s ease,border-color .16s ease}
#agentes .ag-seg button:hover,#agentes .ag-x:hover{color:var(--text-display)}
#agentes .ag-seg button.on{background:var(--text-primary);color:var(--bg);font-weight:600}
#agentes .ag-x{border:1px solid var(--border-visible);border-radius:999px;color:var(--text-primary)}
#agentes .ag-cuerpo{flex:1;display:flex;min-height:0}
#agentes .ag-lienzo{flex:1;position:relative;min-width:0;overflow:hidden}
#agentes canvas{position:absolute;inset:0;width:100%;height:100%;cursor:grab}
#agentes canvas.arrastrando{cursor:grabbing}
#agentes .ag-tip{position:absolute;pointer-events:none;background:color-mix(in srgb,var(--surface-raised) 86%,transparent);backdrop-filter:blur(20px) saturate(180%);-webkit-backdrop-filter:blur(20px) saturate(180%);border:1px solid var(--border-visible);border-radius:12px;padding:8px 12px;font-size:12px;max-width:360px;display:none;z-index:5;line-height:1.4;box-shadow:0 12px 32px rgba(0,0,0,.38)}
#agentes .ag-lista{width:340px;border-left:1px solid var(--border);background:color-mix(in srgb,var(--surface) 64%,transparent);backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);overflow:auto;padding:12px 14px;display:flex;flex-direction:column;gap:9px}
#agentes .ag-c{border:1px solid var(--border);background:color-mix(in srgb,var(--surface-raised) 74%,transparent);border-radius:14px;padding:10px 12px;cursor:pointer;transition:transform .16s ease,border-color .18s ease,box-shadow .18s ease}
#agentes .ag-c:hover{border-color:var(--border-visible);transform:translateY(-1px)}
#agentes .ag-c.sel{border-color:var(--text-primary);box-shadow:0 6px 22px rgba(0,0,0,.28),inset 0 1px 0 rgba(255,255,255,.1)}
#agentes .ag-c.off{opacity:.56}
#agentes .ag-c b{font-size:14px;font-weight:600;color:var(--text-display)}
#agentes .ag-c .l1{display:flex;align-items:center;gap:8px}
#agentes .ag-c .pt{width:8px;height:8px;border-radius:50%;flex:none;background:var(--text-disabled)}
#agentes .ag-c .pt.on{animation:agp 1s infinite;box-shadow:0 0 8px currentColor}
@keyframes agp{50%{opacity:.25}}
#agentes .ag-c .ch{font-family:var(--mono);font-size:10.5px;letter-spacing:.04em;color:var(--text-secondary);margin-top:6px;display:flex;gap:6px;flex-wrap:wrap}
#agentes .ag-c .ch span{border:1px solid var(--border-visible);border-radius:999px;padding:1px 8px;background:color-mix(in srgb,var(--bg) 42%,transparent)}
#agentes .ag-c .us{font-family:var(--mono);font-size:11.5px;color:var(--text-primary);margin-top:6px;word-break:break-word}
#agentes .ag-c .ta{font-size:12px;color:var(--text-secondary);margin-top:4px;line-height:1.35}
#agentes .ag-pie{display:flex;align-items:center;gap:14px;padding:11px 22px;border-top:1px solid var(--border);background:color-mix(in srgb,var(--surface) 78%,transparent);backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);z-index:4}
#agentes .ag-pie input{flex:1;accent-color:var(--text-primary)}
#agentes .ag-pie .ag-t{font-family:var(--mono);font-size:12px;color:var(--text-secondary);min-width:120px;text-align:right}
#agentes .ag-pie button{font-family:var(--mono);font-size:11px;letter-spacing:.08em;text-transform:uppercase;border:1px solid var(--border-visible);border-radius:999px;padding:6px 13px;background:transparent;color:var(--text-primary);cursor:pointer;transition:all .16s ease}
#agentes .ag-pie button.on{background:var(--accent);border-color:var(--accent);color:#fff;box-shadow:0 0 14px color-mix(in srgb,var(--accent) 55%,transparent)}
#agentes .ag-pm{position:absolute;left:0;top:0;width:min(356px,calc(100% - 16px));z-index:4;background:color-mix(in srgb,var(--surface-raised) 86%,transparent);backdrop-filter:blur(26px) saturate(190%);-webkit-backdrop-filter:blur(26px) saturate(190%);border:1px solid var(--border-visible);border-radius:18px;padding:14px;box-shadow:0 16px 42px rgba(0,0,0,.42),inset 0 1px 0 rgba(255,255,255,.12);display:none;flex-direction:column;gap:10px;visibility:hidden}
#agentes .ag-pm.on{display:flex}
#agentes .ag-pm .h{display:flex;align-items:center;gap:8px}
#agentes .ag-pm .h b{font-size:14px;font-weight:600;color:var(--text-display);flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#agentes .ag-pm .pt{width:8px;height:8px;border-radius:50%;flex:none;background:var(--text-disabled)}
#agentes .ag-pm .pt.on{animation:agp 1s infinite}
#agentes .ag-pm .x{border:0;background:transparent;color:var(--text-secondary);cursor:pointer;font-size:14px;padding:2px 4px}
#agentes .ag-pm .ch{font-family:var(--mono);font-size:10.5px;letter-spacing:.04em;color:var(--text-secondary);display:flex;gap:6px;flex-wrap:wrap}
#agentes .ag-pm .ch span{border:1px solid var(--border-visible);border-radius:999px;padding:1px 8px}
#agentes .ag-pm .vivo{font-family:var(--mono);font-size:11.5px;color:var(--text-primary);word-break:break-word;line-height:1.35}
#agentes .ag-pm form{display:flex;gap:6px}
#agentes .ag-pm input{flex:1;min-width:0;background:var(--bg);color:var(--text-primary);border:1px solid var(--border-visible);border-radius:999px;padding:7px 12px;font-family:var(--sans);font-size:13px}
#agentes .ag-pm form button{font-family:var(--mono);font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;border:1px solid var(--accent);border-radius:999px;padding:6px 11px;background:var(--accent);color:#fff;cursor:pointer}
#agentes .ag-pm .q,#agentes .ag-pm .ac{display:flex;gap:6px;flex-wrap:wrap}
#agentes .ag-pm .q button,#agentes .ag-pm .ac button{font-size:11.5px;border:1px solid var(--border-visible);border-radius:999px;padding:3px 10px;background:transparent;color:var(--text-primary);cursor:pointer}
#agentes .ag-pm .ac button.pel{border-color:#d9534f;color:#d9534f}
#agentes .ag-pm .ac button.on{background:var(--text-primary);color:var(--bg)}
#agentes .ag-pm .res{font-size:12px;color:var(--text-secondary);min-height:0;word-break:break-word}
#agentes .ag-pm .res:empty{display:none}
#agentes .ag-pm .ch span.mod,#agentes .sl-p .mod{font-family:var(--mono);font-size:11px;border-radius:999px;padding:1px 9px;color:#fff;white-space:nowrap}
#agentes .feed{font-family:var(--mono);font-size:11px;line-height:1.55;color:var(--text-secondary);display:flex;flex-direction:column;min-width:0}
#agentes .feed div{display:flex;gap:6px;min-width:0}
#agentes .feed i{font-style:normal;font-weight:700;width:11px;text-align:center;flex:none}
#agentes .feed .x{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#agentes .feed em{font-style:normal;flex:none;opacity:.75}
#agentes .feed .now{color:var(--text-primary)}
#agentes .feed .now .x::after{content:'▍';animation:agp 1s infinite;margin-left:2px}
#agentes .feed .mal{color:#E5484D}
#agentes .txt{font-size:12px;line-height:1.4;color:var(--text-secondary);border-left:2px solid var(--border-visible);padding-left:8px;max-height:4.3em;overflow:hidden;word-break:break-word}
#agentes .txt:empty{display:none}
#agentes .ag-pm .txt{max-height:15em;overflow:auto;white-space:pre-wrap;user-select:text}
#agentes .sl-m .tx{max-height:6.5em;overflow:hidden;cursor:pointer;white-space:pre-wrap}
#agentes .sl-m.abierto .tx{max-height:none}
#agentes .sl-m .mas{font-family:var(--mono);font-size:10px;color:var(--text-secondary)}
#agentes .ag-sala{position:absolute;inset:0;z-index:1;background:var(--bg);display:none;grid-template-columns:minmax(0,1fr) 300px}
#agentes.sala .ag-sala{display:grid}
#agentes.sala .ag-lista{display:none}
#agentes .sl-grupos{overflow:auto;padding:14px 18px;display:flex;flex-direction:column;gap:18px}
#agentes .sl-gr h3{margin:0 0 8px;font-size:14px;font-weight:600;color:var(--text-display);display:flex;gap:10px;align-items:baseline;min-width:0}
#agentes .sl-gr h3 small{font-family:var(--mono);font-size:10.5px;letter-spacing:.04em;color:var(--text-secondary);font-weight:400;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#agentes .sl-rej{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:10px}
#agentes .sl-p{border:1px solid var(--border);background:var(--surface);border-radius:12px;padding:9px 11px;display:flex;flex-direction:column;gap:6px;cursor:pointer;min-width:0}
#agentes .sl-p.off{opacity:.55}
#agentes .sl-p.sel{border-color:var(--text-primary)}
#agentes .sl-p .l1{display:flex;align-items:center;gap:8px;min-width:0}
#agentes .sl-p .l1 b{font-size:13.5px;font-weight:600;color:var(--text-display);flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#agentes .sl-p .pt{width:8px;height:8px;border-radius:50%;flex:none;background:var(--text-disabled)}
#agentes .sl-p .pt.on{animation:agp 1s infinite}
#agentes .sl-p .ch{font-family:var(--mono);font-size:10.5px;letter-spacing:.03em;color:var(--text-secondary);display:flex;gap:8px;flex-wrap:wrap}
#agentes .sl-bar{height:2px;border-radius:2px;background:var(--border);position:relative;overflow:hidden}
#agentes .sl-bar i{position:absolute;top:0;bottom:0;width:35%;left:-35%;display:none}
#agentes .sl-bar.on i{display:block;animation:slb 1.3s linear infinite}
@keyframes slb{to{left:100%}}
#agentes .sl-tl{display:flex;gap:2px;height:6px}
#agentes .sl-tl i{border-radius:2px;min-width:3px}
#agentes .sl-p .feed{height:7.75em;justify-content:flex-end;overflow:hidden}
#agentes .sl-msg{border-left:1px solid var(--border);overflow:auto;padding:12px;display:flex;flex-direction:column;gap:7px}
#agentes .sl-msg .sl-t{font-family:var(--mono);font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--text-secondary)}
#agentes .sl-m{font-size:12px;line-height:1.35;padding:7px 9px;border-radius:10px;border:1px solid var(--border);background:var(--surface);word-break:break-word}
#agentes .sl-m.nuevo{animation:slin .5s}
@keyframes slin{from{opacity:0;transform:translateY(-8px)}}
#agentes .sl-m .de{font-family:var(--mono);font-size:10.5px;letter-spacing:.03em;margin-bottom:2px}
#agentes .sl-m .cu{font-family:var(--mono);font-size:10px;color:var(--text-secondary);margin-top:3px}
#agentes .ag-vacio{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:var(--text-secondary);font-family:var(--mono);font-size:13px;pointer-events:none}
@media(max-width:1400px){#agentes .ag-ley2{display:none}}
#agentes .ag-tit{display:flex;flex-direction:column;align-items:flex-start;gap:6px}
#agentes .ag-nueva{display:flex;align-items:center;justify-content:center;width:34px;height:28px;border:1px solid var(--border-visible);border-radius:999px;background:transparent;color:var(--text-primary);cursor:pointer;padding:0}
#agentes .ag-nueva:hover,#agentes .ag-nueva.on{background:var(--text-primary);color:var(--bg)}
#agentes .nv{position:fixed;z-index:25;width:min(460px,calc(100vw - 16px));max-height:72vh;overflow:auto;background:var(--surface-raised);border:1px solid var(--border-visible);border-radius:14px;padding:12px;box-shadow:0 10px 30px rgba(0,0,0,.25);display:none;flex-direction:column;gap:10px}
#agentes .nv.on{display:flex}
#agentes .nv .nv-seg{display:flex;border:1px solid var(--border-visible);border-radius:999px;overflow:hidden;align-self:flex-start}
#agentes .nv .nv-seg button{font-family:var(--mono);font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--text-secondary);background:transparent;border:0;padding:6px 14px;cursor:pointer}
#agentes .nv .nv-seg button.on{background:var(--text-primary);color:var(--bg)}
#agentes .nv .nv-s{font-family:var(--mono);font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--text-secondary);margin-bottom:5px}
#agentes .nv .nv-g{display:flex;flex-wrap:wrap;gap:6px}
#agentes .nv .nv-i{font-size:12px;border:1px solid var(--border-visible);border-radius:999px;padding:4px 11px;background:transparent;color:var(--text-primary);cursor:pointer}
#agentes .nv .nv-i:hover{border-color:var(--text-primary)}
#agentes .nv .nv-i.modo{border-color:var(--accent);color:var(--accent)}
#agentes .nv .nv-i.on{background:var(--text-primary);border-color:var(--text-primary);color:var(--bg)}
#agentes .nv .nv-mod{font-family:var(--mono);font-size:10.5px;letter-spacing:.04em;color:var(--text-secondary)}
#agentes .nv .nv-d{font-size:12px;line-height:1.4;color:var(--text-secondary);border-top:1px solid var(--border);padding-top:9px;min-height:50px}
#agentes .nv .nv-h{display:flex;align-items:center;gap:8px}
#agentes .nv .nv-h b{font-size:14px;color:var(--text-display);flex:1}
#agentes .nv .nv-h button{border:0;background:transparent;color:var(--text-secondary);cursor:pointer;font-size:15px}
#agentes .nv textarea{width:100%;box-sizing:border-box;background:var(--bg);color:var(--text-primary);border:1px solid var(--border-visible);border-radius:10px;padding:8px 10px;font-family:var(--sans);font-size:13px;resize:vertical}
#agentes .nv form{display:flex;flex-direction:column;gap:7px;align-items:flex-end}
#agentes .nv form button{font-family:var(--mono);font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;border:1px solid var(--accent);border-radius:999px;padding:6px 14px;background:var(--accent);color:#fff;cursor:pointer}
#agentes .nv .nv-res{font-size:12px;color:var(--text-secondary)}
@media(max-width:900px){#agentes .ag-lista,#agentes .ag-leyenda,#agentes .sl-msg{display:none}#agentes .ag-sala{grid-template-columns:1fr}}
`;
const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);
const raiz = document.createElement('div');
raiz.id = 'agentes';
raiz.innerHTML = `
<div class="ag-top"><div class="ag-tit"><h2 class="dot">AGENTES</h2><button class="ag-nueva" id="ag-nueva" title="Nueva conversación" aria-label="Nueva conversación"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M4 5h16v11H9l-5 4z"/><path d="M12 8v5M9.5 10.5h5"/></svg></button></div><span class="ag-n" id="ag-n"></span><button class="ag-x" id="ag-oc" style="display:none"></button><span class="ag-sp"></span>
  <span class="ag-leyenda"><span><i style="background:${ORIGEN.claude[1]}"></i>Claude</span><span><i style="background:${ORIGEN.omniroute[1]}"></i>OmniRoute</span><span><i style="background:${ORIGEN.gemini[1]}"></i>Gemini</span></span>
  <span class="ag-leyenda ag-ley2"><span><i style="background:#5B9BF6"></i>R leer</span><span><i style="background:#E8A33D"></i>E editar</span><span><i style="background:#5FD38D"></i>$ shell</span><span><i style="background:#A78BFA"></i>⇆ agente</span><span><i style="background:#3CC8C8"></i>⌕ web</span></span>
  <span class="ag-seg" id="ag-vista"><button data-v="const">Constelación</button><button data-v="carriles">Carriles</button><button data-v="sala">Sala</button></span>
  <span class="ag-seg" id="ag-ventana" title="Ancho de la vista de carriles"><button data-w="120">2 min</button><button data-w="300">5 min</button><button data-w="1200">20 min</button></span>
  <button class="ag-x" id="ag-cerrar" title="Esc">Cerrar ✕</button></div>
<div class="ag-cuerpo"><div class="ag-lienzo" id="ag-lienzo"><canvas id="ag-cv"></canvas><div class="ag-sala" id="ag-sala"><div class="sl-grupos" id="sl-g"></div><div class="sl-msg"><div class="sl-t">Mensajes</div><div id="sl-m" style="display:flex;flex-direction:column;gap:7px"></div></div></div><div class="ag-vacio" id="ag-vacio"></div><div class="ag-tip" id="ag-tip"></div><div class="ag-pm" id="ag-pm"></div></div>
  <div class="ag-lista" id="ag-lista"></div></div>
<div class="ag-pie"><button id="ag-vivo" class="on">● En directo</button><input type="range" id="ag-rango" min="0" max="1" step="0.5" value="1"><span class="ag-t" id="ag-t"></span></div>
<div class="nv" id="nv"></div>`;
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
  if (ocultos.has(n.id)) return false;
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
      ${usa ? `<div class="us">▸ ${esc(corto(usa, 90))}</div>` : ''}${n.tarea && !(n.tipo === 'sub') ? `<div class="ta">${esc(corto(n.tarea, 110))}</div>` : ''}${n.padre && D.nodos.find(z => z.id === n.padre) ? `<div class="ta">↳ de ${esc(corto(titulo(D.nodos.find(z => z.id === n.padre)), 40))}</div>` : ''}</div>`;
  }).join('');
  menuVivo(t);
  $('ag-oc').style.display = ocultos.size ? '' : 'none'; $('ag-oc').textContent = `Mostrar ${ocultos.size} oculto${ocultos.size > 1 ? 's' : ''}`;
  $('ag-vacio').textContent = vis.length <= 1 ? 'Sin agentes trabajando ahora mismo. Rebobina la barra para ver lo de hace unos minutos.' : '';
}

// ---------- menú del agente (junto a su esfera) ----------
let menuDe = null;
const RAPIDAS = [['¿Qué haces?', '¿Qué estás haciendo ahora mismo? Respóndeme en una frase.'], ['Resume', 'Resume en pocas frases lo que has hecho hasta ahora.'],
                 ['Sigue', 'Sigue con lo que estabas haciendo.']];
const copia = async (txt, ok) => { try { await navigator.clipboard.writeText(txt); $('pm-res').textContent = ok; } catch (e) { $('pm-res').textContent = 'No he podido copiar.'; } };
const esAcp = n => n.hablable && n.id !== 'delta';
// los últimos pasos de un agente hasta el instante t: ▸ el que está en marcha (con su tiempo corriendo), ✓ hechos, ✗ fallidos
function pasos(n, t, k) {
  const l = n.segs.filter(g => g.t0 <= t).slice(-k);
  if (!l.length) return '<div><span class="x">Sin herramientas todavía.</span></div>';
  return l.map(g => {
    const act = t <= (g.abierto && vivo ? Infinity : g.t1) && (g.abierto || t < g.t1);
    return `<div class="${act ? 'now' : g.ok ? '' : 'mal'}"><i style="color:${colorHerr(g.tool)}">${esc(glifo(g.tool))}</i><span class="x">${act ? '▸' : g.ok ? '✓' : '✗'} ${esc(nomHerr(g.tool))}${g.det ? ': ' + esc(g.det) : ''}</span><em>${esc(fmt(Math.max(0, (act ? t : g.t1) - g.t0)))}</em></div>`;
  }).join('');
}
function menuArma(n) {
  menuDe = n.id;
  const m = $('ag-pm'), o = ORIGEN[n.origen] || ORIGEN.claude;
  m.innerHTML = `<div class="h"><span class="pt" id="pm-pt"></span><b>${esc(corto(titulo(n), 34))}</b><button class="x" data-a="cerrar" title="Cerrar el menú">✕</button></div>
    <div class="ch"><span class="mod" style="background:${o[1]}">${esc(nombreModelo(n.modelo))}</span><span style="border-color:${o[1]};color:${o[1]}">${o[0]}</span>${n.tipo === 'sub' && n.tarea ? `<span>${esc(corto(n.nombre, 20))}</span>` : ''}${n.ruta ? `<span>${esc(corto(n.ruta, 26))}</span>` : ''}</div>
    <div class="vivo" id="pm-vivo"></div>
    <div class="feed" id="pm-feed"></div><div class="txt" id="pm-txt"></div>
    ${n.hablable ? `<form id="pm-f" autocomplete="off"><input id="pm-i" maxlength="2000" placeholder="Decirle algo…"><button type="submit">Enviar</button></form>
      <div class="q">${RAPIDAS.map(([t], i) => `<button data-q="${i}">${esc(t)}</button>`).join('')}</div>` : ''}
    <div class="res" id="pm-res"></div>
    <div class="ac">${esAcp(n) ? '<button class="pel" data-a="cancelar">Cancelar tarea</button>' : ''}${n.tarea ? '<button data-a="tarea">Copiar tarea</button>' : ''}${n.texto ? '<button data-a="resp">Copiar respuesta</button>' : ''}<button data-a="id">Copiar id</button>${n.id !== 'delta' ? '<button data-a="ocultar">Ocultar</button>' : ''}</div>`;
  m.classList.add('on');
  const i = $('pm-i'); if (i) setTimeout(() => i.focus(), 30);
}
function menuVivo(t) {
  const n = sel && D.nodos.find(x => x.id === sel);
  if (!n || ocultos.has(n.id)) { menuCierra(); return; }
  if (menuDe !== n.id) menuArma(n);
  const s = estadoEn(n, t), on = activo(s.e), o = ORIGEN[n.origen] || ORIGEN.claude;
  $('pm-pt').className = 'pt' + (on ? ' on' : ''); $('pm-pt').style.background = on ? o[1] : '';
  const usa = s.seg ? `${s.seg.tool}${s.seg.det ? ': ' + s.seg.det : ''}` : '';
  $('pm-vivo').textContent = `${s.e}${usa ? ' ▸ ' + corto(usa, 80) : ''}${n.tok ? ` · ${n.parcial ? '≥' : ''}${n.tok} tok` : ''}`;
  $('pm-feed').innerHTML = pasos(n, t, 6);
  const tx = n.texto || '', pt = $('pm-txt'); if (pt.dataset.t !== tx) { pt.dataset.t = tx; pt.textContent = tx; }  // entero y solo si cambia (para no perder el scroll)
}
function menuCierra() { menuDe = null; $('ag-pm').classList.remove('on'); $('ag-pm').innerHTML = ''; }
function menuPos(W, H) {
  const m = $('ag-pm'); if (!menuDe) return;
  const q = vista === 'sala' ? salaRect(menuDe) : rects.find(r => r.id === menuDe && !r.seg && !r.evento);
  if (!q) { m.style.visibility = 'hidden'; return; }
  const w = m.offsetWidth, h = m.offsetHeight;
  let x, y;
  if (q.circ) { x = q.cx + q.r + 56; if (x + w > W - 8) x = q.cx - q.r - 56 - w; y = q.cy - h / 2; }
  else { x = q.x + q.w + 10; y = q.y; }
  x = Math.max(8, Math.min(x, W - w - 8)); y = Math.max(8, Math.min(y, H - h - 8));
  m.style.transform = `translate(${x}px,${y}px)`; m.style.visibility = 'visible';
}
const manda = o => { $('pm-res').textContent = window.enviarWS && window.enviarWS({decir: {a: menuDe, ...o}}) ? 'Enviando…' : 'Sin conexión con el panel.'; };
$('ag-pm').addEventListener('submit', e => {
  e.preventDefault();
  const t = $('pm-i').value.trim(); if (t) manda({texto: t});
});
$('ag-pm').addEventListener('click', e => {
  const n = D && D.nodos.find(x => x.id === menuDe), b = e.target.closest('button'); if (!b || !n) return;
  if (b.dataset.q) { manda({texto: RAPIDAS[+b.dataset.q][1]}); return; }
  const a = b.dataset.a;
  if (a === 'cerrar') { sel = null; menuCierra(); }
  else if (a === 'cancelar') manda({accion: 'cancelar'});
  else if (a === 'tarea') copia(n.tarea, 'Tarea copiada.');
  else if (a === 'resp') copia(n.texto, 'Respuesta copiada.');
  else if (a === 'id') copia(n.id, 'Id copiado.');
  else if (a === 'ocultar') { ocultos.add(n.id); guarda('ag_ocultos', JSON.stringify([...ocultos])); sel = null; menuCierra(); }
  ultLista = 0;
});
$('ag-oc').onclick = () => { ocultos.clear(); guarda('ag_ocultos', '[]'); ultLista = 0; };
addEventListener('decir_res', e => {
  const r = e.detail || {}, el = $('pm-res'), i = $('pm-i');
  if (el) el.textContent = r.msg || '';
  if (r.ok && i) i.value = '';
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

function pintaOrbeDelta3D(cx, cy, R, t, on, voz, colHex, dt) {
  giroDelta += dt * (0.28 + (on ? 0.55 : 0) + voz * 0.65);
  const rgbFg = document.documentElement.dataset.tema === 'ios' ? '28,28,30' : '242,242,242';
  const rgbAc = hexRgb(colHex || '#A78BFA');
  const PAR = 9, SEG = 36, MER = 8, MSEG = 28, TILT = 0.38, DIST = 3.6, NIV = 4;
  const pathsP = Array.from({length: NIV}, () => new Path2D());
  const pathsM = Array.from({length: NIV}, () => new Path2D());
  const proy = (lat, lon) => {
    const def = 1 + Math.sin(lat * 3 + t * 3.2) * Math.cos(lon * 2 - t * 1.9) * (on ? 0.11 + voz * 0.12 : 0.025)
      + Math.sin(lat * 2 - t * 1.1) * 0.025;
    const cl = Math.cos(lat) * def, sl = Math.sin(lat) * def, a = lon + giroDelta;
    const px = cl * Math.cos(a), y = sl, z = cl * Math.sin(a);
    const y2 = y * Math.cos(TILT) - z * Math.sin(TILT), z2 = y * Math.sin(TILT) + z * Math.cos(TILT);
    const f = DIST / (DIST - z2);
    return [cx + px * R * f, cy - y2 * R * f, z2];
  };
  const tramo = (arr, p, q) => {
    const z = (p[2] + q[2]) / 2;
    const idx = Math.min(NIV - 1, Math.max(0, Math.round((z + 1) / 2 * (NIV - 1))));
    arr[idx].moveTo(p[0], p[1]); arr[idx].lineTo(q[0], q[1]);
  };
  // Halo de fondo volumétrico
  const gBg = ctx.createRadialGradient(cx, cy, R * 0.1, cx, cy, R * 1.55);
  gBg.addColorStop(0, `rgba(${rgbAc},${on ? .28 : .12})`);
  gBg.addColorStop(0.65, `rgba(${rgbAc},${on ? .08 : .02})`);
  gBg.addColorStop(1, `rgba(${rgbAc},0)`);
  ctx.fillStyle = gBg;
  ctx.beginPath(); ctx.arc(cx, cy, R * 1.55, 0, Math.PI * 2); ctx.fill();

  for (let i = 0; i < PAR; i++) {
    const lat = (i - (PAR - 1) / 2) / ((PAR - 1) / 2) * 1.35;
    let p = proy(lat, 0);
    for (let j = 1; j <= SEG; j++) {
      const q = proy(lat, j / SEG * Math.PI * 2);
      tramo(pathsP, p, q); p = q;
    }
  }
  for (let i = 0; i < MER; i++) {
    const lon = i / MER * Math.PI * 2;
    let p = proy(-1.45, lon);
    for (let j = 1; j <= MSEG; j++) {
      const q = proy(-1.45 + j / MSEG * 2.9, lon);
      tramo(pathsM, p, q); p = q;
    }
  }
  for (let i = 0; i < NIV; i++) {
    const k = i / (NIV - 1);
    ctx.strokeStyle = `rgba(${rgbFg},${0.08 + 0.32 * k * k})`;
    ctx.lineWidth = 0.6 + 0.45 * k;
    ctx.stroke(pathsM[i]);
    ctx.strokeStyle = `rgba(${rgbFg},${0.16 + 0.72 * k * k})`;
    ctx.lineWidth = 0.8 + 0.65 * k;
    ctx.stroke(pathsP[i]);
  }
  // Anillo ecuatorial reactivo (rojo Nothing / acento vivo)
  const latAnillo = Math.sin(t * 0.65) * 0.95;
  const ani = Array.from({length: NIV}, () => new Path2D());
  let pA = proy(latAnillo, 0);
  for (let j = 1; j <= SEG; j++) {
    const qA = proy(latAnillo, j / SEG * Math.PI * 2);
    tramo(ani, pA, qA); pA = qA;
  }
  const rgbAnillo = on ? '215,25,33' : rgbAc;
  for (let i = 0; i < NIV; i++) {
    const k = i / (NIV - 1);
    ctx.strokeStyle = `rgba(${rgbAnillo},${0.25 + 0.72 * k})`;
    ctx.lineWidth = (on ? 1.5 : 1.1) * (0.65 + 0.55 * k);
    ctx.stroke(ani[i]);
  }
}

function pintaEsferaAgente3D(cx, cy, r, colHex, estado, on, esSel, tipo) {
  const rgb = hexRgb(colHex);
  const ms = performance.now();
  // Halo exterior cuando está trabajando o seleccionado
  if (on || esSel) {
    const gHalo = ctx.createRadialGradient(cx, cy, r * 0.4, cx, cy, r * (on ? 1.85 : 1.45));
    gHalo.addColorStop(0, `rgba(${rgb},${on ? .34 : .22})`);
    gHalo.addColorStop(0.6, `rgba(${rgb},${on ? .10 : .04})`);
    gHalo.addColorStop(1, `rgba(${rgb},0)`);
    ctx.fillStyle = gHalo;
    ctx.beginPath(); ctx.arc(cx, cy, r * (on ? 1.85 : 1.45), 0, Math.PI * 2); ctx.fill();
  }
  // Esfera 3D con iluminación especular desplazada y rim-light
  const gEsf = ctx.createRadialGradient(cx - r * 0.34, cy - r * 0.36, r * 0.08, cx, cy, r);
  gEsf.addColorStop(0, `rgba(255,255,255,${on ? .92 : .55})`);
  gEsf.addColorStop(0.24, `rgba(${rgb},${on ? .92 : .52})`);
  gEsf.addColorStop(0.72, `rgba(${rgb},${on ? .36 : .20})`);
  gEsf.addColorStop(1, `rgba(10,10,14,${on ? .92 : .85})`);
  ctx.fillStyle = gEsf;
  ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.fill();

  // Borde de cristal (Fresnel rim)
  ctx.strokeStyle = `rgba(${rgb},${on ? .95 : esSel ? .85 : .48})`;
  ctx.lineWidth = esSel ? 2.4 : on ? 1.9 : 1.2;
  ctx.stroke();

  // Meridiano sutil interno para dar volumen a las sesiones y al router
  if (tipo !== 'sub') {
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(ms / (on ? 1800 : 4200));
    ctx.strokeStyle = `rgba(255,255,255,${on ? .22 : .09})`;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.ellipse(0, 0, r * 0.88, r * 0.34, 0.35, 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();
  }

  // Anillos orbitales inclinados en 3D cuando está pensando/usando/orquestando
  if (on) {
    ctx.save();
    ctx.translate(cx, cy);
    const vel = estado === 'pensando' ? 0.0018 : estado === 'orquestando' ? 0.0034 : 0.0026;
    ctx.rotate(ms * vel);
    ctx.strokeStyle = `rgba(${rgb},.78)`;
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    ctx.ellipse(0, 0, r * 1.34, r * 0.44, 0.42, 0, Math.PI * 1.45);
    ctx.stroke();
    if (estado === 'orquestando' || tipo === 'sesion') {
      ctx.rotate(-ms * vel * 1.7);
      ctx.strokeStyle = `rgba(255,255,255,.45)`;
      ctx.lineWidth = 1.1;
      ctx.beginPath();
      ctx.ellipse(0, 0, r * 1.22, r * 0.38, -0.55, 0, Math.PI * 1.15);
      ctx.stroke();
    }
    ctx.restore();
  }
}

function bezierPt(ax, ay, cx, cy, bx, by, u) {
  const m = 1 - u;
  return [m * m * ax + 2 * m * u * cx + u * u * bx, m * m * ay + 2 * m * u * cy + u * u * by];
}

function pintaConst(t, W, H, dt) {
  const vis = D.nodos.filter(n => visible(n, t)), por = new Map(vis.map(n => [n.id, n]));
  const obj = objetivos(vis, W, H);
  for (const n of vis) {
    const o = fijados[n.id] || obj[n.id] || [W / 2, H / 2], p = pos[n.id];
    if (!p) { const pa = pos[n.padre]; pos[n.id] = {x: pa ? pa.x : o[0], y: pa ? pa.y : o[1]}; }
    const q = pos[n.id], k = drag && drag.id === n.id ? 1 : 1 - Math.pow(0.0015, dt);
    q.x += (o[0] - q.x) * k; q.y += (o[1] - q.y) * k;
  }
  rects = [];
  const est = new Map(vis.map(n => [n.id, estadoEn(n, t)]));
  const w2s = (wx, wy) => [(wx - W / 2) * cam.z + W / 2 + cam.x, (wy - H / 2) * cam.z + H / 2 + cam.y];

  ctx.save();
  ctx.translate(W / 2 + cam.x, H / 2 + cam.y);
  ctx.scale(cam.z, cam.z);
  ctx.translate(-W / 2, -H / 2);

  // Sinapsis curvas entre quien encarga y quien trabaja + tren de impulsos luminosos cuando está activo
  const curvas = new Map();
  for (const n of vis) {
    const pid = n.padre && por.has(n.padre) ? n.padre : null;
    const a = pos[pid], b = pos[n.id];
    if (!a || !b) continue;
    const stH = est.get(n.id), on = activo(stH.e), c = (ORIGEN[n.origen] || ORIGEN.claude)[1], rgb = hexRgb(c);
    const dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy) || 1;
    const nx = -dy / d, ny = dx / d;
    const curvatura = Math.min(44, d * 0.16) * ((n.id.charCodeAt(0) % 2) ? 1 : -1);
    const mx = (a.x + b.x) / 2 + nx * curvatura, my = (a.y + b.y) / 2 + ny * curvatura;
    curvas.set(`${pid}->${n.id}`, [a.x, a.y, mx, my, b.x, b.y]);
    curvas.set(`${n.id}->${pid}`, [b.x, b.y, mx, my, a.x, a.y]);

    const grad = ctx.createLinearGradient(a.x, a.y, b.x, b.y);
    grad.addColorStop(0, `rgba(${rgb},${on ? .35 : .16})`);
    grad.addColorStop(0.5, `rgba(${rgb},${on ? .88 : .32})`);
    grad.addColorStop(1, `rgba(${rgb},${on ? .95 : .42})`);
    ctx.strokeStyle = grad;
    ctx.lineWidth = on ? 2.4 : 1.3;
    ctx.setLineDash([]);
    ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.quadraticCurveTo(mx, my, b.x, b.y); ctx.stroke();

    // Tren de impulsos sinápticos continuos mientras el hijo trabaja o usa una herramienta
    if (on) {
      const colPulso = stH.seg ? colorHerr(stH.seg.tool) : c;
      for (let k = 0; k < 2; k++) {
        const u = ((performance.now() / 1100) + k * 0.5) % 1;
        const [px, py] = bezierPt(a.x, a.y, mx, my, b.x, b.y, u);
        ctx.fillStyle = colPulso;
        ctx.shadowColor = colPulso; ctx.shadowBlur = 12;
        ctx.beginPath(); ctx.arc(px, py, 3.2, 0, Math.PI * 2); ctx.fill();
      }
      ctx.shadowBlur = 0;
    }

    const rr = (RADIO[n.tipo] || 20) + 6;
    if (d > rr + 30) {
      const [tx, ty] = bezierPt(a.x, a.y, mx, my, b.x, b.y, Math.max(0, 1 - rr / d));
      const [px0, py0] = bezierPt(a.x, a.y, mx, my, b.x, b.y, Math.max(0, 1 - (rr + 10) / d));
      const ad = Math.hypot(tx - px0, ty - py0) || 1, ux = (tx - px0) / ad, uy = (ty - py0) / ad;
      ctx.fillStyle = `rgba(${rgb},${on ? .92 : .45})`;
      ctx.beginPath(); ctx.moveTo(tx, ty); ctx.lineTo(tx - ux * 8 - uy * 4.5, ty - uy * 8 + ux * 4.5); ctx.lineTo(tx - ux * 8 + uy * 4.5, ty - uy * 8 - ux * 4.5); ctx.fill();
    }
    const rot = n.tipo === 'sub' ? n.nombre : n.padre === 'delta' ? 'ACP' : '';
    if (rot && d > 95) {
      const [lx, ly] = bezierPt(a.x, a.y, mx, my, b.x, b.y, 0.5);
      ctx.globalAlpha = on ? .92 : .55; ctx.font = `9.5px ${estilo.mono}`; ctx.textAlign = 'center'; ctx.fillStyle = estilo.dim;
      ctx.fillText(corto(rot, 20), lx, ly - 7);
    }
  }
  const rt = por.get('omniroute');  // el enrutador: línea discontinua hacia lo que sirve
  if (rt) for (const n of vis) if (n.origen === 'omniroute' && n.tipo !== 'router' && pos[n.id] && pos.omniroute) {
    const on = activo(est.get(n.id).e);
    ctx.strokeStyle = ORIGEN.omniroute[1]; ctx.globalAlpha = on ? .52 : .14; ctx.lineWidth = on ? 1.4 : 1; ctx.setLineDash([4, 6]);
    ctx.beginPath(); ctx.moveTo(pos[n.id].x, pos[n.id].y); ctx.lineTo(pos.omniroute.x, pos.omniroute.y); ctx.stroke();
  }
  ctx.setLineDash([]); ctx.globalAlpha = 1;

  // Mensajes y resultados: cometas de luz que viajan por la sinapsis curva con estela
  for (const e of D.eventos) {
    const d = t - e.t;
    if (d < 0 || d > 2.6 || !pos[e.de] || !pos[e.a] || !por.has(e.de) || !por.has(e.a)) continue;
    const u = Math.min(1, d / 1.45), a = pos[e.de], b = pos[e.a];
    const crv = curvas.get(`${e.de}->${e.a}`) || [a.x, a.y, (a.x + b.x) / 2, (a.y + b.y) / 2 - 24, b.x, b.y];
    const [x, y] = bezierPt(crv[0], crv[1], crv[2], crv[3], crv[4], crv[5], u);
    const c = e.tipo === 'resultado' ? VERDE : (ORIGEN[por.get(e.a).origen] || ORIGEN.claude)[1], rgb = hexRgb(c);
    // Estela del cometa
    for (let s = 1; s <= 5; s++) {
      const us = Math.max(0, u - s * 0.035);
      const [sx, sy] = bezierPt(crv[0], crv[1], crv[2], crv[3], crv[4], crv[5], us);
      ctx.fillStyle = `rgba(${rgb},${(1 - s / 6) * 0.45})`;
      ctx.beginPath(); ctx.arc(sx, sy, 5 * (1 - s * 0.14), 0, Math.PI * 2); ctx.fill();
    }
    ctx.fillStyle = '#fff'; ctx.shadowColor = c; ctx.shadowBlur = 18;
    ctx.beginPath(); ctx.arc(x, y, 5.2, 0, Math.PI * 2); ctx.fill(); ctx.shadowBlur = 0;
    ctx.globalAlpha = Math.max(0, 1 - Math.max(0, d - 1.45) / 1.15);
    ctx.font = `600 11px ${estilo.mono}`; ctx.fillStyle = estilo.fg; ctx.textAlign = 'center';
    ctx.fillText((e.tipo === 'resultado' ? '✓ ' : '→ ') + corto(e.txt, 38), x, y - 13);
    ctx.globalAlpha = 1;
  }

  // Nodos: Orbe 3D de alambre vivo para Delta y Esferas 3D con anillos orbitales para los agentes
  for (const n of vis) {
    const p = pos[n.id], s = est.get(n.id), on = activo(s.e), o = ORIGEN[n.origen] || ORIGEN.claude;
    const edad = Math.min(1, (performance.now() - (vistos[n.id] || 0)) / 500);
    const r = (RADIO[n.tipo] || 20) * (0.4 + 0.6 * edad);
    const pul = on ? 1 + 0.055 * Math.sin(performance.now() / 170) : 1;
    const esSel = n.id === sel;
    ctx.globalAlpha = (esSel || !sel ? 1 : .45) * (s.e === 'hecho' ? .65 : 1);

    if (n.tipo === 'delta') {
      const voz = (window.S && (window.S.nivel || (window.S.mic && window.S.mic.nivel))) || (on ? 0.35 : 0);
      pintaOrbeDelta3D(p.x, p.y, r * 1.18 * pul, performance.now() / 1000, on, voz, o[1], dt);
    } else {
      pintaEsferaAgente3D(p.x, p.y, r * pul, o[1], s.e, on, esSel, n.tipo);
      ctx.fillStyle = '#fff'; ctx.textAlign = 'center'; ctx.font = `700 ${r > 24 ? 13 : 11}px ${estilo.sans}`;
      ctx.fillText(n.tipo === 'router' ? '⇄' : s.e === 'hecho' ? '✓' : n.tipo === 'sub' ? '◦' : '●', p.x, p.y + 4.5);
    }

    // Etiquetas bajo el orbe
    const yTxt = p.y + (n.tipo === 'delta' ? r * 1.24 : r) + 17;
    ctx.font = `600 12px ${estilo.sans}`; ctx.fillStyle = estilo.fg; ctx.textAlign = 'center';
    ctx.fillText(corto(titulo(n), 24), p.x, yTxt);
    ctx.font = `10.5px ${estilo.mono}`; ctx.fillStyle = estilo.dim;
    ctx.fillText(corto(nombreModelo(n.modelo), 26), p.x, yTxt + 13);
    ctx.globalAlpha = 1;

    const [sx, sy] = w2s(p.x, p.y), sr = r * cam.z;
    rects.push({id: n.id, x: sx - sr, y: sy - sr, w: 2 * sr, h: 2 * sr, circ: true, cx: sx, cy: sy, r: sr});
  }

  // Herramientas: satélites 3D que orbitan a su agente unidos por un rayo de energía
  const dir = new Map(vis.map(n => [n.id, [0, 0]]));
  for (const n of vis) {
    const pa = n.padre && por.has(n.padre) && n.tipo !== 'router' ? n.padre : null;
    if (!pa || !pos[pa] || !pos[n.id]) continue;
    const a = pos[pa], b = pos[n.id], d = Math.hypot(b.x - a.x, b.y - a.y) || 1, u = [(b.x - a.x) / d, (b.y - a.y) / d];
    dir.get(pa)[0] += u[0]; dir.get(pa)[1] += u[1]; dir.get(n.id)[0] -= u[0]; dir.get(n.id)[1] -= u[1];
  }
  const vivas = new Set(), k2 = 1 - Math.pow(0.002, dt);
  for (const n of vis) {
    const p = pos[n.id], v = dir.get(n.id), r = (RADIO[n.tipo] || 20) * (n.tipo === 'delta' ? 1.15 : 1), aN = (n.id === sel || !sel ? 1 : .45);
    let c = -v[0], sn = -v[1]; const m = Math.hypot(c, sn);
    if (m < .3) { c = 0; sn = -1; } else { c /= m; sn /= m; }
    let ang0 = Math.atan2(sn, c);
    if (ang0 > .45) ang0 -= 2 * Math.PI;
    if (ang0 < -Math.PI - .45) ang0 = c >= 0 ? .45 : -Math.PI - .45;
    ang0 = Math.max(-Math.PI - .45 + 1, Math.min(.45 - 1, ang0));
    let pilla = false;
    const reciente = n.segs.filter(g => g.t0 <= t && (g.abierto && vivo || g.t1 == null || t - g.t1 < 45)).slice(-5);
    for (let i = reciente.length - 1, j = 0; i >= 0; i--, j++) {
      const g = reciente[i], act = g.t0 <= t && t <= (g.abierto && vivo ? Infinity : g.t1), edad = act ? 0 : t - g.t1;
      const key = `${n.id}|${g.t0}`; vivas.add(key);
      const meta = ang0 + (j % 2 ? 1 : -1) * Math.ceil(j / 2) * .52, rad = r + 48;
      const e = sats[key] || (sats[key] = {a: ang0, rad: r});
      e.a += (meta - e.a) * k2; e.rad += (rad - e.rad) * k2;
      const x = p.x + Math.cos(e.a) * e.rad, y = p.y + Math.sin(e.a) * e.rad;
      const col = n.tipo === 'router' ? ORIGEN.omniroute[1] : colorHerr(g.tool), rd = act ? 9.5 + 1.2 * Math.sin(performance.now() / 140) : 6.8;
      ctx.globalAlpha = aN * (act ? 1 : Math.max(.28, 1 - edad / 45 * .72));
      ctx.strokeStyle = col; ctx.lineWidth = act ? 2 : 1.1; ctx.beginPath(); ctx.moveTo(p.x + Math.cos(e.a) * r, p.y + Math.sin(e.a) * r); ctx.lineTo(x, y); ctx.stroke();
      if (act) { ctx.shadowColor = col; ctx.shadowBlur = 14; }
      ctx.fillStyle = col; ctx.beginPath(); ctx.arc(x, y, rd, 0, Math.PI * 2); ctx.fill(); ctx.shadowBlur = 0;
      if (!g.ok) { ctx.strokeStyle = '#E5484D'; ctx.lineWidth = 2; ctx.stroke(); }
      ctx.fillStyle = '#000'; ctx.font = `700 ${act ? 10 : 9}px ${estilo.mono}`; ctx.textAlign = 'center'; ctx.fillText(glifo(g.tool), x, y + 3.5);
      if (act && !pilla) {
        pilla = true;
        let dcha = Math.cos(e.a) >= 0;
        const txt = corto(`${nomHerr(g.tool)}${g.det ? ': ' + g.det : ''}`, 30);
        ctx.font = `600 10.5px ${estilo.mono}`;
        const w = ctx.measureText(txt).width + 12;
        if (dcha && x + rd + 4 + w > W - 6) dcha = false; else if (!dcha && x - rd - 4 - w < 6) dcha = true;
        ctx.textAlign = dcha ? 'left' : 'right';
        const bx = dcha ? x + rd + 4 : x - rd - 4 - w;
        ctx.fillStyle = estilo.sup; ctx.globalAlpha *= .94; ctx.beginPath(); ctx.roundRect(bx, y - 9.5, w, 19, 9.5); ctx.fill();
        ctx.strokeStyle = col; ctx.lineWidth = 1.2; ctx.stroke(); ctx.globalAlpha = aN;
        ctx.fillStyle = estilo.fg; ctx.fillText(txt, bx + (dcha ? 6 : w - 6), y + 3.5);
      }
      ctx.globalAlpha = 1;
      const [sx, sy] = w2s(x, y), sr = 9.5 * cam.z;
      rects.push({id: n.id, x: sx - sr, y: sy - sr, w: 2 * sr, h: 2 * sr, circ: true, cx: sx, cy: sy, r: sr, seg: g});
    }
  }
  ctx.restore();
  for (const k in sats) if (!vivas.has(k)) delete sats[k];
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
  const fy = new Map(), fila = new Map(), prof = n => { let d = 0; for (let q = n; q.padre && por.has(q.padre) && d < 6; q = por.get(q.padre)) d++; return d; };
  orden.forEach((n, i) => {
    const y = TOP + i * hFila, mid = y + hFila / 2, o = ORIGEN[n.origen] || ORIGEN.claude, s = estadoEn(n, t), on = activo(s.e);
    fy.set(n.id, mid);
    if (n.id === sel) { ctx.fillStyle = estilo.sup; ctx.globalAlpha = .6; ctx.fillRect(0, y, W, hFila); ctx.globalAlpha = 1; }
    ctx.strokeStyle = estilo.borde; ctx.globalAlpha = .4; ctx.beginPath(); ctx.moveTo(0, y + hFila); ctx.lineTo(W, y + hFila); ctx.stroke(); ctx.globalAlpha = 1;
    const sangr = Math.min(3, prof(n)) * 14;
    fila.set(n.id, {mid, sangr});
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
  // quién pertenece a quién: codo desde el punto del padre al del hijo
  for (const n of orden) {
    const a = fila.get(n.padre), b = fila.get(n.id);
    if (!a || !b) continue;
    const c = (ORIGEN[n.origen] || ORIGEN.claude)[1];
    ctx.strokeStyle = c; ctx.lineWidth = 1.4; ctx.globalAlpha = .6; ctx.beginPath();
    ctx.moveTo(12 + a.sangr, a.mid - 1); ctx.lineTo(12 + a.sangr, b.mid - 5); ctx.lineTo(12 + b.sangr - 5, b.mid - 5); ctx.stroke(); ctx.globalAlpha = 1;
  }
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

// ---------- sala de control ----------
// Un panel por agente (modelo, estado, tira de herramientas, pasos en vivo y lo último que ha escrito), agrupados por
// sesión: cada conversación de Claude Code con sus subagentes; Delta y OmniRoute aparte. A la derecha, los mensajes
// entre agentes. Los nodos del DOM se reutilizan para que las animaciones no se reinicien en cada repaso.
const salaEls = {}, salaGrs = {}, salaVistos = new Set(), salaAbiertos = new Set();  // salaAbiertos: mensajes desplegados con un clic
let salaPrimera = true;
function salaRect(id) {
  const el = salaEls[id]; if (!el || !el.isConnected) return null;
  const a = el.getBoundingClientRect(), b = $('ag-lienzo').getBoundingClientRect();
  return {x: a.left - b.left, y: a.top - b.top, w: a.width, h: a.height};
}
function salaPanel(n, t, por) {
  let el = salaEls[n.id];
  if (!el) {
    el = salaEls[n.id] = document.createElement('div');
    el.className = 'sl-p'; el.dataset.id = n.id;
    el.innerHTML = '<div class="l1"><span class="pt"></span><b></b><span class="mod"></span></div><div class="ch"></div><div class="sl-bar"><i></i></div><div class="sl-tl"></div><div class="feed"></div><div class="txt"></div>';
  }
  const s = estadoEn(n, t), on = activo(s.e), o = ORIGEN[n.origen] || ORIGEN.claude, q = c => el.querySelector(c);
  el.classList.toggle('off', !on); el.classList.toggle('sel', n.id === sel);
  q('.pt').classList.toggle('on', on); q('.pt').style.background = on ? o[1] : '';
  q('b').textContent = corto(titulo(n), 40);
  q('.mod').textContent = nombreModelo(n.modelo); q('.mod').style.background = o[1];
  const pa = n.padre && por.get(n.padre);
  q('.ch').innerHTML = [`<span style="color:${o[1]}">${o[0]}</span>`, esc(s.e), n.tipo === 'sub' && n.tarea ? esc(corto(n.nombre, 22)) : '',
    n.ruta ? esc(corto(n.ruta, 26)) : '', n.tok ? `${n.parcial ? '≥' : ''}${n.tok} tok` : '', pa ? `↳ ${esc(corto(titulo(pa), 22))}` : ''].filter(Boolean).map(x => `<span>${x}</span>`).join('');
  q('.sl-bar').classList.toggle('on', !!s.seg); q('.sl-bar i').style.background = s.seg ? colorHerr(s.seg.tool) : '';
  q('.sl-tl').innerHTML = n.segs.filter(g => g.t0 <= t).slice(-16).map(g =>
    `<i style="flex:${Math.max(1, Math.log2(2 + (g.t1 - g.t0))).toFixed(2)};background:${colorHerr(g.tool)};opacity:${g.ok ? .9 : .4}"></i>`).join('');
  q('.feed').innerHTML = pasos(n, t, 5);
  q('.txt').textContent = n.texto ? `«${corto(n.texto.replace(/\s+/g, ' '), 300)}»` : n.tarea && n.tipo !== 'sub' ? n.tarea : '';
  return el;
}
function sala(t) {
  const vis = D.nodos.filter(n => visible(n, t)), por = new Map(vis.map(n => [n.id, n]));
  const raizDe = n => { let q = n; for (let d = 0; d < 8 && q.padre && por.has(q.padre) && q.padre !== 'delta' && por.get(q.padre).tipo !== 'router'; d++) q = por.get(q.padre); return q; };
  const grupos = new Map();
  for (const n of vis) { const r = n.tipo === 'router' ? n : raizDe(n); (grupos.get(r.id) || grupos.set(r.id, []).get(r.id)).push(n); }
  // orden estable (no por actividad, para que nada salte bajo el ratón): Delta, conversaciones de la más nueva a la más antigua, OmniRoute
  const ids = [...grupos.keys()].sort((a, b) => (a === 'delta' ? -1 : b === 'delta' ? 1 : 0) || (por.get(a).tipo === 'router') - (por.get(b).tipo === 'router')
    || por.get(b).t0 - por.get(a).t0);
  const cont = $('sl-g');
  ids.forEach((id, i) => {
    let g = salaGrs[id];
    if (!g) { g = salaGrs[id] = document.createElement('section'); g.className = 'sl-gr'; g.innerHTML = '<h3><span></span><small></small></h3><div class="sl-rej"></div>'; }
    const r = por.get(id), mi = grupos.get(id), nAct = mi.filter(n => activo(estadoEn(n, t).e)).length;
    g.querySelector('h3 span').textContent = corto(titulo(r), 40);
    g.querySelector('h3 small').textContent = `${nAct}/${mi.length} activos${r.tarea && r.tipo !== 'sub' ? ' · ' + r.tarea : ''}`;
    const orden = [], anade = n => { orden.push(n); mi.filter(x => x.padre === n.id && x !== n).sort((a, b) => a.t0 - b.t0).forEach(anade); };
    anade(r); for (const n of mi) if (!orden.includes(n)) orden.push(n);
    const rej = g.querySelector('.sl-rej');
    orden.forEach((n, j) => { const el = salaPanel(n, t, por); if (rej.children[j] !== el) rej.insertBefore(el, rej.children[j] || null); });
    while (rej.children.length > orden.length) rej.lastChild.remove();
    if (cont.children[i] !== g) cont.insertBefore(g, cont.children[i] || null);
  });
  while (cont.children.length > ids.length) cont.lastChild.remove();
  // mensajes: lo más nuevo arriba; solo entran animados los que no se habían visto
  const nom = id => { const n = D.nodos.find(z => z.id === id); return n ? corto(titulo(n), 22) : '?'; };
  const evs = D.eventos.filter(e => e.t <= t && (e.de || e.a)).slice(-40).reverse();
  $('sl-m').innerHTML = evs.map(e => {
    const k = `${e.t}|${e.de}|${e.tipo}`, nuevo = !salaPrimera && !salaVistos.has(k); salaVistos.add(k);
    const c = e.tipo === 'resultado' ? VERDE : (ORIGEN[(D.nodos.find(z => z.id === e.a) || {}).origen] || ORIGEN.claude)[1];
    return `<div class="sl-m${nuevo ? ' nuevo' : ''}${salaAbiertos.has(k) ? ' abierto' : ''}" data-k="${esc(k)}" style="border-color:${c}"><div class="de" style="color:${c}">${esc(nom(e.de))} ${e.tipo === 'resultado' ? '✓ →' : '→'} ${esc(nom(e.a))}</div>${e.txt ? `<div class="tx">${esc(e.txt)}</div>` : ''}<div class="cu">hace ${esc(fmt(Math.max(0, t - e.t)))}</div></div>`;
  }).join('') || '<div class="sl-m">Aún no hay encargos entre agentes.</div>';
  salaPrimera = false;
}
$('sl-m').addEventListener('click', e => { const m = e.target.closest('.sl-m'); if (!m || !m.dataset.k || window.getSelection().toString()) return; const k = m.dataset.k; salaAbiertos.has(k) ? salaAbiertos.delete(k) : salaAbiertos.add(k); m.classList.toggle('abierto'); });
$('ag-sala').addEventListener('click', e => { const p = e.target.closest('.sl-p'); if (p) { sel = sel === p.dataset.id ? null : p.dataset.id; ultLista = 0; } });

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
  if (vista === 'const') pintaConst(t, W, H, dt); else if (vista === 'carriles') pintaCarriles(t, W, H);
  if (performance.now() - ultLista > 500) { ultLista = performance.now(); lista(t); if (vista === 'sala') sala(t); }
  menuPos(W, H);
  $('ag-t').textContent = vivo ? 'en directo' : `hace ${fmt(ahoraLive() - t)}`;
  if (vivo) $('ag-rango').value = t;
}
const fmt = s => s < 60 ? `${Math.round(s)} s` : `${Math.floor(s / 60)} min ${String(Math.round(s % 60)).padStart(2, '0')} s`;

// ---------- control ----------
function pon() {
  for (const b of $('ag-vista').children) b.classList.toggle('on', b.dataset.v === vista);
  for (const b of $('ag-ventana').children) b.classList.toggle('on', +b.dataset.w === ventana);
  $('ag-ventana').style.display = vista === 'carriles' ? '' : 'none';
  raiz.classList.toggle('sala', vista === 'sala'); ultLista = 0;
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
cv.addEventListener('mousedown', e => {
  if (vista !== 'const' || e.button !== 0) return;
  const h = bajo(e);
  if (h && !h.q.seg && !h.q.evento && pos[h.q.id]) {
    drag = {tipo: 'nodo', id: h.q.id, x0: e.clientX, y0: e.clientY, mov: false, wx: pos[h.q.id].x, wy: pos[h.q.id].y};
  } else {
    drag = {tipo: 'pan', x0: e.clientX, y0: e.clientY, mov: false, cx: cam.x, cy: cam.y};
  }
  cv.classList.add('arrastrando');
});
addEventListener('mousemove', e => {
  if (!drag) return;
  const dx = e.clientX - drag.x0, dy = e.clientY - drag.y0;
  if (Math.hypot(dx, dy) > 4) drag.mov = true;
  if (!drag.mov) return;
  if (drag.tipo === 'nodo' && pos[drag.id]) {
    const nx = drag.wx + dx / cam.z, ny = drag.wy + dy / cam.z;
    pos[drag.id].x = nx; pos[drag.id].y = ny;
    fijados[drag.id] = [nx, ny];
  } else if (drag.tipo === 'pan') {
    cam.x = drag.cx + dx; cam.y = drag.cy + dy;
  }
});
addEventListener('mouseup', () => {
  if (drag) {
    setTimeout(() => { drag = null; }, 0);
    cv.classList.remove('arrastrando');
  }
});
cv.addEventListener('wheel', e => {
  if (vista !== 'const') return;
  e.preventDefault();
  const factor = e.deltaY < 0 ? 1.12 : 0.89;
  cam.z = Math.max(0.45, Math.min(2.6, cam.z * factor));
}, {passive: false});
cv.addEventListener('dblclick', e => {
  if (vista !== 'const') return;
  const h = bajo(e);
  if (h && h.q.id) delete fijados[h.q.id];
  else { cam = {x: 0, y: 0, z: 1}; fijados = {}; }
});
cv.addEventListener('mousemove', e => {
  if (drag && drag.mov) { $('ag-tip').style.display = 'none'; return; }
  const h = bajo(e), tip = $('ag-tip');
  if (!h) { tip.style.display = 'none'; return; }
  const n = D.nodos.find(z => z.id === h.q.id) || {};
  let html;
  if (h.q.seg) html = `<b>${esc(h.q.seg.tool)}</b> · ${esc(fmt(h.q.seg.t1 - h.q.seg.t0))}${h.q.seg.ok ? '' : ' · falló'}<br>${esc(h.q.seg.det)}`;
  else if (h.q.evento) html = `<b>${h.q.evento.tipo === 'resultado' ? 'Resultado' : 'Encargo'}</b><br>${esc(corto(h.q.evento.txt, 600))}`;
  else html = `<b>${esc(n.nombre)}</b> · ${esc((ORIGEN[n.origen] || [''])[0])}<br>${esc(n.modelo)}${n.ruta ? ' · ' + esc(n.ruta) : ''}<br>${esc(corto(n.tarea, 140))}`;
  tip.innerHTML = html; tip.style.display = 'block';
  tip.style.left = Math.min(h.x + 14, cv.clientWidth - 370) + 'px'; tip.style.top = Math.min(h.y + 14, cv.clientHeight - 80) + 'px';
});
cv.addEventListener('mouseleave', () => { $('ag-tip').style.display = 'none'; });
cv.addEventListener('click', e => { if (drag && drag.mov) return; const h = bajo(e); sel = h && h.q.id !== sel ? h.q.id : null; ultLista = 0; });

// ---------- nueva conversación: el selector permanente bajo el título ----------
// Claude Code (agentes, frameworks, modos Workflow y Juez) o DeltaOS. El catálogo se lee del disco (agentes_catalogo.py) y
// al lanzar solo viaja el id elegido y el texto: la sesión ACP nueva sale en la constelación como un nodo más.
// Tras Claude Code o DeltaOS se elige el modelo: directo/por defecto o un combo de OmniRoute (solo viaja su nombre, se valida en el servidor).
let CAT = null, nvAbierto = false, nvCli = lee('ag_nv_cli', 'claude'), nvSel = null, nvCierre = 0, nvCombo = lee('ag_nv_combo', '');
const nv = $('nv'), NV_AYUDA = 'Pasa el ratón por una opción para ver qué hace; púlsala para empezar con ella.';
const nvItems = (l, cls = '') => l.map(a => `<button class="nv-i ${cls}" data-id="${esc(a.id)}" data-d="${esc(a.d)}">${esc(a.n)}</button>`).join('');
const nvBloque = (t, l, cls) => l.length ? `<div><div class="nv-s">${t}</div><div class="nv-g">${nvItems(l, cls)}</div></div>` : '';
function nvTodos() { return CAT ? [...CAT.claude.agentes, ...CAT.claude.frameworks, ...CAT.claude.modos, ...CAT.delta] : []; }
// el combo solo cuenta donde trabaja Claude Code: todo lo de Claude Code y «Cambiar algo de Delta» (hablar es Gemini Live; Antigravity y Cherry, los suyos)
const nvConCombo = id => !String(id).startsWith('delta:') || id === 'delta:cambiar';
function nvComboAct() { return (CAT && (CAT.combos || []).find(c => c.id === nvCombo)) || null; }
function nvModelos() {
  const def = nvCli === 'claude' ? ['Claude directo', 'Claude con tu login de Claude Code, sin pasar por OmniRoute.']
    : ['Por defecto', 'Lo de siempre: ~/.claude/settings.json (OmniRoute, auto/best-coding).'];
  const act = nvComboAct() ? nvCombo : '';
  return `<div><div class="nv-s">${nvCli === 'claude' ? 'Modelo' : 'Modelo para «Cambiar algo de Delta»'}</div><div class="nv-g">`
    + `<button class="nv-i ${act ? '' : 'on'}" data-combo="" data-d="${esc(def[1])}">${esc(def[0])}</button>`
    + (CAT.combos || []).map(c => `<button class="nv-i ${act === c.id ? 'on' : ''}" data-combo="${esc(c.id)}" data-d="${esc(c.id + ' · ' + c.d)}">${esc(c.n)}</button>`).join('')
    + '</div>' + (CAT.desvio ? `<div class="nv-mod">Ojo: OmniRoute manda lo que ve como código a ${esc(CAT.desvio)}; Claude Code suele acabar ahí.</div>` : '') + '</div>';
}
function nvPinta() {
  if (!CAT) { nv.innerHTML = '<div class="nv-d" id="nv-d">Cargando el catálogo…</div>'; return; }
  const a = nvSel && nvTodos().find(x => x.id === nvSel);
  if (a) {
    const cb = nvComboAct(), mod = !nvConCombo(a.id) ? '' : cb ? `OmniRoute · ${cb.id}` + (CAT.desvio && cb.id !== CAT.desvio ? ` (lo que parezca código, a ${CAT.desvio})` : '') : a.g === 'delta' ? 'Modelo por defecto' : 'Claude directo';
    nv.innerHTML = `<div class="nv-h"><button data-a="atras" title="Volver">←</button><b>${esc(a.n)}</b></div><div class="nv-d">${esc(a.d)}</div>${mod ? `<div class="nv-mod">▸ ${esc(mod)}</div>` : ''}
      <form id="nv-f"><textarea id="nv-t" rows="4" maxlength="2000" placeholder="${a.g === 'delta' ? 'Qué le dices o le pides a Delta…' : '¿Qué quieres que haga?'}"></textarea><button type="submit">Empezar</button></form><div class="nv-res" id="nv-res"></div>`;
    setTimeout(() => { const t = $('nv-t'); if (t) t.focus(); }, 30);
    return;
  }
  const c = CAT.claude, esp = c.agentes.filter(x => x.g === 'especialista');
  nv.innerHTML = `<div class="nv-seg"><button data-c="claude" class="${nvCli === 'claude' ? 'on' : ''}">Claude Code</button><button data-c="delta" class="${nvCli === 'delta' ? 'on' : ''}">DeltaOS</button></div>` + nvModelos()
    + (nvCli === 'claude'
      ? nvBloque('Genéricos', c.agentes.filter(x => x.g === 'genérico')) + nvBloque('Especialistas', esp) + nvBloque('Frameworks de plugins', c.frameworks) + nvBloque('Modos', c.modos, 'modo')
      : nvBloque('Delta', CAT.delta))
    + `<div class="nv-d" id="nv-d">${NV_AYUDA}</div>`;
}
function nvCierra() { nvAbierto = false; nvSel = null; clearTimeout(nvCierre); nv.classList.remove('on'); $('ag-nueva').classList.remove('on'); }
function nvAbre() {
  nvAbierto = true; nvSel = null; nv.classList.add('on'); $('ag-nueva').classList.add('on'); nvPinta();
  const r = $('ag-nueva').getBoundingClientRect(); nv.style.left = Math.max(8, r.left) + 'px'; nv.style.top = r.bottom + 8 + 'px';
  if (!(window.enviarWS && window.enviarWS({catalogo: 1}))) nv.innerHTML = '<div class="nv-d">Sin conexión con el panel.</div>';
}
$('ag-nueva').addEventListener('click', e => { e.stopPropagation(); nvAbierto ? nvCierra() : nvAbre(); });
// composedPath y no nv.contains: al pulsar una opción nvPinta() rehace el HTML y el botón pulsado ya no está dentro de nv
document.addEventListener('click', e => { const p = e.composedPath(); if (nvAbierto && !p.includes(nv) && !p.includes($('ag-nueva'))) nvCierra(); });
nv.addEventListener('mouseover', e => {
  const d = $('nv-d'); if (!d || nvSel) return;
  const b = e.target.closest('[data-d]'); d.textContent = b ? b.dataset.d : NV_AYUDA;
});
nv.addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  if (b.dataset.c) { nvCli = b.dataset.c; guarda('ag_nv_cli', nvCli); nvPinta(); }
  else if ('combo' in b.dataset) { nvCombo = b.dataset.combo; guarda('ag_nv_combo', nvCombo); nvPinta(); }
  else if (b.dataset.id) { nvSel = b.dataset.id; nvPinta(); }
  else if (b.dataset.a === 'atras') { nvSel = null; nvPinta(); }
});
nv.addEventListener('submit', e => {
  e.preventDefault();
  const t = $('nv-t').value.trim(), r = $('nv-res'); if (!t) { r.textContent = 'Escribe qué quieres que haga.'; return; }
  r.textContent = window.enviarWS && window.enviarWS({nueva: {id: nvSel, texto: t, ...(nvConCombo(nvSel) && nvComboAct() ? {combo: nvCombo} : {})}}) ? 'Enviando…' : 'Sin conexión con el panel.';
});
nv.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey && e.target.id === 'nv-t') { e.preventDefault(); $('nv-f').requestSubmit(); } });
addEventListener('catalogo_res', e => { CAT = e.detail; if (nvAbierto && !nvSel) nvPinta(); });
addEventListener('nueva_res', e => {
  const r = e.detail || {}, el = $('nv-res'); if (el) el.textContent = r.msg || '';
  if (r.ok) nvCierre = setTimeout(nvCierra, 1600);
});

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
  abierto = false; nvCierra(); menuCierra(); clearInterval(timer); cancelAnimationFrame(raf);
  document.body.classList.remove('agentes');
}
addEventListener('keydown', e => {
  if (e.key !== 'Escape' || !abierto) return;
  if (nvAbierto) { nvCierra(); return; }
  if (document.activeElement === $('pm-i')) { sel = null; menuCierra(); return; }
  cerrar();
});
window.Agentes = {abrir, cerrar, alternar: () => (abierto ? cerrar() : abrir()), abierto: () => abierto};
const btn = $('b-ag'); if (btn) btn.onclick = () => window.Agentes.alternar();
