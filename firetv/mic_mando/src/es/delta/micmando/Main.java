package es.delta.micmando;

import android.app.Activity;
import android.media.MediaRecorder;
import android.os.Bundle;
import android.view.Gravity;
import android.widget.TextView;

/** Versión con pantalla: graba con la app a la vista (la del primer experimento). */
public class Main extends Activity {
    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        TextView tv = new TextView(this);
        tv.setTextSize(36);
        tv.setGravity(Gravity.CENTER);
        tv.setTextColor(0xffffffff);
        setContentView(tv);
        int seg = getIntent().getIntExtra("seg", 12);
        int src = getIntent().getIntExtra("src", MediaRecorder.AudioSource.VOICE_RECOGNITION);
        new Thread(() -> Grabadora.grabar(this, seg, src, s -> runOnUiThread(() -> tv.setText(s)))).start();
    }
}
