// Escena «orbe» del salvapantallas: una esfera de alambre que respira y se deforma con la voz.
//
// Sustituye al escudo de puntos (lo pidió el usuario el 2026-10-21: no le gustaba). La idea es la del
// «geometric orb»: paralelos y meridianos blancos sobre negro, nada de resplandores ni azules, y el
// rojo del panel como único acento. La deformación es lo que la hace suya:
//   · Delta habla   → la esfera ondula con SU nivel de voz (d.nivel), y gira más deprisa.
//   · Delta escucha → ondula con lo que entra por el micro (d.mic.nivel), más suave; así se ve de un
//     vistazo que el micro está vivo, que es la avería que más veces nos ha pillado.
//   · en reposo      → solo respira, muy despacio.
//
// Se dibuja en 2D (sin WebGL: three.js ya lo usa la escena de la impresora y aquí sobra): los puntos
// de la esfera se proyectan a mano y los tramos se agrupan en unos pocos trazos por nivel de opacidad,
// que si no son ~1.600 strokes por fotograma.

const FG = '242,242,242', ROJO = '255,45,31';
const PAR = 15, SEG = 72, MER = 12, MSEG = 60;   // paralelos y meridianos, y en cuántos tramos va cada uno
const TILT = .40, DIST = 3.6;                    // inclinación del eje y distancia de la cámara (perspectiva)
const NIV = 5;                                   // niveles de opacidad (profundidad): un trazo por nivel
const ARR = 1.3;                                 // segundos que tarda en salir, del ecuador hacia los polos

let t0 = 0, NV = 0, MV = 0, giro = 0, ult = 0;
export const entrar = () => { t0 = performance.now() / 1000; giro = 0; ult = 0; };

const suave = v => v < 0 ? 0 : v > 1 ? 1 : v * v * (3 - 2 * v);
const nuevos = () => Array.from({length: NIV}, () => new Path2D());

// Un punto de la esfera ya girado, inclinado y proyectado. lat ∈ [-π/2, π/2], lon ∈ [0, 2π).
// `def` es el radio deformado por la voz; se calcula aquí para que paralelos y meridianos coincidan.
function proy(lat, lon, t, voz, cx, cy, R) {
  // La onda es suave a propósito (frecuencias bajas): con ondas rápidas la esfera deja de leerse
  // como esfera y se convierte en una flor. A la ondulación se le suma un hinchado uniforme con la voz.
  const r = 1 + Math.sin(lat * 3 + t * 3.4) * Math.cos(lon * 2 - t * 1.8) * voz * .17 + voz * .05
    + Math.sin(lat * 2 - t * .9) * .022;                       // respiración de fondo, siempre
  const cl = Math.cos(lat) * r, sl = Math.sin(lat) * r, a = lon + giro;
  const px = cl * Math.cos(a), y = sl, z = cl * Math.sin(a);
  const y2 = y * Math.cos(TILT) - z * Math.sin(TILT), z2 = y * Math.sin(TILT) + z * Math.cos(TILT);
  const f = DIST / (DIST - z2);
  return [cx + px * R * f, cy - y2 * R * f, z2];
}

export function pintar(cv, d) {
  const k = Math.min(devicePixelRatio || 1, 2), w = cv.clientWidth, h = cv.clientHeight;
  if (!w || !h) return;
  if (cv.width !== Math.round(w * k)) { cv.width = w * k; cv.height = h * k; }
  const x = cv.getContext('2d'), W = cv.width, H = cv.height;
  const ms = performance.now(), t = ms / 1000 - t0;
  // los niveles se persiguen en vez de saltar: el valor llega cada 0,4 s por el WebSocket
  NV += ((d.nivel || 0) - NV) * .25;
  MV += (((d.mic || {}).nivel || 0) - MV) * .25;
  const est = d.estado || 'dormido', hablando = est === 'hablando';
  const voz = hablando ? NV : est === 'escuchando' ? MV * .7 : 0;
  // el giro se acumula con el tiempo real: así puede cambiar de velocidad sin dar un salto
  const dt = ult ? Math.min(.1, (ms - ult) / 1000) : 0; ult = ms;
  giro += dt * (.10 + (hablando ? .30 : est === 'trabajando' ? .22 : 0) + voz * .5);

  x.clearRect(0, 0, W, H);
  const cx = W / 2, cy = H * .44, R = Math.min(H * .30, W * .23);
  const nac = suave(t / ARR);                       // sale del ecuador hacia los polos
  const paso = Math.ceil(PAR / 2 * nac);            // en pasos discretos: aparece un paralelo, luego otro

  // ---- paralelos ----
  const pal = nuevos();
  for (let i = 0; i < PAR; i++) {
    const c = i - (PAR - 1) / 2;                    // 0 = ecuador
    if (Math.abs(c) > paso) continue;
    const lat = c / ((PAR - 1) / 2) * 1.40;         // sin llegar al polo: ahí los paralelos degeneran en un punto
    let p = proy(lat, 0, t, voz, cx, cy, R);
    for (let j = 1; j <= SEG; j++) {
      const q = proy(lat, j / SEG * Math.PI * 2, t, voz, cx, cy, R);
      tramo(pal, p, q);
      p = q;
    }
  }
  // ---- meridianos: más tenues, solo para que se lea el volumen ----
  const mer = nuevos();
  if (nac > .6) for (let i = 0; i < MER; i++) {
    const lon = i / MER * Math.PI * 2;
    let p = proy(-1.52, lon, t, voz, cx, cy, R);
    for (let j = 1; j <= MSEG; j++) {
      const q = proy(-1.52 + j / MSEG * 3.04, lon, t, voz, cx, cy, R);
      tramo(mer, p, q);
      p = q;
    }
  }
  trazar(x, mer, FG, .26 * nac, k * .55);
  trazar(x, pal, FG, .92 * nac, k * .85);

  // ---- el anillo rojo: el único acento. Sube y baja despacio, y marca el nivel de voz. ----
  if (nac > .8) {
    const lat = Math.sin(t * .34) * 1.2, a = .42 + .58 * Math.min(1, voz * 1.8);
    const ani = nuevos();
    let p = proy(lat, 0, t, voz, cx, cy, R);
    for (let j = 1; j <= SEG; j++) {
      const q = proy(lat, j / SEG * Math.PI * 2, t, voz, cx, cy, R);
      tramo(ani, p, q);
      p = q;
    }
    trazar(x, ani, ROJO, a, k * (1 + Math.min(1, voz * 2)));
  }

  if (nac < 1) return;
  pie(x, W, H, cy + R * 1.28, d, t, k);
}

// El rótulo de abajo (logotipo + línea de datos). Lo usa también la escena «blob», que es otra
// esfera distinta pero el mismo sistema: conviene que los dos digan lo mismo y en el mismo sitio.
export function pie(x, W, H, y, d, t, k) {
  nombre(x, W, y, Math.min(H * .052, W * .044), t);
  estado(x, W, Math.min(y + H * .11, H * .93), d, t, k);
}

// Cada tramo va al trazo que le toca por profundidad: lo de delante, entero; lo de detrás, apenas.
function tramo(paths, p, q) {
  const z = (p[2] + q[2]) / 2;                      // -1 (detrás) … 1 (delante)
  const n = Math.min(NIV - 1, Math.max(0, Math.round((z + 1) / 2 * (NIV - 1))));
  paths[n].moveTo(p[0], p[1]); paths[n].lineTo(q[0], q[1]);
}

function trazar(x, paths, color, base, ancho) {
  for (let i = 0; i < NIV; i++) {
    const a = base * (.10 + .90 * (i / (NIV - 1)) ** 1.8);
    if (a <= .006) continue;
    x.strokeStyle = `rgba(${color},${a})`;
    x.lineWidth = ancho * (.6 + .5 * i / (NIV - 1));
    x.stroke(paths[i]);
  }
}

// El logotipo, calcado de la referencia que dio el usuario (2026-10-21): «Delta.OS» en la misma
// matriz de puntos que el resto del panel, con el punto de separación en rojo —ahí se lee DELTA ·
// Operative System— y, dentro de la O, cuatro puntos rojos que parpadean como un testigo de
// grabación. Antes era todo «DELTAOS» seguido y en mayúsculas y no se entendía el concepto.
function nombre(x, W, y, tam, t) {
  x.save();
  x.font = `900 ${tam}px Doto, monospace`;
  x.textAlign = 'left'; x.textBaseline = 'top';
  x.letterSpacing = `${tam * .10}px`;
  const an = v => x.measureText(v).width;
  const wD = an('Delta'), wP = an('.'), wO = an('O');
  let px = W / 2 - (wD + wP + an('OS')) / 2;
  x.fillStyle = `rgba(${FG},.92)`; x.fillText('Delta', px, y); px += wD;
  x.fillStyle = `rgba(${ROJO},.95)`; x.fillText('.', px, y); px += wP;
  x.fillStyle = `rgba(${FG},.92)`; x.fillText('OS', px, y);
  // los cuatro puntos del hueco de la O: mismo paso y mismo tamaño que los de la tipografía
  const paso = tam * .135, r = tam * .045, cx = px + wO / 2 - tam * .115, cy = y + tam * .44;
  x.fillStyle = `rgba(${ROJO},${.22 + .78 * (Math.sin(t * 3.2) > -.2 ? 1 : 0)})`;
  for (const dx of [-1, 1]) for (const dy of [-1, 1]) {
    x.beginPath(); x.arc(cx + dx * paso / 2, cy + dy * paso / 2, r, 0, 7); x.fill();
  }
  x.restore();
}

const ETI = {dormido: 'EN REPOSO', escuchando: 'ESCUCHANDO', hablando: 'HABLANDO', trabajando: 'TRABAJANDO'};

// La línea de datos: estado, CPU, RAM, temperatura, micro y enlace. El micro aquí no es decoración:
// si pone OFF o 0 dB con la esfera quieta, el problema es el audio y no Delta.
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
  // el testigo rojo parpadea: es el latido del sistema
  x.fillStyle = `rgba(${ROJO},${Math.sin(t * 3.4) > -.3 ? 1 : .12})`;
  x.beginPath(); x.arc(px - 16 * k, y, 4 * k, 0, 7); x.fill();
  x.fillStyle = `rgba(${FG},.62)`;
  x.fillText(txt, px, y);
  x.restore();
}
