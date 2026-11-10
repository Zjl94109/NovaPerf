package com.novaperf.sdk;

import java.io.PrintWriter;
import java.io.StringWriter;

/** 崩溃落盘：在进程退出前把堆栈写进当前会话，诊断报告可直接定位崩溃时间点。 */
public final class CrashHandler implements Thread.UncaughtExceptionHandler {
    public interface Sink {
        void onCrash(String stack);
    }

    private final Thread.UncaughtExceptionHandler previous;
    private final Sink sink;

    public CrashHandler(Sink sink) {
        this.sink = sink;
        this.previous = Thread.getDefaultUncaughtExceptionHandler();
    }

    public void install() {
        Thread.setDefaultUncaughtExceptionHandler(this);
    }

    @Override
    public void uncaughtException(Thread thread, Throwable ex) {
        try {
            StringWriter sw = new StringWriter();
            ex.printStackTrace(new PrintWriter(sw));
            sink.onCrash(sw.toString());
        } catch (Throwable ignored) {
        }
        if (previous != null) previous.uncaughtException(thread, ex);
    }
}
