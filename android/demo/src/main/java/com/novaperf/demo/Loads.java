package com.novaperf.demo;

import android.os.SystemClock;

import com.novaperf.sdk.NovaPerf;

import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.ArrayList;
import java.util.List;

/** 可复现的负载制造器：UI 按钮与 CLI 广播共用同一套实现，保证真机验证可自动化。 */
public final class Loads {
    private static final List<byte[]> KEEP = new ArrayList<>();
    private static volatile boolean cpuRunning = false;

    private Loads() {
    }

    public static void cpu(final int seconds) {
        if (cpuRunning) return;
        cpuRunning = true;
        final int s = Math.max(1, Math.min(seconds, 120));
        NovaPerf.flag("cpu_load_start", "忙循环 " + s + "s");
        new Thread(new Runnable() {
            @Override
            public void run() {
                long end = SystemClock.elapsedRealtime() + s * 1000L;
                double x = 0.123;
                while (SystemClock.elapsedRealtime() < end && cpuRunning) {
                    for (int i = 0; i < 30000; i++) x = Math.sqrt(x + i) % 9973.0;
                }
                cpuRunning = false;
                NovaPerf.flag("cpu_load_end", "x=" + x);
            }
        }, "novaperf-cpu-load").start();
    }

    public static void mem(int mb) {
        int size = Math.max(1, Math.min(mb, 400));
        NovaPerf.flag("mem_alloc_start", "+" + size + "MB");
        int blocks = Math.max(1, size / 6);
        for (int i = 0; i < blocks; i++) {
            KEEP.add(new byte[6 * 1024 * 1024]);
            KEEP.get(KEEP.size() - 1)[0] = 1; // 触发真实物理页分配
        }
        NovaPerf.flag("mem_alloc_end", "keep=" + KEEP.size() + " blocks");
    }

    public static void free() {
        KEEP.clear();
        System.gc();
        NovaPerf.flag("mem_release");
    }

    public static void net(final int count) {
        final int n = Math.max(1, Math.min(count, 100));
        NovaPerf.flag("network_start", n + " x HTTPS GET");
        new Thread(new Runnable() {
            @Override
            public void run() {
                for (int i = 0; i < n; i++) {
                    HttpURLConnection c = null;
                    long t0 = System.currentTimeMillis();
                    try {
                        c = (HttpURLConnection) new URL("https://www.baidu.com/?n=" + i).openConnection();
                        c.setConnectTimeout(4000);
                        c.setReadTimeout(4000);
                        c.setRequestMethod("GET");
                        int code = c.getResponseCode();
                        InputStream in = c.getInputStream();
                        byte[] buf = new byte[2048];
                        while (in.read(buf) > 0) { /* 真实下行流量 */ }
                        in.close();
                        NovaPerf.noteHttp("https://www.baidu.com/", System.currentTimeMillis() - t0, code, false);
                    } catch (Exception e) {
                        NovaPerf.noteHttp("https://www.baidu.com/", System.currentTimeMillis() - t0, -1, true);
                    } finally {
                        if (c != null) c.disconnect();
                    }
                }
                NovaPerf.flag("network_end");
            }
        }, "novaperf-network").start();
    }

    public static void jank(int ms) {
        int d = Math.max(1, Math.min(ms, 3000));
        NovaPerf.flag("jank_start", "主线程 sleep " + d + "ms");
        SystemClock.sleep(d);
        NovaPerf.flag("jank_end");
    }

    public static void scene(String name) {
        if (name == null || name.length() == 0) name = "default";
        NovaPerf.scene(name);
        NovaPerf.flag("scene:" + name);
    }

    public static void flag(String label) {
        NovaPerf.flag(label == null ? "flag" : label);
    }
}
