package es.delta.micmando;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.util.Log;
import android.view.WindowManager;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import java.net.HttpURLConnection;
import java.net.URL;

/**
 * La interfaz de DeltaOS en la tele: el panel del portátil a pantalla completa, con la tele siempre despierta.
 * Si el portátil deja de contestar (apagado, suspendido, sin wifi) vuelve al inicio del Fire TV.
 * Solo la arranca ADB (permiso DUMP), que le pasa la URL con la clave:
 *   am start -n es.delta.micmando/.Tele --es url http://IP:7876/?t=CLAVE [--ei zoom 100]
 *   am start -n es.delta.micmando/.Tele --ez salir true
 */
public class Tele extends Activity {
    static final String T = "DeltaTele";
    static final int FALLOS_MAX = 3, CADA_MS = 10000;
    static final int ZOOM = 100;  // %; la tele (1920×1080, densidad 2) le daría al panel solo 960×540 de sitio
    WebView wv;
    volatile boolean viva = true;
    volatile String portatil;  // http://IP:7876 (el WebView solo se puede tocar desde el hilo de la pantalla)

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        wv = new WebView(this);
        wv.setBackgroundColor(Color.BLACK);
        wv.getSettings().setJavaScriptEnabled(true);
        wv.getSettings().setDomStorageEnabled(true);
        wv.getSettings().setMediaPlaybackRequiresUserGesture(false);  // la voz de Delta, más adelante
        wv.setWebViewClient(new Cliente(this));
        setContentView(wv);
        abrir(getIntent());
        new Thread(this::vigilar).start();
    }

    @Override
    protected void onNewIntent(Intent i) {
        super.onNewIntent(i);
        abrir(i);
    }

    void abrir(Intent i) {
        if (i.getBooleanExtra("salir", false)) {
            salir();
            return;
        }
        String url = i.getStringExtra("url");
        int zoom = i.getIntExtra("zoom", ZOOM);
        wv.setInitialScale(zoom);
        if (url == null) {
            if (portatil == null) finish();
            else if (i.hasExtra("zoom")) wv.reload();  // probar otro zoom sin volver a pasar la clave
            return;
        }
        Log.i(T, "abro " + Uri.parse(url).getHost() + " zoom=" + zoom);
        Uri p = Uri.parse(url);
        portatil = p.getScheme() + "://" + p.getAuthority();
        wv.loadUrl(url);
    }

    /** Cada 10 s pregunta al portátil; a los 3 fallos seguidos, fuera. */
    void vigilar() {
        int fallos = 0;
        while (viva) {
            try { Thread.sleep(CADA_MS); } catch (InterruptedException e) { return; }
            String u = portatil;
            if (u == null) continue;
            try {
                HttpURLConnection c = (HttpURLConnection) new URL(u + "/fonts/").openConnection();
                c.setConnectTimeout(4000);
                c.setReadTimeout(4000);
                c.getResponseCode();  // cualquier respuesta vale: el portátil está
                c.disconnect();
                fallos = 0;
            } catch (Exception e) {
                if (++fallos >= FALLOS_MAX) {
                    Log.w(T, "el portátil no contesta: " + e);
                    runOnUiThread(this::salir);
                    return;
                }
            }
        }
    }

    void salir() {
        viva = false;
        startActivity(new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        finish();
    }

    @Override
    protected void onDestroy() {
        viva = false;
        wv.destroy();
        super.onDestroy();
    }
}

/** Clase aparte, no anónima: el d8 de build-tools 34 se cae con la clase anónima que genera javac 25. */
class Cliente extends WebViewClient {
    final Tele t;

    Cliente(Tele t) { this.t = t; }

    @Override
    public void onReceivedError(WebView v, WebResourceRequest r, WebResourceError e) {
        if (r.isForMainFrame()) {
            Log.w(Tele.T, "no carga: " + e.getDescription());
            t.salir();
        }
    }
}
