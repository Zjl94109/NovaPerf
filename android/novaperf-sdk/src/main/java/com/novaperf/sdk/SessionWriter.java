package com.novaperf.sdk;

import android.content.Context;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.os.Build;
import android.view.Display;
import android.view.WindowManager;

import java.io.BufferedWriter;
import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStreamWriter;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

/**
 * JSONL 会话写入器。
 * 数据落在应用私有外部目录，无需任何存储权限；逐行 append + flush，进程被杀也不丢已采数据。
 */
public final class SessionWriter {
    private static final String SDK_TAG = "novaperf/1.0.0";

    private final File file;
    private final String sessionId;
    private BufferedWriter writer;
    private final long startedAt = System.currentTimeMillis();
    private int sampleCount = 0;
    private int frameCount = 0;
    private volatile boolean closed = false;

    public SessionWriter(Context ctx) {
        File base = ctx.getExternalFilesDir(null);
        if (base == null) base = ctx.getFilesDir();
        File dir = new File(base, "novaperf");
        if (!dir.exists() && !dir.mkdirs()) {
            throw new IllegalStateException("NovaPerf: cannot create " + dir.getAbsolutePath());
        }
        // 毫秒后缀：短会话重复 START 时不会覆盖上一次数据（无冒号，兼容所有 Android 版本）
        sessionId = new SimpleDateFormat("yyyyMMdd_HHmmss_SSS", Locale.US).format(new Date(startedAt));
        file = new File(dir, "session_" + sessionId + ".jsonl");
        try {
            writer = new BufferedWriter(new OutputStreamWriter(
                    new FileOutputStream(file, false), "UTF-8"));
        } catch (Exception e) {
            throw new IllegalStateException("NovaPerf: cannot open session file", e);
        }
    }

    public String path() {
        return file.getAbsolutePath();
    }

    public long startedAt() {
        return startedAt;
    }

    public boolean isClosed() {
        return closed;
    }

    public synchronized void noteFrame(int n) {
        frameCount += n;
    }

    public synchronized void writeLine(String json) {
        if (closed || json == null) return;
        try {
            writer.write(json);
            writer.write("\n");
            writer.flush();
        } catch (Exception ignored) {
        }
    }

    public void writeMeta(Context ctx) {
        String app = ctx.getPackageName();
        String version = "unknown";
        try {
            PackageInfo pi = ctx.getPackageManager().getPackageInfo(app, 0);
            if (pi.versionName != null) version = pi.versionName;
        } catch (PackageManager.NameNotFoundException ignored) {
        }
        float hz = 60f;
        try {
            WindowManager wm = (WindowManager) ctx.getSystemService(Context.WINDOW_SERVICE);
            if (wm != null) {
                Display d = wm.getDefaultDisplay();
                if (d != null && d.getRefreshRate() > 0) hz = d.getRefreshRate();
            }
        } catch (Exception ignored) {
        }
        writeLine(Json.obj(
                "v", 1, "t", startedAt, "type", "meta",
                "session_id", sessionId,
                "platform", "android",
                "app", app,
                "app_name", app.substring(app.lastIndexOf('.') + 1),
                "app_version", version,
                "device", Build.MANUFACTURER,
                "model", Build.MODEL,
                "os", "Android " + Build.VERSION.RELEASE,
                "api", Build.VERSION.SDK_INT,
                "cores", Runtime.getRuntime().availableProcessors(),
                "refresh_hz", Math.round(hz * 10) / 10.0,
                "root_required", false,
                "sdk", SDK_TAG,
                "started_at", startedAt));
    }

    public synchronized void writeSample(String json) {
        sampleCount++;
        writeLine(json);
    }

    public void writeEvent(String kind, String level, String label,
                           String detail, String stack, Number durationMs, String page) {
        writeLine(Json.obj(
                "v", 1, "t", System.currentTimeMillis(), "type", "event",
                "kind", kind, "level", level, "label", label,
                "detail", detail, "stack", stack,
                "page", page, "duration_ms", durationMs));
    }

    public synchronized void writeSummary() {
        writeLine(Json.obj(
                "v", 1, "t", System.currentTimeMillis(), "type", "summary",
                "duration_ms", System.currentTimeMillis() - startedAt,
                "samples", sampleCount, "frames", frameCount));
    }

    public synchronized void close() {
        if (closed) return;
        try {
            if (writer != null) {
                writer.flush();
                writer.close();
            }
        } catch (Exception ignored) {
        }
        closed = true;
    }

    /** 极轻量 JSON 构造器：不引入任何第三方库；null 写为 JSON null，NaN/Inf 也写为 null。 */
    public static final class Json {
        private Json() {
        }

        public static String obj(Object... kv) {
            StringBuilder sb = new StringBuilder("{");
            for (int i = 0; i + 1 < kv.length; i += 2) {
                if (i > 0) sb.append(',');
                sb.append(str(String.valueOf(kv[i]))).append(':').append(val(kv[i + 1]));
            }
            return sb.append('}').toString();
        }

        private static String val(Object o) {
            if (o == null) return "null";
            if (o instanceof Boolean) return o.toString();
            if (o instanceof Double || o instanceof Float) {
                double d = ((Number) o).doubleValue();
                if (Double.isNaN(d) || Double.isInfinite(d)) return "null";
                return String.valueOf(Math.round(d * 100.0) / 100.0);
            }
            if (o instanceof Number) return o.toString();
            return str(String.valueOf(o));
        }

        private static String str(String s) {
            StringBuilder sb = new StringBuilder("\"");
            for (int i = 0; i < s.length(); i++) {
                char c = s.charAt(i);
                switch (c) {
                    case '"': sb.append("\\\""); break;
                    case '\\': sb.append("\\\\"); break;
                    case '\n': sb.append("\\n"); break;
                    case '\r': sb.append("\\r"); break;
                    case '\t': sb.append("\\t"); break;
                    default:
                        if (c < 0x20) sb.append(String.format(Locale.US, "\\u%04x", (int) c));
                        else sb.append(c);
                }
            }
            return sb.append('"').toString();
        }
    }
}
