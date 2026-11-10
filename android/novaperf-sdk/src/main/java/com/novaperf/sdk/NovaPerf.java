package com.novaperf.sdk;

import android.app.Application;
import android.content.Context;
import android.net.TrafficStats;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.Looper;
import android.util.Log;

import java.io.File;
import java.io.FileOutputStream;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * NovaPerf 门面：SDK 自采集、自落盘，无控制台 App、无 AIDL/binder、无 native、无 root。
 *
 * 用法（宿主 App）：
 *   NovaPerf.attach(getApplication());   // Application.onCreate
 *   NovaPerf.start(ctx);                 // 或由 CLI 通过显式广播启动
 *   NovaPerf.flag("进入战斗");
 *   NovaPerf.stop();
 */
public final class NovaPerf {
    public static final String TAG = "NovaPerf";
    private static final NovaPerf I = new NovaPerf();
    private static final long PROCESS_AT = System.currentTimeMillis();

    private Context app;
    private SessionWriter writer;
    private HandlerThread thread;
    private Handler sampler;
    private FrameMonitor frameMonitor;
    private BatteryMonitor battery;
    private AnrWatchdog anr;
    private CrashHandler crash;
    private volatile boolean running = false;
    private volatile String scene = "default";
    private volatile String page = "unknown";
    private volatile long intervalMs = 1000;
    private volatile boolean frameDetail = false;
    private volatile long startedAt = 0;
    private volatile int seq = 0;
    private volatile long firstFrameAt = 0;
    private ProcStats.Snapshot prev;
    private long prevTx = -1, prevRx = -1;
    private final AtomicInteger netReq = new AtomicInteger();
    private final AtomicInteger netErr = new AtomicInteger();
    private final AtomicInteger anrRisk = new AtomicInteger();
    private int cores = Math.max(1, Runtime.getRuntime().availableProcessors());

    private NovaPerf() {
    }

    // ------------------------------------------------------------------ 公共 API

    public static void attach(Context ctx) {
        I.attachInternal(ctx);
    }

    public static void start(Context ctx) {
        I.startInternal(ctx, 0, 1000, false, null);
    }

    public static void start(Context ctx, long durationMs, long interval, boolean frames, String sceneName) {
        I.startInternal(ctx, durationMs, interval, frames, sceneName);
    }

    public static void stop() {
        I.stopInternal();
    }

    public static void flag(String label) {
        I.flagInternal(label, null);
    }

    public static void flag(String label, String detail) {
        I.flagInternal(label, detail);
    }

    public static void scene(String name) {
        if (name == null || name.length() == 0) return;
        I.scene = name;
        I.event("scene", "info", "场景切换:" + name, null, null, null);
    }

    public static void page(String name) {
        if (name != null) I.page = name;
    }

    public static void lifecycle(String label) {
        I.event("lifecycle", "info", label, null, null, null);
    }

    public static void log(String level, String msg) {
        I.event("log", level == null ? "info" : level, msg, null, null, null);
    }

    /** 接入网络层（OkHttp 拦截器 / URLSessionTaskMetrics）后调用，用于 net_req / net_err。 */
    public static void noteHttp(String url, long durationMs, int statusCode, boolean error) {
        I.netReq.incrementAndGet();
        if (error) I.netErr.incrementAndGet();
        if (I.running) {
            I.event("http", error ? "error" : "info",
                    (statusCode > 0 ? statusCode + " " : "") + trimUrl(url),
                    null, null, (double) durationMs);
        }
    }

    public static boolean isRunning() {
        return I.running;
    }

    /** 供 CLI 的 STATUS 广播读取；同时写入 status.json（adb shell cat 可读）。 */
    public static String status() {
        return SessionWriter.Json.obj(
                "running", I.running,
                "sdk", "novaperf/1.0.0",
                "session_path", I.writer == null ? null : I.writer.path(),
                "started_at", I.startedAt == 0 ? null : I.startedAt,
                "samples", I.seq,
                "scene", I.scene,
                "page", I.page);
    }

    public static void writeStatusFile() {
        I.writeStatus();
    }

    /** FrameMonitor 首帧回调（包内可见）。 */
    static void onFirstFrame() {
        if (I.firstFrameAt == 0L) {
            I.firstFrameAt = System.currentTimeMillis();
            I.event("lifecycle", "info", "cold_start",
                    "Application init -> first frame", null,
                    (double) (I.firstFrameAt - PROCESS_AT));
        }
    }

    // ------------------------------------------------------------------ 内部实现

    private synchronized void attachInternal(Context ctx) {
        if (app != null || ctx == null) return;
        app = ctx.getApplicationContext();
        cores = Math.max(1, Runtime.getRuntime().availableProcessors());
        if (app instanceof Application) {
            try {
                ((Application) app).registerActivityLifecycleCallbacks(new PageTracker());
            } catch (Throwable ignored) {
            }
        }
        crash = new CrashHandler(new CrashHandler.Sink() {
            @Override
            public void onCrash(String stack) {
                event("crash", "error", "未捕获异常", null, stack, null);
                if (writer != null) {
                    writer.writeSummary();
                    writer.close();
                }
            }
        });
        crash.install();
    }

    private synchronized void startInternal(Context ctx, long durationMs, long interval,
                                            boolean frames, String sceneName) {
        attachInternal(ctx);
        if (running) return;
        if (interval >= 200) intervalMs = interval;
        frameDetail = frames;
        if (sceneName != null && sceneName.length() > 0) scene = sceneName;
        try {
            writer = new SessionWriter(app);
            writer.writeMeta(app);
        } catch (Throwable e) {
            Log.e(TAG, "cannot open session: " + e);
            return;
        }
        startedAt = System.currentTimeMillis();
        seq = 0;
        firstFrameAt = 0;
        netReq.set(0);
        netErr.set(0);
        anrRisk.set(0);
        prev = ProcStats.read();
        prevTx = uidTx();
        prevRx = uidRx();

        frameMonitor = new FrameMonitor();
        frameMonitor.setSink(new FrameMonitor.Sink() {
            @Override
            public void onFrame(double dtMs, boolean jank, boolean bigJank) {
                if (!frameDetail || writer == null) return;
                writer.writeLine(SessionWriter.Json.obj(
                        "v", 1, "t", System.currentTimeMillis(), "type", "frame",
                        "dt_ms", dtMs, "jank", jank, "big_jank", bigJank));
            }
        });
        battery = new BatteryMonitor(app);
        battery.start();
        anr = new AnrWatchdog(new AnrWatchdog.Sink() {
            @Override
            public void onAnr(String stack) {
                anrRisk.set(1);
                event("anr", "error", "疑似主线程阻塞(>2s)",
                        "NovaPerf watchdog，非系统 ANR 弹窗", stack, null);
            }
        });
        anr.start();

        thread = new HandlerThread("novaperf-sampler");
        thread.start();
        sampler = new Handler(thread.getLooper());
        running = true;
        // Choreographer 必须在主线程注册
        new Handler(Looper.getMainLooper()).post(new Runnable() {
            @Override
            public void run() {
                if (running && frameMonitor != null) frameMonitor.start();
            }
        });
        event("lifecycle", "info", "session_start", "SDK 自采集会话开始", null, null);
        sampler.post(tick);
        if (durationMs > 0) {
            sampler.postDelayed(new Runnable() {
                @Override
                public void run() {
                    stop();
                }
            }, durationMs);
        }
        writeStatus();
        Log.i(TAG, "START " + status());
    }

    private synchronized void stopInternal() {
        if (!running) return;
        running = false;
        if (sampler != null) sampler.removeCallbacksAndMessages(null);
        if (frameMonitor != null) {
            final FrameMonitor fm = frameMonitor;
            new Handler(Looper.getMainLooper()).post(new Runnable() {
                @Override
                public void run() {
                    fm.stop();
                }
            });
        }
        if (battery != null) battery.stop();
        if (anr != null) anr.stop();
        event("lifecycle", "info", "session_stop", null, null, null);
        if (writer != null) {
            writer.writeSummary();
            writer.close();
        }
        if (thread != null) thread.quitSafely();
        writeStatus();
        Log.i(TAG, "STOP " + status());
        thread = null;
        sampler = null;
        anr = null;
        battery = null;
        frameMonitor = null;
    }

    private final Runnable tick = new Runnable() {
        @Override
        public void run() {
            if (!running) return;
            try {
                sampleOnce();
            } catch (Throwable e) {
                Log.e(TAG, "sample failed: " + e);
            }
            if (running && sampler != null) sampler.postDelayed(this, intervalMs);
        }
    };

    private void sampleOnce() {
        ProcStats.Snapshot cur = ProcStats.read();
        long dt = prev == null ? intervalMs : cur.wallMs - prev.wallMs;
        if (dt <= 0) dt = intervalMs;
        FrameMonitor.Stats fs = frameMonitor == null ? new FrameMonitor.Stats() : frameMonitor.drain(dt);
        if (writer != null) writer.noteFrame(fs.frames);

        long tx = uidTx(), rx = uidRx();
        Double txBps = (prevTx < 0 || tx < 0) ? null : ProcStats.rateBps(prevTx, tx, dt);
        Double rxBps = (prevRx < 0 || rx < 0) ? null : ProcStats.rateBps(prevRx, rx, dt);
        prevTx = tx;
        prevRx = rx;

        Double gcDelta = null;
        if (prev != null && prev.gcCount != null && cur.gcCount != null) {
            long d = cur.gcCount - prev.gcCount;
            gcDelta = (double) (d < 0 ? 0 : d);
        }
        Double busy = anr == null ? null : (double) anr.maxDelayAndReset();
        int risk = anrRisk.getAndSet(0) | (busy != null && busy > 2000 ? 1 : 0);

        String thermal = battery == null ? "unknown" : battery.thermal();
        Double battPct = battery == null ? null : battery.percent();
        Double tempC = battery == null ? null : battery.tempC();
        if (battery != null) battery.refreshThermal();

        String line = SessionWriter.Json.obj(
                "v", 1, "t", System.currentTimeMillis(), "type", "sample",
                "seq", ++seq,
                "fps", fs.fps, "frame_ms", fs.frameMs, "frame_p95_ms", fs.p95Ms,
                "jank", fs.jank, "big_jank", fs.bigJank, "frozen", fs.frozen,
                "cpu_app_pct", ProcStats.cpuAppPct(prev, cur, cores), "cpu_sys_pct", null,
                "threads", cur.threads, "fds", cur.fds,
                "pss_kb", cur.pssKb, "heap_kb", cur.heapKb, "native_kb", cur.nativeKb,
                "gc_count", gcDelta,
                "net_tx_bps", txBps, "net_rx_bps", rxBps,
                "net_req", netReq.getAndSet(0), "net_err", netErr.getAndSet(0),
                "io_read_bps", prev == null ? null : ProcStats.rateBps(prev.readBytes, cur.readBytes, dt),
                "io_write_bps", prev == null ? null : ProcStats.rateBps(prev.writeBytes, cur.writeBytes, dt),
                "battery_pct", battPct, "temp_c", tempC, "thermal_state", thermal,
                "gpu_pct", null,
                "main_thread_busy_ms", busy, "anr_risk", risk,
                "page", page, "scene", scene);
        if (writer != null) writer.writeSample(line);
        prev = cur;
    }

    private void flagInternal(String label, String detail) {
        if (label == null) label = "flag";
        event("scene", "info", label, detail, null, null);
    }

    private void event(String kind, String level, String label,
                       String detail, String stack, Number durationMs) {
        if (writer != null && !writer.isClosed()) {
            writer.writeEvent(kind, level, label, detail, stack, durationMs, page);
        }
    }

    private void writeStatus() {
        if (app == null) return;
        try {
            File base = app.getExternalFilesDir(null);
            if (base == null) base = app.getFilesDir();
            File dir = new File(base, "novaperf");
            if (!dir.exists()) dir.mkdirs();
            FileOutputStream out = new FileOutputStream(new File(dir, "status.json"), false);
            out.write(status().getBytes("UTF-8"));
            out.close();
        } catch (Throwable ignored) {
        }
    }

    private static long uidTx() {
        try {
            return TrafficStats.getUidTxBytes(android.os.Process.myUid());
        } catch (Throwable e) {
            return -1;
        }
    }

    private static long uidRx() {
        try {
            return TrafficStats.getUidRxBytes(android.os.Process.myUid());
        } catch (Throwable e) {
            return -1;
        }
    }

    private static String trimUrl(String url) {
        if (url == null) return "";
        return url.length() > 180 ? url.substring(0, 180) : url;
    }
}
