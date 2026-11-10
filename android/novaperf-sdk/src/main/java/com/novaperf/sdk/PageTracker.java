package com.novaperf.sdk;

import android.app.Activity;
import android.app.Application;
import android.os.Bundle;

/** 自动记录当前页面（无需宿主 App 手工上报）。 */
public final class PageTracker implements Application.ActivityLifecycleCallbacks {
    @Override
    public void onActivityCreated(Activity a, Bundle b) {
    }

    @Override
    public void onActivityStarted(Activity a) {
    }

    @Override
    public void onActivityResumed(Activity a) {
        String name = a.getClass().getSimpleName();
        NovaPerf.page(name);
        NovaPerf.lifecycle("resume:" + name);
    }

    @Override
    public void onActivityPaused(Activity a) {
    }

    @Override
    public void onActivityStopped(Activity a) {
    }

    @Override
    public void onActivitySaveInstanceState(Activity a, Bundle b) {
    }

    @Override
    public void onActivityDestroyed(Activity a) {
    }
}
