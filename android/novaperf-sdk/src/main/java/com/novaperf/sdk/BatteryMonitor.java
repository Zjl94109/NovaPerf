package com.novaperf.sdk;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.os.BatteryManager;
import android.os.Build;
import android.os.PowerManager;

/** 电量 / 电池温度 / 系统热状态。全部走公开 API，读不到写 null。 */
public final class BatteryMonitor {
    private final Context ctx;
    private volatile Double percent;
    private volatile Double tempC;
    private volatile String thermal = "unknown";
    private BroadcastReceiver receiver;

    public BatteryMonitor(Context ctx) {
        this.ctx = ctx.getApplicationContext();
    }

    public void start() {
        IntentFilter filter = new IntentFilter(Intent.ACTION_BATTERY_CHANGED);
        receiver = new BroadcastReceiver() {
            @Override
            public void onReceive(Context c, Intent i) {
                update(i);
            }
        };
        try {
            if (Build.VERSION.SDK_INT >= 33) {
                // Android 13+ 显式声明不导出，避免 targetSdk 34 抛 IllegalArgumentException
                ctx.registerReceiver(receiver, filter, Context.RECEIVER_NOT_EXPORTED);
            } else {
                ctx.registerReceiver(receiver, filter);
            }
        } catch (Throwable ignored) {
        }
        try {
            Intent sticky = ctx.registerReceiver(null, filter);
            if (sticky != null) update(sticky);
        } catch (Throwable ignored) {
        }
        refreshThermal();
    }

    public void stop() {
        if (receiver != null) {
            try {
                ctx.unregisterReceiver(receiver);
            } catch (Throwable ignored) {
            }
        }
        receiver = null;
    }

    public Double percent() {
        return percent;
    }

    public Double tempC() {
        return tempC;
    }

    public String thermal() {
        return thermal;
    }

    public void refreshThermal() {
        if (Build.VERSION.SDK_INT < 29) return;
        try {
            PowerManager pm = (PowerManager) ctx.getSystemService(Context.POWER_SERVICE);
            if (pm == null) return;
            switch (pm.getCurrentThermalStatus()) {
                case PowerManager.THERMAL_STATUS_NONE:
                    thermal = "nominal";
                    break;
                case PowerManager.THERMAL_STATUS_LIGHT:
                case PowerManager.THERMAL_STATUS_MODERATE:
                    thermal = "fair";
                    break;
                case PowerManager.THERMAL_STATUS_SEVERE:
                    thermal = "serious";
                    break;
                case PowerManager.THERMAL_STATUS_CRITICAL:
                case PowerManager.THERMAL_STATUS_EMERGENCY:
                case PowerManager.THERMAL_STATUS_SHUTDOWN:
                    thermal = "critical";
                    break;
                default:
                    thermal = "unknown";
            }
        } catch (Throwable ignored) {
        }
    }

    private void update(Intent i) {
        int level = i.getIntExtra(BatteryManager.EXTRA_LEVEL, -1);
        int scale = i.getIntExtra(BatteryManager.EXTRA_SCALE, -1);
        if (level >= 0 && scale > 0) percent = level * 100.0 / scale;
        int t = i.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, Integer.MIN_VALUE);
        if (t != Integer.MIN_VALUE) tempC = t / 10.0;
    }
}
