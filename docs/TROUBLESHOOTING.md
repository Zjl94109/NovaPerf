# 排查手册（真机 / 构建 / 报告）

以下均为本项目在 OnePlus PJT110 / Android 16 / Windows 上实测踩过的坑。

## A. 设备与安装

| 现象 | 原因 | 处理 |
|---|---|---|
| `adb install` 卡住不动 | ColorOS 弹「继续安装」确认框 | 后台执行 install，同时 `uiautomator dump /sdcard/window.xml` 找「继续安装」坐标，`input tap x y` |
| `pm grant` / `appops set` 报 SecurityException | ROM 限制 adb 授权 | 用 `adb install -g` 带权限安装；NovaPerf 不依赖任何危险权限 |
| 隐式广播 `result=0` 但没反应 | ColorOS / Android 16 静默拦截隐式广播 | 一律 `-n <pkg>/com.novaperf.sdk.NovaControlReceiver` 显式组件 |
| SDK 控制台断连、`DeadObjectException` | 上一代 GT 的跨进程 binder 问题 | NovaPerf 没有控制台 App、没有 binder；如遇旧环境问题请 force-stop 旧 App |
| `adb pull /sdcard/...` 路径被改写 | Git Bash MSYS 路径转换 | `MSYS_NO_PATHCONV=1` + 本地路径写 `D:/...`；CLI 用 Python 直接调 adb，不受影响 |

## B. 没有数据 / 字段为 null

| 现象 | 检查 |
|---|---|
| 设备上找不到 session 文件 | `adb shell cat /sdcard/Android/data/<pkg>/files/novaperf/status.json` 看 `running` 与 `session_path`；确认宿主 App 调用了 `NovaPerf.attach/start`，或发送过 START 广播 |
| 有 meta 没有 sample | 采样 HandlerThread 未启动 / App 被立即 force-stop；看 `adb logcat -s NovaPerf` 是否有 `START` 与 `sample failed` |
| `fps` 为 null | 该窗口没有有效帧（切后台、界面静止）；契约规定「无帧写 null」而不是 0 |
| `cpu_sys_pct` / `gpu_pct` 恒 null | 设计如此：免特权设备没有可靠的全局 CPU / per-App GPU 接口，**不伪造** |
| `net_*_bps` 为 null | 部分 ROM 的 `TrafficStats.getUidTxBytes` 返回 `UNSUPPORTED(-1)`；iOS 无系统级按 App 流量统计 |
| 1% Low 显示「—」 | 未开启逐帧明细；START 时加 `--ez frames true`，或 `collect --frames` |
| 会话文件被覆盖 | 旧版本用秒级文件名；v1.0.0 起会话 ID 带毫秒 `yyyyMMdd_HHmmss_SSS`，且无冒号，兼容 Android 11+ 分区存储 |

## C. 构建

| 现象 | 处理 |
|---|---|
| `Cannot create service ... journal-1.lock (拒绝访问)` | 旧 Gradle 守护进程占用缓存锁；`gradlew.bat --stop` 后把 `GRADLE_USER_HOME/caches/journal-1/journal-1.lock` 重命名让 Gradle 重建（本机实测有效） |
| `No cached version available for offline mode` | 去掉 `--offline` 在线解析一次依赖（AGP 的 `protobuf-java-util` 首次需下载），之后可离线 |
| `SDK location not found` | `ANDROID_HOME` 环境变量指错；在 `android/local.properties` 写 `sdk.dir=C\:\\Users\\<你>\\AppData\\Local\\Android\\Sdk`（此文件已在 `.gitignore`，不入库） |
| `JdkImageTransform` / jlink 失败 | Java 17 sourceCompatibility + AGP 8.2 + compileSdk 36 的组合；本项目固定 Java 8 兼容性规避 |
| `switch/case R.id.xxx 需要常量表达式` | AGP 8 默认 non-final R；`android.nonFinalResIds=false`（本项目未用 switch 资源 ID） |
| `android:exported` 报错 | Android 12+ 强制声明；用 XML 解析器改 manifest，别用正则（会破坏自闭合标签） |
| `setAppCacheEnabled` 找不到 | API 33 已删除；本项目未使用该 API |
| Linux CI 报 `gradlew: Permission denied` | `chmod +x android/gradlew`；CI workflow 已包含 |

## D. 报告与门禁

| 现象 | 处理 |
|---|---|
| 报告打开是空白 | 检查浏览器控制台；`python cli/novaperf.py report ...` 是否成功、模板占位符 `__NOVAPERF_DATA__` 是否被替换 |
| 门禁 FAIL 但曲线看着正常 | `python cli/novaperf.py summary session.jsonl` 看每条问题的 `rule` 与 `evidence`；规则与阈值见 `docs/DIAGNOSIS_RULES.md` |
| 报告说没问题、CI 却挂了 | 两边必须用**同一份** `--rules`；不要只给 gate 传阈值 |
| 帧耗时全部被判「超预算」 | 确认 `refresh_declared` 与 `refresh_effective`；诊断引擎按实测帧节奏算预算，若被改回声明值会误报 |
| 想复现报告数字 | 报告底部有源文件 SHA256 前 16 位；用 `examples/` 里的原始 JSONL 重跑 `report` 即可 |

## E. iOS

| 现象 | 处理 |
|---|---|
| `swift build` 在 macOS 失败 | 确认 Xcode 15+ / Swift 5.9；UIKit 依赖已用 `#if os(iOS)` 隔离 |
| `noteHTTP` 没有数据 | 需在 `URLSessionTaskDelegate` 的 `didFinishCollecting metrics` 中主动调用，iOS 没有系统级流量统计 |
| 模拟器没有电量 | `UIDevice.batteryLevel` 在模拟器返回 -1，契约写 `null` |
| 崩溃堆栈不完整 | 仅捕获 `NSException`；Mach 信号类崩溃请接 MetricKit / 崩溃上报 SDK |
| 会话文件导出 | `Info.plist` 开 `UIFileSharingEnabled`，从 Finder / iTunes 文件共享取 `Documents/novaperf/` |
