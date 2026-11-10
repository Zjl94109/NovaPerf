package com.novaperf.sdk;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.util.Log;

/**
 * CLI 控制面。必须用显式组件调用（隐式广播会被 ColorOS 等 ROM 静默拦截）：
 *   adb shell am broadcast -n <宿主包名>/com.novaperf.sdk.NovaControlReceiver -a com.novaperf.START
 *
 * 可选 extras：
 *   --el duration_ms 30000   自动停止（0=常驻）
 *   --el interval_ms 1000    采样间隔
 *   --ez frames true         逐帧明细
 *   --es scene 战斗          场景名
 *   --es label 进入战斗      FLAG 打点文本
 *   --ez force true          START 时强制重启会话
 */
public final class NovaControlReceiver extends BroadcastReceiver {
    public static final String ACTION_START = "com.novaperf.START";
    public static final String ACTION_STOP = "com.novaperf.STOP";
    public static final String ACTION_FLAG = "com.novaperf.FLAG";
    public static final String ACTION_SCENE = "com.novaperf.SCENE";
    public static final String ACTION_STATUS = "com.novaperf.STATUS";

    @Override
    public void onReceive(Context ctx, Intent intent) {
        if (intent == null || intent.getAction() == null) return;
        NovaPerf.attach(ctx);
        String action = intent.getAction();
        try {
            if (ACTION_START.equals(action)) {
                if (intent.getBooleanExtra("force", false)) NovaPerf.stop();
                NovaPerf.start(ctx,
                        intent.getLongExtra("duration_ms", 0),
                        intent.getLongExtra("interval_ms", 1000),
                        intent.getBooleanExtra("frames", false),
                        intent.getStringExtra("scene"));
            } else if (ACTION_STOP.equals(action)) {
                NovaPerf.stop();
            } else if (ACTION_FLAG.equals(action)) {
                String label = intent.getStringExtra("label");
                NovaPerf.flag(label == null ? "flag" : label, intent.getStringExtra("detail"));
            } else if (ACTION_SCENE.equals(action)) {
                String name = intent.getStringExtra("scene");
                if (name == null) name = intent.getStringExtra("label");
                NovaPerf.scene(name == null ? "default" : name);
            } else if (ACTION_STATUS.equals(action)) {
                NovaPerf.writeStatusFile();
            }
        } catch (Throwable e) {
            Log.e(NovaPerf.TAG, "control failed: " + e);
        }
        Log.i(NovaPerf.TAG, "ACTION=" + action + " " + NovaPerf.status());
    }
}
