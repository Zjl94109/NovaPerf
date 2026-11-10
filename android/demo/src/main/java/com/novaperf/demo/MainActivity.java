package com.novaperf.demo;

import android.app.Activity;
import android.graphics.Color;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import com.novaperf.sdk.NovaPerf;

/** 手动负载面板；CLI 自动化走 DemoControlReceiver，两者共用 Loads。 */
public final class MainActivity extends Activity {
    private final Handler ui = new Handler(Looper.getMainLooper());
    private TextView status;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(28, 40, 28, 28);

        TextView title = new TextView(this);
        title.setText("NovaPerf Demo · 负载制造器");
        title.setTextSize(21);
        title.setTextColor(Color.rgb(20, 24, 32));
        root.addView(title);

        status = new TextView(this);
        status.setTextSize(13);
        status.setTextColor(Color.rgb(90, 100, 115));
        status.setPadding(0, 12, 0, 24);
        root.addView(status);

        add(root, "CPU 负载 8 秒", new Runnable() {
            public void run() { Loads.cpu(8); }
        });
        add(root, "分配 60MB 内存", new Runnable() {
            public void run() { Loads.mem(60); }
        });
        add(root, "释放内存 + GC", new Runnable() {
            public void run() { Loads.free(); }
        });
        add(root, "网络请求 x20", new Runnable() {
            public void run() { Loads.net(20); }
        });
        add(root, "主线程卡顿 350ms", new Runnable() {
            public void run() { Loads.jank(350); }
        });
        add(root, "场景：进入战斗", new Runnable() {
            public void run() { Loads.scene("battle"); }
        });
        add(root, "场景：回到 idle", new Runnable() {
            public void run() { Loads.scene("idle"); }
        });
        add(root, "停止采集并落盘", new Runnable() {
            public void run() { NovaPerf.stop(); }
        });
        add(root, "重启采集会话", new Runnable() {
            public void run() { NovaPerf.start(getApplicationContext(), 0, 1000, false, "demo"); }
        });

        ScrollView sv = new ScrollView(this);
        sv.addView(root);
        setContentView(sv);
        refresh();
    }

    private void add(LinearLayout root, String text, final Runnable action) {
        Button b = new Button(this);
        b.setText(text);
        b.setAllCaps(false);
        b.setGravity(Gravity.START | Gravity.CENTER_VERTICAL);
        b.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                action.run();
                toast("已触发：" + ((Button) v).getText());
            }
        });
        root.addView(b);
    }

    private void refresh() {
        status.setText(NovaPerf.status());
        ui.postDelayed(new Runnable() {
            public void run() { refresh(); }
        }, 2000);
    }

    private void toast(String s) {
        Toast.makeText(this, s, Toast.LENGTH_SHORT).show();
    }
}
