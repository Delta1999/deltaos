package es.delta.micmando;

import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import android.os.SystemClock;
import android.util.Log;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.nio.charset.StandardCharsets;

/**
 * El micro del mando como micro de Delta: con el botón pulsado manda el audio (16 kHz mono s16le, a pelo) por TCP
 * al portátil, que lo mete en Delta en lugar de su propio micro. La primera línea es la clave del panel.
 * Sin botón no hay audio y no se manda nada (el portátil rellena con silencio). Si el portátil no está, reintenta.
 */
final class Emisora {
    static final String T = "DeltaMic";
    static final int RATE = 16000;
    static final int VACIADO_MS = 200;  // al arrancar, el sistema entrega audio viejo de la grabación anterior
    static volatile boolean seguir;

    static void emitir(String host, int puerto, String clave) {
        int min = AudioRecord.getMinBufferSize(RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
        AudioRecord ar = new AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, RATE, AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT, Math.max(min, RATE));
        if (ar.getState() != AudioRecord.STATE_INITIALIZED) {
            Log.e(T, "AudioRecord sin inicializar (¿falta el permiso RECORD_AUDIO?)");
            return;
        }
        byte[] buf = new byte[RATE / 10 * 2];  // 100 ms
        Socket s = null;
        OutputStream out = null;
        ar.startRecording();
        long t0 = SystemClock.elapsedRealtime();
        Log.i(T, "emito a " + host + ":" + puerto);
        while (seguir) {
            if (s == null) {
                try {
                    s = new Socket();
                    s.connect(new InetSocketAddress(host, puerto), 3000);
                    s.setTcpNoDelay(true);
                    out = s.getOutputStream();
                    out.write((clave + "\n").getBytes(StandardCharsets.US_ASCII));
                    out.flush();
                    Log.i(T, "conectada al portátil");
                } catch (IOException e) {
                    cerrar(s);
                    s = null;
                    SystemClock.sleep(3000);
                    continue;
                }
            }
            int n = ar.read(buf, 0, buf.length, AudioRecord.READ_NON_BLOCKING);
            if (n <= 0) {
                SystemClock.sleep(20);
                continue;
            }
            if (SystemClock.elapsedRealtime() - t0 < VACIADO_MS) continue;
            try {
                out.write(buf, 0, n);
            } catch (IOException e) {
                Log.w(T, "el portátil cortó: " + e);
                cerrar(s);
                s = null;
            }
        }
        ar.stop();
        ar.release();
        cerrar(s);
        Log.i(T, "emisora parada");
    }

    static void cerrar(Socket s) {
        try { if (s != null) s.close(); } catch (IOException ignored) { }
    }
}
