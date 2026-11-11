package com.homehub.wall;

import android.app.job.JobParameters;
import android.app.job.JobService;

/** The backup: runs about every 15 minutes even if Android killed the app's process. */
public class AdbWatchJob extends JobService {
    @Override public boolean onStartJob(JobParameters p) {
        AdbWatchdog.check(this);
        return false;
    }

    @Override public boolean onStopJob(JobParameters p) { return false; }
}
