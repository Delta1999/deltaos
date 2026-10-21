// Escena «tiempo» del salvapantallas: la estación meteorológica de DeltaOS a pantalla completa.
//
// Antes era una tarjeta grande centrada con tres datos y los bordes de la pantalla vacíos. Ahora ocupa
// el ancho entero (lo pidió el usuario el 2026-10-21): cabecera con la temperatura, rejilla de datos,
// una gráfica de 27 h y la fila de tres días.
//
// El movimiento es a propósito mínimo —esto es un panel, no un adorno—: un destello que recorre la
// curva de temperatura, el punto de «ahora» latiendo, las barras de lluvia respirando y la franja de
// noche detrás. Nada se desplaza por su cuenta: del arrastre contra el quemado ya se encarga el
// `deriva` del CSS.
//
// Se dibuja en 2D a mano (sin WebGL, como el orbe): la gráfica es un solo lienzo que se repinta cada
// fotograma, y los textos van en HTML porque así escalan con vh/vw sin recalcular nada.

const FG = '242,242,242', ROJO = '255,45,31', DIM = '110,110,110';
const $ = i => document.getElementById(i);
const hm = m => `${Math.floor(m / 60)}:${String(m % 60).padStart(2, '0')}`;
const SEM = ['DOM', 'LUN', 'MAR', 'MIÉ', 'JUE', 'VIE', 'SÁB'];
const HORAS = 10;              // cuántos tramos de 3 h entran en la gráfica (wttr da uno cada 3 h)

let t0 = 0, ultDatos = 0;
export const entrar = () => { t0 = performance.now() / 1000; ultDatos = 0; };

const noche = (w, min) => min < w.sale || min > w.pone;
const dia = f => { const [a, m, d] = f.split('-').map(Number); return new Date(a, m - 1, d); };

// ---- los textos: cabecera, rejilla de datos, tres días y pie. Se refrescan cada minuto. ----
function textos(w) {
  const n = new Date(), min = n.getHours() * 60 + n.getMinutes();
  $('ft-temp').textContent = w.temp + '°';
  $('ft-desc').textContent = `${w.desc} · ${w.ciudad}`;
  const campos = [['sensación', w.sens + '°'], ['mín / máx', `${w.min}° / ${w.max}°`],
    ['viento', `${w.viento}<i> km/h ${w.dir}</i>`], ['lluvia', w.lluvia + '%'],
    ['humedad', w.hum + '%'], ['uv', w.uv], ['presión', `${w.presion ?? '—'}<i> hPa</i>`],
    ['nubes', (w.nubes ?? '—') + '%']];
  $('ft-datos').innerHTML = campos.map(([k, v]) => `<div><span>${k}</span><b>${v}</b></div>`).join('');

  const hoy = n.getDate();
  $('ft-dias').innerHTML = (w.dias || []).map((x, i) => {
    const f = dia(x.f), nom = f.getDate() === hoy ? 'HOY' : SEM[f.getDay()];
    return `<div><span>${nom} ${String(f.getDate()).padStart(2, '0')}</span><canvas id="ftd${i}"></canvas>` +
      `<b>${x.max}°<i> ${x.min}°</i></b><span>lluvia ${x.ll}% · uv ${x.uv}</span>` +
      `<span>↑ ${hm(x.sale)} ↓ ${hm(x.pone)}</span></div>`;
  }).join('');
  (w.dias || []).forEach((x, i) => window.icono($('ftd' + i), x.c, false, 4));

  window.icono($('ft-ico'), w.code, noche(w, min), 10);
  $('ft-pie').innerHTML = [`↑ ${hm(w.sale)}  ↓ ${hm(w.pone)}`, w.luna ? `${w.luna} · ${w.ilum}%` : '',
    w.vis != null ? `visibilidad ${w.vis} km` : '', w.precip ? `caído ${w.precip} mm` : '',
    w.obs ? `dato de las ${w.obs.replace(/\s?(AM|PM)/i, m => m.trim().toUpperCase())}` : '']
    .filter(Boolean).map(x => `<span>${x}</span>`).join('');
}

// ---- la gráfica: 27 h de temperatura en puntos, lluvia en barras y la noche de fondo ----
function grafica(cv, w, t) {
  const k = Math.min(devicePixelRatio || 1, 2), cw = cv.clientWidth, ch = cv.clientHeight;
  if (!cw || !ch) return;
  if (cv.width !== Math.round(cw * k) || cv.height !== Math.round(ch * k)) { cv.width = cw * k; cv.height = ch * k; }
  const x = cv.getContext('2d'), W = cv.width, H = cv.height;
  x.clearRect(0, 0, W, H);

  const n = new Date(), ahora = n.getHours() + n.getMinutes() / 60;
  const hs = (w.horas || []).filter(h => h.k + 3 > ahora).slice(0, HORAS)
    .map(h => ({ll: 0, v: 0, ...h}));   // clima viejo (de antes de reiniciar): sin lluvia ni viento por hora
  if (hs.length < 2) return;
  const ML = 14 * k, MR = 14 * k, TOP = 34 * k, BOT = H * .56, SUELO = H * .78;
  const px = i => ML + i * (W - ML - MR) / (hs.length - 1);
  const pk = h => ML + (h - hs[0].k) / (hs[hs.length - 1].k - hs[0].k) * (W - ML - MR);
  const ts = hs.map(h => h.t), mn = Math.min(...ts) - 1.5, mx = Math.max(...ts) + 1.5;
  const py = v => BOT - (v - mn) / (mx - mn) * (BOT - TOP);

  // franjas de noche: se ve de un golpe dónde cae el amanecer y el anochecer
  for (const h of hs) {
    if (!noche(w, (h.k % 24) * 60 + 90)) continue;
    const a = pk(h.k), b = pk(Math.min(h.k + 3, hs[hs.length - 1].k));
    x.fillStyle = 'rgba(255,255,255,.028)';
    x.fillRect(a, TOP - 18 * k, Math.max(1, b - a), SUELO - TOP + 18 * k);
  }

  // barras de lluvia: respiran, cada una con su fase, para que la escena no esté del todo quieta
  const an = (W - ML - MR) / hs.length * .22;
  hs.forEach((h, i) => {
    const alto = (h.ll / 100) * (SUELO - BOT - 6 * k) * (1 + .07 * Math.sin(t * 1.1 + i * .9));
    if (h.ll < 3) return;
    x.fillStyle = `rgba(${ROJO},${.16 + .34 * h.ll / 100})`;
    x.fillRect(px(i) - an / 2, SUELO - alto, an, alto);
  });

  // la curva, en puntos (el panel habla en matriz de puntos); un destello la recorre despacio
  const dest = (t * .09) % 1.25;
  const PASO = 5 * k;
  for (let i = 0; i < hs.length - 1; i++) {
    const x0 = px(i), x1 = px(i + 1), y0 = py(hs[i].t), y1 = py(hs[i + 1].t), largo = x1 - x0;
    for (let q = 0; q < largo; q += PASO) {
      const u = q / largo, cxp = x0 + q, cyp = y0 + (y1 - y0) * u;
      const s = (i + u) / (hs.length - 1), cerca = Math.max(0, 1 - Math.abs(s - dest) * 9);
      x.fillStyle = `rgba(${FG},${.30 + .55 * cerca})`;
      x.beginPath(); x.arc(cxp, cyp, k * (1.1 + 1.1 * cerca), 0, 7); x.fill();
    }
  }
  // cada tramo de 3 h: su punto, su temperatura y su hora; la lluvia solo si la hay
  x.textAlign = 'center';
  hs.forEach((h, i) => {
    x.fillStyle = `rgba(${FG},.9)`;
    x.beginPath(); x.arc(px(i), py(h.t), 2.3 * k, 0, 7); x.fill();
    x.font = `900 ${15 * k}px Doto, monospace`; x.textBaseline = 'bottom';
    x.fillText(h.t + '°', px(i), py(h.t) - 8 * k);
    x.font = `500 ${11 * k}px "IBM Plex Mono", monospace`; x.textBaseline = 'top';
    x.fillStyle = `rgba(${DIM},.95)`;
    x.fillText(String(h.k % 24).padStart(2, '0') + 'h', px(i), SUELO + 7 * k);
    x.fillStyle = `rgba(${h.ll >= 30 ? ROJO : DIM},.8)`;
    x.fillText(h.ll ? h.ll + '%' : '·', px(i), SUELO + 22 * k);
    x.fillStyle = `rgba(${DIM},.7)`;
    x.fillText(h.v + ' km/h', px(i), SUELO + 37 * k);
  });

  // amanecer y anochecer, donde caigan
  x.font = `500 ${11 * k}px "IBM Plex Mono", monospace`; x.textBaseline = 'bottom';
  for (const [m, et] of [[w.sale, '↑'], [w.pone, '↓']]) {
    for (const d of [0, 24]) {
      const h = m / 60 + d;
      if (h < hs[0].k || h > hs[hs.length - 1].k) continue;
      const p = pk(h);
      x.strokeStyle = `rgba(${FG},.16)`; x.lineWidth = k; x.setLineDash([2 * k, 4 * k]);
      x.beginPath(); x.moveTo(p, TOP - 18 * k); x.lineTo(p, SUELO); x.stroke(); x.setLineDash([]);
      x.fillStyle = `rgba(${FG},.45)`; x.fillText(et + ' ' + hm(m), p, TOP - 22 * k);
    }
  }

  // «ahora»: la línea roja late despacio y el punto sobre la curva con ella
  const p = pk(ahora), i0 = Math.max(0, Math.min(hs.length - 2, hs.findIndex(h => h.k > ahora) - 1));
  const u = (ahora - hs[i0].k) / 3, ty = py(hs[i0].t + (hs[i0 + 1].t - hs[i0].t) * Math.max(0, Math.min(1, u)));
  const lat = .55 + .45 * Math.sin(t * 2.2);
  x.strokeStyle = `rgba(${ROJO},${.22 + .2 * lat})`; x.lineWidth = 1.4 * k;
  x.beginPath(); x.moveTo(p, TOP - 18 * k); x.lineTo(p, SUELO); x.stroke();
  x.fillStyle = `rgba(${ROJO},1)`;
  x.beginPath(); x.arc(p, ty, k * (3 + 1.6 * lat), 0, 7); x.fill();
}

export function pintar(t, d) {
  const w = d.clima;
  if (!w) return;
  const ms = performance.now();
  if (!ultDatos || ms - ultDatos > 60e3) { ultDatos = ms; textos(w); }
  grafica($('ft-graf'), w, ms / 1000 - t0);
}
