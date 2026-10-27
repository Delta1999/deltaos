"""Puente de la GoPro Hero 3 para la visión de Delta: corre en la caja de la impresora, no en el portátil.
La caja lleva un adaptador WiFi USB dedicado unido a la red de la GoPro (10.5.5.x). Este servicio:
  1. mantiene encendida la vista previa de la cámara (solo funciona en modo vídeo) y
  2. reenvía SOLO el puerto del flujo (8080) por la IP de Tailscale de la caja, para que vision.py lo abra como
     http://<ip tailscale>:18080/live/amba.m3u8. Los comandos de control (disparador, modos, borrar) no se exponen.
Solo biblioteca estándar. La contraseña de la cámara va en GOPRO_ENV (EnvironmentFile), nunca en el repo."""
import asyncio
import os
import urllib.request

GOPRO_IP = os.environ.get("GOPRO_IP", "10.5.5.9")
GOPRO_PW = os.environ["GOPRO_PW"]
ESCUCHA = (os.environ.get("ESCUCHA_IP", "100.114.68.63"), int(os.environ.get("ESCUCHA_PUERTO", "18080")))
STREAM = 8080  # puerto del flujo HLS en la cámara


def _orden(ruta):
    try:
        urllib.request.urlopen(f"http://{GOPRO_IP}{ruta}", timeout=5).read()
    except Exception:  # 410 = ya estaba así; cámara apagada = se reintenta en el siguiente ciclo
        pass


def _secuencia():
    """Número de secuencia de la lista HLS: sube unos 4 por segundo mientras la cámara emite; None si no contesta."""
    try:
        lista = urllib.request.urlopen(f"http://{GOPRO_IP}:{STREAM}/live/amba.m3u8", timeout=4).read().decode()
        return int(lista.split("#EXT-X-MEDIA-SEQUENCE:")[1].split()[0])
    except (OSError, IndexError, ValueError):
        return None


async def mantener():
    """Vigila la vista previa. Sin respuesta: modo vídeo (la Hero 3 no da vista previa en otro modo) y vista previa
    encendida. Respuesta pero la secuencia no avanza (la cámara se queda emitiendo lo mismo): apagar y encender."""
    anterior = None
    while True:
        actual = await asyncio.to_thread(_secuencia)
        if actual is None:
            await asyncio.to_thread(_orden, f"/camera/CM?t={GOPRO_PW}&p=%00")
            await asyncio.sleep(2)
            await asyncio.to_thread(_orden, f"/camera/PV?t={GOPRO_PW}&p=%02")
        elif actual == anterior:
            await asyncio.to_thread(_orden, f"/camera/PV?t={GOPRO_PW}&p=%00")
            await asyncio.sleep(2)
            await asyncio.to_thread(_orden, f"/camera/PV?t={GOPRO_PW}&p=%02")
        anterior = actual
        await asyncio.sleep(10)


async def _tuberia(lee, escribe):
    try:
        while datos := await lee.read(65536):
            escribe.write(datos)
            await escribe.drain()
    except OSError:
        pass
    finally:
        escribe.close()


async def atender(cli_r, cli_w):
    try:
        cam_r, cam_w = await asyncio.wait_for(asyncio.open_connection(GOPRO_IP, STREAM), 5)
    except (OSError, asyncio.TimeoutError):
        cli_w.close()
        return
    await asyncio.gather(_tuberia(cli_r, cam_w), _tuberia(cam_r, cli_w))


async def main():
    servidor = await asyncio.start_server(atender, *ESCUCHA)
    print(f"puente GoPro: {ESCUCHA[0]}:{ESCUCHA[1]} -> {GOPRO_IP}:{STREAM}", flush=True)
    async with servidor:
        await asyncio.gather(servidor.serve_forever(), mantener())


asyncio.run(main())
