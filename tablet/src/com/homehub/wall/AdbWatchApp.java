package com.homehub.wall;

import android.app.Application;
import android.os.Handler;
import android.os.Looper;

/** Process start: begin the 60 s wireless debugging check and make sure the 15 minute backup job is scheduled. */
public class AdbWatchApp extends Application implements Runnable {
    private final Handler h = new Handler(Looper.getMainLooper());

    @Override public void onCreate() {
        super.onCreate();
        h.post(this);
        AdbWatchdog.schedule(this);
    }

    @Override public void run() {
        AdbWatchdog.check(this);
        h.postDelayed(this, AdbWatchdog.EVERY_MS);
    }
}
