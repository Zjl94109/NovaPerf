package com.novaperf.sdk;

import android.os.Debug;
import android.os.SystemClock;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;

/**
 * 只读 /proc/self/* —— 自身进程信息，Android 11+ 免 ROOT 允许。
 * 刻意不读全局 /proc/stat：SELinux 会拒绝，且会中断整条采样链。
 */
public final class ProcStats {
    private ProcStats() {
    }

    public static final class Snapshot {
        public long wallMs;
        public Long appJiffies;      // utime + stime + cutime + cstime
        public Long threads;
        public Long fds;
        public Long readBytes;
        public Long writeBytes;
        public Long gcCount;
        public Long heapKb;
        public Long nativeKb;
        public Long pssKb;
    }

    public static Snapshot read() {
        Snapshot s = new Snapshot();
        s.wallMs = SystemClock.elapsedRealtime();

        String stat = firstLine("/proc/self/stat");
        if (stat != null) {
            try {
                int close = stat.lastIndexOf(')');
                if (close > 0) {
                    String[] a = stat.substring(close + 2).trim().split("\\s+");
                    // a[0] 对应 field3(state)；field14=utime → a[11]
                    if (a.length > 14) {
                        s.appJiffies = parseL(a[11]) + parseL(a[12]) + parseL(a[13]) + parseL(a[14]);
                    }
                }
            } catch (Exception ignored) {
            }
        }

        for (String line : allLines("/proc/self/status")) {
            if (line.startsWith("Threads:")) {
                s.threads = parseNullable(line.substring(8).trim());
                break;
            }
        }

        for (String line : allLines("/proc/self/io")) {
            if (line.startsWith("read_bytes:")) s.readBytes = parseNullable(line.substring(11).trim());
            else if (line.startsWith("write_bytes:")) s.writeBytes = parseNullable(line.substring(12).trim());
        }

        File fdDir = new File("/proc/self/fd");
        String[] fds = fdDir.list();
        if (fds != null) s.fds = (long) fds.length;

        try {
            Debug.MemoryInfo mi = new Debug.MemoryInfo();
            Debug.getMemoryInfo(mi);
            s.pssKb = (long) mi.getTotalPss();
        } catch (Throwable ignored) {
        }
        Runtime rt = Runtime.getRuntime();
        s.heapKb = (rt.totalMemory() - rt.freeMemory()) / 1024;
        s.nativeKb = Debug.getNativeHeapAllocatedSize() / 1024;
        try {
            String gc = Debug.getRuntimeStat("art.gc.gc-count");
            if (gc != null) s.gcCount = Long.parseLong(gc);
        } catch (Throwable ignored) {
        }
        return s;
    }

    /** CPU% = 100 × (Δjiffies × 10ms) / (Δwall × cores)，裁剪到 [0,100]。 */
    public static Double cpuAppPct(Snapshot prev, Snapshot cur, int cores) {
        if (prev == null || cur == null || prev.appJiffies == null || cur.appJiffies == null) return null;
        long dt = cur.wallMs - prev.wallMs;
        if (dt <= 0) return null;
        double v = 100.0 * ((cur.appJiffies - prev.appJiffies) * 10.0) / (dt * Math.max(1, cores));
        if (v < 0) v = 0;
        if (v > 100) v = 100;
        return v;
    }

    public static Double rateBps(Long prev, Long cur, long dtMs) {
        if (prev == null || cur == null || dtMs <= 0) return null;
        long d = cur - prev;
        if (d < 0) d = 0;   // 计数器重置
        return d * 1000.0 / dtMs;
    }

    private static long parseL(String s) {
        try {
            return Long.parseLong(s);
        } catch (Exception e) {
            return 0;
        }
    }

    private static Long parseNullable(String s) {
        try {
            return Long.parseLong(s);
        } catch (Exception e) {
            return null;
        }
    }

    private static String firstLine(String path) {
        BufferedReader r = null;
        try {
            r = new BufferedReader(new FileReader(path));
            return r.readLine();
        } catch (Exception e) {
            return null;
        } finally {
            close(r);
        }
    }

    private static java.util.List<String> allLines(String path) {
        java.util.List<String> out = new java.util.ArrayList<>();
        BufferedReader r = null;
        try {
            r = new BufferedReader(new FileReader(path));
            String line;
            while ((line = r.readLine()) != null) out.add(line);
        } catch (Exception ignored) {
        } finally {
            close(r);
        }
        return out;
    }

    private static void close(BufferedReader r) {
        if (r != null) try {
            r.close();
        } catch (Exception ignored) {
        }
    }
}
