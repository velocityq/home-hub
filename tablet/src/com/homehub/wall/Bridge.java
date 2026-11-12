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

/** What the page can call, as window.HubAndroid. */
class Bridge {
    final MainActivity a;

    Bridge(MainActivity a) { this.a = a; }

    @JavascriptInterface
    public String version() { return "1"; }

    /** First run only (the setup screen in assets/setup.html): pair with the hub at a home network
     *  address with the 6 digit code from `hubserver pair`, then keep the address and the new key.
     *  Refused on any other page, so the hub's own page can never change where the app points. */
    @JavascriptInterface
    public String pair(String addr, String code) {
        if (!a.setupShowing) return MainActivity.result(false, "Setup is not open.");
        return a.pairWith(addr, code);
    }

    /** The "not answering" page offers this: go back to the setup screen to type a new address. */
    @JavascriptInterface
    public void changeHub() {
        if (!a.offline) return;
        a.ui.post(a::showSetup);
    }

    @JavascriptInterface
    public String startRecording() {
        if (a.checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            a.ui.post(() -> a.requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, MainActivity.MIC_REQUEST));
            return "denied";
        }
        synchronized (a.recLock) {
            a.stopQuietly();
            try {
                a.recFile = new File(a.getCacheDir(), "talk.m4a");
                MediaRecorder r = new MediaRecorder();
                r.setAudioSource(MediaRecorder.AudioSource.VOICE_RECOGNITION);
                r.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4);
                r.setAudioEncoder(MediaRecorder.AudioEncoder.AAC);
                r.setAudioChannels(1);
                r.setAudioSamplingRate(16000);
                r.setAudioEncodingBitRate(48000);
                r.setMaxDuration(16000);
                r.setOutputFile(a.recFile.getAbsolutePath());
                r.prepare();
                r.start();
                a.rec = r;
                return "ok";
            } catch (IOException | RuntimeException e) {
                Log.w(MainActivity.TAG, "mic: " + e);
                a.stopQuietly();
                return "error";
            }
        }
    }

    @JavascriptInterface
    public void stopRecording() {
        new Thread(() -> {
            String b64 = "";
            synchronized (a.recLock) {
                if (a.rec != null) {
                    boolean good = true;
                    try { a.rec.stop(); } catch (RuntimeException e) { good = false; }   // too short: no sound
                    a.rec.release();
                    a.rec = null;
                    if (good && a.recFile != null && a.recFile.length() > 0 && a.recFile.length() < 2_000_000) {
                        try (FileInputStream in = new FileInputStream(a.recFile)) {
                            byte[] buf = new byte[(int) a.recFile.length()];
                            int n = 0;
                            while (n < buf.length) {
                                int got = in.read(buf, n, buf.length - n);
                                if (got < 0) break;
                                n += got;
                            }
                            b64 = Base64.encodeToString(buf, 0, n, Base64.NO_WRAP);
                        } catch (IOException e) {
                            Log.w(MainActivity.TAG, "read: " + e);
                        }
                    }
                }
                if (a.recFile != null) { a.recFile.delete(); a.recFile = null; }   // no recording is kept
            }
            a.sendToPage("window.__hubNativeAudio && window.__hubNativeAudio('" + b64 + "','audio/mp4')");
        }).start();
    }

    @JavascriptInterface
    public void cancelRecording() {
        new Thread(a::stopQuietly).start();
    }

    // ---------- Face ID (see FaceEngine). The page gets names and progress, never a picture. ----------
    @JavascriptInterface
    public String faceStatus() { return a.face.statusNow().toString(); }

    @JavascriptInterface
    public String faceEnrol(String name) {
        if (!FaceStore.known(name)) return "unknown";
        if (a.checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            a.ui.post(() -> {
                a.enrolAfterAsk = name;
                a.requestPermissions(new String[]{Manifest.permission.CAMERA}, MainActivity.CAM_REQUEST);
            });
            return "asking";
        }
        a.face.enrol(name);
        return "ok";
    }

    @JavascriptInterface
    public void faceCancel() { a.face.cancelEnrol(); }

    @JavascriptInterface
    public void faceForget(String name) { a.face.forget(name); }

    @JavascriptInterface
    public void openAirTouch() {
        a.ui.post(() -> {
            Intent i = a.getPackageManager().getLaunchIntentForPackage(MainActivity.AIRTOUCH);
            if (i == null) {
                a.web.evaluateJavascript("window.toast && toast('The AirTouch app was not found.')", null);
                return;
            }
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            a.startActivity(i);
        });
    }
}
