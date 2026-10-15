#!/usr/bin/env python3
"""
Gemini Live Assistant:
- Bidirectional live voice chat via Gemini Live API (google-genai SDK)
- Live screen capture streamed to Gemini as video frames
- 100% Native Linux PipeWire/PulseAudio stack (parec + paplay)
- Wayland-native screen capture via Spectacle (-m monitor activo)
- Desactivación de keepalive pings cliente para evitar 'sent 1011 keepalive ping timeout'
"""

import os
import sys
import asyncio
import collections
import io
import argparse
import subprocess
import time
import traceback
import warnings
from PIL import Image

warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning)

# Parchear ws_connect de google.genai para deshabilitar ping_interval en el cliente
# El servidor de Google Live gestiona su propio heartbeat; enviar pings locales
# causa timeout 1011 cuando el ancho de banda está copado por audio y vídeo.
import acciones
import claude_acp  # noqa: F401  (registra sus herramientas en acciones)
import avisos
import movil  # noqa: F401
import deltaos  # noqa: F401  (visor del panel, investigación y skills)
import panel
import google.genai.live as genai_live
_original_ws_connect = genai_live.ws_connect

def _patched_ws_connect(*args, **kwargs):
    kwargs["ping_interval"] = None
    kwargs["ping_timeout"] = None
    return _original_ws_connect(*args, **kwargs)

genai_live.ws_connect = _patched_ws_connect

try:
    from google import genai
    from google.genai import types
except ImportError as e:
    print(f"Error importando dependencias: {e}")
    sys.exit(1)

# Audio configuration
AUDIO_INPUT_CHANNELS = 1
AUDIO_INPUT_RATE = 16000
AUDIO_CHUNK = 1024
PRE_CHUNKS = 6 * AUDIO_INPUT_RATE * 2 // AUDIO_CHUNK  # 6 s de pcm s16: la palabra clave solo salta al final de la frase

AUDIO_OUTPUT_RATE = 24000

def _has_aec():
    out = subprocess.run(["pactl", "list", "short", "sources"], capture_output=True, text=True).stdout
    return "echo-cancel-source" in out

SESSION_HANDLE = {}
AEC = _has_aec()
REC_DEV = ["-d", "echo-cancel-source"] if AEC else []
PLAY_DEV = ["-d", "echo-cancel-sink"] if AEC else []

def start_player():
    return subprocess.Popen(
        ["paplay", "--raw", "--format=s16le", f"--rate={AUDIO_OUTPUT_RATE}", "--channels=1",
         "--latency-msec=60", *PLAY_DEV],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# Available voice options in Gemini Live
VOICES = ["Zephyr", "Puck", "Charon", "Kore", "Fenrir", "Leda", "Orus", "Aoede", "Callirrhoe", "Autonoe",
          "Enceladus", "Iapetus", "Umbriel", "Algieba", "Despina", "Erinome", "Algenib", "Rasalgethi",
          "Laomedeia", "Achernar", "Alnilam", "Schedar", "Gacrux", "Pulcherrima", "Achird",
          "Zubenelgenubi", "Vindemiatrix", "Sadachbia", "Sadaltager", "Sulafat"]

WAKE_WORD = "delta"
UMBRAL_WW = 0.5  # calibrar: subir si se despierta solo, bajar si no te oye

class EyDelta:
    """Wake word entrenada «hey delta» (livekit-wakeword, ONNX). Puntúa los últimos 2 s cada ~100 ms."""
    def __init__(self, ruta):
        from livekit.wakeword import WakeWordModel
        self.m, self.buf, self.n = WakeWordModel(models=[ruta]), collections.deque(maxlen=2 * AUDIO_INPUT_RATE * 2 // AUDIO_CHUNK), 0
    def Reset(self):
        self.buf.clear()
    def oye(self, data) -> bool:
        import numpy as np
        self.buf.append(data); self.n += 1
        if len(self.buf) < self.buf.maxlen or self.n % 3:
            return False
        return max(self.m.predict(np.frombuffer(b"".join(self.buf), np.int16)).values(), default=0) >= UMBRAL_WW

def load_wakeword():
    """Detector local de la palabra clave: nada sale a la red mientras duerme. Usa «hey delta» entrenada si existe; si no, Vosk."""
    import glob
    onnx = sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), "modelos", "wakeword", "output", "**", "hey_delta*.onnx"), recursive=True))
    if onnx:
        try:
            print(f"Palabra clave: «Ey Delta» ({os.path.basename(onnx[0])})")
            return EyDelta(onnx[0])
        except Exception as e:
            print(f"Modelo «Ey Delta» no cargó ({e}); sigo con Vosk.")
    try:
        import json, vosk
        vosk.SetLogLevel(-1)
        model = vosk.Model(os.path.join(os.path.dirname(os.path.abspath(__file__)), "modelos", "vosk-model-small-es-0.42"))
        rec = vosk.KaldiRecognizer(model, AUDIO_INPUT_RATE, json.dumps([WAKE_WORD, "[unk]"]))
        rec.SetWords(True)
        return rec
    except Exception as e:
        print(f"Palabra clave no disponible ({e}); usa Enter para activar.")
        return None

UMBRAL_VOSK = 0.85  # calibrable: sube si aún despiertan la tele o los vídeos

def wake_heard(rec, data) -> bool:
    """ponytail: la gramática cerrada confunde «dentro», «detalle», «delgado»… con «delta» (medido con espeak);
    solo finales: «Delta, <orden>» entra entera gracias a PRE. Filtro de 2ª etapa en saludar(); arreglo real: wake word entrenada."""
    import json
    if isinstance(rec, EyDelta):
        return rec.oye(data)
    if rec.AcceptWaveform(data):  # ponytail: sin parciales ni texto sin confianza; la tele los disparaba
        return any(w.get("word") == WAKE_WORD and w.get("conf", 0) >= UMBRAL_VOSK for w in json.loads(rec.Result()).get("result", []))
    return False

def capture_screen_wayland(max_size=(1024, 1024), quality=60):
    """
    Captura la pantalla en Wayland usando spectacle con la opción -m (monitor activo).
    En Wayland, librerías como MSS solo ven un buffer negro debido al aislamiento de seguridad.
    Spectacle es el estándar oficial de KDE Plasma Wayland.
    """
    tmp_path = "/tmp/gemini_wayland_capture.png"
    try:
        res = subprocess.run(
            ["spectacle", "-b", "-n", "-m", "-o", tmp_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8.0
        )
        if res.returncode == 0 and os.path.exists(tmp_path):
            with Image.open(tmp_path) as img:
                img = img.convert("RGB")
                img.thumbnail(max_size, Image.Resampling.BILINEAR)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=quality)
                return buf.getvalue(), img.convert("L").resize((64, 36)).tobytes()
    except Exception:
        pass
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    return None, None

async def mirar_detalle():
    """La pantalla en vivo va a 1024 px y solo si cambia; esto manda una captura nítida bajo demanda."""
    jpeg, _ = await asyncio.to_thread(capture_screen_wayland, (2560, 2560), 85)
    if not jpeg or not acciones.ST["session"]:
        return "Error: no pude capturar la pantalla."
    await acciones.ST["session"].send_realtime_input(video=types.Blob(data=jpeg, mime_type="image/jpeg"))
    return "Te acabo de enviar una captura nítida de la pantalla completa: léela con detalle y responde."

acciones.registrar([acciones._fn("mirar_detalle",
    "Captura la pantalla en alta resolución cuando necesites leer texto pequeño, código o detalles que no distingues.")], (mirar_detalle,))

UMBRAL_CAMBIO = 1.5  # diferencia media (0..255) en la miniatura 64x36: por debajo, la pantalla «no ha cambiado»

def cambio(a: bytes, b: bytes) -> float:
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)

def medir_mic(pcm: bytes):
    """Nivel RMS/pico del micro y racha de saturación: alimentan los relojes y alertas del panel."""
    ST = acciones.ST
    m = memoryview(pcm[: len(pcm) // 2 * 2]).cast("h")
    pico = max(map(abs, m), default=0)
    rms = (sum(x * x for x in m[::4]) / max(1, len(m[::4]))) ** 0.5
    ST.update(mic_rms=rms, mic_pico=pico, mic_t=time.monotonic(),
              mic_clip=0.95 * ST.get("mic_clip", 0) + 0.05 * (pico >= 32000))
    if rms > 800 and ST["activo"] and not ST.get("hablando"):
        ST["t_voz"] = ST["mic_t"]  # último instante en que el usuario sonaba: de ahí se mide la latencia

PRE = collections.deque(maxlen=PRE_CHUNKS)  # últimos ~6 s de audio mientras duerme: solo en RAM, nada sale a la red

async def saludar(session):
    """Tras «Delta», ANTES del audio: la instrucción entra como contexto sin disparar respuesta (turn_complete=False);
    responde solo el VAD al audio. Mandarla como texto aparte daba dos respuestas solapadas (medido: «dos voces»)."""
    try:
        await session.send_client_content(turns=types.Content(role="user", parts=[types.Part(text=(
            "[EVENTO DEL SISTEMA: el detector local cree que el usuario te ha llamado con «Delta», pero a veces se confunde. "
            "Escucha el audio anterior: si NO se oye claramente «Delta» dicho a ti (p.ej. dijo «dentro», «detalle» o hablaba "
            "con otra persona o con un vídeo), no digas absolutamente nada y llama a dormir. "
            "Si te llamó y ya pidió algo, atiéndelo sin saludar. Si solo te llamó, salúdale en una frase muy corta y natural (varía cada vez), "
            "dile brevemente lo que importe de este contexto si hay algo, y pregunta qué necesita. "
            f"Contexto: {panel.contexto(acciones.ST)}. No menciones esta etiqueta.]"))]), turn_complete=False)
    except Exception as e:
        print(f"No pude saludar: {e}")

MAX_PEND = 10 * AUDIO_INPUT_RATE * 2 // AUDIO_CHUNK  # tope de audio guardado mientras reconecta (10 s)

def _blob(c):
    return types.Blob(data=c, mime_type="audio/pcm;rate=16000")

async def audio_input_loop():
    """Micro siempre abierto (parec). Dormido: solo la palabra clave en local, nada sale a la red.
    Despierto: a la sesión que haya; si aún está conectando (tras el reposo), se guarda y se manda al conectar."""
    ST = acciones.ST
    ww = load_wakeword()
    print(f"\n🎙️ En espera: di «{'Ey Delta' if isinstance(ww, EyDelta) else 'Delta'}» o pulsa Enter para activarme.")
    pend, llamado, estaba = [], False, False
    while True:  # si parec muere, se relanza
        recorder = subprocess.Popen(
            ["parec", *REC_DEV, "--raw", "--format=s16le", f"--rate={AUDIO_INPUT_RATE}", f"--channels={AUDIO_INPUT_CHANNELS}"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            while data := await asyncio.to_thread(recorder.stdout.read, AUDIO_CHUNK):
                if ST.get("privacidad"):
                    continue  # modo privacidad: se descarta todo, ni la palabra clave se procesa
                medir_mic(data)
                if not ST["activo"]:
                    estaba = False
                    PRE.append(data)
                    if ww and wake_heard(ww, data):
                        ww.Reset()
                        acciones.activar()
                        pend, llamado, estaba = list(PRE), True, True  # lo dicho justo antes y durante «Delta»
                        PRE.clear()
                    continue
                if not estaba:  # despertado por Enter, panel o aviso: lo de antes no es para Gemini
                    PRE.clear()
                    pend, estaba = [], True
                session = ST["session"]
                if session is None or (not AEC and ST.get("hablando")):
                    # Sin sesión: guardar hasta que conecte. Sin AEC y hablando él: micro mudo (el altavoz le interrumpiría).
                    if session is None:
                        pend.append(data)
                        del pend[:-MAX_PEND]
                    continue
                try:
                    if llamado:
                        llamado = False
                        await saludar(session)
                    for c in pend:
                        await session.send_realtime_input(audio=_blob(c))
                    pend = []
                    await session.send_realtime_input(audio=_blob(data))
                except Exception:
                    pend.append(data)  # sesión cerrándose: la siguiente lo recibe
                    await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"Error en entrada de audio: {e}")
        finally:
            recorder.terminate()
        await asyncio.sleep(1)

async def screen_capture_loop(session, interval=8.0):
    """Mira la pantalla cada `interval` s despierto y solo la envía si ha cambiado (la 1ª tras despertar, siempre)."""
    print(f"🖥️ Captura de pantalla en vivo activada (cada {interval}s, solo si cambia)...")
    firma = None
    try:
        while True:
            if not acciones.ST["activo"] or acciones.ST.get("privacidad"):
                firma = None
                await asyncio.sleep(0.3)
                continue
            jpeg_bytes, nueva = await asyncio.to_thread(capture_screen_wayland)
            if jpeg_bytes and (firma is None or cambio(firma, nueva) > UMBRAL_CAMBIO):
                firma = nueva
                await session.send_realtime_input(video=types.Blob(data=jpeg_bytes, mime_type="image/jpeg"))
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"Error en captura de pantalla: {e}")

def nivel_audio(pcm: bytes) -> float:
    """Amplitud RMS 0..1 de PCM int16 (submuestreado: basta para animar)."""
    m = memoryview(pcm[: len(pcm) // 2 * 2]).cast("h")[::8]
    return min(1.0, (sum(x * x for x in m) / max(1, len(m))) ** 0.5 / 9000)

async def receive_and_play_loop(session):
    """Recibe la respuesta de audio y la reproduce por paplay nativo."""
    player = start_player()
    rotar = False  # GoAway recibido: reconectar en cuanto nadie hable

    try:
        # receive() termina en cada turn_complete: hay que re-llamarlo para el turno siguiente
        while True:
            async for response in session.receive():
                upd = getattr(response, 'session_resumption_update', None)
                if upd and upd.new_handle:
                    SESSION_HANDLE.update(h=upd.new_handle, t=time.monotonic())
                if response.usage_metadata:
                    panel.uso(response.usage_metadata)
                if response.tool_call:
                    acciones.tarea(acciones.atender(session, response.tool_call))
                if response.go_away:  # el servidor cortará en time_left: reconectar con el handle sin cortar una frase
                    print(f"\n↻ GoAway ({response.go_away.time_left}), reconecto al acabar el turno…", flush=True)
                    rotar = True
                if rotar and not acciones.ST["hablando"]:
                    return
                server_content = response.server_content
                if server_content is not None:
                    if server_content.model_turn or server_content.turn_complete:
                        acciones.ST["ultima"] = time.monotonic()
                    if getattr(server_content, 'output_transcription', None):
                        t = server_content.output_transcription.text
                        if t:
                            print(t, end="", flush=True)
                            panel.texto("delta", t)
                    if getattr(server_content, 'input_transcription', None):
                        t = server_content.input_transcription.text
                        if t:
                            if t.strip() == "<noise>":  # Gemini oye ruido, no voz: micro saturado o roto
                                acciones.ST["ruido"] = acciones.ST.get("ruido", 0) + 1
                            else:
                                acciones.ST["ruido"] = 0
                                acciones.ST["t_tu"] = time.monotonic()  # el usuario ha hablado (permisos por voz)
                                panel.texto("tú", t)

                    if getattr(server_content, 'interrupted', False):
                        acciones.ST["hablando"] = False
                        player.kill()
                        player = start_player()

                    model_turn = server_content.model_turn
                    if model_turn is not None:
                        for part in model_turn.parts:
                            if part.text and not getattr(part, 'thought', False):
                                print(part.text, end="", flush=True)
                            if part.inline_data:
                                audio_data = part.inline_data.data
                                tv = acciones.ST.pop("t_voz", None)
                                if tv and not acciones.ST["hablando"] and time.monotonic() - tv < 8:
                                    acciones.ST["lat"] = round((time.monotonic() - tv) * 1000)
                                acciones.ST["hablando"] = True
                                if player.poll() is not None or not player.stdin or player.stdin.closed:
                                    try:
                                        player.kill()
                                    except Exception:
                                        pass
                                    player = start_player()
                                panel.habla(nivel_audio(audio_data))
                                try:
                                    player.stdin.write(audio_data)
                                    player.stdin.flush()
                                except (BrokenPipeError, OSError) as pe:
                                    print(f"\n⚠️ [Audio] Fallo escribiendo en player ({pe}), reiniciando paplay...", flush=True)
                                    try:
                                        player.kill()
                                    except Exception:
                                        pass
                                    player = start_player()
                                    try:
                                        player.stdin.write(audio_data)
                                        player.stdin.flush()
                                    except Exception:
                                        pass
                    if server_content.turn_complete:
                        print("\n---")
                        acciones.ST["hablando"] = False
                        panel.fin_turno()
                        if rotar:
                            return
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"\nError en bucle de recepción: {e}")
        traceback.print_exc()
    finally:
        if player.stdin and not player.stdin.closed:
            player.stdin.close()
        player.terminate()

REPOSO = 120  # s dormido con la sesión abierta antes de colgar; al despertar reconecta en ~1 s con el handle
CADUCA_HANDLE = 90 * 60  # s; el servidor guarda la sesión ~2 h

async def centinela():
    """Termina tras REPOSO s dormido y sin nada pendiente: colgar ahorra cuota y evita sesiones zombis."""
    st, desde = acciones.ST, None
    while True:
        await asyncio.sleep(1)
        ocupado = st["activo"] or st["pending"] or st.get("herramienta") or st.get("claude", {}).get("estado") in ("trabajando", "esperando permiso")
        desde = None if ocupado else desde or time.monotonic()
        if desde and time.monotonic() - desde > REPOSO:
            print("\n🌙 Cuelgo la sesión hasta que me llames.", flush=True)
            return

async def vigilante():
    """Vuelve a dormir tras INACTIVIDAD s sin que el modelo hable ni actúe."""
    while True:
        await asyncio.sleep(2)
        st = acciones.ST
        if st["activo"] and not st["pending"] and time.monotonic() - st["ultima"] > acciones.INACTIVIDAD:
            acciones.dormir_ahora()

async def main():
    parser = argparse.ArgumentParser(description="Delta: asistente de voz y pantalla (Gemini Live)")
    parser.add_argument("--sin-panel", action="store_true", help="No arrancar el panel web de estado")
    parser.add_argument("--voice", default="Charon", choices=VOICES, help="Voz del asistente (30 disponibles, p.ej. Orus, Zephyr, Algieba)")
    parser.add_argument("--interval", type=float, default=8.0, help="Intervalo de capturas de pantalla en segundos (def: 8)")
    parser.add_argument("--no-screen", action="store_true", help="Desactiva la captura de pantalla (solo voz)")
    args = parser.parse_args()

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY no está definida en el entorno.")
        sys.exit(1)

    print("==================================================")
    print("            DELTA · asistente de voz              ")
    print("==================================================")
    print(f"Voz seleccionada : {args.voice}")
    print(f"Pantalla en vivo : {'Desactivada' if args.no_screen else f'Activada ({args.interval}s)'}")
    print("Presiona Ctrl+C para salir.")

    client = genai.Client()

    model_id = "gemini-3.8-live"
    def make_config(handle):
      return types.LiveConnectConfig(
        # Sin compresión, audio+vídeo caduca a ~2 min; con ella la sesión sigue.
        context_window_compression=types.ContextWindowCompressionConfig(
            sliding_window=types.SlidingWindow()),
        session_resumption=types.SessionResumptionConfig(handle=handle),
        tools=acciones.TOOLS,
        response_modalities=[types.Modality.AUDIO],
        speech_config=types.SpeechConfig(
            language_code="es-ES",  # sin esto Charon sale con acento latino
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=args.voice
                )
            )
        ),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        system_instruction=types.Content(
            parts=[types.Part.from_text(
                text=(
                    open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "personalidad.txt"), encoding="utf-8").read() + "\n\n"
                    "El usuario te hablará por voz y verás su pantalla en vivo. "
                    "Sé conciso y directo al responder por voz. "
                    "Responde siempre en español de España: pronunciación y acento castellano peninsular (no latinoamericano), con seseo prohibido (distingue z/c de s), y vocabulario de España (ordenador, vale, coger, móvil). "
                    "Cuando el usuario pregunte por algo que ve en su pantalla, descríbeselo o guíale con claridad. "
                    "Tienes herramientas: búsqueda web, abrir apps/URLs, scripts de WORMHOLE y ciclo de verificación, shell, delegar en Claude Code, estado de proyectos, memoria (recordar/olvidar), estado e historial de la impresora Klipper (solo lectura) y programar aviso cuando falten N minutos de impresión, poner y controlar música, volumen, brillo, portapapeles, ventanas (activar, minimizar, cerrar, mover a la otra pantalla) y notificaciones. "
                    "También: mostrar webs, Google, YouTube, Wikipedia, mapas e informes integrados en la pantalla del panel (DeltaOS), búsqueda rápida en internet (buscar: úsala cuando te pidan buscar algo y di los datos clave), investigación profunda con informe y citas SOLO si la piden expresamente, captura nítida de pantalla (mirar_detalle) y skills. "
                    "Úsalas cuando el usuario pida una acción, sin pedir permiso tú: la terminal ya le pregunta si es peligroso. "
                    "Cuando trabajes con herramientas, narra en voz lo que haces en frases muy cortas («Enseguida.», «Consultando la impresora.»), sin leer resultados enteros. "
                    "Si te piden enseñar, ver o abrir algo para mirarlo, usa mostrar (sale en el panel); abrir es solo para el navegador o apps del escritorio. "
                    "Skills: si una tarea encaja con una skill instalada, léela con usar_skill y síguela. Si no tienes ninguna que encaje y es algo que hará falta a menudo, "
                    "búscala con buscar_skills e instálala tú mismo sin pedir permiso, y dile al usuario cuál has instalado. Skills instaladas:\n" + deltaos.resumen_skills() + "\n"
                    "Si el usuario te pide una capacidad que aún no tienes, invoca anotar_mejora para que el desarrollador la implemente. Los fallos (micro, audio, impresora) no son mejoras: díselos al usuario de palabra y como mucho anótalos una vez. "
                    "Temporizadores, alarmas y recordatorios con hora: programar_aviso (no recordar, que es para datos). Móvil por KDE Connect: leer notificaciones, responderlas, SMS y hacerlo sonar. "
                    "Los trabajos largos corren en segundo plano y recibirás un [AVISO DEL SISTEMA] al acabar: díselo al usuario en una frase. "
                    "Usa recordar cuando el usuario diga que recuerdes algo, y dormir cuando se despida. "
                    "No hables por iniciativa propia por lo que cambie en la pantalla: habla solo cuando el usuario te hable o llegue un [AVISO DEL SISTEMA] o [EVENTO DEL SISTEMA]. "
                    "Notas guardadas del usuario:\n" + (acciones.leer_memoria() or "(ninguna todavía)")
                )
            )]
        )
    )

    loop = asyncio.get_running_loop()
    if sys.stdin.isatty():
        loop.add_reader(sys.stdin.fileno(), lambda: acciones.entrada_stdin(sys.stdin.readline()))
    acciones.tarea(vigilante())
    if not args.sin_panel:
        await panel.start(acciones.ST, args.voice)
    acciones.tarea(acciones.vigilar_impresora())
    acciones.tarea(avisos.vigilar())

    acciones.tarea(audio_input_loop())  # el micro vive siempre; la sesión va y viene
    fallos = 0
    while True:
        if not acciones.ST["activo"]:
            acciones.ST["reposo"] = True
            while not acciones.ST["activo"]:
                await asyncio.sleep(0.1)
        # el handle caduca (~2 h en el servidor) y uno inválido da 1007 en bucle: tras 2 fallos seguidos, sesión nueva
        handle = SESSION_HANDLE.get("h") if fallos < 2 and time.monotonic() - SESSION_HANDLE.get("t", 0) < CADUCA_HANDLE else None
        t0 = time.monotonic()
        try:
            async with client.aio.live.connect(model=model_id, config=make_config(handle)) as session:
                acciones.ST.update(session=session, reposo=False)
                print(f"\n🔗 Sesión {'reanudada' if handle else 'nueva'}", flush=True)
                for aviso in acciones.ST.pop("avisos", []):  # llegaron mientras estaba colgado
                    await acciones.avisar(aviso, notificar=False)
                tasks = [asyncio.create_task(receive_and_play_loop(session)), asyncio.create_task(centinela())]
                if not args.no_screen:
                    tasks.append(asyncio.create_task(screen_capture_loop(session, args.interval)))
                # Si cualquier bucle termina (sesión rota, GoAway o reposo largo): cancelar y seguir.
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for t in pending:
                    t.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
        except Exception as e:
            print(f"\nError en la sesión Live: {e}")
        acciones.ST["session"] = None
        fallos = fallos + 1 if time.monotonic() - t0 < 15 else 0
        await asyncio.sleep(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
