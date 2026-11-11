package com.homehub.wall;

import android.content.Context;
import android.content.res.AssetFileDescriptor;

import org.tensorflow.lite.Interpreter;

import java.io.FileInputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.FloatBuffer;
import java.nio.MappedByteBuffer;
import java.nio.channels.FileChannel;
import java.util.HashMap;
import java.util.Map;

/**
 * The two small face models, both run on the tablet with LiteRT (TensorFlow Lite), one CPU thread.
 *
 *  - BlazeFace short range (MediaPipe, Apache 2.0): finds a face, its box, eyes, nose and mouth.
 *  - MobileFaceNet (Qualcomm AI Hub export of foamliu/MobileFaceNet, Apache 2.0): 128 numbers that
 *    describe a face, so two looks at the same person give close numbers.
 *
 * Only numbers come out of here. The pictures that go in are overwritten by the next camera frame.
 */
final class FaceModels {

    /** One face found in a frame, in upright frame pixels. */
    static final class Face {
        float score;
        float cx, cy, bw, bh;           // box centre and size
        float[] kp = new float[12];     // 6 points x (u, v): right eye, left eye, nose, mouth, right ear, left ear
        int rot;
        float eyeDist() { return (float) Math.hypot(kp[2] - kp[0], kp[3] - kp[1]); }
    }

    private static MappedByteBuffer asset(Context c, String name) throws IOException {
        AssetFileDescriptor fd = c.getAssets().openFd(name);   // stored uncompressed in the APK (build.sh -0 tflite)
        try (FileInputStream in = new FileInputStream(fd.getFileDescriptor())) {
            return in.getChannel().map(FileChannel.MapMode.READ_ONLY, fd.getStartOffset(), fd.getDeclaredLength());
        }
    }

    private static Interpreter interp(Context c, String name) throws IOException {
        Interpreter.Options o = new Interpreter.Options();
        o.setNumThreads(1);             // leave the other cores to the screen
        return new Interpreter(asset(c, name), o);
    }

    // ------------------------------------------------------------------ BlazeFace
    static final class Detector {
        static final int N = 128, A = 896;
        final Interpreter tfl;
        final ByteBuffer in = ByteBuffer.allocateDirect(N * N * 3 * 4).order(ByteOrder.nativeOrder());
        final float[][][] reg = new float[1][A][16];
        final float[][][] cls = new float[1][A][1];
        final float[] anchors = new float[A * 2];
        final Map<Integer, Object> outs = new HashMap<>();
        final float[] p = new float[2];
        int regIdx, clsIdx;

        Detector(Context c) throws IOException {
            tfl = interp(c, "blaze_face_short_range.tflite");
            regIdx = tfl.getOutputIndex("regressors");
            clsIdx = tfl.getOutputIndex("classificators");
            outs.put(regIdx, reg);
            outs.put(clsIdx, cls);
            // SSD anchors for the short range model: 16x16 cells x 2, then 8x8 cells x 6, centred, fixed size.
            int k = 0;
            int[][] grids = {{16, 2}, {8, 6}};
            for (int[] g : grids)
                for (int y = 0; y < g[0]; y++)
                    for (int x = 0; x < g[0]; x++)
                        for (int r = 0; r < g[1]; r++) {
                            anchors[k++] = (x + 0.5f) / g[0];
                            anchors[k++] = (y + 0.5f) / g[0];
                        }
        }

        /** The best face in the frame turned by rot, or null. The frame is letterboxed into a square. */
        Face detect(FaceImage img, int rot, float minScore) {
            int uw = img.uw(rot), uh = img.uh(rot);
            float side = Math.max(uw, uh), padU = (side - uw) / 2f, padV = (side - uh) / 2f, step = side / N;
            FloatBuffer f = in.asFloatBuffer();
            for (int j = 0; j < N; j++) {
                float v = (j + 0.5f) * step - padV;
                for (int i = 0; i < N; i++) {
                    float u = (i + 0.5f) * step - padU;
                    if (u < 0 || v < 0 || u >= uw || v >= uh) { f.put(-1f); f.put(-1f); f.put(-1f); continue; }
                    img.up(rot, u, v, p);
                    int c = img.rgb((int) p[0], (int) p[1]);
                    f.put(((c >> 16) & 255) / 127.5f - 1f);
                    f.put(((c >> 8) & 255) / 127.5f - 1f);
                    f.put((c & 255) / 127.5f - 1f);
                }
            }
            in.rewind();
            tfl.runForMultipleInputsOutputs(new Object[]{in}, outs);
            int best = -1; float bestS = 0;
            for (int a = 0; a < A; a++) {
                float s = cls[0][a][0];
                s = s < -100 ? -100 : (s > 100 ? 100 : s);
                s = (float) (1 / (1 + Math.exp(-s)));
                if (s > bestS) { bestS = s; best = a; }
            }
            if (best < 0 || bestS < minScore) return null;
            float[] r = reg[0][best];
            float ax = anchors[best * 2], ay = anchors[best * 2 + 1];
            Face fc = new Face();
            fc.score = bestS;
            fc.rot = rot;
            fc.cx = (r[0] / N + ax) * side - padU;
            fc.cy = (r[1] / N + ay) * side - padV;
            fc.bw = r[2] / N * side;
            fc.bh = r[3] / N * side;
            for (int q = 0; q < 6; q++) {
                fc.kp[q * 2] = (r[4 + q * 2] / N + ax) * side - padU;
                fc.kp[q * 2 + 1] = (r[5 + q * 2] / N + ay) * side - padV;
            }
            return fc;
        }

        void close() { tfl.close(); }
    }

    // ------------------------------------------------------------------ MobileFaceNet
    static final class Embedder {
        static final int S = 112;
        // where the eyes sit in the 112 x 112 face the model was trained on (the ArcFace layout)
        static final float LX = 38.2946f, LY = 51.6963f, RX = 73.5318f, RY = 51.5014f;
        final Interpreter tfl;
        final ByteBuffer in1 = ByteBuffer.allocateDirect(3 * S * S * 4).order(ByteOrder.nativeOrder());
        final ByteBuffer in2 = ByteBuffer.allocateDirect(3 * S * S * 4).order(ByteOrder.nativeOrder());
        final float[][] out = new float[2][128];
        final Map<Integer, Object> outs = new HashMap<>();
        final Object[] ins = new Object[2];
        final float[] p = new float[2], c = new float[3];

        Embedder(Context ctx) throws IOException {
            tfl = interp(ctx, "mobile_facenet.tflite");
            ins[tfl.getInputIndex("img1")] = in1;
            ins[tfl.getInputIndex("img2")] = in2;
            outs.put(0, out);
        }

        /**
         * 128 numbers for this face, length 1. The face is lined up on its eyes, and the model sees it
         * once as is and once mirrored; the two answers are added, which makes the numbers steadier.
         */
        float[] embed(FaceImage img, Face f) {
            // the eye nearer the left of the upright frame goes to the template's left eye
            float e1u = f.kp[0], e1v = f.kp[1], e2u = f.kp[2], e2v = f.kp[3];
            if (e1u > e2u) { float t = e1u; e1u = e2u; e2u = t; t = e1v; e1v = e2v; e2v = t; }
            float tx = RX - LX, ty = RY - LY, sx = e2u - e1u, sy = e2v - e1v;
            float n2 = tx * tx + ty * ty;
            float a = (sx * tx + sy * ty) / n2, b = (tx * sy - ty * sx) / n2;   // template -> frame: [a -b; b a]
            FloatBuffer f1 = in1.asFloatBuffer(), f2 = in2.asFloatBuffer();
            int plane = S * S;
            for (int y = 0; y < S; y++) {
                for (int x = 0; x < S; x++) {
                    float dx = x - LX, dy = y - LY;
                    float u = a * dx - b * dy + e1u, v = b * dx + a * dy + e1v;
                    img.up(f.rot, u, v, p);
                    img.rgbf(p[0], p[1], c);
                    int i = y * S + x, im = y * S + (S - 1 - x);
                    for (int k = 0; k < 3; k++) { f1.put(k * plane + i, c[k]); f2.put(k * plane + im, c[k]); }
                }
            }
            in1.rewind(); in2.rewind();
            tfl.runForMultipleInputsOutputs(ins, outs);
            float[] e = new float[128];
            double n = 0;
            for (int k = 0; k < 128; k++) { e[k] = out[0][k] + out[1][k]; n += e[k] * e[k]; }
            float inv = (float) (1 / Math.sqrt(Math.max(n, 1e-12)));
            for (int k = 0; k < 128; k++) e[k] *= inv;
            return e;
        }

        void close() { tfl.close(); }
    }

    static float dot(float[] a, float[] b) {
        float s = 0;
        for (int k = 0; k < a.length; k++) s += a[k] * b[k];
        return s;
    }
}
