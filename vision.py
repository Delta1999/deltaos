"""Visión de Delta (fase 5.1): cámaras → eventos (presencia, atención, gestos, postura, fatiga).

Proceso aparte, no dentro de Delta: el vídeo come CPU y si se cuelga una cámara no debe colgar la voz.
Lo que ve lo deja en dos ficheros del $XDG_RUNTIME_DIR (se borran al apagar):
  - delta-vision.json            el estado de ahora (lo leen Delta y el panel)
  - delta-vision-eventos.jsonl   lo que pasa (llega, se va, gesto, otra persona, bostezo…)

Las cámaras son FUENTES intercambiables (vision.json): la webcam del portátil hoy; mañana la del jardín o la del
comedero del gato. La GoPro Hero 3 entra por pasarela/gopro_puente.py (en la caja de la impresora). Todo lo que
OpenCV abre vale: /dev/videoN, rtsp://, http://…mjpeg, .m3u8. Una contraseña de RTSP no va en vision.json:
${VARIABLE} se toma del entorno (.env). «recorte» [x0,y0,x1,y1] amplía una zona solo para detectar la cara.

Privacidad: todo en local (MediaPipe en CPU), NINGÚN fotograma se guarda ni sale de aquí. Si existe
$XDG_RUNTIME_DIR/delta-vision-pausa (modo privacidad) la cámara se suelta y se apaga su luz.

Uso:  .venv/bin/python vision.py                   vigilar (todas las fuentes activas)
      .venv/bin/python vision.py --evaluar 60      informe de cuánto sirve cada cámara (para decidir si vale)
"""
import argparse
import json
import math
import os
import re
import threading
import time
from collections import deque
from pathlib import Path

os.environ.setdefault("GLOG_minloglevel", "2")  # MediaPipe llena el log de avisos internos que no dicen nada
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

AQUI = Path(__file__).parent
CONFIG = AQUI / "vision.json"
MODELOS = AQUI / "modelos" / "vision"
RUN = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
ESTADO = RUN / "delta-vision.json"
EVENTOS = RUN / "delta-vision-eventos.jsonl"
PAUSA = RUN / "delta-vision-pausa"

DEFECTO = {"fps": 5, "ancho": 640, "rotar": "auto", "analisis": ["presencia", "gestos", "postura"],
           "llega_s": 2.0, "se_va_s": 120.0, "gesto_s": 0.8, "gesto_pausa_s": 3.0, "postura_cada_s": 1.0,
           "activa": True, "recorte": None}


# ---------- configuración ----------
def _expandir(v):
    return re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), ""), v) if isinstance(v, str) else v


def cargar_config(ruta=CONFIG):
    """Lista de fuentes con los valores por defecto rellenos. Sin vision.json: la webcam del portátil."""
    try:
        fuentes = json.loads(Path(ruta).read_text())["fuentes"]
    except FileNotFoundError:
        fuentes = [{"nombre": "portatil", "url": "/dev/video0"}]
    return [{**DEFECTO, **{k: _expandir(v) for k, v in f.items()}} for f in fuentes]


# ---------- geometría ----------
def angulos(matriz):
    """Matriz de transformación facial 4×4 de MediaPipe → (giro, cabeceo) en grados.
    giro (yaw) > 0: mira a su izquierda; cabeceo (pitch) > 0: mira hacia arriba. 0, 0 = de frente a la cámara."""
    r = [fila[:3] for fila in matriz[:3]]
    giro = math.degrees(math.asin(max(-1.0, min(1.0, -r[2][0]))))
    cabeceo = math.degrees(math.atan2(r[2][1], r[2][2]))
    return giro, cabeceo


# ---------- lógica (sin cámara: se prueba en test_vision.py) ----------
class Presencia:
    """Con histéresis: llega si se le ve `llega_s` seguidos; se va si NO se le ve `se_va_s` seguidos.
    Mirar el móvil o un papel un minuto no es irse (por eso el margen largo para marcharse)."""

    def __init__(self, llega_s=2.0, se_va_s=120.0):
        self.llega_s, self.se_va_s = llega_s, se_va_s
        self.presente, self.desde = False, None
        self._visto = self._no_visto = None

    def ver(self, hay_cara, t):
        """Devuelve 'llega' / 'se_va' cuando cambia el estado, si no None."""
        if hay_cara:
            self._no_visto = None
            self._visto = t if self._visto is None else self._visto
            if not self.presente and t - self._visto >= self.llega_s:
                self.presente, self.desde = True, t
                return "llega"
        else:
            self._visto = None
            self._no_visto = t if self._no_visto is None else self._no_visto
            if self.presente and t - self._no_visto >= self.se_va_s:
                self.presente, self.desde = False, t
                return "se_va"
        return None


class Gestos:
    """Un gesto cuenta si se mantiene `sostener_s` (los de un frame suelto son ruido) y luego descansa `pausa_s`."""

    def __init__(self, sostener_s=0.8, pausa_s=3.0, umbral=0.6):
        self.sostener_s, self.pausa_s, self.umbral = sostener_s, pausa_s, umbral
        self._cual = self._desde = None
        self._ultimo = -1e9

    def ver(self, gesto, score, t):
        if not gesto or gesto == "None" or score < self.umbral:
            self._cual = None
            return None
        if gesto != self._cual:
            self._cual, self._desde = gesto, t
            return None
        if t - self._desde >= self.sostener_s and t - self._ultimo >= self.pausa_s:
            self._ultimo = t
            self._desde = t + 1e9  # no repetir hasta soltarlo
            return gesto
        return None


class Fatiga:
    """Parpadeos por minuto y bostezos (boca muy abierta más de 1.5 s), a partir de los blendshapes de la cara."""

    def __init__(self):
        self.parpadeos = deque()
        self._cerrado = False
        self._boca = None

    def ver(self, parpadeo, boca, t):
        ev = None
        if parpadeo > 0.5 and not self._cerrado:
            self.parpadeos.append(t)
        self._cerrado = parpadeo > 0.5
        while self.parpadeos and t - self.parpadeos[0] > 60:
            self.parpadeos.popleft()
        if boca > 0.6:
            self._boca = t if self._boca is None else self._boca
            if t - self._boca >= 1.5:
                ev, self._boca = "bostezo", t + 1e9
        else:
            self._boca = None
        return ev

    def por_minuto(self):
        return len(self.parpadeos)


def nitidez(gris):
    import cv2
    return float(cv2.Laplacian(gris, cv2.CV_64F).var())


# ---------- cámara ----------
class Fuente:
    """Lee en un hilo y se queda solo con el último fotograma (si el análisis va lento no se acumula retraso).
    Si la cámara se cae, reintenta sola."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.frame, self.t, self.leidos = None, 0.0, 0
        self._cap, self._fin = None, threading.Event()
        self._hilo = threading.Thread(target=self._leer, daemon=True)

    def _abrir(self):
        import cv2
        url = self.cfg["url"]
        cap = cv2.VideoCapture(int(url[10:]) if url.startswith("/dev/video") else url,
                               cv2.CAP_V4L2 if url.startswith("/dev/video") else cv2.CAP_ANY)
        if url.startswith("/dev/video"):  # MJPG: a 720p da 30 fps; en YUYV solo 10
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap if cap.isOpened() else None

    def _leer(self):
        while not self._fin.is_set():
            if PAUSA.exists():
                self._soltar()
                self.frame = None
                self._fin.wait(1)
                continue
            if self._cap is None:
                self._cap = self._abrir()
                if self._cap is None:
                    self._fin.wait(10)
                    continue
            ok, f = self._cap.read()
            if not ok:
                self._soltar()
                self._fin.wait(5)
                continue
            self.frame, self.t = f, time.monotonic()
            self.leidos += 1

    def _soltar(self):
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def empezar(self):
        self._hilo.start()
        return self

    def parar(self):
        self._fin.set()
        self._hilo.join(3)
        self._soltar()


# ---------- análisis ----------
ROTAR = {0: None, 90: "ROTATE_90_CLOCKWISE", 180: "ROTATE_180", 270: "ROTATE_90_COUNTERCLOCKWISE"}


def zona_cara(frame, recorte, ancho_dest=640):
    """(imagen, ancho en px del fotograma que abarca). Con recorte [x0, y0, x1, y1] (fracciones 0-1) se recorta y se
    amplía: el detector de caras no ve las pequeñas (la GoPro da 320×240 y la cara sale de ~35 px)."""
    import cv2
    h, w = frame.shape[:2]
    if not recorte:
        return frame, w
    x0, y0, x1, y1 = recorte
    zona = frame[int(h * y0):int(h * y1), int(w * x0):int(w * x1)]
    k = ancho_dest / zona.shape[1]
    return cv2.resize(zona, None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC), zona.shape[1]


class Analizador:
    def __init__(self, cfg):
        from mediapipe.tasks.python import BaseOptions, vision as v
        self.cfg, self.v = cfg, v
        modo = v.RunningMode.VIDEO
        quiere = set(cfg["analisis"])
        self.cara = v.FaceLandmarker.create_from_options(v.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(MODELOS / "face_landmarker.task")), running_mode=modo,
            num_faces=3, output_face_blendshapes=True, output_facial_transformation_matrixes=True))
        self.manos = v.GestureRecognizer.create_from_options(v.GestureRecognizerOptions(
            base_options=BaseOptions(model_asset_path=str(MODELOS / "gesture_recognizer.task")), running_mode=modo,
            num_hands=2)) if "gestos" in quiere else None
        self.cuerpo = v.PoseLandmarker.create_from_options(v.PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(MODELOS / "pose_landmarker_lite.task")), running_mode=modo)) \
            if "postura" in quiere else None
        self.rotar = None if cfg["rotar"] == "auto" else int(cfg["rotar"])
        self._prueba = {0: 0, 180: 0}  # rotar=auto: caras vistas con cada giro hasta decidir
        self._ms = self._n = self._ult_cuerpo = 0

    def _girar(self, f, grados):
        import cv2
        return f if not ROTAR[grados] else cv2.rotate(f, getattr(cv2, ROTAR[grados]))

    def analizar(self, frame):
        import cv2
        import mediapipe as mp
        h, w = frame.shape[:2]
        if w > self.cfg["ancho"]:
            frame = cv2.resize(frame, (self.cfg["ancho"], int(h * self.cfg["ancho"] / w)), interpolation=cv2.INTER_AREA)
        self._ms += max(1, int(1000 / self.cfg["fps"]))
        # la webcam de este portátil sale al revés: con rotar=auto se prueban las dos, fotograma sí, fotograma no
        self._n += 1
        g = (0, 180)[self._n % 2] if self.rotar is None else self.rotar
        frame = self._girar(frame, g)
        rgb = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        gris = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        r = {"rotar": g, "res": [frame.shape[1], frame.shape[0]], "brillo": float(gris.mean()), "nitidez": nitidez(gris)}
        zona, ancho_zona = zona_cara(frame, self.cfg["recorte"])
        c = self.cara.detect_for_video(rgb if zona is frame else mp.Image(
            image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(zona, cv2.COLOR_BGR2RGB)), self._ms)
        r["caras"] = len(c.face_landmarks)
        if self.rotar is None:
            self._prueba[g] += r["caras"] > 0
            if max(self._prueba.values()) >= 10 and min(self._prueba.values()) <= 3:  # decidido
                self.rotar = max(self._prueba, key=self._prueba.get)
                r["rotacion_decidida"] = self.rotar
        if c.face_landmarks:
            # la cara principal = la más grande (la más cerca)
            i = max(range(len(c.face_landmarks)),
                    key=lambda k: max(p.x for p in c.face_landmarks[k]) - min(p.x for p in c.face_landmarks[k]))
            lm = c.face_landmarks[i]
            r["ancho_cara"] = (max(p.x for p in lm) - min(p.x for p in lm)) * ancho_zona
            if c.facial_transformation_matrixes:
                r["giro"], r["cabeceo"] = angulos(c.facial_transformation_matrixes[i].tolist())
            if c.face_blendshapes:
                b = {x.category_name: x.score for x in c.face_blendshapes[i]}
                r["parpadeo"] = (b.get("eyeBlinkLeft", 0) + b.get("eyeBlinkRight", 0)) / 2
                r["boca"] = b.get("jawOpen", 0)
        if self.manos:
            g_ = self.manos.recognize_for_video(rgb, self._ms)
            if g_.gestures:
                mejor = max((x[0] for x in g_.gestures), key=lambda x: x.score)
                r["gesto"], r["gesto_score"] = mejor.category_name, mejor.score
            r["manos"] = len(g_.hand_landmarks)
        # En este i5: cara 16 ms, manos 22, cuerpo 21. La postura cambia despacio: una vez por segundo basta.
        if self.cuerpo and self._ms - self._ult_cuerpo >= 1000 * self.cfg["postura_cada_s"]:
            self._ult_cuerpo = self._ms
            p = self.cuerpo.detect_for_video(rgb, self._ms)
            r["cuerpo_mirado"] = True
            if p.pose_landmarks:
                lm = p.pose_landmarks[0]
                hi, hd, nariz = lm[11], lm[12], lm[0]
                r["hombros_visibles"] = min(hi.visibility, hd.visibility)
                if r["hombros_visibles"] > 0.5:
                    ancho = abs(hi.x - hd.x) or 1e-6
                    # cabeza caída: la nariz se acerca a la línea de los hombros (relativo al ancho de hombros)
                    r["cabeza_hombros"] = ((hi.y + hd.y) / 2 - nariz.y) / ancho
                    r["inclinacion"] = math.degrees(math.atan2(hd.y - hi.y, hd.x - hi.x))
        return r


# ---------- vigilar ----------
def _escribir(ruta, datos):
    tmp = ruta.with_suffix(".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False))
    tmp.replace(ruta)


def _evento(fuente, tipo, **datos):
    linea = {"t": time.time(), "h": time.strftime("%H:%M:%S"), "fuente": fuente, "evento": tipo, **datos}
    with EVENTOS.open("a") as f:
        f.write(json.dumps(linea, ensure_ascii=False) + "\n")
    print(f"👁️ {fuente}: {tipo} {datos or ''}")


MIRANDO = 25  # grados de giro/cabeceo dentro de los que cuenta como mirando la pantalla


def vigilar():
    fuentes = [f for f in cargar_config() if f["activa"]]
    trabajos = []
    for cfg in fuentes:
        trabajos.append({"cfg": cfg, "src": Fuente(cfg).empezar(), "an": Analizador(cfg),
                         "pres": Presencia(cfg["llega_s"], cfg["se_va_s"]), "gest": Gestos(cfg["gesto_s"], cfg["gesto_pausa_s"]),
                         "fat": Fatiga(), "visto": 0.0, "max_caras": 0})
    print(f"👁️ visión: {', '.join(f['nombre'] for f in fuentes)}")
    try:
        while True:
            estado = {"t": time.time(), "pausa": PAUSA.exists(), "fuentes": {}}
            for w in trabajos:
                src, cfg, n = w["src"], w["cfg"], w["cfg"]["nombre"]
                if src.frame is None or src.t <= w["visto"]:
                    estado["fuentes"][n] = {"ok": False, "pausa": estado["pausa"]}
                    continue
                w["visto"] = ahora = src.t
                r = w["an"].analizar(src.frame)
                if "rotacion_decidida" in r:
                    _evento(n, "rotacion", grados=r["rotacion_decidida"])
                # con rotar=auto, hasta decidir la mitad de los fotogramas van girados al revés: sin cara una sí y
                # otra no, y la presencia nunca llegaba a confirmarse. Se espera a que esté decidida.
                ev = w["pres"].ver(r["caras"] > 0, ahora) if w["an"].rotar is not None else None
                if ev:
                    _evento(n, ev)
                if r["caras"] >= 2 and w["max_caras"] < 2:
                    _evento(n, "otra_persona", caras=r["caras"])
                w["max_caras"] = r["caras"]
                gesto = w["gest"].ver(r.get("gesto"), r.get("gesto_score", 0), ahora)
                if gesto:
                    _evento(n, "gesto", gesto=gesto)
                if "parpadeo" in r and w["fat"].ver(r["parpadeo"], r["boca"], ahora):
                    _evento(n, "bostezo")
                mirando = r["caras"] > 0 and abs(r.get("giro", 99)) < MIRANDO and abs(r.get("cabeceo", 99)) < MIRANDO
                desde = w["pres"].desde  # reloj monótono → hora de pared
                estado["fuentes"][n] = {"ok": True, "presente": w["pres"].presente, "mirando": mirando,
                                        "presente_desde": time.strftime("%H:%M", time.localtime(time.time() - (time.monotonic() - desde)))
                                        if w["pres"].presente and desde else None,
                                        "parpadeos_min": w["fat"].por_minuto(),
                                        **{k: (round(v, 2) if isinstance(v, float) else v) for k, v in r.items()}}
            _escribir(ESTADO, estado)
            time.sleep(1 / max(f["fps"] for f in fuentes))
    except KeyboardInterrupt:
        pass
    finally:
        for w in trabajos:
            w["src"].parar()


# ---------- evaluar: ¿sirve esta cámara? ----------
def evaluar(segundos):
    """Para decidir con datos si una cámara vale (la del portátil quizá no). Pide al usuario que se mueva:
    sentado mirando, girar la cabeza, levantar la mano, irse un momento."""
    for cfg in [f for f in cargar_config() if f["activa"]]:
        src, an = Fuente(cfg).empezar(), Analizador(cfg)
        print(f"\n👁️ Evaluando «{cfg['nombre']}» ({cfg['url']}) {segundos} s… siéntese, mire, gire la cabeza, levante la mano.")
        filas, t0, visto = [], time.monotonic(), 0.0
        while time.monotonic() - t0 < segundos:
            if src.frame is not None and src.t > visto:
                visto = src.t
                filas.append(an.analizar(src.frame))
            time.sleep(1 / cfg["fps"])
        dur, leidos = time.monotonic() - t0, src.leidos
        src.parar()
        if not filas:
            print("   ❌ No llega imagen (¿otra app usa la cámara?, ¿URL mal?).")
            continue
        media = lambda k: sum(f[k] for f in filas if k in f) / max(1, sum(k in f for f in filas))
        con_cara = [f for f in filas if f["caras"]]
        gestos = sorted({f["gesto"] for f in filas if f.get("gesto") not in (None, "None")})
        print(f"   cámara: {leidos / dur:.0f} fps leídos · analizados {len(filas) / dur:.1f}/s · "
              f"rotación {an.rotar if an.rotar is not None else 'sin decidir'}° · {filas[-1]['res'][0]}×{filas[-1]['res'][1]}")
        print(f"   imagen: brillo {media('brillo'):.0f}/255 · nitidez {media('nitidez'):.0f} "
              f"({'buena' if media('nitidez') > 100 else 'floja' if media('nitidez') > 30 else 'borrosa'})")
        print(f"   cara: en el {100 * len(con_cara) / len(filas):.0f} % de los fotogramas"
              + (f" · ancho {media('ancho_cara'):.0f} px · giro {min(f['giro'] for f in con_cara if 'giro' in f):.0f}…"
                 f"{max(f['giro'] for f in con_cara if 'giro' in f):.0f}°" if con_cara and any('giro' in f for f in con_cara) else ""))
        print(f"   manos: en el {100 * sum(f.get('manos', 0) > 0 for f in filas) / len(filas):.0f} % · gestos vistos: {', '.join(gestos) or 'ninguno'}")
        cuerpo = [f for f in filas if f.get("cuerpo_mirado")] or [{}]
        print(f"   hombros visibles: {100 * sum(f.get('hombros_visibles', 0) > 0.5 for f in cuerpo) / len(cuerpo):.0f} % "
              "(sin hombros no hay postura)")


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("--evaluar", type=float, metavar="S", help="evalúa cada cámara durante S segundos y sale")
    x = a.parse_args()
    evaluar(x.evaluar) if x.evaluar else vigilar()
