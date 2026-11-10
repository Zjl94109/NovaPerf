package com.novaperf.demo;

import android.app.Application;

import com.novaperf.sdk.NovaPerf;

/** 冷启动即开始采集；CLI 也可用显式广播重新 START/STOP。 */
public final class DemoApp extends Application {
    @Override
    public void onCreate() {
        super.onCreate();
        NovaPerf.attach(this);
        NovaPerf.start(this, 0, 1000, false, "demo");
    }
}
