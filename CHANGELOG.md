# Changelog

## v1.0.1 — 2026-11-10

发布工程性修复。**SDK / CLI / 诊断引擎 / 报告功能与 v1.0.0 完全一致**，Android 源码未改动，`NovaPerf-SDK.aar` 与 `NovaPerf-Demo.apk` 沿用 v1.0.0 已真机验证的产物（未重编译）。

### 修复
- `android.yml`：移除在本账号 runner 上崩溃的 `setup-android@v3`（`Failed to find package 'tools'`），改用 runner 自带 Android SDK + `sdkmanager` 补装 platform 36 / build-tools。
- `ios.yml`：GitHub 判 `macos-14-arm64-us-default is not supported` 直接取消工作流；改为「每次提交自动跑 Linux Swift 语法校验 + 完整 macOS 构建手动触发」，避免仓库里常驻一个永远排队的作业。
- `ios.yml`：`setup-swift@v2` 下载 Swift 5.9 工具链返回 404，改用官方 `swift:5.9` 容器。
- **iOS 验证强度升级**：Linux CI 从「只做 `swiftc -parse` 语法校验」提升为 `swift build` + `swift test` 真实编译并执行单元测试。为此把 `Darwin` 专属能力用条件编译隔离：`NSUncaughtExceptionHandler`（崩溃捕获）、`ProcessInfo.thermalState`（热状态）；Linux 上热状态诚实返回 `unknown`、不注册崩溃钩子。共享核心（JSONL 契约、SessionWriter、采样调度、null 语义）在 Linux 上被真实编译执行，但 **UIKit / CADisplayLink / Mach 分支仍只能在 macOS / iOS 验证**。
- 补 Unix `android/gradlew`（`100755` + LF，`.gitattributes` 约束），Linux CI 可直接执行 Gradle wrapper。

### 文档 / 产物
- README、CHANGELOG、`ios/README.md` 如实标注 iOS 未真机验证与 macOS runner 限制，SPM 接入示例改用真实仓库地址。
- `dist/NovaPerf-Report.html` / `report_preview.png` 刷新为逐帧精确版（1% Low 24.84、5% Low 46.32、基线对比、门禁 PASS、健康分 92）。

### 发版资产（v1.0.1）
| 文件 | 说明 |
| --- | --- |
| `NovaPerf-SDK.aar` | Android SDK（纯 Java，minSdk 23，零依赖） |
| `NovaPerf-Demo.apk` | 被测 Demo（可直接安装复现负载） |
| `NovaPerf-Report.html` | 单文件离线诊断报告（真机数据） |
| `report_preview.png` | 报告渲染截图 |

### CI（最终提交）
- Android SDK & Demo：**success**（AAR / APK 构建 + 产物上传）
- CLI, Diagnostics & Gate：**success**（契约校验 / 报告 / 门禁）
- iOS Swift Package：`swift-syntax` **success**；`macos-build` 手动触发（未执行，已在文档标注）

## v1.0.0 — 2026-11-10

首个完全换代版本。**不依赖任何 GT 3.x / GT v3.2.0 / PerfLab 代码**，从零实现。

### 新增
- **Android SDK（纯 Java AAR，minSdk 23 / compileSdk 36）**：Choreographer 帧、`/proc/self/*` CPU/IO/线程/FD、`Debug.getMemoryInfo` PSS、`TrafficStats` 网络、BatteryManager 电量温度、主线程 ANR watchdog、崩溃捕获、页面生命周期、场景打点、JSONL append 落盘、显式广播控制面。零 native、零第三方库、零权限申请、免 ROOT。
- **iOS Swift Package**：CADisplayLink 帧、`task_info` CPU / phys_footprint、`ProcessInfo.thermalState`、`UIDevice` 电量、`URLSessionTaskMetrics` 埋点、NSException 崩溃捕获，输出同一 JSONL 契约；UIKit 依赖条件编译，macOS CI 可编译与单测。
- **CLI（仅 Python 标准库）**：`doctor / validate / collect / pull / report / diff / gate / summary`。
- **诊断型单文件离线报告**：健康分、Top 问题证据链（规则/数值/关联/根因/排查动作/定位）、9 条联动时间轴、场景带与事件打点、指标覆盖率、事件检索与堆栈、原始采样表与 CSV、基线对比、CI 门禁、指标口径与源文件 SHA256。浅/深主题，无 CDN。
- **统一数据契约 v1**：`schema/session.schema.json`、`docs/DATA_SCHEMA.md`、`docs/METRICS.md`，Android/iOS 同构，不可用写 `null`。
- **Demo App**：CPU/内存/网络/卡顿负载，UI 按钮 + 广播双通道，供 CLI 全自动回归。
- **CI**：Android 构建、iOS(macOS) 构建与单测、CLI 契约校验/报告/门禁。
- **开源交付**：MIT LICENSE、README、使用手册、诊断规则、排查手册、贡献指南、Windows 一键脚本。

### 真机验证（OnePlus PJT110 / Android 16 / 免 ROOT）
- 编译 0 错误；AAR 35KB / Demo APK 56KB。
- 两次真机会话：47 采样 / 38 事件；24 采样 / 36 事件 / 1474 逐帧。
- CPU 1.5→29.6%、PSS 24→95MB、20 个 HTTPS 200 请求、350ms 主线程阻塞被 watchdog 记录、AvgFPS 58–59、1%Low 24.84（逐帧精确）、P95 16.84ms。
- 显式广播 START/STOP/FLAG/SCENE/STATUS 全部生效；无崩溃、无权限错误。
- 报告健康分 92、门禁 PASS，无头浏览器渲染验证通过。

### 已知限制
- 免特权设备无可靠的全局 CPU / per-App GPU 接口，`cpu_sys_pct` / `gpu_pct` 恒 `null`。
- iOS 无系统级按 App 流量与 IO 统计，相关字段为 `null`；需业务层接 `URLSessionTaskMetrics` 才有 `net_req/net_err`。
- 本机为 Windows，**iOS 端未做真机验证 / macOS 编译验证**；CI 每次提交自动跑 Linux Swift 语法校验（`swiftc -parse`），完整 `swift build`/`swift test`/iOS Simulator 构建保留为手动触发的 macOS 作业（本账号 macOS runner 存在配置限制与排队）。
- 未开启逐帧明细时不输出精确 1% Low（不估算冒充）。
