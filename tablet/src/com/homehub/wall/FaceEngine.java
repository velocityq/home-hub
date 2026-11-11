package com.homehub.wall;

import android.content.Context;
import android.content.pm.PackageManager;
import android.graphics.ImageFormat;
import android.graphics.SurfaceTexture;
import android.hardware.Camera;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.Process;
import android.os.SystemClock;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/**
 * Face ID for the wall, all on the tablet.
 *
 * The camera is open only while the wall app is on screen AND someone has set up their face (or is
 * setting it up right now). It takes one look a second when nobody is there, three a second while a
 * face is being worked out, and one every three seconds in a dark room. Each look is one frame in a
 * single reused buffer: the camera fills it, the face code reads it, and the next frame overwrites
 * it. No frame is written to storage or sent anywhere. The only thing that leaves this class is a
 * name (or nobody), handed to the page, which tells the hub.
 *
 * Everything runs on one low priority background thread; the models use one CPU core.
 */
final class FaceEngine implements Camera.PreviewCallback {
    interface Listener { void onFaceEvent(JSONObject e); }

    static final String TAG = MainActivity.TAG;
    static final int NEED = 8;                     // looks taken when someone sets up their face
    static final long ENROL_MS = 20000;            // how long set up keeps trying
    static final long GONE_MS = 15000;             // nobody seen this long: back to "nobody"
    static final int DARK = 18;                    // mean brightness below this is a dark room
    static final String NO_CAMERA = "The tablet's camera has stopped answering. It comes back when the tablet restarts.";

    final Context ctx;
    final FaceStore store;
    final Listener out;
    final HandlerThread thread;
    final Handler h;

    // camera (thread h only)
    Camera cam;
    SurfaceTexture tex;
    byte[] buf;
    FaceImage.Nv21 img;
    String camState = "off";                       // off | on | denied | error | none
    boolean wanted;                                // the wall app is on screen
    boolean forced;                                // adb test switch: camera on even with nobody set up
    boolean probed;

    // models (thread h only, loaded on first use)
    FaceModels.Detector det;
    FaceModels.Embedder emb;

    // who is here
    String who;
    String cand;
    int candCount;
    long lastFace, lastWho;
    final int[] rotHits = new int[4];
    int rotCycle;
    int guessRot;

    // set up
    String enrolName;
    long enrolUntil, enrolLast;
    int enrolSeen, enrolSmall;
    List<float[]> enrolLooks;

    // numbers for the log (one line a minute)
    long statFrom; int statLooks, statFaces, statEmb; long statDet, statEmbMs, statAll;

    FaceEngine(Context c, Listener l) {
        ctx = c.getApplicationContext();
        out = l;
        store = new FaceStore(ctx);
        thread = new HandlerThread("face", Process.THREAD_PRIORITY_BACKGROUND);
        thread.start();
        h = new Handler(thread.getLooper());
    }

    // ------------------------------------------------------------------ called from the screen thread
    void resume() { h.post(() -> { wanted = true; h.postDelayed(this::sync, 1500); }); }

    void pause() {
        h.post(() -> {
            wanted = false;
            if (enrolName != null) enrolDone(false, "Set up stopped because the screen went off. Try again.");
            sync();
            setWho(null);
        });
    }

    void enrol(String name) {
        h.post(() -> {
            if (!FaceStore.known(name)) return;
            if (enrolName != null) { emit(enrolEvent(enrolName, "busy", "Someone is setting up their face. Try again in a moment.")); return; }
            if (!permitted()) { camState = "denied"; emit(enrolEvent(name, "failed", "The camera is not allowed for this app.")); status(); return; }
            enrolName = name;
            enrolLooks = new ArrayList<>();
            enrolUntil = SystemClock.uptimeMillis() + ENROL_MS;
            enrolLast = 0; enrolSeen = 0; enrolSmall = 0;
            emit(enrolEvent(name, "looking", null));
            sync();
            if (cam == null && enrolName != null) enrolDone(false, "none".equals(camState) ? NO_CAMERA : "The camera did not open. Try again in a minute.");
        });
    }

    void cancelEnrol() { h.post(() -> { if (enrolName != null) enrolDone(false, null); }); }

    void forget(String name) {
        h.post(() -> {
            if (!FaceStore.known(name)) return;
            store.forget(name);
            Log.i(TAG, "face: forgot " + name);
            if (name.equals(who)) setWho(null);
            emit(event("forgot").put2("name", name));
            sync();
            status();
        });
    }

    void force(boolean on) { h.post(() -> { forced = on; Log.i(TAG, "face: test switch " + (on ? "on" : "off")); sync(); }); }

    JSONObject statusNow() {
        // read from any thread: a snapshot good enough for the page's first draw
        JSONObject o = event("status");
        try {
            o.put("camera", "off".equals(camState) && Camera.getNumberOfCameras() < 1 ? "none" : camState);
            o.put("enrolled", new JSONArray(store.enrolled()));
            o.put("who", who == null ? JSONObject.NULL : who);
            o.put("rotationKnown", store.rotation >= 0);
        } catch (Exception ignored) { }
        return o;
    }

    // ------------------------------------------------------------------ camera on and off
    boolean permitted() {
        return ctx.checkSelfPermission(android.Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED;
    }

    /** Opens or closes the camera to match: on screen, and someone set up (or setting up, or the test switch). */
    void sync() {
        boolean need = wanted && (enrolName != null || forced || !store.enrolled().isEmpty());
        if (need && cam == null) open();
        else if (!need && cam != null) close();
    }

    void open() {
        if (!permitted()) { camState = "denied"; status(); return; }
        if (Camera.getNumberOfCameras() < 1) { camState = "none"; status(); return; }
        try {
            if (det == null) {
                long t = SystemClock.uptimeMillis();
                det = new FaceModels.Detector(ctx);
                emb = new FaceModels.Embedder(ctx);
                Log.i(TAG, "face: models loaded in " + (SystemClock.uptimeMillis() - t) + " ms");
            }
            cam = Camera.open(0);
            // The tablet's camera service can die under us (its driver crashed on 11 Nov 2026): let go, say so.
            cam.setErrorCallback((err, c) -> h.post(() -> {
                Log.w(TAG, "face: the camera reported error " + err + "; camera off");
                close();
                camState = Camera.getNumberOfCameras() < 1 ? "none" : "error";
                status();
                if ("error".equals(camState)) h.postDelayed(this::sync, 30000);
            }));
            Camera.CameraInfo info = new Camera.CameraInfo();
            Camera.getCameraInfo(0, info);
            guessRot = info.orientation % 360;
            Camera.Parameters ps = cam.getParameters();
            Camera.Size best = null;
            for (Camera.Size s : ps.getSupportedPreviewSizes()) {
                // 640 x 480 or the nearest below it: enough for a face at arm's length, light to read
                if (s.width * s.height > 640 * 480) continue;
                if (best == null || s.width * s.height > best.width * best.height) best = s;
            }
            if (best == null) best = ps.getPreviewSize();
            int[] fps = null;
            for (int[] r : ps.getSupportedPreviewFpsRange())
                if (fps == null || r[1] < fps[1] || (r[1] == fps[1] && r[0] < fps[0])) fps = r;
            if (!probed) {
                probed = true;
                StringBuilder sb = new StringBuilder();
                for (Camera.Size s : ps.getSupportedPreviewSizes()) sb.append(s.width).append('x').append(s.height).append(' ');
                StringBuilder fb = new StringBuilder();
                for (int[] r : ps.getSupportedPreviewFpsRange()) fb.append(r[0]).append('-').append(r[1]).append(' ');
                Log.i(TAG, "face: camera facing=" + (info.facing == Camera.CameraInfo.CAMERA_FACING_FRONT ? "front" : "back")
                        + " orientation=" + info.orientation + " sizes=" + sb + "fps=" + fb
                        + "hwfaces=" + ps.getMaxNumDetectedFaces());
            }
            ps.setPreviewSize(best.width, best.height);
            ps.setPreviewFormat(ImageFormat.NV21);
            try {
                if (fps != null) ps.setPreviewFpsRange(fps[0], fps[1]);
                cam.setParameters(ps);
            } catch (RuntimeException e) {         // some drivers refuse the fps range: size only
                ps = cam.getParameters();
                ps.setPreviewSize(best.width, best.height);
                ps.setPreviewFormat(ImageFormat.NV21);
                cam.setParameters(ps);
            }
            Camera.Size sz = cam.getParameters().getPreviewSize();
            img = new FaceImage.Nv21(sz.width, sz.height);
            buf = new byte[sz.width * sz.height * 3 / 2];
            img.d = buf;
            tex = new SurfaceTexture(false);
            cam.setPreviewTexture(tex);
            cam.setPreviewCallbackWithBuffer(this);
            cam.startPreview();
            camState = "on";
            statFrom = SystemClock.uptimeMillis();
            Log.i(TAG, "face: camera on " + sz.width + "x" + sz.height + (fps != null ? " fps " + fps[0] / 1000 + "-" + fps[1] / 1000 : ""));
            h.postDelayed(feed, 800);              // let the exposure settle before the first look
            status();
        } catch (Exception e) {
            Log.w(TAG, "face: camera did not open: " + e);
            close();
            camState = Camera.getNumberOfCameras() < 1 ? "none" : "error";
            status();
            if ("error".equals(camState)) h.postDelayed(this::sync, 30000);      // try again later
        }
    }

    void close() {
        h.removeCallbacks(feed);
        if (cam != null) {
            try { cam.setPreviewCallbackWithBuffer(null); cam.stopPreview(); } catch (RuntimeException ignored) { }
            cam.release();
            cam = null;
            Log.i(TAG, "face: camera off");
        }
        if (tex != null) { tex.release(); tex = null; }
        if (buf != null) java.util.Arrays.fill(buf, (byte) 0);
        buf = null; img = null;
        if (!"denied".equals(camState) && !"none".equals(camState)) camState = "off";
        status();
    }

    /** Hands the camera its one buffer. Until then it has nowhere to put a frame, so it drops them. */
    final Runnable feed = () -> { if (cam != null && buf != null) cam.addCallbackBuffer(buf); };

    @Override
    public void onPreviewFrame(byte[] data, Camera c) {
        if (cam == null || data != buf) return;
        long t0 = SystemClock.uptimeMillis();
        long delay = 1000;
        try {
            delay = look(t0);
        } catch (Exception e) {
            Log.w(TAG, "face: look failed: " + e);
        }
        long dt = SystemClock.uptimeMillis() - t0;
        statAll += dt; statLooks++;
        // never let the face work take more than about a third of one core (a quarter of the tablet's 4)
        delay = Math.max(delay, dt * 2);
        if (t0 - statFrom >= 60000) {
            Log.i(TAG, "face: last " + (t0 - statFrom) / 1000 + " s: " + statLooks + " looks, " + statFaces + " with a face, "
                    + statEmb + " named; per look " + (statLooks > 0 ? statAll / statLooks : 0) + " ms (find "
                    + (statLooks > 0 ? statDet / statLooks : 0) + " ms, name " + (statEmb > 0 ? statEmbMs / statEmb : 0)
                    + " ms); who=" + who);
            statFrom = t0; statLooks = statFaces = statEmb = 0; statDet = statEmbMs = statAll = 0;
        }
        h.postDelayed(feed, Math.max(0, delay - dt));
    }

    // ------------------------------------------------------------------ one look
    /** Returns how long to wait before the next look. */
    long look(long now) {
        boolean dark = img.meanLuma() < DARK;
        if (who != null && now - lastWho > GONE_MS) setWho(null);
        if (enrolName != null && now > enrolUntil) {
            enrolDone(false, enrolSeen == 0 ? "I couldn't see a face. Stand about an arm's length from the screen, in good light."
                    : enrolSmall > enrolSeen / 2 ? "Come a little closer and look straight at the screen." : "That took too long. Try again, looking straight at the screen.");
        }
        if (dark) return enrolName != null ? 400 : 3000;

        FaceModels.Face f = find(now);
        if (f == null) {
            if (enrolName != null) return 250;
            return now - lastFace < 4000 ? 333 : 1000;
        }
        statFaces++;
        lastFace = now;

        float ed = f.eyeDist();
        float mu = (f.kp[0] + f.kp[2]) / 2, mv = (f.kp[1] + f.kp[3]) / 2;
        boolean frontal = Math.abs(f.kp[4] - mu) < 0.45f * ed;
        boolean inside = f.cx - f.bw / 2 > 0 && f.cy - f.bh / 2 > 0
                && f.cx + f.bw / 2 < img.uw(f.rot) && f.cy + f.bh / 2 < img.uh(f.rot);
        boolean upright = f.kp[7] > mv + 0.3f * ed;      // mouth below the eyes
        if (enrolName != null) enrolSeen++;
        if (!(upright && inside && frontal && ed >= (enrolName != null ? 26 : 20) && f.score >= 0.7f)) {
            if (enrolName != null) enrolSmall++;
            return enrolName != null ? 250 : 333;
        }

        long te = SystemClock.uptimeMillis();
        float[] e = emb.embed(img, f);
        statEmbMs += SystemClock.uptimeMillis() - te; statEmb++;

        if (enrolName != null) {
            if (now - enrolLast >= 250) {
                enrolLooks.add(e);
                enrolLast = now;
                emit(enrolEvent(enrolName, "progress", null));
                if (enrolLooks.size() >= NEED) enrolFinish();
            }
            return 250;
        }

        FaceStore.Match m = store.match(e);
        if (m.name != null) {
            if (m.name.equals(cand)) candCount++; else { cand = m.name; candCount = 1; }
            if (m.name.equals(who)) lastWho = now;
            else if (candCount >= 2) { lastWho = now; setWho(m.name); }
        } else {
            cand = null; candCount = 0;
        }
        if (Log.isLoggable(TAG, Log.DEBUG) || m.name == null || !m.name.equals(who))
            Log.i(TAG, "face: look best=" + m.best + " " + fmt(m.score) + " next " + fmt(m.next) + " eyes " + (int) ed + "px -> " + m.name);
        return who != null && who.equals(m.name) ? 2000 : 333;   // known: check again every 2 s
    }

    /** Finds a face. Until the camera's rotation is known, each look tries a different rotation (all four while setting up). */
    FaceModels.Face find(long now) {
        long t = SystemClock.uptimeMillis();
        FaceModels.Face f = null;
        if (store.rotation >= 0) {
            f = det.detect(img, store.rotation, 0.6f);
        } else {
            int[] order = {guessRot, (guessRot + 180) % 360, (guessRot + 90) % 360, (guessRot + 270) % 360};
            int tries = enrolName != null ? 4 : 1;
            for (int i = 0; i < tries; i++) {
                int r = order[(rotCycle++) % 4];
                FaceModels.Face g = det.detect(img, r, 0.75f);
                if (g != null && g.kp[7] > (g.kp[1] + g.kp[3]) / 2 + 0.3f * g.eyeDist() && (f == null || g.score > f.score)) f = g;
            }
            if (f != null && ++rotHits[f.rot / 90] >= 3) {
                store.setRotation(f.rot);
                Log.i(TAG, "face: the camera's rotation is " + f.rot + " degrees (saved)");
                status();
            }
        }
        statDet += SystemClock.uptimeMillis() - t;
        return f;
    }

    // ------------------------------------------------------------------ set up
    void enrolFinish() {
        String name = enrolName;
        List<float[]> looks = enrolLooks;
        // the looks must agree with each other (one person in view the whole time)
        float sum = 0; int n = 0; float lo = 1;
        for (int i = 0; i < looks.size(); i++)
            for (int j = i + 1; j < looks.size(); j++) { float s = FaceModels.dot(looks.get(i), looks.get(j)); sum += s; n++; lo = Math.min(lo, s); }
        float agree = n > 0 ? sum / n : 1;
        // and must not look like the other person already set up
        String other = null; float otherS = -1;
        for (String p : store.enrolled()) {
            if (p.equals(name)) continue;
            List<float[]> o = new ArrayList<>(store.people.get(p));
            float s = 0;
            for (float[] e : looks) { float b = -1; for (float[] t : o) b = Math.max(b, FaceModels.dot(e, t)); s += b; }
            s /= looks.size();
            if (s > otherS) { otherS = s; other = p; }
        }
        Log.i(TAG, "face: set up " + name + ": looks agree " + fmt(agree) + " (lowest " + fmt(lo) + ")"
                + (other != null ? ", closeness to " + other + " " + fmt(otherS) : ""));
        if (agree < 0.45f) { enrolDone(false, "The looks didn't match each other. Try again with only you in front of the screen."); return; }
        if (other != null && otherS >= 0.6f) { enrolDone(false, "This face is very close to " + other + "'s. If that is you, tap Forget my face in " + other + "'s view first."); return; }
        store.put(name, looks);
        if (store.rotation < 0) {               // set up was the first real face: keep the rotation it was found at
            int r = 0, best = -1;
            for (int i = 0; i < 4; i++) if (rotHits[i] > best) { best = rotHits[i]; r = i * 90; }
            store.setRotation(r);
        }
        enrolDone(true, null);
        lastWho = SystemClock.uptimeMillis();
        setWho(name);
    }

    void enrolDone(boolean ok, String msg) {
        String name = enrolName;
        enrolName = null;
        enrolLooks = null;
        emit(enrolEvent(name, ok ? "done" : (msg == null ? "cancelled" : "failed"), msg));
        sync();
        status();
    }

    JSONObject enrolEvent(String name, String state, String msg) {
        JSONObject o = event("enrol");
        try {
            o.put("name", name);
            o.put("state", state);
            o.put("got", enrolLooks == null ? (state.equals("done") ? NEED : 0) : enrolLooks.size());
            o.put("need", NEED);
            if (msg != null) o.put("msg", msg);
        } catch (Exception ignored) { }
        return o;
    }

    // ------------------------------------------------------------------ events
    void setWho(String name) {
        if (name == null ? who == null : name.equals(who)) return;
        who = name;
        cand = null; candCount = 0;
        Log.i(TAG, "face: who is here: " + (name == null ? "nobody" : name));
        emit(event("who").put2("who", name == null ? JSONObject.NULL : name).put2("how", "face"));
    }

    void status() { emit(statusNow()); }

    void emit(JSONObject e) { out.onFaceEvent(e); }

    static Ev event(String type) { Ev o = new Ev(); o.put2("type", type); return o; }

    /** A JSONObject with a put that does not throw, for one line events. */
    static final class Ev extends JSONObject {
        Ev put2(String k, Object v) { try { put(k, v); } catch (Exception ignored) { } return this; }
    }

    static String fmt(float f) { return String.format(java.util.Locale.ROOT, "%.2f", f); }
}
