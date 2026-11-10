# 指标口径（精准性约定）

> 原则：**能算准才算，算不准就写 `null`**。报告里所有数字都能追溯到这里的公式；任何「不可用」都不会被画成 0。

## 帧率与流畅度

| 指标 | 公式 | 备注 |
|---|---|---|
| 帧间隔 `dt` | 相邻 `Choreographer` / `CADisplayLink` 回调时间戳之差 | 过滤 `dt <= 0` 与 `dt > 1000ms`（切后台/暂停），不参与统计 |
| FPS | 窗口内有效帧数 / 窗口有效时长；无帧时为 `null` | 不把「无帧」当成 0 FPS 拉低均值 |
| AvgFPS | 所有**有效窗口** FPS 的算术平均 | 剔除无帧窗口 |
| 1% Low FPS | `1000 / 最慢 1% 帧的平均 dt` | 至少取 1 帧 |
| P95 / P99 帧耗时 | 全部有效 `dt` 的 95 / 99 分位（线性插值） | |
| Jank | `dt > 2 × 前三帧 dt 均值` 且 `dt > 84ms` | PerfDog 通用判定 |
| BigJank | 同上且 `dt > 125ms` | |
| 冻帧 Frozen | `dt > 700ms` | 单独标记，不计入 Jank |
| 帧预算 | `1000 / refresh_hz` | 报告画参考线 |

## CPU

**Android**（不读全局 `/proc/stat`：Android 11+ SELinux 会拒绝，也是上一代整条采样链中断的根因）：

```
app_jiffies = utime + stime + cutime + cstime   // /proc/self/stat 第 14~17 字段
cpu_app_pct = 100 × (Δapp_jiffies × 10) / (Δwall_ms × cores)
cores       = Runtime.getRuntime().availableProcessors()
```
`10` 为 Linux 用户态 HZ=100 的 jiffy 毫秒数。结果裁剪到 `[0, 100]`。
`cpu_sys_pct` 保持 `null`（免 root 下无法可靠取得全局占用），**不用估算值冒充**。

**iOS**：
```
cpu_time = task_info(TASK_BASIC_INFO) + thread_basic_info 的 user_time + system_time
cpu_app_pct = 100 × Δcpu_time / Δwall
```

`threads`：`/proc/self/status` 的 `Threads`（Android）/ `task_threads`（iOS）。

## 内存

| 平台 | 指标 | 来源 |
|---|---|---|
| Android | `pss_kb` | `Debug.getMemoryInfo().getTotalPss()`（实测在 ColorOS 上实时可靠；`ActivityManager.getProcessMemoryInfo` 会返回缓存旧值，禁止使用） |
| Android | `heap_kb` / `native_kb` | `Runtime.totalMemory()-freeMemory()`（近似 Dalvik heap）、`Debug.getNativeHeapAllocatedSize()` |
| iOS | `pss_kb` | `task_info(TASK_VM_INFO)` 的 `phys_footprint`（与 Xcode Memory Gauge 同源） |

**内存增长**：诊断引擎对 `pss_kb` 做线性回归，若斜率 > 阈值且场景结束后未回落，输出「疑似泄漏」问题（证据：起止值、斜率、持续窗口数）。

## 网络 / IO

```
net_tx_bps = (tx_bytes_now - tx_bytes_prev) × 1000 / Δt_ms
io_read_bps = (read_bytes_now - read_bytes_prev) × 1000 / Δt_ms
```
- Android 累计量来自 `TrafficStats.getUidTxBytes/getUidRxBytes` 与 `/proc/self/io` 的 `read_bytes/write_bytes`。
- **累计值是绝对值，速率必须差分**；首帧无前值时写 0。
- iOS 无系统级按 App 流量统计，`net_*_bps` 为 `null`；`net_req/net_err` 由 `NetworkTracker`（URLSessionTaskMetrics）提供。
- `UID_TRAFFIC` 在部分 ROM 返回 `-1`（UNSUPPORTED），此时写 `null` 并在报告标注。

## 温度 / 电量

- Android：`ACTION_BATTERY_CHANGED` 的 `EXTRA_TEMPERATURE / 10`（°C）、`EXTRA_LEVEL/EXTRA_SCALE`；`PowerManager.getCurrentThermalStatus()`（API 29+）映射 `thermal_state`。
- iOS：`ProcessInfo.processInfo.thermalState`、`UIDevice.current.batteryLevel`。
- 设备不暴露温度时 `temp_c = null`，报告显示「不可用」而非 0°C。

## GPU

免 root / 免越狱设备上**没有公开稳定的 per-App GPU 占用接口**。`gpu_pct` 恒为 `null`，报告中该卡片显示「需厂商/系统级接口」。这是刻意设计：不编造数据。

## ANR / 卡顿

- `AnrWatchdog`：主线程 Handler 每 500ms 投递心跳，若超过 2000ms 未执行 → `anr_risk=1` 并产生 `event(kind=anr, level=error)`，附带主线程堆栈。
- 这只是**疑似 ANR**（不等于系统 ANR 弹窗），报告措辞严格区分，避免误导排查。

## 启动

`startup_ms` = Application 初始化完成 → 首个 `Choreographer`/`CADisplayLink` 帧回调；通过 `event(kind=lifecycle, label=cold_start)` 记录。

## 诊断口径

诊断引擎（`cli/novaperf.py`）中的问题项一律包含：

```
时间窗口 | 触发规则(可复核) | 实测数值 | 关联指标 | 根因假设 | 建议排查动作 | 跳转定位
```

规则阈值集中在 `RULES` 常量，可被 `--rules` 覆盖；`gate` 用同一套阈值做 CI 门禁，保证「报告看到的」与「流水线卡掉的」完全一致。
