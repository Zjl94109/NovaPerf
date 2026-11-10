# NovaPerf 架构

## 与上一代（GT 3.x）的根本区别

NovaPerf 是**全新实现**，不引用、不链接、不兼容任何 GT 3.x 代码：

| 维度 | GT 3.x | NovaPerf |
|---|---|---|
| 采集拓扑 | 被测 App SDK → **AIDL/binder** → 独立「GT 控制台 App」→ 写盘 | **SDK 自采集、自落盘**，无控制台 App |
| 控制面 | 向另一个 App 发广播，组件被杀即 `DeadObjectException`，需 force-stop 重连 | 被测 App 内部广播接收器 + 本地 API，无跨进程依赖 |
| 数据格式 | `^` 分隔的私有文本 + `data.js` 静态报告 | 版本化 **JSONL 数据契约**（Android/iOS 共用） |
| native | `libyhook.so` / `libmem_fill_tool.so`（32 位、部分需 root） | **零 native、零 hook、零 root** |
| 报告 | 静态图表 | **诊断引擎驱动**的交互式报告（问题清单 + 证据 + 根因 + 定位） |
| 平台 | 仅 Android | Android + iOS 同一契约、同一报告 |
| 存储 | `/sdcard/GTR/`（含冒号文件名、Android 11+ 拒绝） | 应用私有外部目录 / iOS Documents，无需权限 |
| CI | 无 | `gate` 门禁 + `diff` 版本对比 + GitHub Actions |

## 三层

```
┌─ 采集层 ─────────────────────────────────────────────┐
│ android/novaperf-sdk   (纯 Java AAR, 免 root)          │
│ ios/Sources/NovaPerf   (Swift Package, 免越狱)         │
│   自采集 · 自落盘 · 场景打点 · 异常捕获                  │
└──────────────────────┬──────────────────────────────┘
                       │ 统一 JSONL（schema/session.schema.json）
┌──────────────────────▼──────────────────────────────┐
│ 控制 / 传输层  cli/novaperf.py                         │
│   doctor · collect · pull · report · diff · gate       │
└──────────────────────┬──────────────────────────────┘
                       │ 结构化诊断结果
┌──────────────────────▼──────────────────────────────┐
│ 诊断层  report/template.html                           │
│   健康分 · Top 问题清单 · 证据链 · 根因假设 · 排查建议   │
│   多指标联动时间轴 · 事件检索 · 基线门禁 · CSV           │
└─────────────────────────────────────────────────────┘
```

## 设计原则

1. **不依赖被测设备特权**：所有指标只用公开 API 或 `/proc/self/*`；读不到的字段写 `null`，**绝不填 0 冒充**，报告显示「不可用」。
2. **采集不打扰被测应用**：采样在单独 HandlerThread；JSONL 追加写；主线程只做极轻的帧回调与心跳。
3. **可复现、可审计**：所有指标口径写进 `docs/METRICS.md`；报告内嵌口径说明与原始数据导出。
4. **可诊断而非只可展示**：诊断引擎输出「时间窗口 + 数值证据 + 关联指标 + 根因假设 + 排查动作」，并支持一键跳转到对应时间段。
5. **平台无关的诊断逻辑**：Android/iOS 产出同一 schema，报告与门禁逻辑完全共用。

## 控制面

Android：`com.novaperf.START` / `STOP` / `FLAG` / `SCENE` 显式广播（组件导出），或应用内 `NovaPerf.start()/stop()`。
iOS：`NovaPerf.shared.start()` / `stop()`，或 `NotificationCenter`，文件通过 `UIFileSharingEnabled` / `UIDocumentPicker` 导出。

> 实测教训（ColorOS / Android 16）：**隐式广播会被系统静默拦截**，`am broadcast -a ...` 返回 `result=0` 但接收器不执行。CLI 一律使用显式组件 `-n <pkg>/.NovaControlReceiver`。

## 目录

| 路径 | 内容 |
|---|---|
| `android/novaperf-sdk/` | Android 采集 SDK（library） |
| `android/demo/` | 负载制造 Demo（application） |
| `ios/` | Swift Package + 单元测试 + 示例 |
| `cli/novaperf.py` | 控制 / 拉取 / 诊断 / 门禁 |
| `report/template.html` | 单文件离线诊断报告模板 |
| `schema/` | JSONL 数据契约（JSON Schema） |
| `docs/` | 架构、契约、口径、排查手册 |
| `.github/workflows/` | Android 构建 + iOS(macOS) 编译 CI |
| `dist/` | 发版产物与真机验证报告 |
