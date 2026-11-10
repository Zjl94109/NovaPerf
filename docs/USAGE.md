# 使用手册

## 1. 环境

| 组件 | 要求 | 备注 |
|---|---|---|
| JDK | 17+ | AGP 8.2 需要 |
| Android SDK | platform 36 + build-tools | `ANDROID_HOME` 或 `android/local.properties` 的 `sdk.dir` |
| adb | platform-tools | `doctor` 会自动探测 `%LOCALAPPDATA%\Android\Sdk\platform-tools` |
| Python | 3.9+ | CLI 只用标准库，无需 pip install |
| 设备 | Android 6.0+（minSdk 23） | 免 ROOT；已在 Android 16 / ColorOS 验证 |
| Xcode（可选） | 15+ / macOS 14 | 仅 iOS 端构建与测试需要 |

```bash
python cli/novaperf.py doctor
```

## 2. 构建与出包

Windows：

```bat
scripts\build.bat
```

Linux / macOS / CI：

```bash
cd android
chmod +x gradlew
./gradlew :novaperf-sdk:assembleRelease :demo:assembleDebug --console=plain
```

产物：`android/novaperf-sdk/build/outputs/aar/novaperf-sdk-release.aar`、`android/demo/build/outputs/apk/debug/demo-debug.apk`，`scripts/build.bat` 会复制到 `dist/`。

> 若离线构建报 `No cached version available for offline mode`，去掉 `--offline` 让 Gradle 解析一次依赖（本机首次构建即如此），之后可离线。

## 3. 接入 Android App

1. 把 `NovaPerf-SDK.aar` 加入 `app/libs/`，在 `build.gradle` 添加 `implementation(files("libs/NovaPerf-SDK.aar"))`；或直接 `implementation(project(":novaperf-sdk"))`。
2. SDK 的 `AndroidManifest.xml` 会合并进宿主 App，`NovaControlReceiver` 自动注册，**无需手写 receiver**。
3. 需要网络负载时宿主 App 自己加 `INTERNET` 权限；SDK 本身不申请任何权限。
4. 初始化：

```java
public class MyApp extends Application {
    public void onCreate() {
        super.onCreate();
        NovaPerf.attach(this);
        NovaPerf.start(this, 0, 1000, false, "launch");
    }
}
```

| API | 作用 |
|---|---|
| `NovaPerf.attach(ctx)` | 注册页面生命周期监听、崩溃捕获（幂等） |
| `NovaPerf.start(ctx, durationMs, intervalMs, frameDetail, scene)` | 开启会话；`durationMs=0` 常驻，`frameDetail=true` 写逐帧明细 |
| `NovaPerf.stop()` | 写 `summary`、关闭文件（幂等） |
| `NovaPerf.flag(label, detail)` | 场景打点（event/scene） |
| `NovaPerf.scene(name)` / `page(name)` | 切换场景 / 指定页面 |
| `NovaPerf.noteHttp(url, durationMs, statusCode, error)` | 网络埋点，产出 `net_req` / `net_err` / http 事件 |
| `NovaPerf.log(level, msg)` | 应用日志进报告 |
| `NovaPerf.status()` / `writeStatusFile()` | 状态查询与 `status.json` |

## 4. 广播控制面（CLI 使用）

**必须用显式组件**；ColorOS / Android 16 上隐式广播会被静默拦截（`result=0` 但 receiver 不执行）。

```bash
adb shell am broadcast -n <宿主包名>/com.novaperf.sdk.NovaControlReceiver \
  -a com.novaperf.START --ez force true --el duration_ms 30000 --el interval_ms 1000 \
  --ez frames true --es scene battle
```

| action | extras | 说明 |
|---|---|---|
| `com.novaperf.START` | `force`(bool)、`duration_ms`(long)、`interval_ms`(long)、`frames`(bool)、`scene`(string) | 开新会话；`force=true` 先停旧会话 |
| `com.novaperf.STOP` | — | 结束并落盘 |
| `com.novaperf.FLAG` | `label`、`detail`(string) | 打点 |
| `com.novaperf.SCENE` | `scene` 或 `label`(string) | 切场景 |
| `com.novaperf.STATUS` | — | 写 `status.json` 供 CLI 读取 |

Demo 的自动化负载（只用于验证，业务 App 不需要）：

```bash
adb shell am broadcast -n com.novaperf.demo/com.novaperf.demo.DemoControlReceiver -a com.novaperf.demo.CPU --ei seconds 6
adb shell am broadcast -n com.novaperf.demo/com.novaperf.demo.DemoControlReceiver -a com.novaperf.demo.MEM --ei mb 60
adb shell am broadcast -n com.novaperf.demo/com.novaperf.demo.DemoControlReceiver -a com.novaperf.demo.NET --ei count 20
adb shell am broadcast -n com.novaperf.demo/com.novaperf.demo.DemoControlReceiver -a com.novaperf.demo.JANK --ei ms 350
adb shell am broadcast -n com.novaperf.demo/com.novaperf.demo.DemoControlReceiver -a com.novaperf.demo.FREE
```

## 5. CLI 命令

| 命令 | 作用 |
|---|---|
| `doctor` | 探测 adb / 设备 / 产物 / 模板 |
| `validate FILE` | 校验 JSONL 契约（版本、时间戳单调、无 NaN、meta/sample/summary） |
| `collect` | 一键：force-stop → 启动 → START → 负载脚本 → STOP → pull → validate → report |
| `pull --pkg X --out F` | 拉取设备 `status.json` 指向的最新会话 |
| `report FILE -o OUT --baseline B --rules R --title T` | 生成单文件离线报告 |
| `diff BASE CURRENT --out HTML` | 基线对比（KPI 变化 + 健康分） |
| `gate FILE --rules R` | CI 门禁，失败返回 1 |
| `summary FILE` | 输出诊断 JSON 供流水线消费 |

`collect` 常用参数：

```
--device c30d87e5     指定设备（默认自动挑真机，跳过 emulator）
--pkg com.xxx.app     宿主包名
--activity            启动 Activity（默认 Demo）
--duration 25         会话秒数
--interval 1000       采样间隔 ms
--frames              开启逐帧明细（可算精确 1% Low / P99）
--scenario full|none  是否自动制造 CPU/内存/网络/卡顿负载
--out examples/x.jsonl
--report-out dist/x.html
```

## 6. 报告导航

| 区块 | 用途 |
|---|---|
| 指标总览 | 14 张 KPI 卡、指标覆盖率、场景分段 |
| 诊断摘要 | 问题清单（规则 / 证据 / 关联 / 根因 / 排查动作 / 定位按钮） |
| 联动时间轴 | 9 条曲线共享时间轴，悬停看全指标；框选放大；场景带与事件虚线 |
| 事件检索 | 类型 / 级别 / 全文过滤，崩溃与 ANR 堆栈，点击定位 |
| 原始采样 | 逐行原始 JSONL 表格，CSV 全量导出 |
| 基线 / 门禁 | 版本对比 + PASS/FAIL 及失败原因 |
| 指标口径 | 内嵌公式与来源，含源文件 SHA256 |

## 7. CI

```yaml
- run: python cli/novaperf.py validate session.jsonl
- run: python cli/novaperf.py gate session.jsonl     # 失败即阻断发布
```

阈值覆盖：把 `RULES` 中需要改的键写成 JSON 文件，用 `--rules rules.json` 传给 `report` 与 `gate`（两者必须一致）。
