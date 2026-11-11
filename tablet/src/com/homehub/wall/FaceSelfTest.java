package com.homehub.wall;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.os.SystemClock;
import android.util.Log;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * A test of the face code with public test pictures, run only from adb:
 *   am start -n com.homehub.wall/.MainActivity --es facetest http://<imac>:<port>/
 * The folder there has list.txt ("label file" per line). Pictures are read into memory, never saved.
 * The first two labels with 4 or more pictures play the two people who set up their face (first 3
 * pictures each); every other picture is a stranger. Results go to the log as "facetest:" lines,
 * followed by every file in the app's own storage (to show no picture was written).
 */
final class FaceSelfTest {
    static void run(FaceEngine eng, String base) {
        eng.h.post(() -> {
            try { go(eng, base); } catch (Exception e) { Log.w(FaceEngine.TAG, "facetest: failed: " + e); }
            listFiles(eng.ctx.getDataDir(), "");
        });
    }

    static byte[] get(String u) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(u).openConnection();
        c.setConnectTimeout(5000); c.setReadTimeout(10000);
        try (InputStream in = c.getInputStream()) {
            ByteArrayOutputStream b = new ByteArrayOutputStream();
            byte[] t = new byte[16384]; int n;
            while ((n = in.read(t)) > 0) b.write(t, 0, n);
            return b.toByteArray();
        } finally { c.disconnect(); }
    }

    static void go(FaceEngine eng, String base) throws Exception {
        String T = FaceEngine.TAG;
        if (eng.det == null) { eng.det = new FaceModels.Detector(eng.ctx); eng.emb = new FaceModels.Embedder(eng.ctx); }
        Map<String, List<float[]>> byLabel = new LinkedHashMap<>();
        int pics = 0, noFace = 0; long detMs = 0, embMs = 0;
        for (String line : new String(get(base + "list.txt"), "UTF-8").split("\n")) {
            String[] p = line.trim().split("\\s+");
            if (p.length != 2) continue;
            byte[] b = get(base + p[1]);
            Bitmap bm = BitmapFactory.decodeByteArray(b, 0, b.length);
            if (bm == null) continue;
            int[] px = new int[bm.getWidth() * bm.getHeight()];
            bm.getPixels(px, 0, bm.getWidth(), 0, 0, bm.getWidth(), bm.getHeight());
            FaceImage img = new FaceImage.Argb(bm.getWidth(), bm.getHeight(), px);
            bm.recycle();
            pics++;
            long t = SystemClock.uptimeMillis();
            FaceModels.Face f = eng.det.detect(img, 0, 0.6f);
            detMs += SystemClock.uptimeMillis() - t;
            if (f == null) { noFace++; continue; }
            t = SystemClock.uptimeMillis();
            float[] e = eng.emb.embed(img, f);
            embMs += SystemClock.uptimeMillis() - t;
            List<float[]> l = byLabel.get(p[0]);
            if (l == null) { l = new ArrayList<>(); byLabel.put(p[0], l); }
            l.add(e);
            java.util.Arrays.fill(px, 0);
        }
        int found = pics - noFace;
        Log.i(T, "facetest: " + pics + " pictures, face found in " + found + "; find " + (pics > 0 ? detMs / pics : 0)
                + " ms, name " + (found > 0 ? embMs / found : 0) + " ms per face (" + eng.det.N + " px finder, one core)");

        Map<String, List<float[]>> enrolled = new LinkedHashMap<>();
        for (Map.Entry<String, List<float[]>> en : byLabel.entrySet())
            if (enrolled.size() < 2 && en.getValue().size() >= 4) enrolled.put(en.getKey(), new ArrayList<>(en.getValue().subList(0, 3)));
        int right = 0, wrong = 0, missed = 0, strangers = 0, falseYes = 0;
        float gMin = 2, gSum = 0, iMax = -2, iSum = 0; int gN = 0, iN = 0;
        for (Map.Entry<String, List<float[]>> en : byLabel.entrySet()) {
            boolean isEnrolled = enrolled.containsKey(en.getKey());
            List<float[]> l = en.getValue();
            for (int i = isEnrolled ? 3 : 0; i < l.size(); i++) {
                FaceStore.Match m = FaceStore.match(enrolled, l.get(i));
                if (isEnrolled) {
                    if (en.getKey().equals(m.name)) right++; else if (m.name != null) wrong++; else missed++;
                    float g = -1; for (float[] t : enrolled.get(en.getKey())) g = Math.max(g, FaceModels.dot(t, l.get(i)));
                    gMin = Math.min(gMin, g); gSum += g; gN++;
                    for (Map.Entry<String, List<float[]>> o : enrolled.entrySet()) {
                        if (o.getKey().equals(en.getKey())) continue;
                        float s = -1; for (float[] t : o.getValue()) s = Math.max(s, FaceModels.dot(t, l.get(i)));
                        iMax = Math.max(iMax, s); iSum += s; iN++;
                    }
                } else {
                    strangers++;
                    if (m.name != null) falseYes++;
                    for (List<float[]> o : enrolled.values()) {
                        float s = -1; for (float[] t : o) s = Math.max(s, FaceModels.dot(t, l.get(i)));
                        iMax = Math.max(iMax, s); iSum += s; iN++;
                    }
                }
            }
        }
        Log.i(T, "facetest: set up " + enrolled.keySet() + " with 3 pictures each; their other pictures: " + right + " right, "
                + wrong + " named as the wrong person, " + missed + " not recognised");
        Log.i(T, "facetest: strangers: " + strangers + " pictures, " + falseYes + " wrongly named as someone set up");
        Log.i(T, "facetest: same person score mean " + FaceEngine.fmt(gN > 0 ? gSum / gN : 0) + " lowest " + FaceEngine.fmt(gMin)
                + "; different person mean " + FaceEngine.fmt(iN > 0 ? iSum / iN : 0) + " highest " + FaceEngine.fmt(iMax)
                + " (match needs " + FaceStore.MATCH + " and a lead of " + FaceStore.MARGIN + ")");

        // the saved file: write a test person, then Forget, and check the file is gone (only when nobody is set up)
        FaceStore st = eng.store;
        if (st.enrolled().isEmpty() && st.rotation < 0 && !enrolled.isEmpty()) {
            st.put("Test person", enrolled.values().iterator().next());
            Log.i(T, "facetest: saved test numbers as Test person: faces.json " + (st.file.exists() ? st.file.length() + " bytes" : "missing"));
            st.forget("Test person");
            Log.i(T, "facetest: after Forget: faces.json " + (st.file.exists() ? "STILL THERE" : "deleted") + ", people " + st.enrolled());
        }
    }

    static void listFiles(File d, String pre) {
        File[] fs = d.listFiles();
        if (fs == null) return;
        for (File f : fs) {
            if (f.isDirectory()) listFiles(f, pre + f.getName() + "/");
            else Log.i(FaceEngine.TAG, "facetest: app file " + pre + f.getName() + " " + f.length() + " bytes");
        }
    }
}
