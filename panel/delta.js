// Escena «delta» del salvapantallas: la identidad del sistema dibujada en matriz de puntos.
//
// Todo lo que se ve aquí son puntos sobre negro, blanco, y el rojo como único acento (el ojo del
// perro y el testigo de la línea de estado). El movimiento va a pasos discretos a propósito: nada
// de curvas suaves ni resplandores, que es justo lo que separa esta estética de un «glow» azul.
//
// Al entrar hace la secuencia de arranque (3 s) y se queda en reposo reaccionando a la voz:
// mientras Delta habla late con su nivel, mientras escucha late con lo que entra por el micro
// —así se ve de un vistazo que el micro está vivo, que es la avería que más veces nos ha pillado—.
//
// El logo (la cabeza) no está dibujado a mano: sale de logo.json, que genera trazar_logo.py
// desde la imagen del logotipo. Si cambia el logotipo, se regenera y aquí no se toca nada.

const FG = '242,242,242', ROJO = '255,45,31';
const ARR = {punto: .3, onda: .6, forma: 1.5, texto: 2.2, fin: 3.0};  // segundos de la secuencia

let L = null, orig = null;
fetch('/logo.json').then(r => r.json()).then(j => {
  L = j;
  // Cada punto del logo nace en un sitio cualquiera de la pantalla y viaja al suyo. El sitio no es
  // aleatorio de verdad: se deriva del índice, así la secuencia se ve igual en cada arranque.
  orig = new Float32Array(L.pts.length * 2);
  for (let k = 0; k < L.pts.length; k++) {
    const a = (k * 2654435761) % 1000 / 1000, b = (k * 40503) % 997 / 997;
    orig[k * 2] = a; orig[k * 2 + 1] = b;
  }
});

let t0 = 0, NV = 0, MV = 0;
export const entrar = () => { t0 = performance.now() / 1000; };

const paso = (v, n) => Math.round(v * n) / n;             // easing a saltos: el movimiento es seco
const suave = v => v < 0 ? 0 : v > 1 ? 1 : v * v * (3 - 2 * v);
const punto = (x, c, px, py, r, a) => {
  if (a <= .004 || r <= 0) return;
  x.fillStyle = `rgba(${c},${a})`;
  x.beginPath(); x.arc(px, py, r, 0, 7); x.fill();
};

export function pintar(cv, d) {
  const k = Math.min(devicePixelRatio || 1, 2), w = cv.clientWidth, h = cv.clientHeight;
  if (!w || !h) return;
  if (cv.width !== Math.round(w * k)) { cv.width = w * k; cv.height = h * k; }
  const x = cv.getContext('2d'), W = cv.width, H = cv.height;
  const t = performance.now() / 1000 - t0;
  // los niveles se persiguen en vez de saltar: el valor llega cada 0,4 s por el WebSocket
  NV += ((d.nivel || 0) - NV) * .25;
  MV += (((d.mic || {}).nivel || 0) - MV) * .25;

  x.clearRect(0, 0, W, H);
  const est = d.estado || 'dormido', hablando = est === 'hablando';
  const G = Math.max(3, Math.min(H * .0055, W * .0042)) * k;   // paso de la rejilla de fondo

  if (t < ARR.punto) { semilla(x, W, H, t, G); return; }
  if (t < ARR.forma) oleada(x, W, H, t, G);
  if (!L) return;

  // ---- el logo ----
  // El sitio de cada cosa sale del anterior y no de un porcentaje de la pantalla: con porcentajes
  // el vúmetro se metía dentro del nombre en cuanto la ventana era bajita (probado a 800×600).
  const alto = Math.min(H * .46, W * .38), u = alto / L.h;    // u = lado de la celda del logo
  const an = L.w * u, x0 = W / 2 - an / 2, y0 = H * .07;
  const nac = t < ARR.texto ? suave((t - ARR.onda) / (ARR.texto - ARR.onda)) : 1;
  const viaje = t < ARR.texto ? paso(nac, 10) : 1;            // converge a saltos, no deslizándose
  // Respiración en reposo: un pulso lento que recorre la cabeza de arriba abajo. Cuando Delta
  // habla manda su voz; cuando escucha, el micro. Es el mismo punto, solo cambia de dónde late.
  const voz = hablando ? NV : est === 'escuchando' ? MV * .7 : 0;

  for (let i = 0; i < L.pts.length; i++) {
    const p = L.pts[i];
    let px = x0 + (p[0] + .5) * u, py = y0 + (p[1] + .5) * u;
    if (viaje < 1) {
      px += (orig[i * 2] * W - px) * (1 - viaje);
      py += (orig[i * 2 + 1] * H - py) * (1 - viaje);
    }
    const onda = Math.max(0, Math.sin(p[1] * .09 - t * 1.6)) * .5;
    const v = p[2] * (.55 + .45 * onda + voz * .9);
    punto(x, FG, px, py, u * (.17 + .13 * Math.min(1, v)) * viaje, Math.min(1, .16 + .84 * v) * nac);
  }
  // El ojo: el único rojo del dibujo. Se enciende al final de la secuencia, como quien despierta.
  const ojo = t > ARR.texto - .4 ? 1 : 0;
  for (const p of L.ojo) {
    const lat = .55 + .45 * Math.sin(t * 2.2) + voz;
    punto(x, ROJO, x0 + (p[0] + .5) * u, y0 + (p[1] + .5) * u, u * (.3 + .22 * Math.min(1, lat)), Math.min(1, lat) * ojo);
  }
  // Anillo girando alrededor de la cabeza: solo cuando hay algo en marcha, para que signifique algo.
  if (ojo && (est === 'escuchando' || est === 'trabajando'))
    anillo(x, W / 2, y0 + alto / 2, an / 2 * 1.14, alto / 2 * 1.08, t, est, k);

  if (t < ARR.texto) return;
  // ---- el nombre, que se imprime de izquierda a derecha ----
  const tam = Math.min(H * .095, W * .08), yn = y0 + alto + H * .035;
  nombre(x, W, yn, tam, paso(Math.min(1, (t - ARR.texto) / .55), 14));
  if (t < ARR.fin - .3) return;
  // ---- el vúmetro de puntos y la línea de estado ----
  const yv = Math.min(yn + tam * 1.5 + H * .06, H * .88);
  vumetro(x, W, yv, Math.min(W * .42, an * 1.5), tam * .1, hablando ? NV : MV, hablando);
  estado(x, W, (yv + H) / 2, d, t, k);
}

// 0,3 s: un solo punto blanco en el centro. Nada más.
function semilla(x, W, H, t, G) {
  punto(x, FG, W / 2, H * .40, G * (.3 + 2.4 * (t / ARR.punto)), Math.min(1, t / .12));
}

// La rejilla se enciende en oleada desde el centro, en anillos discretos.
function oleada(x, W, H, t, G) {
  const f = (t - ARR.punto) / (ARR.forma - ARR.punto), r = paso(f, 12) * Math.hypot(W, H) * .62;
  const sal = t > ARR.onda ? Math.max(0, 1 - (t - ARR.onda) / (ARR.forma - ARR.onda)) : 1;
  for (let py = G; py < H; py += G * 3) for (let px = G; px < W; px += G * 3) {
    const dd = Math.hypot(px - W / 2, py - H * .40);
    if (dd > r) continue;
    const borde = Math.max(0, 1 - (r - dd) / (G * 14));       // la cresta brilla, la estela se apaga
    punto(x, FG, px, py, G * (.2 + .5 * borde), (.1 + .75 * borde) * sal);
  }
}

// DELTAOS en la tipografía de puntos del panel, revelado por columnas: se imprime, no aparece.
function nombre(x, W, y, tam, rev) {
  x.save();
  x.font = `900 ${tam}px Doto, monospace`;
  x.textAlign = 'center'; x.textBaseline = 'top';
  const txt = 'DELTAOS', an = x.measureText(txt).width;
  x.beginPath(); x.rect(W / 2 - an / 2 - tam * .2, y, an * rev + tam * .2, tam * 1.4); x.clip();
  x.letterSpacing = `${tam * .07}px`;
  x.fillStyle = `rgb(${FG})`;
  x.fillText(txt, W / 2, y);
  x.restore();
}

// Columnas de puntos que suben con la voz. Sin FFT: el nivel es uno solo, así que cada columna
// lo reparte con su propio vaivén. Lo que importa es ver que entra o sale señal, no el espectro.
function vumetro(x, W, y, an, G, nivel, propia) {
  const n = 24, dx = an / n, alto = 7;
  for (let i = 0; i < n; i++) {
    const c = i - (n - 1) / 2, borde = 1 - Math.abs(c) / (n / 2) * .55;
    const vib = .55 + .45 * Math.sin(i * .9 + performance.now() / 1000 * (propia ? 7 : 4));
    const v = Math.min(1, nivel * 1.5 * borde * vib);
    const enc = Math.round(v * alto);
    for (let j = 0; j < alto; j++) {
      const on = j < enc;
      punto(x, on && j >= alto - 2 ? ROJO : FG, W / 2 + c * dx, y - j * G * 1.9,
        G * (on ? .36 : .16), on ? .95 : .085);
    }
  }
}

const ETI = {dormido: 'EN REPOSO', escuchando: 'ESCUCHANDO', hablando: 'HABLANDO', trabajando: 'TRABAJANDO'};

// La línea de datos del logotipo, pero con las cifras de verdad de esta máquina.
function estado(x, W, y, d, t, k) {
  const s = d.sistema || {}, m = d.mic || {};
  const campos = [ETI[d.estado] || 'LISTO', `CPU ${s.cpu ?? '--'}%`, `RAM ${s.ram ?? '--'}%`,
    s.temp != null ? `${s.temp}°` : null, `MIC ${m.estado === 'off' ? 'OFF' : (m.db ?? '--') + ' dB'}`,
    d.conexion === 'conectado' ? 'ENLACE OK' : 'RECONECTANDO'].filter(Boolean);
  x.save();
  x.font = `500 ${13 * k}px "IBM Plex Mono", monospace`;
  x.textAlign = 'left'; x.textBaseline = 'middle';
  x.letterSpacing = `${2.4 * k}px`;
  const txt = campos.join('   ·   '), an = x.measureText(txt).width, px = W / 2 - an / 2;
  // el testigo rojo parpadea: es el latido del sistema, lo único que se mueve aquí
  punto(x, ROJO, px - 16 * k, y, 4 * k, Math.sin(t * 3.4) > -.3 ? 1 : .12);
  x.fillStyle = `rgba(${FG},.62)`;
  x.fillText(txt, px, y);
  x.restore();
}

function anillo(x, cx, cy, rx, ry, t, est, k) {
  const n = 56, giro = t * (est === 'trabajando' ? 1.7 : .55);
  for (let i = 0; i < n; i++) {
    const a = i / n * Math.PI * 2 + giro;
    // una cometa: el punto de cabeza va entero y los de atrás se apagan en cola
    const f = (i / n + .5) % 1, v = Math.pow(1 - f, est === 'trabajando' ? 3 : 6);
    punto(x, est === 'trabajando' ? ROJO : FG, cx + Math.cos(a) * rx, cy + Math.sin(a) * ry,
      k * (1.1 + 2.2 * v), .07 + .8 * v);
  }
}
