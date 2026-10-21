package es.delta.micmando;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.media.MediaRecorder;
import android.os.IBinder;
import android.util.Log;

/**
 * Versión sin pantalla: la misma grabación como servicio en primer plano, para probar si Android 9 deja grabar
 * con otra app delante (a una app escondida el micro le da silencio). Arranque, solo desde ADB:
 *   am start-foreground-service -n es.delta.micmando/.Servicio --ei seg 180
 * o, para que el mando sea el micro de Delta (ver Emisora), hasta am stopservice:
 *   am start-foreground-service -n es.delta.micmando/.Servicio --es enviar IP:7877 --es clave CLAVE
 */
public class Servicio extends Service {
    static final String CANAL = "mic";
    static volatile boolean grabando = false;

    @Override
    public int onStartCommand(Intent i, int flags, int id) {
        NotificationManager nm = getSystemService(NotificationManager.class);
        nm.createNotificationChannel(new NotificationChannel(CANAL, "Micro del mando", NotificationManager.IMPORTANCE_LOW));
        startForeground(1, new Notification.Builder(this, CANAL)
                .setSmallIcon(android.R.drawable.ic_btn_speak_now)
                .setContentTitle("Delta escucha el mando")
                .build());
        String enviar = i == null ? null : i.getStringExtra("enviar");  // IP:puerto del portátil
        if (enviar != null) {
            if (!Emisora.seguir) {
                Emisora.seguir = true;
                String clave = i.getStringExtra("clave");
                int dp = enviar.lastIndexOf(':');
                new Thread(() -> Emisora.emitir(enviar.substring(0, dp), Integer.parseInt(enviar.substring(dp + 1)), clave)).start();
            }
            return START_NOT_STICKY;
        }
        if (grabando) {
            Log.w(Grabadora.T, "ya estaba grabando");
            return START_NOT_STICKY;
        }
        grabando = true;
        int seg = i == null ? 60 : i.getIntExtra("seg", 60);
        int src = i == null ? MediaRecorder.AudioSource.VOICE_RECOGNITION
                : i.getIntExtra("src", MediaRecorder.AudioSource.VOICE_RECOGNITION);
        new Thread(() -> {
            Grabadora.grabar(this, seg, src, s -> { });
            grabando = false;
            stopForeground(true);
            stopSelf();
        }).start();
        return START_NOT_STICKY;
    }

    @Override
    public void onDestroy() {
        Emisora.seguir = false;  // am stopservice
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent i) {
        return null;
    }
}
