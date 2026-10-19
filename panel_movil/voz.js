// Voz de Delta en el móvil: mantener pulsado 🎙 para hablar. El móvil habla DIRECTO con Gemini Live
// (token de un uso que da el PC, con modelo, voz y herramientas bloqueados); el PC solo responde a las herramientas.
(() => {  // ámbito propio: no choca con los nombres de index.html
const WS = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContentConstrained";
const CIERRE_INACTIVO = 120_000;  // ms sin hablar → se cierra la sesión (no gasta)
const TROZO = 1600;               // muestras a 16 kHz por envío (100 ms)

const V = {ws: null, listo: null, ctxIn: null, ctxOut: null, mic: null, nodo: null, hablando: false,
           fin: 0, fuentes: [], yo: null, d: null, temporizador: null};

const b64 = buf => { let s = ""; const b = new Uint8Array(buf); for (let i = 0; i < b.length; i += 0x8000) s += String.fromCharCode(...b.subarray(i, i + 0x8000)); return btoa(s); };
const deb64 = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
const enviar = o => V.ws?.readyState === 1 && V.ws.send(JSON.stringify(o));

function conectar(alEstado) {
  if (V.listo) return V.listo;
  V.listo = (async () => {
    alEstado("conectando");
    const r = await post("/voz/token", {});
    if (!r.token) throw new Error("el PC no dio token (" + (r.error || "?") + ")");
    const ws = new WebSocket(`${WS}?access_token=${encodeURIComponent(r.token)}`);
    ws.binaryType = "arraybuffer";
    V.ws = ws;
    await new Promise((ok, mal) => {
      ws.onopen = () => ws.send(JSON.stringify({setup: {model: "models/" + r.modelo}}));
      ws.onerror = () => mal(new Error("sin conexión con Gemini"));
      ws.onmessage = e => { const d = leer(e.data); if (d.setupComplete) { ws.onmessage = ev => recibir(leer(ev.data)); ok(); } };
    });
    ws.onclose = () => { V.ws = null; V.listo = null; alEstado("cerrado"); };
    alEstado("listo");
  })();
  V.listo.catch(() => { V.listo = null; });
  return V.listo;
}

const leer = data => JSON.parse(typeof data === "string" ? data : new TextDecoder().decode(data));

async function recibir(d) {
  if (d.toolCall) {
    const respuestas = await Promise.all(d.toolCall.functionCalls.map(async fc => {
      let resultado;
      try { resultado = (await post("/voz/herramienta", {nombre: fc.name})).resultado; } catch { resultado = {error: "PC sin respuesta"}; }
      return {id: fc.id, name: fc.name, response: {resultado}};
    }));
    enviar({toolResponse: {functionResponses: respuestas}});
  }
  const sc = d.serverContent;
  if (!sc) return;
  if (sc.interrupted) callar();
  for (const p of sc.modelTurn?.parts || []) if (p.inlineData?.data) sonar(deb64(p.inlineData.data));
  if (sc.inputTranscription?.text) { V.yo ||= burbuja("yo", ""); V.yo.textContent += sc.inputTranscription.text; }
  if (sc.outputTranscription?.text) {
    V.yo = null;
    V.d ||= burbuja("d", "");
    V.d.textContent += sc.outputTranscription.text;
    chat.scrollTop = chat.scrollHeight;
  }
  if (sc.turnComplete) V.d = null;
}

// ---- salida: PCM 16 bits a 24 kHz, en cola sin huecos ----
function sonar(bytes) {
  V.ctxOut ||= new AudioContext({sampleRate: 24000});
  const n = bytes.length >> 1, dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const buf = V.ctxOut.createBuffer(1, n, 24000), ch = buf.getChannelData(0);
  for (let i = 0; i < n; i++) ch[i] = dv.getInt16(2 * i, true) / 32768;
  const src = V.ctxOut.createBufferSource();
  src.buffer = buf; src.connect(V.ctxOut.destination);
  V.fin = Math.max(V.fin, V.ctxOut.currentTime + 0.05);
  src.start(V.fin); V.fin += buf.duration;
  V.fuentes.push(src); src.onended = () => V.fuentes.splice(V.fuentes.indexOf(src), 1);
}
function callar() { V.fuentes.forEach(s => { try { s.stop(); } catch {} }); V.fuentes = []; V.fin = 0; }

// ---- entrada: micro a 16 kHz → PCM 16 bits ----
const WORKLET = `registerProcessor("pcm", class extends AudioWorkletProcessor {
  constructor(){ super(); this.b = new Int16Array(${TROZO}); this.i = 0; }
  process([e]){ const c = e[0]; if (!c) return true;
    for (let k = 0; k < c.length; k++){ const v = Math.max(-1, Math.min(1, c[k])); this.b[this.i++] = v < 0 ? v * 32768 : v * 32767;
      if (this.i === this.b.length){ this.port.postMessage(this.b.buffer.slice(0)); this.i = 0; } }
    return true; } });`;

async function abrirMicro() {
  if (V.mic) return;
  V.ctxIn = new AudioContext({sampleRate: 16000});
  await V.ctxIn.audioWorklet.addModule(URL.createObjectURL(new Blob([WORKLET], {type: "text/javascript"})));
  V.mic = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true, noiseSuppression: true, autoGainControl: true}});
  V.nodo = new AudioWorkletNode(V.ctxIn, "pcm");
  V.nodo.port.onmessage = e => V.hablando && enviar({realtimeInput: {audio: {data: b64(e.data), mimeType: "audio/pcm;rate=16000"}}});
  V.ctxIn.createMediaStreamSource(V.mic).connect(V.nodo);
}
function cerrarMicro() {  // suelta el micro (Android deja de mostrar el punto verde)
  V.mic?.getTracks().forEach(t => t.stop()); V.ctxIn?.close();
  V.mic = V.nodo = V.ctxIn = null;
}

function programarCierre() {
  clearTimeout(V.temporizador);
  V.temporizador = setTimeout(() => { V.ws?.close(); cerrarMicro(); }, CIERRE_INACTIVO);
}

// ---- botón: mantener pulsado para hablar ----
function montarVoz(boton) {
  const estado = e => { boton.dataset.estado = e; boton.classList.toggle("vivo", e === "hablando"); boton.classList.toggle("espera", e === "conectando"); };
  let soltado = false;
  async function empezar(ev) {
    ev.preventDefault(); boton.setPointerCapture?.(ev.pointerId);
    soltado = false; callar(); V.ctxOut?.resume();
    try { await Promise.all([conectar(estado), abrirMicro()]); }
    catch (e) { estado("cerrado"); burbuja("d", "No puedo usar la voz: " + e.message); return; }
    if (soltado) return;  // un toque corto: ya está conectado para la próxima
    V.yo = V.d = null; V.hablando = true; estado("hablando");
    enviar({realtimeInput: {activityStart: {}}});
    programarCierre();
  }
  function terminar() {
    soltado = true;
    if (!V.hablando) return;
    V.hablando = false; estado("listo");
    enviar({realtimeInput: {activityEnd: {}}});
    programarCierre();
  }
  boton.addEventListener("pointerdown", empezar);
  ["pointerup", "pointercancel", "pointerleave"].forEach(t => boton.addEventListener(t, terminar));
  boton.addEventListener("contextmenu", e => e.preventDefault());  // pulsación larga sin menú de Android
}

window.montarVoz = montarVoz;
})();
