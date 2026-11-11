package com.homehub.wall;

import android.app.job.JobInfo;
import android.app.job.JobScheduler;
import android.content.ComponentName;
import android.content.Context;
import android.content.pm.PackageManager;
import android.provider.Settings;
import android.util.Log;

/**
 * Keeps Wireless debugging on. The tablet switched it off by itself on 10 November, which cut the iMac off.
 * Needs a one time grant over adb: pm grant com.homehub.wall android.permission.WRITE_SECURE_SETTINGS
 * (same idea as couch-tv's on-TV app). Cheap: one settings read every 60 s, no wake lock, nothing else.
 * Two triggers: a 60 s timer while the app's process is alive, and a 15 minute JobScheduler job that
 * survives the process being killed.
 */
public class AdbWatchdog {
    static final String TAG = "HomeHubAdbWatch";
    static final String KEY = "adb_wifi_enabled";
    static final long EVERY_MS = 60_000L;
    static final int JOB_ID = 4417;

    public static void schedule(Context c) {
        try {
            JobScheduler js = (JobScheduler) c.getSystemService(Context.JOB_SCHEDULER_SERVICE);
            if (js.getPendingJob(JOB_ID) != null) return;
            js.schedule(new JobInfo.Builder(JOB_ID, new ComponentName(c, AdbWatchJob.class))
                    .setPeriodic(15 * 60 * 1000L).build());
        } catch (RuntimeException e) {
            Log.w(TAG, "could not schedule the backup job: " + e);
        }
    }

    /** If wireless debugging is off, switch it back on and log it. */
    public static void check(Context c) {
        try {
            if (c.checkSelfPermission("android.permission.WRITE_SECURE_SETTINGS") != PackageManager.PERMISSION_GRANTED) {
                Log.w(TAG, "no WRITE_SECURE_SETTINGS grant, cannot keep wireless debugging on");
                return;
            }
            // Switched OFF on 11 Nov 2026: turning Wireless debugging on from here makes Android ask
            // "Allow wireless debugging on this network?" on the wall every time (the tablet does not
            // keep "Always allow"), which the owner rightly found worse than the drop. Now it only logs.
            if (Settings.Global.getInt(c.getContentResolver(), KEY, 0) != 1) {
                Log.i(TAG, "wireless debugging is off (left off on purpose, no popup on the wall)");
            }
        } catch (RuntimeException e) {
            Log.w(TAG, "watchdog check failed: " + e);
        }
    }
}
