package es.delta.micmando;

import android.content.Context;
import android.media.AudioDeviceInfo;
import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioRecord;
import android.os.SystemClock;
import android.util.Log;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.function.Consumer;

/**
 * Graba `seg` segundos de la fuente `src` a 16 kHz mono y guarda cada pulsación del botón en files/tomaN.wav.
 * Sin el botón pulsado no existe ninguna entrada de audio: por eso la lectura es no bloqueante, y un hueco de
 * más de PAUSA_MS sin audio separa una toma de la siguiente. Nivel y entradas van a logcat (etiqueta DeltaMic).
 */
final class Grabadora {
    static final String T = "DeltaMic";
    static final int RATE = 16000;
    static final int PAUSA_MS = 1000;
    static final int VACIADO_MS = 200;  // al arrancar el sistema entrega audio viejo de la grabación anterior
    static final int TOMA_MIN = RATE / 5 * 2;  // < 0,2 s: restos del búfer, no una pulsación

    static void grabar(Context ctx, int seg, int src, Consumer<String> pantalla) {
        AudioManager am = (AudioManager) ctx.getSystemService(Context.AUDIO_SERVICE);
        File dir = ctx.getExternalFilesDir(null);
        File[] viejos = dir.listFiles();
        if (viejos != null) for (File f : viejos) if (f.getName().endsWith(".wav")) f.delete();

        int min = AudioRecord.getMinBufferSize(RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
        AudioRecord ar;
        try {
            ar = new AudioRecord(src, RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, Math.max(min, RATE));
        } catch (Exception e) {
            Log.e(T, "AudioRecord falla: " + e);
            pantalla.accept("Error: " + e.getMessage());
            return;
        }
        if (ar.getState() != AudioRecord.STATE_INITIALIZED) {
            Log.e(T, "AudioRecord sin inicializar (¿falta el permiso RECORD_AUDIO?)");
            pantalla.accept("Sin permiso de micrófono");
            return;
        }
        List<ByteArrayOutputStream> tomas = new ArrayList<>();
        ByteArrayOutputStream actual = null;
        byte[] buf = new byte[RATE / 4 * 2];  // 250 ms
        int vaciasMs = 0;
        ar.startRecording();
        Log.i(T, "inicio src=" + src + " estado=" + ar.getRecordingState() + " min=" + min + " entradas: " + listar(am));
        long t0 = SystemClock.elapsedRealtime(), fin = t0 + seg * 1000L;
        while (SystemClock.elapsedRealtime() < fin) {
            int n = ar.read(buf, 0, buf.length, AudioRecord.READ_NON_BLOCKING);
            if (n < 0) {
                Log.w(T, "read=" + n);
                SystemClock.sleep(50);
                continue;
            }
            if (n == 0) {
                vaciasMs += 50;
                if (vaciasMs >= PAUSA_MS) actual = null;
                if (vaciasMs % 5000 == 0) Log.i(T, "sin audio desde hace " + vaciasMs + " ms; entradas: " + listar(am));
                SystemClock.sleep(50);
                continue;
            }
            vaciasMs = 0;
            if (SystemClock.elapsedRealtime() - t0 < VACIADO_MS) {  // restos de la grabación anterior
                Log.i(T, "descarto " + n + " bytes viejos del búfer");
                continue;
            }
            if (actual == null) {
                actual = new ByteArrayOutputStream();
                tomas.add(actual);
                Log.i(T, "toma " + tomas.size() + " empieza");
            }
            actual.write(buf, 0, n);
            long suma = 0;
            int pico = 0;
            for (int i = 0; i + 1 < n; i += 2) {
                short s = (short) ((buf[i] & 0xff) | (buf[i + 1] << 8));
                suma += (long) s * s;
                pico = Math.max(pico, Math.abs(s));
            }
            int rms = (int) Math.sqrt(suma / (n / 2.0));
            AudioDeviceInfo ruta = ar.getRoutedDevice();
            Log.i(T, "toma=" + tomas.size() + " t=" + (SystemClock.elapsedRealtime() - t0) + " rms=" + rms + " pico=" + pico
                    + " ruta=" + (ruta == null ? "-" : describir(ruta)));
            pantalla.accept("Mantén pulsado el botón del micro y habla\n\n"
                    + ((fin - SystemClock.elapsedRealtime()) / 1000 + 1) + " s\n"
                    + new String(new char[Math.min(30, rms / 100)]).replace('\0', '|'));
        }
        ar.stop();
        ar.release();
        int guardadas = 0;
        for (ByteArrayOutputStream toma : tomas) {
            if (toma.size() < TOMA_MIN) {
                Log.i(T, "descarto un trozo de " + toma.size() + " bytes");
                continue;
            }
            File f = new File(dir, "toma" + (++guardadas) + ".wav");
            try {
                escribirWav(f, toma.toByteArray());
                Log.i(T, "guardada " + f.getName() + ": " + toma.size() + " bytes");
            } catch (IOException e) {
                Log.e(T, "no pude guardar " + f + ": " + e);
            }
        }
        Log.i(T, "fin: " + guardadas + " tomas en " + dir);
        pantalla.accept("Hecho: " + guardadas + " tomas");
    }

    static String listar(AudioManager am) {
        StringBuilder sb = new StringBuilder();
        for (AudioDeviceInfo d : am.getDevices(AudioManager.GET_DEVICES_INPUTS)) sb.append(describir(d)).append(' ');
        return sb.length() == 0 ? "(ninguna)" : sb.toString();
    }

    static String describir(AudioDeviceInfo d) {
        return d.getId() + ":" + d.getType() + ":" + d.getProductName() + ":" + d.getAddress();
    }

    static void escribirWav(File f, byte[] pcm) throws IOException {
        try (FileOutputStream o = new FileOutputStream(f)) {
            o.write(new byte[]{'R', 'I', 'F', 'F'});
            le32(o, 36 + pcm.length);
            o.write(new byte[]{'W', 'A', 'V', 'E', 'f', 'm', 't', ' '});
            le32(o, 16);
            le16(o, 1);          // PCM
            le16(o, 1);          // mono
            le32(o, RATE);
            le32(o, RATE * 2);   // bytes/s
            le16(o, 2);          // bloque
            le16(o, 16);         // bits
            o.write(new byte[]{'d', 'a', 't', 'a'});
            le32(o, pcm.length);
            o.write(pcm);
        }
    }

    static void le16(FileOutputStream o, int v) throws IOException {
        o.write(v & 0xff);
        o.write((v >> 8) & 0xff);
    }

    static void le32(FileOutputStream o, int v) throws IOException {
        le16(o, v & 0xffff);
        le16(o, (v >> 16) & 0xffff);
    }
}
