# 贡献指南

欢迎 Issue / PR。项目坚持三条底线：

1. **不引入上一代依赖**：不得引用 GT 3.x、GT v3.2.0、PerfLab 的代码、包名、AIDL 或 `^` 数据格式；迁移工具也不得成为运行时依赖。
2. **免特权**：新指标必须能在免 ROOT / 免越狱设备上用公开 API 或 `/proc/self/*` 取得；读不到就写 `null`，**禁止填 0 或估算值冒充**。
3. **可审计**：任何新指标或口径变更必须同时更新 `schema/session.schema.json`、`docs/DATA_SCHEMA.md`、`docs/METRICS.md`、`docs/DIAGNOSIS_RULES.md`，并附一次真实设备（或 macOS CI）验证证据。

## 开发流程

```bash
# Android
cd android && ./gradlew :novaperf-sdk:assembleRelease :demo:assembleDebug

# iOS（macOS）
cd ios && swift build && swift test

# CLI / 报告
python cli/novaperf.py validate examples/session_frames.jsonl
python cli/novaperf.py report examples/session_frames.jsonl -o /tmp/report.html
python cli/novaperf.py gate examples/session_frames.jsonl
```

提交前请跑通三条 CI workflow 对应的本地命令。报告模板改动请在浏览器里实际打开验证（无头浏览器 `--dump-dom` 也可）。

## 代码约定

- Android SDK：纯 Java 8 兼容、零第三方依赖、无反射、无 native；采样在 HandlerThread，主线程只做帧回调与心跳。
- iOS SDK：Swift 5.9，UIKit 依赖一律 `#if os(iOS)` 隔离，保证 macOS 上 `swift test` 可跑。
- CLI：仅 Python 标准库，Python 3.9+；诊断规则集中在 `RULES`，`report` 与 `gate` 必须共用。
- 报告：单文件、离线、无 CDN；新增可视化不得引入外部脚本或字体。

## 数据契约变更

JSONL 的 `v` 字段用于版本化。破坏性变更必须递增 `v` 并保留旧版读取能力（CLI 应给出明确报错，而不是静默忽略）。

## License

贡献即视为同意以 MIT 许可发布。
