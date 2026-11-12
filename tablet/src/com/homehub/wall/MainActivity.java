package com.homehub.wall;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.media.MediaRecorder;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.Base64;
import android.util.Log;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;

/**
 * Shows the home hub's wall screen (served by the hub on the iMac) full screen.
 *
 * Why an app and not a browser: a web page opened by network address may not use the microphone,
 * so this app records the voice itself (only while the mic button is held) and hands the
 * recording to the page, which sends it to the hub like any other recording.
 *
 * It is not the home app. The AirTouch app and its aircon service keep running; the page has a
 * button that opens the AirTouch app in one tap.
 */
public class MainActivity extends Activity {
    static final String TAG = "HomeHubWall";
    static final String AIRTOUCH = "au.com.polyaire.airtouch5.console";
    /** The hub address when none was set over adb: assets/hub_url.txt, written by build.sh from
     *  ~/.home-hub/tablet-hub-url (never in git). Empty: the app shows how to set it. */
    String defaultHub() {
        try (java.io.InputStream in = getAssets().open("hub_url.txt")) {
            byte[] b = new byte[200];
            int n = in.read(b);
            String u = n > 0 ? new String(b, 0, n, java.nio.charset.StandardCharsets.UTF_8).trim() : "";
            return u.matches(LAN_URL) ? u : "";
        } catch (IOException e) {
            return "";
        }
    }
    static final int MIC_REQUEST = 7;

    WebView web;
    SharedPreferences prefs;
    final Handler ui = new Handler(Looper.getMainLooper());
    final Object recLock = new Object();
    MediaRecorder rec;
    File recFile;
    boolean offline;
    volatile boolean setupShowing;
    final Runnable retry = this::load;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        prefs = getSharedPreferences("hub", MODE_PRIVATE);
        // Face ID: only a name (or nobody) and set up progress reach the page. See FaceEngine.
        face = new FaceEngine(this, e -> sendToPage("window.__hubFace && window.__hubFace(" + e.toString() + ")"));
        readIntent(getIntent());

        web = new WebView(this);
        web.setBackgroundColor(0xFF0B0B0F);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        s.setSupportZoom(false);
        web.addJavascriptInterface(new Bridge(this), "HubAndroid");
        web.setWebViewClient(new HubClient(this));
        setContentView(web);
        immersive();
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, MIC_REQUEST);
        }
        load();
    }

    /** First set-up only: `am start ... --es key <wall key> [--es hub http://...:8790/]`. */
    void readIntent(Intent i) {
        if (i == null || i.getExtras() == null) return;
        SharedPreferences.Editor e = prefs.edit();
        String key = i.getStringExtra("key");
        boolean newKey = key != null && key.matches("[A-Za-z0-9_\\-]{16,128}");
        if (newKey) e.putString("key", key);
        String hub = i.getStringExtra("hub");
        // Only a hub on the home network, on plain http with a port: never a page on the internet.
        if (hub != null && hub.matches(LAN_URL) && !hub.equals(hubUrl())) {
            e.putString("hub", hub);
            // Any app on the tablet can send this intent. A new hub address without its own key forgets
            // the old key, so the wall key is never handed to a computer it was not made for.
            if (!newKey) e.remove("key");
        }
        e.apply();
        // adb test switches for Face ID: "facecam" on|off keeps the camera on with nobody set up (until the
        // app restarts); "facetest" runs the face code on public test pictures from a home network folder.
        String fc = i.getStringExtra("facecam");
        if (fc != null) face.force("on".equals(fc));
        String ft = i.getStringExtra("facetest");
        if (ft != null && ft.matches(LAN_URL)) FaceSelfTest.run(face, ft);
    }

    static final String LAN_URL = "http://(192\\.168|10|172\\.(1[6-9]|2[0-9]|3[01]))(\\.[0-9]{1,3}){2,3}:[0-9]{2,5}/";
    static final int CAM_REQUEST = 8;
    FaceEngine face;
    String enrolAfterAsk;

    @Override
    public void onRequestPermissionsResult(int code, String[] perms, int[] res) {
        if (code == CAM_REQUEST) {
            boolean ok = res.length > 0 && res[0] == PackageManager.PERMISSION_GRANTED;
            if (ok && enrolAfterAsk != null) face.enrol(enrolAfterAsk);
            else if (!ok && enrolAfterAsk != null) face.emit(face.enrolEvent(enrolAfterAsk, "failed", "The camera was not allowed, so Face ID can't be set up."));
            enrolAfterAsk = null;
        }
    }

    String hubUrl() {
        return prefs.getString("hub", defaultHub());
    }

    void load() {
        offline = false;
        String key = prefs.getString("key", null);
        if (hubUrl().isEmpty()) {
            showSetup();
            return;
        }
        setupShowing = false;
        // The page keeps the key in its own storage and clears it from the address straight away.
        // "?v=" makes every load a real page load (a change after "#" alone would not reload it).
        web.loadUrl(hubUrl() + "?v=" + System.currentTimeMillis() + (key != null ? "#key=" + key : ""));
    }

    /** The first run screen (assets/setup.html): the hub address and a pairing code, typed on the tablet. */
    void showSetup() {
        ui.removeCallbacks(retry);
        offline = false;
        String html;
        try (java.io.InputStream in = getAssets().open("setup.html")) {
            html = new String(readAll(in), java.nio.charset.StandardCharsets.UTF_8);
        } catch (IOException e) {
            html = "<html><body style='background:#0b0b0f;color:#fff;font-family:sans-serif;padding:48px'>"
                + "<h1>Set the hub address</h1></body></html>";
        }
        setupShowing = true;
        web.loadDataWithBaseURL(null, html, "text/html", "utf-8", null);
    }

    static byte[] readAll(java.io.InputStream in) throws IOException {
        java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int n;
        while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
        return out.toByteArray();
    }

    static String result(boolean ok, String error) {
        try {
            org.json.JSONObject o = new org.json.JSONObject().put("ok", ok);
            if (error != null) o.put("error", error);
            return o.toString();
        } catch (org.json.JSONException e) {
            return "{\"ok\":false}";
        }
    }

    /** Runs on the bridge's own thread (never the UI thread). Home network addresses only. */
    String pairWith(String addr, String code) {
        String a = addr == null ? "" : addr.trim().replaceFirst("^https?://", "").replaceFirst("/+$", "");
        if (!a.contains(":")) a = a + ":8790";
        String hub = "http://" + a + "/";
        if (!hub.matches(LAN_URL)) return result(false, "Type the address the pair command showed, like 192.168.x.x");
        if (code == null || !code.matches("[0-9]{6}")) return result(false, "The code is 6 numbers.");
        java.net.HttpURLConnection c = null;
        try {
            c = (java.net.HttpURLConnection) new java.net.URL(hub + "api/pair").openConnection();
            c.setConnectTimeout(6000);
            c.setReadTimeout(12000);
            c.setRequestMethod("POST");
            c.setDoOutput(true);
            c.setRequestProperty("Content-Type", "application/json");
            byte[] body = new org.json.JSONObject().put("code", code).put("name", "wall-tablet").toString()
                .getBytes(java.nio.charset.StandardCharsets.UTF_8);
            c.getOutputStream().write(body);
            int status = c.getResponseCode();
            java.io.InputStream in = status < 400 ? c.getInputStream() : c.getErrorStream();
            org.json.JSONObject r = new org.json.JSONObject(in == null ? "{}" : new String(readAll(in), java.nio.charset.StandardCharsets.UTF_8));
            String key = r.optString("key", "");
            if (status == 200 && r.optBoolean("ok") && key.matches("[A-Za-z0-9_\\-]{16,128}")) {
                prefs.edit().putString("hub", hub).putString("key", key).apply();
                ui.postDelayed(this::load, 600);
                return result(true, null);
            }
            return result(false, r.optString("error", "The hub said no. Make a new code and try again."));
        } catch (java.net.SocketTimeoutException | java.net.ConnectException e) {
            return result(false, "No hub answered at " + a + ". Check the address and that the tablet is on the same Wi-Fi.");
        } catch (IOException | org.json.JSONException | RuntimeException e) {
            Log.w(TAG, "pair: " + e);
            return result(false, "That did not work. Check the address and try again.");
        } finally {
            if (c != null) c.disconnect();
        }
    }

    void showOffline() {
        if (offline) return;
        offline = true;
        String html = "<html><body style='margin:0;background:#0b0b0f;color:#fff;font-family:sans-serif;"
                + "display:flex;align-items:center;justify-content:center;height:100vh;flex-direction:column'>"
                + "<div style='font-size:30px;font-weight:600'>The home hub is not answering</div>"
                + "<div style='font-size:20px;opacity:.7;margin-top:12px'>Trying again every few seconds.</div>"
                + (getPackageManager().getLaunchIntentForPackage(AIRTOUCH) == null ? "<div style='height:20px'></div>"
                : "<button onclick='HubAndroid.openAirTouch()' style='margin-top:36px;font-size:20px;padding:16px 28px;"
                + "border-radius:28px;border:0;background:#3aa0ff;color:#fff'>Open the AirTouch app</button>")
                + "<button onclick='HubAndroid.changeHub()' style='margin-top:16px;font-size:18px;padding:14px 26px;"
                + "border-radius:28px;border:1px solid rgba(255,255,255,.3);background:none;color:#fff'>Connect to a different hub</button>"
                + "</body></html>";
        web.loadDataWithBaseURL(null, html, "text/html", "utf-8", null);
        ui.postDelayed(retry, 5000);
    }

    void immersive() {
        WindowInsetsController c = getWindow().getInsetsController();
        if (c != null) {
            c.hide(WindowInsets.Type.statusBars() | WindowInsets.Type.navigationBars());
            c.setSystemBarsBehavior(WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
        }
    }

    @Override
    protected void onNewIntent(Intent i) {
        super.onNewIntent(i);
        if (i != null && i.getExtras() != null) {
            readIntent(i);
            load();
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        immersive();
        web.onResume();
        face.resume();
    }

    @Override
    protected void onPause() {
        stopQuietly();               // the screen went off or another app came up: drop any recording
        face.pause();                // and the camera goes off
        web.onPause();
        super.onPause();
    }

    @Override
    public void onWindowFocusChanged(boolean focus) {
        super.onWindowFocusChanged(focus);
        if (focus) immersive();
    }

    @Override
    public void onBackPressed() {
        // Back closes an open card on the page; it never leaves the app.
        web.evaluateJavascript("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}))", null);
    }

    @Override
    protected void onDestroy() {
        stopQuietly();
        web.destroy();
        super.onDestroy();
    }

    void stopQuietly() {
        synchronized (recLock) {
            if (rec != null) {
                try { rec.stop(); } catch (RuntimeException ignored) { }
                rec.release();
                rec = null;
            }
            if (recFile != null) { recFile.delete(); recFile = null; }
        }
    }

    void sendToPage(String js) {
        ui.post(() -> web.evaluateJavascript(js, null));
    }

}
