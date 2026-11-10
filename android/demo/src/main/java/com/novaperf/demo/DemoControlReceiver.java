package com.novaperf.demo;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.util.Log;

import com.novaperf.sdk.NovaPerf;

/**
 * 让 CLI / CI 用显式广播复现负载，无需坐标点击：
 *   adb shell am broadcast -n com.novaperf.demo/.DemoControlReceiver -a com.novaperf.demo.CPU --ei seconds 8
 * 动作：CPU / MEM / FREE / NET / JANK / SCENE / FLAG
 */
public final class DemoControlReceiver extends BroadcastReceiver {
    private static final String P = "com.novaperf.demo.";

    @Override
    public void onReceive(Context ctx, Intent i) {
        if (i == null || i.getAction() == null) return;
        NovaPerf.attach(ctx);
        String a = i.getAction();
        try {
            if ((P + "CPU").equals(a)) {
                Loads.cpu(i.getIntExtra("seconds", 8));
            } else if ((P + "MEM").equals(a)) {
                Loads.mem(i.getIntExtra("mb", 60));
            } else if ((P + "FREE").equals(a)) {
                Loads.free();
            } else if ((P + "NET").equals(a)) {
                Loads.net(i.getIntExtra("count", 20));
            } else if ((P + "JANK").equals(a)) {
                Loads.jank(i.getIntExtra("ms", 350));
            } else if ((P + "SCENE").equals(a)) {
                Loads.scene(i.getStringExtra("scene"));
            } else if ((P + "FLAG").equals(a)) {
                Loads.flag(i.getStringExtra("label"));
            }
        } catch (Throwable e) {
            Log.e(NovaPerf.TAG, "demo load failed: " + e);
        }
        Log.i(NovaPerf.TAG, "DEMO_ACTION=" + a);
    }
}
