package es.delta.micmando;

import android.app.Activity;
import android.media.AudioDeviceInfo;
import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import android.os.Bundle;
import android.os.SystemClock;
import android.util.Log;
import android.view.Gravity;
import android.widget.TextView;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;

/**
 * Experimento: graba `seg` segundos de la fuente `src` (por defecto VOICE_RECOGNITION) a 16 kHz mono,
 * y en cuanto aparece una entrada de audio con dirección Bluetooth (el mando) la fija como preferida.
 * Deja el audio en files/mando.wav y va escribiendo nivel y entradas en logcat (etiqueta DeltaMic).
 * Tiene que estar en primer plano: desde Android 9 las apps en segundo plano graban silencio.
 */
public class Main extends Activity {
    static final String T = "DeltaMic";
    static final int RATE = 16000;
    TextView tv;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        tv = new TextView(this);
        tv.setTextSize(36);
        tv.setGravity(Gravity.CENTER);
        tv.setTextColor(0xffffffff);
        setContentView(tv);
        final int seg = getIntent().getIntExtra("seg", 12);
        final int src = getIntent().getIntExtra("src", MediaRecorder.AudioSource.VOICE_RECOGNITION);
        new Thread(() -> grabar(seg, src)).start();
    }

    void pantalla(String s) {
        runOnUiThread(() -> tv.setText(s));
    }

    static String listar(AudioManager am) {
        StringBuilder sb = new StringBuilder();
        for (AudioDeviceInfo d : am.getDevices(AudioManager.GET_DEVICES_INPUTS)) sb.append(describir(d)).append(' ');
        return sb.length() == 0 ? "(ninguna)" : sb.toString();
    }

    static String describir(AudioDeviceInfo d) {
        return d.getId() + ":" + d.getType() + ":" + d.getProductName() + ":" + d.getAddress();
    }

    void grabar(int seg, int src) {
        AudioManager am = (AudioManager) getSystemService(AUDIO_SERVICE);
        int min = AudioRecord.getMinBufferSize(RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
        AudioRecord ar;
        try {
            ar = new AudioRecord(src, RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, Math.max(min, RATE));
        } catch (Exception e) {
            Log.e(T, "AudioRecord falla: " + e);
            pantalla("Error: " + e.getMessage());
            return;
        }
        if (ar.getState() != AudioRecord.STATE_INITIALIZED) {
            Log.e(T, "AudioRecord sin inicializar (¿falta el permiso RECORD_AUDIO?)");
            pantalla("Sin permiso de micrófono");
            return;
        }
        ByteArrayOutputStream pcm = new ByteArrayOutputStream();
        byte[] buf = new byte[RATE / 4 * 2];  // 250 ms
        String entradasAntes = null;  // null: la primera lista se escribe siempre, aunque venga vacía
        int vacias = 0;
        boolean fijado = false;
        ar.startRecording();
        Log.i(T, "inicio src=" + src + " estado=" + ar.getRecordingState() + " min=" + min);
        long t0 = SystemClock.elapsedRealtime(), fin = t0 + seg * 1000L;
        while (SystemClock.elapsedRealtime() < fin) {
            // No bloqueante: sin el botón pulsado no hay ninguna entrada de audio y read() se quedaría colgado
            int n = ar.read(buf, 0, buf.length, AudioRecord.READ_NON_BLOCKING);
            if (n < 0) {
                Log.w(T, "read=" + n);
                SystemClock.sleep(50);
                continue;
            }
            if (n == 0) {
                if (++vacias % 20 == 0) Log.i(T, "sin audio desde hace " + vacias * 50 + " ms; entradas: " + listar(am));
                SystemClock.sleep(50);
                continue;
            }
            vacias = 0;
            pcm.write(buf, 0, n);
            long suma = 0;
            int pico = 0;
            for (int i = 0; i + 1 < n; i += 2) {
                short s = (short) ((buf[i] & 0xff) | (buf[i + 1] << 8));
                suma += (long) s * s;
                pico = Math.max(pico, Math.abs(s));
            }
            int rms = (int) Math.sqrt(suma / (n / 2.0));

            StringBuilder sb = new StringBuilder();
            AudioDeviceInfo mando = null;
            for (AudioDeviceInfo d : am.getDevices(AudioManager.GET_DEVICES_INPUTS)) {
                sb.append(describir(d)).append(' ');
                if (d.getAddress() != null && d.getAddress().contains(":")) mando = d;
            }
            String entradas = sb.toString();
            if (!entradas.equals(entradasAntes)) {
                Log.i(T, "entradas: " + entradas);
                entradasAntes = entradas;
            }
            if (mando != null && !fijado) {
                fijado = ar.setPreferredDevice(mando);
                Log.i(T, "fijo el mando " + describir(mando) + " -> " + fijado);
            }
            AudioDeviceInfo ruta = ar.getRoutedDevice();
            long t = SystemClock.elapsedRealtime() - t0;
            Log.i(T, "t=" + t + " rms=" + rms + " pico=" + pico + " ruta=" + (ruta == null ? "-" : describir(ruta)));
            int barras = Math.min(30, rms / 100);
            pantalla("Mantén pulsado el botón del micro y habla\n\n"
                    + ((fin - SystemClock.elapsedRealtime()) / 1000 + 1) + " s\n"
                    + new String(new char[barras]).replace('\0', '|')
                    + "\n\nruta: " + (ruta == null ? "-" : ruta.getProductName() + " " + ruta.getAddress()));
        }
        ar.stop();
        ar.release();
        File f = new File(getExternalFilesDir(null), "mando.wav");
        try {
            escribirWav(f, pcm.toByteArray());
            Log.i(T, "fin: " + f.getAbsolutePath() + " " + pcm.size() + " bytes");
            pantalla("Hecho");
        } catch (IOException e) {
            Log.e(T, "no pude guardar el wav: " + e);
            pantalla("Error al guardar");
        }
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
