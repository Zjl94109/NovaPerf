# JSONL 数据契约 v1

一个会话 = 一个 `.jsonl` 文件，每行一个 JSON 对象，**无外部依赖、无压缩、可逐行流式读取**。
Android 与 iOS 输出**完全相同**的字段集合；平台不支持的指标写 `null`（不是 0、不是 ""）。

## 公共字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `v` | int | schema 版本，当前 `1` |
| `t` | int | 事件时间戳，epoch 毫秒 |
| `type` | string | `meta` / `sample` / `frame` / `event` / `summary` |

## `meta`（每次会话首行）

```json
{"v":1,"t":1731210000000,"type":"meta","session_id":"20261110_123000","platform":"android",
 "app":"com.novaperf.demo","app_name":"NovaPerf Demo","app_version":"1.0.0",
 "device":"OPPO","model":"PJT110","os":"Android 16","api":36,
 "cores":8,"refresh_hz":60,"root_required":false,"sdk":"novaperf/1.0.0",
 "started_at":1731210000000}
```

`platform`: `android` | `ios`。`root_required` 恒为 `false`（框架设计约束）。

## `sample`（默认 1 秒一行，核心指标）

```json
{"v":1,"t":1731210001000,"type":"sample","seq":1,
 "fps":59.8,"frame_ms":16.7,"frame_p95_ms":18.4,"jank":0,"big_jank":0,"frozen":0,
 "cpu_app_pct":12.3,"cpu_sys_pct":null,"threads":42,"fds":128,
 "pss_kb":102400,"heap_kb":20480,"native_kb":12288,"gc_count":3,
 "net_tx_bps":1024.0,"net_rx_bps":8192.0,"net_req":0,"net_err":0,
 "io_read_bps":0.0,"io_write_bps":4096.0,
 "battery_pct":78.0,"temp_c":31.4,"thermal_state":"nominal",
 "gpu_pct":null,"main_thread_busy_ms":8.2,"anr_risk":0,
 "page":"MainActivity","scene":"idle"}
```

| 字段 | 单位 | 说明 |
|---|---|---|
| `fps` | 帧/秒 | 1 秒窗口内有效帧率 |
| `frame_ms` | ms | 窗口内平均帧间隔 |
| `frame_p95_ms` | ms | 窗口内帧间隔 P95 |
| `jank` / `big_jank` / `frozen` | 次 | 窗口内卡顿计数 |
| `cpu_app_pct` | % | 被测进程 CPU 占用（0–100×核数上限 100） |
| `cpu_sys_pct` | % / null | 系统整体占用；受限平台为 null |
| `threads` / `fds` | 个 | `/proc/self/status` Threads、`/proc/self/fd` 计数 |
| `pss_kb` | KB | PSS（Android）/ phys_footprint（iOS） |
| `heap_kb` / `native_kb` | KB | Dalvik/ART heap 与 native heap |
| `gc_count` | 次 | 窗口内 GC 增量 |
| `net_tx_bps` / `net_rx_bps` | B/s | 累计字节差分 |
| `net_req` / `net_err` | 次 | 网络请求数 / 错误数（需接入 `NetworkTracker`） |
| `io_read_bps` / `io_write_bps` | B/s | `/proc/self/io` 差分 |
| `battery_pct` | % | 电量 |
| `temp_c` | °C / null | 电池温度；设备不暴露时为 null |
| `thermal_state` | string | `nominal/fair/serious/critical/unknown` |
| `gpu_pct` | % / null | 免特权设备通常不可得，保持 null，**不伪造** |
| `main_thread_busy_ms` | ms | 窗口内主线程心跳最大延迟 |
| `anr_risk` | 0/1 | 心跳延迟 > 2000ms 置 1 |
| `page` / `scene` | string | 当前页面 / 当前场景 |

## `frame`（可选，逐帧明细）

```json
{"v":1,"t":1731210000983,"type":"frame","dt_ms":16.6,"jank":false,"big_jank":false}
```
数据量大，默认关闭；开启后用于精确复盘长帧。

## `event`（异常、场景、生命周期、日志、HTTP）

```json
{"v":1,"t":1731210002000,"type":"event","kind":"scene","level":"info",
 "label":"进入战斗","detail":"用户点击开始","page":"MainActivity","duration_ms":null,"stack":null}
```

| `kind` | 触发 |
|---|---|
| `scene` | `NovaPerf.flag()` 打点 |
| `lifecycle` | Activity / ViewController 切换 |
| `anr` | 主线程心跳超时 |
| `crash` | 未捕获异常 / signal |
| `jank_burst` | 连续窗口出现卡顿聚集 |
| `thermal` | 温度状态升级 |
| `http` | 请求完成（URLSessionTaskMetrics / OkHttp 拦截器） |
| `log` | 应用日志（可选接入） |
| `gc` | GC 事件（若平台可得） |

`level`: `info` / `warn` / `error`。

## `summary`（会话末行）

```json
{"v":1,"t":1731210030000,"type":"summary","duration_ms":30000,"samples":30,"frames":1792}
```

## 约束

1. 时间必须单调递增（允许同毫秒）；诊断引擎按 `t` 排序并做去重。
2. 数值字段禁止 `NaN` / `Infinity`；不确定一律 `null`。
3. 文件编码 UTF-8，换行 `\n`；写入采用 append + flush，进程被杀也不丢已采数据。
4. `meta` 必须为首行；缺失时诊断引擎按 `unknown` 处理并在报告中标注。
