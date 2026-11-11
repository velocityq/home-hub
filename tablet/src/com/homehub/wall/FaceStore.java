package com.homehub.wall;

import android.content.Context;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * What the tablet keeps about faces: for each person who set up their face, up to 10 lists of 128
 * numbers, plus which way the camera is turned. No picture, ever. One file in the app's private
 * storage (no_backup/faces.json), readable by this app only. "Forget my face" deletes the person's
 * numbers and rewrites the file (or deletes it when nobody is left).
 */
final class FaceStore {
    /** Names come from the page (which has them from the hub's config.json "people"). A name is a first
     *  name: letters, spaces, apostrophes and hyphens, at most 24 characters, and at most 8 people. */
    static final java.util.regex.Pattern NAME = java.util.regex.Pattern.compile("[A-Za-z][A-Za-z' -]{0,23}");
    static final int MAX_PEOPLE = 8;
    static final int KEEP = 10;
    // A look counts as a person when it is this close to one of their saved looks (cosine, 1 = identical)
    // and clearly closer to them than to anyone else. Measured on this tablet: see PLAN.md, Face ID, Verified.
    static final float MATCH = 0.45f, MARGIN = 0.10f;

    final File file;
    final Map<String, List<float[]>> people = new LinkedHashMap<>();
    int rotation = -1;              // -1: not known yet, found the first time a face is seen

    FaceStore(Context c) {
        file = new File(c.getNoBackupFilesDir(), "faces.json");
        load();
    }

    static boolean known(String name) {
        return name != null && NAME.matcher(name).matches();
    }

    synchronized void load() {
        people.clear();
        rotation = -1;
        if (!file.exists()) return;
        try (FileInputStream in = new FileInputStream(file)) {
            byte[] b = new byte[(int) file.length()];
            int n = 0;
            while (n < b.length) { int g = in.read(b, n, b.length - n); if (g < 0) break; n += g; }
            JSONObject o = new JSONObject(new String(b, 0, n, StandardCharsets.UTF_8));
            rotation = o.optInt("rotation", -1);
            JSONObject ps = o.optJSONObject("people");
            if (ps != null) {
                java.util.Iterator<String> names = ps.keys();
                while (names.hasNext() && people.size() < MAX_PEOPLE) {
                    String name = names.next();
                    if (!known(name)) continue;
                    JSONArray arr = ps.optJSONArray(name);
                    if (arr == null) continue;
                    List<float[]> l = new ArrayList<>();
                    for (int i = 0; i < arr.length() && i < KEEP; i++) {
                        JSONArray v = arr.getJSONArray(i);
                        float[] e = new float[v.length()];
                        for (int k = 0; k < e.length; k++) e[k] = (float) v.getDouble(k);
                        l.add(e);
                    }
                    if (!l.isEmpty()) people.put(name, l);
                }
            }
        } catch (Exception e) {
            Log.w(MainActivity.TAG, "faces: could not read the saved faces: " + e);
        }
    }

    synchronized void save() {
        try {
            if (people.isEmpty() && rotation < 0) { file.delete(); return; }
            JSONObject o = new JSONObject();
            o.put("version", 1);
            o.put("rotation", rotation);
            JSONObject ps = new JSONObject();
            for (Map.Entry<String, List<float[]>> en : people.entrySet()) {
                JSONArray arr = new JSONArray();
                for (float[] e : en.getValue()) {
                    JSONArray v = new JSONArray();
                    for (float x : e) v.put(Math.round(x * 1e5) / 1e5);
                    arr.put(v);
                }
                ps.put(en.getKey(), arr);
            }
            o.put("people", ps);
            File tmp = new File(file.getPath() + ".tmp");
            try (FileOutputStream out = new FileOutputStream(tmp)) {
                out.write(o.toString().getBytes(StandardCharsets.UTF_8));
                out.getFD().sync();
            }
            if (!tmp.renameTo(file)) throw new java.io.IOException("rename failed");
        } catch (Exception e) {
            Log.w(MainActivity.TAG, "faces: could not save: " + e);
        }
    }

    synchronized void put(String name, List<float[]> looks) {
        if (!known(name) || (!people.containsKey(name) && people.size() >= MAX_PEOPLE)) return;
        people.put(name, new ArrayList<>(looks.subList(0, Math.min(KEEP, looks.size()))));
        save();
    }

    synchronized void forget(String name) {
        people.remove(name);
        save();
    }

    synchronized List<String> enrolled() {
        return new ArrayList<>(people.keySet());
    }

    synchronized void setRotation(int r) {
        rotation = r;
        save();
    }

    /** The best match for one look. */
    static final class Match {
        String name;          // null when nobody is close enough
        float score, next;    // best person's score, and the best other person's score
        String best;          // the closest person even when not close enough (for the log)
    }

    synchronized Match match(float[] e) {
        return match(people, e);
    }

    static Match match(Map<String, List<float[]>> ppl, float[] e) {
        Match m = new Match();
        m.score = -1; m.next = -1;
        for (Map.Entry<String, List<float[]>> en : ppl.entrySet()) {
            float s = -1;
            for (float[] t : en.getValue()) s = Math.max(s, FaceModels.dot(t, e));
            if (s > m.score) { m.next = m.score; m.score = s; m.best = en.getKey(); }
            else if (s > m.next) m.next = s;
        }
        if (m.best != null && m.score >= MATCH && m.score - Math.max(m.next, 0) >= MARGIN) m.name = m.best;
        return m;
    }
}
