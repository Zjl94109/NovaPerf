# NovaPerf

**开源 · 免 ROOT / 免越狱 · Android + iOS 双端共用 · 诊断型性能报告**

NovaPerf 是**从零实现**的现代化性能测试框架：被测 App 内的 SDK 自采集、自落盘，产出统一 JSONL 数据契约，由 CLI 诊断引擎生成单文件离线交互报告。

> **与上一代彻底切割**：不引用、不链接、不兼容任何 GT 3.x / GT v3.2.0 / PerfLab 的代码、包名、AIDL 协议或 `^` 分隔数据格式。没有控制台 App、没有跨进程 binder、没有 native hook、没有 32 位 so、不需要 root 或越狱。设计对比见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

---

## 为什么需要换代

上一代（GT 3.1）在 Android 11+ / Android 16 上的结构性问题，不是打补丁能解决的：

| 问题 | 后果 | NovaPerf |
|---|---|---|
| 数据目录名含冒号 `HH:mm:ss` | MediaProvider 拒绝写盘，跑完没数据 | 应用私有外部目录 + `yyyyMMdd_HHmmss_SSS`，无需存储权限 |
| SDK → AIDL/binder → 控制台 App | 控制台被杀即 `DeadObjectException`，需 force-stop 重连 | SDK 自己采集自己写，零跨进程依赖 |
| 读全局 `/proc/stat` | Android 11+ SELinux `EACCES`，整条采样链中断 | 只读 `/proc/self/*` + 官方 API（Debug/TrafficStats） |
| 32 位 native so / 部分插件需 root | ColorOS 弹「兼容性不足」、无 root 无法用 | 纯 Java / 纯 Swift，零 native |
| `data.js` 静态图表 | 只能看曲线，不能定位问题 | 诊断引擎：问题清单 + 证据 + 根因假设 + 排查动作 |
| 仅 Android | iOS 无方案 | 双端同一 JSONL 契约、同一报告、同一门禁 |

---

## 30 秒上手（Windows + 真机）

前提：JDK 17+、Android SDK platform-tools（adb）、Python 3.9+、一台开了 USB 调试的 Android 真机。

```bat
:: 1. 构建 SDK AAR 和 Demo APK（产物自动复制到 dist\）
scripts\build.bat

:: 2. 带权限安装（ColorOS 首次会弹「继续安装」，点一下即可）
adb install -g -r dist\NovaPerf-Demo.apk

:: 3. 一条命令跑完全流程：启动 → 制造负载 → 打点 → 停止 → 拉取 → 出报告
python cli\novaperf.py collect --duration 25 --frames --scenario full

:: 生成 dist\NovaPerf-Report.html，双击打开即可（单文件、离线、无 CDN）
```

**接入自己的 App**（Android Studio）：把 `dist/NovaPerf-SDK.aar` 放进 `app/libs/`，或引用 `android/novaperf-sdk` 模块：

```java
// Application.onCreate
NovaPerf.attach(this);
NovaPerf.start(this, 0, 1000, false, "launch");   // durationMs, intervalMs, frameDetail, scene

// 业务打点
NovaPerf.flag("进入战斗");
NovaPerf.scene("battle");
NovaPerf.noteHttp(url, costMs, statusCode, false); // OkHttp 拦截器里调用

// 结束
NovaPerf.stop();
```

SDK 的控制接收器已随 AAR manifest 合并，CLI 用**显式组件广播**驱动（隐式广播会被部分 ROM 静默拦截）：

```bat
adb shell am broadcast -n <你的包名>/com.novaperf.sdk.NovaControlReceiver -a com.novaperf.START --ez force true --el duration_ms 30000
adb shell am broadcast -n <你的包名>/com.novaperf.sdk.NovaControlReceiver -a com.novaperf.FLAG --es label "进入战斗"
adb shell am broadcast -n <你的包名>/com.novaperf.sdk.NovaControlReceiver -a com.novaperf.STOP
```

会话文件位于 `/sdcard/Android/data/<包名>/files/novaperf/session_*.jsonl`（无需存储权限）。

---

## 报告：能查问题，不只是能看图

`report/template.html` + `cli/novaperf.py` 的输出包含：

- **健康分**与 Top 问题清单：每项含 `时间窗口 / 触发规则（可复核）/ 实测数值 / 关联指标 / 根因假设 / 排查动作 / 一键定位`
- **多指标联动时间轴**：9 条曲线共享时间轴，悬停显示同一时刻全部指标；场景分段带、事件打点虚线、问题窗口框选放大
- **指标覆盖率**：每个字段的有效采样数与覆盖率；`null` 显示「不可用」而非 0
- **事件检索**：按类型/级别/全文过滤，含 HTTP、崩溃堆栈、疑似 ANR 主线程堆栈，点击跳转时间轴
- **原始采样表格 + CSV 导出**：所有数字可回溯到设备原始文件（含 SHA256 前 16 位）
- **基线对比 / CI 门禁**：`report` 与 `gate` 共用同一套 `RULES` 阈值，保证「看到的」和「流水线卡掉的」一致
- **指标口径说明**：每个数字的公式与数据来源内嵌在报告里

报告默认浅色，右上角可切深色；无 CDN、无外部字体、可离线打开、可打印。

```bash
python cli/novaperf.py doctor                         # 环境自检
python cli/novaperf.py validate <session.jsonl>       # 契约校验
python cli/novaperf.py collect --frames               # 真机一键采集
python cli/novaperf.py report <session.jsonl> --baseline <baseline.jsonl> -o report.html
python cli/novaperf.py diff <baseline.jsonl> <current.jsonl>
python cli/novaperf.py gate <session.jsonl>           # CI 门禁，失败返回 1
python cli/novaperf.py summary <session.jsonl>        # 输出 JSON 供流水线消费
```

---

## 指标覆盖（免特权可得的全部指标）

| 类别 | 字段 |
|---|---|
| 帧 / 流畅度 | `fps`、`frame_ms`、`frame_p95_ms`、`jank`、`big_jank`、`frozen`、逐帧 `frame.dt_ms`、1% Low / 5% Low / P95 / P99 |
| CPU | `cpu_app_pct`、`threads`、`fds`（Android） |
| 内存 | `pss_kb`、`heap_kb`、`native_kb`、`gc_count` |
| 网络 | `net_tx_bps`、`net_rx_bps`、`net_req`、`net_err` |
| IO | `io_read_bps`、`io_write_bps` |
| 设备 | `battery_pct`、`temp_c`、`thermal_state` |
| 稳定性 | `main_thread_busy_ms`、`anr_risk`、`crash`、`cold_start`、`lifecycle`、`scene`/`page` 打点 |

**精度硬约束**：算不准就写 `null`，绝不填 0 冒充。免特权设备明确不可得并写 `null` 的字段：
`cpu_sys_pct`（全局 CPU）、`gpu_pct`（per-App GPU）、iOS 的 `net_*_bps`/`io_*`/`temp_c`/`fds`/`heap_kb`。
未开启逐帧明细时，1% Low 不参与统计（不会用窗口聚合值冒充精确值）；帧预算按**实测渲染节奏**计算，避免 120Hz 屏把正常 60fps 误判成超预算。完整口径见 [docs/METRICS.md](docs/METRICS.md)。

---

## 真机验证结果（OnePlus PJT110 / Android 16 / 免 ROOT）

仓库 `examples/` 内含两份真实会话，`dist/NovaPerf-Report.html` 是由逐帧会话生成的最终报告。

| 项目 | 实测 |
|---|---|
| 编译 | Gradle 8.4 / AGP 8.2 / compileSdk 36，`SDK AAR 35KB` + `Demo APK 56KB`，0 错误 |
| 采集 | 24–47 个采样窗口、1474 帧逐帧明细、36–38 个事件，无崩溃、无权限错误 |
| CPU | 1.5% → 29.6%（忙循环负载），回落正常 |
| PSS | 24 → 95 MB（+60MB 分配），释放打点后回落 |
| 网络 | 20 个 HTTPS 200 请求，TX/RX 速率随请求变化 |
| 帧 | AvgFPS 58–59、1% Low 24.84（逐帧精确）、P95 16.84ms、Jank 可复现 |
| 主线程 | 350ms 阻塞被 watchdog 记录（194–280ms 心跳延迟） |
| 控制面 | 显式广播 START / STOP / FLAG / SCENE / STATUS 全部生效 |
| 报告 | 健康分 92、门禁 PASS、无头浏览器渲染验证通过 |
| iOS | Swift Package + macOS CI 编译/单测配置；**本机为 Windows，未做 iOS 真机验证** |

---

## iOS

见 [ios/README.md](ios/README.md)：Swift Package、`CADisplayLink` 帧、`task_info` CPU / phys_footprint、`ProcessInfo.thermalState`、`URLSessionTaskMetrics` 网络埋点、`UIFileSharingEnabled` 导出。所有 UIKit 依赖用 `#if os(iOS)` 隔离，macOS CI 上可 `swift build` / `swift test` / `xcodebuild -destination iOS Simulator`。

> **如实说明**：当前开发环境是 Windows，没有 Xcode / macOS / iOS 真机，iOS 端只做到「可在 macOS 编译 + 单元测试 + CI 配置」，未做真机验证。这是本版本唯一未实机验证的部分。

---

## 目录

```
android/novaperf-sdk/   纯 Java AAR（免 ROOT、零 native、零第三方依赖）
android/demo/           负载制造 Demo（UI 按钮 + 广播双通道）
ios/                    Swift Package + 单元测试 + 接入文档
cli/novaperf.py         控制 / 拉取 / 诊断 / 门禁 / 报告（仅标准库）
report/template.html    单文件离线诊断报告模板
schema/                 JSONL 数据契约（JSON Schema v1）
docs/                   架构 / 契约 / 指标口径 / 使用手册 / 诊断规则 / 排查手册
examples/               两份真机会话（含逐帧明细）
dist/                   发版产物：AAR、APK、最终报告、报告截图
.github/workflows/      Android 构建、iOS(macOS) 构建与测试、CLI 门禁
scripts/                Windows 一键构建
```

---

## 开源与版本

- License：**MIT**（[LICENSE](LICENSE)），永久免费、可商用、可修改。
- 当前版本：**v1.0.0**（[CHANGELOG.md](CHANGELOG.md)）。
- 贡献方式见 [CONTRIBUTING.md](CONTRIBUTING.md)；数据契约变更必须同步 `schema/`、`docs/`、SDK 与 CLI。
