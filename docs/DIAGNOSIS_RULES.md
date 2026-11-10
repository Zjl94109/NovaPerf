# 诊断规则（报告与门禁共用）

规则集中在 `cli/novaperf.py` 的 `RULES`。`report` 展示的问题 = `gate` 卡掉的问题，阈值完全一致，避免「报告说没问题、流水线却挂了」或反之。

## 阈值表

| 键 | 默认 | 含义 |
|---|---|---|
| `fps_ratio` | 0.85 | 低帧阈值 = min(60, 实测渲染 Hz) × 0.85 |
| `frame_p95_ratio` | 1.6 | 窗口 P95 帧耗时 > 帧预算 × 1.6 |
| `jank_per_min` | 3 | Jank 密度上限 |
| `cpu_mean_max` | 50 | CPU 均值上限（%） |
| `cpu_p95_max` | 85 | CPU P95 上限（%） |
| `pss_growth_kb` | 30000 | 内存尖峰判定增量（KB） |
| `pss_slope_kb_per_s` | 250 | 疑似泄漏的最小持续斜率（KB/s） |
| `net_rx_p95_bps` | 1000000 | 下行突发阈值（B/s） |
| `io_write_p95_bps` | 500000 | 写盘突发阈值（B/s） |
| `main_thread_ms` | 400 | 主线程心跳延迟阈值（ms） |
| `anr_max` / `crash_max` / `http_err_max` | 0 | 疑似 ANR / 崩溃 / 网络错误容忍数 |
| `battery_drop_pct` | 3 | 会话内电量下降告警（%） |
| `score_min` | 70 | 健康分下限 |
| `max_critical` / `max_warn` | 0 / 5 | 严重 / 警告问题数上限 |

健康分 = `100 - Σ(问题权重)`，权重 `critical=18 / warn=8 / info=2`，下限 0。

## 规则与判据

| 规则 ID | 触发条件 | 严重度 | 输出证据 |
|---|---|---|---|
| `low_fps` | 窗口 `fps < 阈值` | critical（低于阈值×0.7）/ warn | 最低/均值 FPS、持续窗口数、帧预算 |
| `startup_low_fps` | 同上，但出现在前 3 个窗口且存在 `cold_start` 事件 | warn | 单独归类为启动抖动，给 `startup_ms` 与异步初始化建议 |
| `long_frame` | `frame_p95_ms > 帧预算 × 1.6` | warn | P95 峰值与均值 |
| `jank_burst` | Jank/分钟 > 阈值 | warn | Jank / BigJank / 冻帧、折算每分钟 |
| `cpu_hot` | CPU 均值 > 50 或 P95 > 85 | warn | 均值 / P95 / 峰值、关联 GC 与线程 |
| `mem_leak` | PSS 斜率 > 250KB/s 且未回落、无释放打点、**非单次阶跃** | critical（斜率×2）/ warn | 起止值、斜率、峰值、堆/native 关联 |
| `mem_spike` | PSS 峰值 - 基线 > 30MB 且不满足泄漏条件 | warn | 基线/峰值、单次跃升 MB、释放打点 |
| `net_burst` | 下行 P95 > 1MB/s | info | 峰值、累计流量、HTTP 事件数 |
| `io_burst` | 写盘 P95 > 500KB/s | warn | 峰值，关联主线程延迟与 FPS |
| `main_thread_block` | 心跳延迟 > 400ms | warn | 峰值延迟、关联 Jank/IO |
| `anr_risk` | `anr_risk=1` 或 `event(anr)` | critical | 明确标注「疑似 ANR，不等于系统弹窗」+ 主线程堆栈 |
| `crash` | `event(crash)` | critical | 崩溃次数与堆栈 |
| `http_error` | `net_err>0` 或 http error 事件 | warn | 失败计数与错误事件数 |
| `thermal` | `thermal_state ∈ serious/critical` | warn | 持续窗口数、温度、FPS 关联 |
| `battery_drain` | 电量下降 ≥3% | info | 起止电量、CPU/网络关联 |

## 刻意做的三个「防误报」设计

1. **帧预算按实测渲染节奏算**：设备可能声明 120Hz，但系统把 App 限制在 60fps。用 `frame_ms` 中位数反推实测 Hz，再取 `min(声明, 实测)` 作为帧预算依据；否则所有窗口都会被误报「超预算」。
2. **阶跃分配 ≠ 内存泄漏**：单次 PSS 跃升超过总变化 50%、存在 `mem_release` 打点、或末尾已回落 >15%，都归类为「内存尖峰」而非「持续增长」。
3. **冷启动抖动单列**：首窗口伴随 `cold_start` 事件时降为 warn 并给启动优化建议，不按稳态性能问题阻断门禁。

## 覆盖阈值示例

`rules.json`：

```json
{
  "cpu_mean_max": 40,
  "jank_per_min": 2,
  "score_min": 85,
  "max_warn": 2
}
```

```bash
python cli/novaperf.py report session.jsonl --rules rules.json -o report.html
python cli/novaperf.py gate session.jsonl --rules rules.json
```

## 精度边界

- 未开启逐帧明细时 `low1_fps = null`，不会用窗口 P95 估算值冒充精确 1% Low；报告会提示如何开启。
- 不可用字段（`gpu_pct` / `cpu_sys_pct` / iOS 的 `net_*_bps` 等）不参与任何规则判定，只在覆盖率表显示「不可用」。
- 所有问题都带 `i0/i1` 采样索引与 `t0/t1` 时间戳，可一键跳到时间轴对应区间复核。
