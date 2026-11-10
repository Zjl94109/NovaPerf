package com.novaperf.sdk;

import android.os.Handler;
import android.os.Looper;

import java.util.concurrent.atomic.AtomicLong;

/**
 * 主线程心跳：每 500ms 投递一次，统计延迟；>2s 未执行视为「疑似主线程阻塞」。
 * 注意：这不是系统 ANR 弹窗，报告措辞必须区分。
 */
public final class AnrWatchdog {
    public interface Sink {
        void onAnr(String stack);
    }

    private static final long BEAT_MS = 500;
    private static final long ANR_MS = 2000;

    private final Handler main = new Handler(Looper.getMainLooper());
    private final AtomicLong lastBeat = new AtomicLong(System.currentTimeMillis());
    private final Object delayLock = new Object();
    private final Sink sink;
    private long maxDelay;
    private volatile boolean running;
    private volatile boolean fired;
    private Thread watchdog;
    private long nextScheduled;

    public AnrWatchdog(Sink sink) {
        this.sink = sink;
    }

    public void start() {
        if (running) return;
        running = true;
        fired = false;
        lastBeat.set(System.currentTimeMillis());
        nextScheduled = System.currentTimeMillis() + BEAT_MS;
        main.postDelayed(beat, BEAT_MS);
        watchdog = new Thread(new Runnable() {
            @Override
            public void run() {
                while (running) {
                    try {
                        Thread.sleep(250);
                    } catch (InterruptedException e) {
                        return;
                    }
                    if (!running) return;
                    long gap = System.currentTimeMillis() - lastBeat.get();
                    if (gap > ANR_MS) {
                        if (!fired) {
                            fired = true;
                            sink.onAnr(stackOfMainThread());
                        }
                    } else if (gap < 1000) {
                        fired = false;
                    }
                }
            }
        }, "novaperf-anr");
        watchdog.setDaemon(true);
        watchdog.start();
    }

    public void stop() {
        running = false;
        main.removeCallbacks(beat);
        if (watchdog != null) watchdog.interrupt();
    }

    /** 取走本采样窗口内最大心跳延迟（ms）并归零。 */
    public long maxDelayAndReset() {
        synchronized (delayLock) {
            long v = maxDelay;
            maxDelay = 0;
            return v;
        }
    }

    private final Runnable beat = new Runnable() {
        @Override
        public void run() {
            if (!running) return;
            long now = System.currentTimeMillis();
            long delay = now - nextScheduled;
            if (delay < 0) delay = 0;
            synchronized (delayLock) {
                if (delay > maxDelay) maxDelay = delay;
            }
            lastBeat.set(now);
            nextScheduled = now + BEAT_MS;
            main.postDelayed(this, BEAT_MS);
        }
    };

    private static String stackOfMainThread() {
        try {
            StackTraceElement[] st = Looper.getMainLooper().getThread().getStackTrace();
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < st.length && i < 40; i++) sb.append(st[i]).append('\n');
            return sb.toString();
        } catch (Throwable e) {
            return null;
        }
    }
}
