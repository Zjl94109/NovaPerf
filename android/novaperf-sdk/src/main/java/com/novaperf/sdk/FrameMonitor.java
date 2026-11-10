package com.novaperf.sdk;

import android.view.Choreographer;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/** 主线程 Choreographer 帧回调；只做极轻的时间戳记录，统计在采样线程聚合。 */
public final class FrameMonitor {
    private final Choreographer choreographer = Choreographer.getInstance();
    private final Object lock = new Object();
    private final List<Double> window = new ArrayList<>();
    private final ArrayDeque<Double> last3 = new ArrayDeque<>();
    private volatile boolean running = false;
    private Sink sink;
    private long lastFrameNs = 0;
    private boolean firstFrameReported = false;
    private int jank = 0, bigJank = 0, frozen = 0;

    /** 可选逐帧明细输出（默认关闭，避免高刷设备产生过量数据）。 */
    public interface Sink {
        void onFrame(double dtMs, boolean jank, boolean bigJank);
    }

    public void setSink(Sink s) {
        sink = s;
    }

    public static final class Stats {
        public Double fps;
        public Double frameMs;
        public Double p95Ms;
        public int jank;
        public int bigJank;
        public int frozen;
        public int frames;
    }

    private final Choreographer.FrameCallback callback = new Choreographer.FrameCallback() {
        @Override
        public void doFrame(long frameTimeNanos) {
            if (!running) return;
            if (lastFrameNs > 0) {
                double dt = (frameTimeNanos - lastFrameNs) / 1_000_000.0;
                if (dt > 0 && dt < 1000) {
                    boolean isJank, isBig;
                    synchronized (lock) {
                        double prev3 = avg3();
                        isJank = prev3 > 0 && dt > 2 * prev3 && dt > 84;
                        isBig = isJank && dt > 125;
                        if (isJank) jank++;
                        if (isBig) bigJank++;
                        if (dt > 700) frozen++;
                        window.add(dt);
                        last3.addLast(dt);
                        if (last3.size() > 3) last3.removeFirst();
                    }
                    Sink s = sink;
                    if (s != null) s.onFrame(dt, isJank, isBig);
                } else if (dt >= 1000) {
                    // 切后台 / 暂停造成的超大间隔：不参与统计，且重置前三帧基线
                    synchronized (lock) {
                        last3.clear();
                    }
                }
            }
            lastFrameNs = frameTimeNanos;
            if (!firstFrameReported) {
                firstFrameReported = true;
                NovaPerf.onFirstFrame();
            }
            choreographer.postFrameCallback(this);
        }
    };

    private double avg3() {
        if (last3.isEmpty()) return 0;
        double sum = 0;
        for (double d : last3) sum += d;
        return sum / last3.size();
    }

    public void start() {
        if (running) return;
        running = true;
        lastFrameNs = 0;
        synchronized (lock) {
            window.clear();
            last3.clear();
            jank = bigJank = frozen = 0;
        }
        choreographer.postFrameCallback(callback);
    }

    public void stop() {
        running = false;
        choreographer.removeFrameCallback(callback);
    }

    /** 取走本窗口统计并重置；windowMs 为采样线程的实际间隔。 */
    public Stats drain(long windowMs) {
        Stats s = new Stats();
        synchronized (lock) {
            s.frames = window.size();
            if (!window.isEmpty()) {
                double sum = 0;
                for (double d : window) sum += d;
                s.frameMs = sum / window.size();
                List<Double> sorted = new ArrayList<>(window);
                Collections.sort(sorted);
                s.p95Ms = percentile(sorted, 0.95);
                s.fps = windowMs > 0 ? window.size() * 1000.0 / windowMs : null;
            }
            s.jank = jank;
            s.bigJank = bigJank;
            s.frozen = frozen;
            window.clear();
            jank = bigJank = frozen = 0;
        }
        return s;
    }

    private static double percentile(List<Double> sorted, double q) {
        if (sorted.isEmpty()) return 0;
        double k = (sorted.size() - 1) * q;
        int lo = (int) Math.floor(k), hi = (int) Math.ceil(k);
        if (lo == hi) return sorted.get(lo);
        return sorted.get(lo) + (sorted.get(hi) - sorted.get(lo)) * (k - lo);
    }
}
