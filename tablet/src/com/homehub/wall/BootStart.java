package com.homehub.wall;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/**
 * After a restart, bring the hub to the front by itself (the owner, 11 Nov 2026: "It should just open
 * up on that when we turn it on"). The watchdog no longer switches Wireless debugging on (it made
 * Android ask on the wall every time), so after a restart adb needs someone to switch it on.
 *
 * The AirTouch app must run for the aircon service to answer (11 Nov 2026: after a restart with the
 * hub as home, the hub showed "Aircon not answering"). So: open AirTouch at 3 s, then bring the hub
 * forward at 12 s and again at 25 s. AirTouch keeps running behind it.
 * Starting an activity from the background needs "display over other apps", granted once over adb
 * (appops set com.homehub.wall SYSTEM_ALERT_WINDOW allow).
 */
public class BootStart extends BroadcastReceiver {
    static final long[] AFTER_MS = {12000, 25000};
    /** The AirTouch app runs the aircon service the hub talks to: open it first after a restart. */
    static final String AIRTOUCH = "au.com.polyaire.airtouch5.console";
    static final long AIRTOUCH_AT_MS = 3000;

    @Override public void onReceive(Context context, Intent intent) {
        String a = intent == null ? null : intent.getAction();
        if (!Intent.ACTION_BOOT_COMPLETED.equals(a) && !Intent.ACTION_MY_PACKAGE_REPLACED.equals(a)) return;
        new Waker(context.getApplicationContext(), goAsync()).start();
    }

    /** Waits, then brings the hub forward at each time in AFTER_MS. */
    static final class Waker extends Thread {
        private final Context app;
        private final PendingResult done;

        Waker(Context app, PendingResult done) {
            super("boot-start");
            this.app = app;
            this.done = done;
        }

        @Override public void run() {
            try {
                Thread.sleep(AIRTOUCH_AT_MS);
                long waited = AIRTOUCH_AT_MS;
                Intent air = app.getPackageManager().getLaunchIntentForPackage(AIRTOUCH);
                if (air != null) {
                    air.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                    try { app.startActivity(air); } catch (RuntimeException ignored) { }
                }
                for (long at : AFTER_MS) {
                    Thread.sleep(at - waited);
                    waited = at;
                    Intent i = new Intent(app, MainActivity.class)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_REORDER_TO_FRONT);
                    try { app.startActivity(i); } catch (RuntimeException ignored) { }
                }
            } catch (InterruptedException ignored) {
            } finally {
                done.finish();
            }
        }
    }
}
