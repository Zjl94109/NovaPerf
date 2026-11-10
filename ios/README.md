# NovaPerf iOS SDK

免越狱、零第三方依赖、无私有 API 的 Swift Package。输出与 Android **完全相同**的 JSONL 数据契约（`docs/DATA_SCHEMA.md`），因此 CLI 诊断引擎和报告可直接使用 iOS 会话文件。

> 本机为 Windows（无 Xcode / macOS），iOS 端**未在真机验证**。CI 每次提交自动跑 Linux Swift 语法校验（`swiftc -parse`）；完整 `swift build` / `swift test` / `xcodebuild -destination iOS Simulator` 作业因账号 macOS runner 配置限制（`macos-14-arm64-us-default is not supported`，`macos-13` 排队）改为**手动触发**（Actions → iOS Swift Package → Run workflow）。代码中所有 UIKit 依赖都用 `#if os(iOS)` 隔离。

## 集成（Swift Package Manager）

Xcode → File → Add Package Dependencies → 填入本仓库路径，选择 `NovaPerf` library；或 `Package.swift`：

```swift
dependencies: [.package(url: "https://github.com/Zjl94109/NovaPerf.git", from: "1.0.1")]
targets: [.target(name: "YourApp", dependencies: ["NovaPerf"])]
```

`Info.plist` 增加（用于从 Finder / iTunes 文件共享导出会话）：

```xml
<key>UIFileSharingEnabled</key><true/>
<key>LSSupportsOpeningDocumentsInPlace</key><true/>
```

## 代码接入

```swift
import NovaPerf

// AppDelegate / SceneDelegate
NovaPerf.shared.start(intervalMs: 1000, frameDetail: true)
NovaPerf.shared.setPage("BattleViewController")

// 场景打点
NovaPerf.shared.setScene("battle")
NovaPerf.shared.flag("进入战斗")

// URLSessionTaskMetrics（网络请求数 / 错误数 / 耗时）
func urlSession(_ session: URLSession, task: URLSessionTask,
                didFinishCollecting metrics: URLSessionTaskMetrics) {
    let duration = metrics.taskInterval.duration * 1000
    let code = (task.response as? HTTPURLResponse)?.statusCode ?? -1
    NovaPerf.shared.noteHTTP(url: task.originalRequest?.url?.absoluteString ?? "",
                             durationMs: duration, statusCode: code,
                             error: task.error != nil || code >= 400)
}

// 结束（App 进入后台或测试结束时）
NovaPerf.shared.stop()
print(NovaPerf.shared.sessionFiles())   // Documents/novaperf/session_*.jsonl
```

## 指标来源与已知限制

| 指标 | iOS 来源 | 说明 |
|---|---|---|
| FPS / 帧间隔 / Jank | `CADisplayLink` 时间戳差分 | 口径与 Android `Choreographer` 一致 |
| `cpu_app_pct` | `task_info(TASK_BASIC_INFO)` 的 user_time + system_time 差分 | 归一化到单核 0–100% |
| `pss_kb` | `task_info(TASK_VM_INFO).phys_footprint` | 与 Xcode Memory Gauge 同源 |
| `threads` | `task_threads` | |
| `battery_pct` | `UIDevice.batteryLevel` | 模拟器返回 `null` |
| `thermal_state` | `ProcessInfo.thermalState` | nominal/fair/serious/critical |
| `net_req` / `net_err` | `noteHTTP()` / `URLSessionTaskMetrics` | 需业务层接入 |
| `net_tx_bps` / `net_rx_bps` | **不可得** | iOS 无系统级按 App 流量统计，契约写 `null` |
| `cpu_sys_pct` / `gpu_pct` / `temp_c` / `io_*` / `fds` / `heap_kb` | **不可得** | 一律 `null`，报告显示「不可用」而非 0 |
| 崩溃 | `NSSetUncaughtExceptionHandler` | 捕获 ObjC/Swift NSException；Mach 信号类崩溃建议接 MetricKit |

**不伪造数据**是硬约束：`docs/METRICS.md` 中未定义可靠来源的字段恒为 `null`。

## CLI 使用（无需 Mac）

iOS 会话文件导出到 PC 后，与 Android 完全相同的命令：

```bash
python cli/novaperf.py validate session_ios.jsonl
python cli/novaperf.py report session_ios.jsonl -o report.html
python cli/novaperf.py gate session_ios.jsonl
```

## 本地验证（macOS）

```bash
cd ios
swift build -c release
swift test
xcodebuild -scheme NovaPerf -destination 'generic/platform=iOS Simulator' \
  -sdk iphonesimulator -configuration Release build CODE_SIGNING_ALLOWED=NO
```
