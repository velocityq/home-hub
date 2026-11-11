package com.homehub.wall;

/**
 * A picture in memory that the face code reads pixel by pixel: a camera frame (NV21) or, for the
 * self test only, a downloaded test picture. Nothing here is ever written to storage.
 *
 * Rotation: the camera may sit sideways or upside down. "Upright" coordinates (u, v) are the frame
 * turned clockwise by rot degrees; up() maps them back to the raw frame.
 */
abstract class FaceImage {
    final int w, h;

    FaceImage(int w, int h) { this.w = w; this.h = h; }

    /** RGB at a raw pixel, packed 0xRRGGBB. x and y are clamped. */
    abstract int rgb(int x, int y);

    /** Brightness 0..255 at a raw pixel. */
    abstract int luma(int x, int y);

    int uw(int rot) { return rot == 90 || rot == 270 ? h : w; }
    int uh(int rot) { return rot == 90 || rot == 270 ? w : h; }

    /** Upright (u, v) to raw x, y, written into out[0], out[1]. */
    final void up(int rot, float u, float v, float[] out) {
        switch (rot) {
            case 90:  out[0] = v;         out[1] = h - 1 - u; break;
            case 180: out[0] = w - 1 - u; out[1] = h - 1 - v; break;
            case 270: out[0] = w - 1 - v; out[1] = u;         break;
            default:  out[0] = u;         out[1] = v;
        }
    }

    /** Bilinear RGB at a raw position, as three floats 0..1 in out[0..2]. */
    final void rgbf(float x, float y, float[] out) {
        if (x < 0) x = 0; if (y < 0) y = 0;
        if (x > w - 1) x = w - 1; if (y > h - 1) y = h - 1;
        int x0 = (int) x, y0 = (int) y;
        int x1 = Math.min(x0 + 1, w - 1), y1 = Math.min(y0 + 1, h - 1);
        float fx = x - x0, fy = y - y0;
        int a = rgb(x0, y0), b = rgb(x1, y0), c = rgb(x0, y1), d = rgb(x1, y1);
        for (int k = 0; k < 3; k++) {
            int sh = 16 - 8 * k;
            float top = ((a >> sh) & 255) * (1 - fx) + ((b >> sh) & 255) * fx;
            float bot = ((c >> sh) & 255) * (1 - fx) + ((d >> sh) & 255) * fx;
            out[k] = (top * (1 - fy) + bot * fy) / 255f;
        }
    }

    /** Mean brightness over a sparse grid (about 1,200 samples). */
    final int meanLuma() {
        long sum = 0; int n = 0;
        int sx = Math.max(1, w / 40), sy = Math.max(1, h / 30);
        for (int y = sy / 2; y < h; y += sy)
            for (int x = sx / 2; x < w; x += sx) { sum += luma(x, y); n++; }
        return n == 0 ? 0 : (int) (sum / n);
    }

    /** A camera frame in NV21 (the Android camera's default preview format). */
    static final class Nv21 extends FaceImage {
        byte[] d;
        Nv21(int w, int h) { super(w, h); }

        @Override int luma(int x, int y) {
            if (x < 0) x = 0; if (y < 0) y = 0; if (x >= w) x = w - 1; if (y >= h) y = h - 1;
            return d[y * w + x] & 255;
        }

        @Override int rgb(int x, int y) {
            if (x < 0) x = 0; if (y < 0) y = 0; if (x >= w) x = w - 1; if (y >= h) y = h - 1;
            int yy = (d[y * w + x] & 255) - 16;
            if (yy < 0) yy = 0;
            int uv = w * h + (y >> 1) * w + (x & ~1);
            int v = (d[uv] & 255) - 128, u = (d[uv + 1] & 255) - 128;
            int y1192 = 1192 * yy;
            int r = (y1192 + 1634 * v) >> 10;
            int g = (y1192 - 833 * v - 400 * u) >> 10;
            int b = (y1192 + 2066 * u) >> 10;
            r = r < 0 ? 0 : (r > 255 ? 255 : r);
            g = g < 0 ? 0 : (g > 255 ? 255 : g);
            b = b < 0 ? 0 : (b > 255 ? 255 : b);
            return (r << 16) | (g << 8) | b;
        }
    }

    /** Packed ARGB pixels (the self test's pictures). */
    static final class Argb extends FaceImage {
        final int[] p;
        Argb(int w, int h, int[] p) { super(w, h); this.p = p; }

        @Override int rgb(int x, int y) {
            if (x < 0) x = 0; if (y < 0) y = 0; if (x >= w) x = w - 1; if (y >= h) y = h - 1;
            return p[y * w + x] & 0xFFFFFF;
        }

        @Override int luma(int x, int y) {
            int c = rgb(x, y);
            return (((c >> 16) & 255) * 77 + ((c >> 8) & 255) * 150 + (c & 255) * 29) >> 8;
        }
    }
}
