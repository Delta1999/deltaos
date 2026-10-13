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

def load_wakeword():
    """Reconocedor Vosk local restringido a la palabra clave: nada sale a la red mientras duerme."""
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

def wake_heard(rec, data) -> bool:
    # Solo resultados finales con confianza alta: evita falsos positivos de audios de fondo.
    if not rec.AcceptWaveform(data):
        return False
    import json
    return any(w["word"] == WAKE_WORD and w["conf"] >= 0.90
               for w in json.loads(rec.Result()).get("result", []))

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
                return buf.getvalue()
    except Exception:
        pass
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    return None

async def audio_input_loop(session):
    """Lee audio del micrófono directamente desde parec (PipeWire/PulseAudio nativo)."""
    recorder = subprocess.Popen(
        ["parec", *REC_DEV, "--raw", "--format=s16le", f"--rate={AUDIO_INPUT_RATE}", f"--channels={AUDIO_INPUT_CHANNELS}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL
    )

    print("\n🎙️ En espera: di «Delta» o pulsa Enter para activarme.")
    ww = load_wakeword()
    try:
        while True:
            data = await asyncio.to_thread(recorder.stdout.read, AUDIO_CHUNK)
            if not data:
                break
            if not acciones.ST["activo"]:
                # dormido: nada sale a la red; solo escucha local la palabra clave
                if ww and wake_heard(ww, data):
                    ww.Reset()
                    acciones.activar()
                continue
            audio_blob = types.Blob(data=data, mime_type="audio/pcm;rate=16000")
            await session.send_realtime_input(audio=audio_blob)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"Error en entrada de audio: {e}")
    finally:
        recorder.terminate()

async def screen_capture_loop(session, interval=6.0):
    """Envía capturas de pantalla periódicas usando video=types.Blob."""
    print(f"🖥️ Captura de pantalla en vivo activada (cada {interval}s)...")
    try:
        while True:
            jpeg_bytes = await asyncio.to_thread(capture_screen_wayland) if acciones.ST["activo"] else None
            if jpeg_bytes:
                video_blob = types.Blob(data=jpeg_bytes, mime_type="image/jpeg")
                await session.send_realtime_input(video=video_blob)
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

    try:
        # receive() termina en cada turn_complete: hay que re-llamarlo para el turno siguiente
        while True:
            async for response in session.receive():
                upd = getattr(response, 'session_resumption_update', None)
                if upd and upd.new_handle:
                    SESSION_HANDLE["h"] = upd.new_handle
                if response.tool_call:
                    asyncio.create_task(acciones.atender(session, response.tool_call))
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
                            panel.texto("tú", t)

                    if getattr(server_content, 'interrupted', False):
                        player.kill()
                        player = start_player()

                    model_turn = server_content.model_turn
                    if model_turn is not None:
                        for part in model_turn.parts:
                            if part.text and not getattr(part, 'thought', False):
                                print(part.text, end="", flush=True)
                            if part.inline_data:
                                audio_data = part.inline_data.data
                                if player.stdin and not player.stdin.closed:
                                    panel.habla(nivel_audio(audio_data))
                                    try:
                                        player.stdin.write(audio_data)
                                        player.stdin.flush()
                                    except (BrokenPipeError, OSError):
                                        pass
                    if server_content.turn_complete:
                        print("\n---")
                        panel.fin_turno()
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"\nError en bucle de recepción: {e}")
        traceback.print_exc()
    finally:
        if player.stdin and not player.stdin.closed:
            player.stdin.close()
        player.terminate()

async def vigilante():
    """Vuelve a dormir tras INACTIVIDAD s sin que el modelo hable ni actúe."""
    while True:
        await asyncio.sleep(2)
        st = acciones.ST
        if st["activo"] and not st["pending"] and time.monotonic() - st["ultima"] > acciones.INACTIVIDAD:
            acciones.dormir_ahora()

async def main():
    parser = argparse.ArgumentParser(description="Gemini Live Screen & Voice Assistant")
    parser.add_argument("--sin-panel", action="store_true", help="No arrancar el panel web de estado")
    parser.add_argument("--voice", default="Aoede", choices=VOICES, help="Voz del asistente (30 disponibles, p.ej. Orus, Zephyr, Algieba)")
    parser.add_argument("--interval", type=float, default=6.0, help="Intervalo de capturas de pantalla en segundos (def: 6)")
    parser.add_argument("--no-screen", action="store_true", help="Desactiva la captura de pantalla (solo voz)")
    args = parser.parse_args()

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY no está definida en el entorno.")
        sys.exit(1)

    print("==================================================")
    print("      GEMINI LIVE SCREEN & VOICE ASSISTANT        ")
    print("==================================================")
    print(f"Voz seleccionada : {args.voice}")
    print(f"Pantalla en vivo : {'Desactivada' if args.no_screen else f'Activada ({args.interval}s)'}")
    print("Presiona Ctrl+C para salir.")

    client = genai.Client()

    model_id = "gemini-2.5-flash-native-audio-latest"
    def make_config(handle):
      return types.LiveConnectConfig(
        # Sin compresión, audio+vídeo caduca a ~2 min; con ella la sesión sigue.
        context_window_compression=types.ContextWindowCompressionConfig(
            sliding_window=types.SlidingWindow()),
        session_resumption=types.SessionResumptionConfig(handle=handle),
        tools=acciones.TOOLS,
        response_modalities=[types.Modality.AUDIO],
        speech_config=types.SpeechConfig(
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
                    "Eres un asistente conversacional en tiempo real en español. "
                    "El usuario te hablará por voz y verás su pantalla en vivo. "
                    "Sé conciso, directo, natural y amigable al responder por voz. "
                    "Responde siempre en español de España: pronunciación y acento castellano peninsular (no latinoamericano), con seseo prohibido (distingue z/c de s), y vocabulario de España (ordenador, vale, coger, móvil). "
                    "Cuando el usuario pregunte por algo que ve en su pantalla, descríbeselo o guíale con claridad. "
                    "Tienes herramientas: búsqueda web, abrir apps/URLs, scripts de WORMHOLE y ciclo de verificación, shell, delegar en Claude Code, estado de proyectos, memoria (recordar/olvidar), estado de la impresora Klipper y programar aviso cuando falten N minutos de impresión, volumen, brillo, portapapeles, ventanas (activar, minimizar, cerrar, mover a la otra pantalla) y notificaciones. "
                    "Úsalas cuando el usuario pida una acción, sin pedir permiso tú: la terminal ya le pregunta si es peligroso. "
                    "Si el usuario te pide alguna acción o capacidad que aún no sepas o no puedas realizar, invoca anotar_mejora inmediatamente para que el desarrollador la implemente. "
                    "Los trabajos largos corren en segundo plano y recibirás un [AVISO DEL SISTEMA] al acabar: díselo al usuario en una frase. "
                    "Usa recordar cuando el usuario diga que recuerdes algo, y dormir cuando se despida. "
                    "Notas guardadas del usuario:\n" + (acciones.leer_memoria() or "(ninguna todavía)")
                )
            )]
        )
    )

    loop = asyncio.get_running_loop()
    if sys.stdin.isatty():
        loop.add_reader(sys.stdin.fileno(), lambda: acciones.entrada_stdin(sys.stdin.readline()))
    asyncio.create_task(vigilante())
    if not args.sin_panel:
        await panel.start(acciones.ST, args.voice)
    asyncio.create_task(acciones.vigilar_impresora())

    handle = None
    while True:
        try:
            async with client.aio.live.connect(model=model_id, config=make_config(handle)) as session:
                acciones.ST["session"] = session
                tasks = [
                    asyncio.create_task(audio_input_loop(session)),
                    asyncio.create_task(receive_and_play_loop(session))
                ]
                if not args.no_screen:
                    tasks.append(asyncio.create_task(screen_capture_loop(session, args.interval)))
                # Si cualquier bucle termina, la sesión está rota: cancelar y reconectar.
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for t in pending:
                    t.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                handle = SESSION_HANDLE.get("h", handle)
            acciones.ST["session"] = None
            print("\n⚠️ Sesión cerrada, reconectando...")
        except Exception as e:
            print(f"\nError en la sesión Live: {e}")
            traceback.print_exc()
            handle = SESSION_HANDLE.get("h", handle)
        await asyncio.sleep(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
