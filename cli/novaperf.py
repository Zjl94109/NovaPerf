#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NovaPerf CLI — 采集控制 / 数据拉取 / 诊断引擎 / 门禁 / 单文件报告。

零第三方依赖（仅 Python 标准库）。Android 与 iOS 输出同一 JSONL 契约，诊断逻辑完全共用。
用法: python cli/novaperf.py --help
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
TEMPLATE = ROOT / "report" / "template.html"
SDK_VERSION = "novaperf/1.0.0"

# ------------------------------------------------------------------ 规则（报告与门禁共用同一套阈值）
RULES = {
    "fps_ratio": 0.85,              # 低于 refresh_hz*0.85 判低帧（上限按 60Hz 归一）
    "frame_p95_ratio": 1.6,         # 窗口 P95 帧耗时 > 帧预算 * 1.6
    "jank_per_min": 3,
    "cpu_mean_max": 50.0,
    "cpu_p95_max": 85.0,
    "pss_growth_kb": 30000,
    "pss_slope_kb_per_s": 250.0,
    "net_rx_p95_bps": 1000000.0,
    "io_write_p95_bps": 500000.0,
    "main_thread_ms": 400.0,
    "anr_max": 0,
    "crash_max": 0,
    "http_err_max": 0,
    "battery_drop_pct": 3.0,
    "score_min": 70,
    "max_critical": 0,
    "max_warn": 5,
}

SEV_WEIGHT = {"critical": 18, "warn": 8, "info": 2}

METRIC_DEFS = [
    ("fps", "帧/秒", "窗口内有效帧数 / 窗口时长", "Choreographer / CADisplayLink"),
    ("frame_ms", "ms", "窗口内平均帧间隔", "帧回调时间戳差分"),
    ("frame_p95_ms", "ms", "窗口内帧间隔 P95", "线性插值分位"),
    ("jank / big_jank / frozen", "次", "dt>2×前三帧均值且>84ms / >125ms / >700ms", "PerfDog 通用规则"),
    ("cpu_app_pct", "%", "100 × (Δjiffies×10ms)/(Δwall×cores)", "/proc/self/stat（Android）"),
    ("cpu_sys_pct", "%", "全局 CPU 占用；免特权不可得", "恒 null，不伪造"),
    ("threads / fds", "个", "进程线程数 / 打开文件数", "/proc/self/status, /proc/self/fd"),
    ("pss_kb", "KB", "PSS / phys_footprint", "Debug.getMemoryInfo / task_vm_info"),
    ("heap_kb / native_kb", "KB", "ART heap / native heap", "Runtime / Debug"),
    ("gc_count", "次", "窗口内 GC 增量", "Debug.getRuntimeStat"),
    ("net_tx_bps / net_rx_bps", "B/s", "累计字节差分 ×1000/Δt", "TrafficStats / iOS 为 null"),
    ("net_req / net_err", "次", "窗口内请求数 / 错误数", "网络层埋点 noteHttp"),
    ("io_read_bps / io_write_bps", "B/s", "/proc/self/io 差分", "read_bytes / write_bytes"),
    ("battery_pct / temp_c", "% / °C", "电量与电池温度", "ACTION_BATTERY_CHANGED"),
    ("thermal_state", "枚举", "系统热状态", "PowerManager / ProcessInfo"),
    ("gpu_pct", "%", "per-App GPU 占用", "免特权不可得，恒 null"),
    ("main_thread_busy_ms", "ms", "主线程心跳最大延迟", "500ms 心跳 watchdog"),
    ("anr_risk", "0/1", "心跳延迟>2s 置 1（疑似 ANR，非系统弹窗）", "AnrWatchdog"),
]

NUMERIC_KEYS = [
    "fps", "frame_ms", "frame_p95_ms", "jank", "big_jank", "frozen",
    "cpu_app_pct", "cpu_sys_pct", "threads", "fds", "pss_kb", "heap_kb",
    "native_kb", "gc_count", "net_tx_bps", "net_rx_bps", "net_req", "net_err",
    "io_read_bps", "io_write_bps", "battery_pct", "temp_c", "gpu_pct",
    "main_thread_busy_ms", "anr_risk",
]


# ------------------------------------------------------------------ 基础工具

def out(msg=""):
    print(msg, flush=True)


def find_adb():
    p = shutil.which("adb")
    if p:
        return p
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk" / "platform-tools" / "adb.exe",
        Path(os.environ.get("ANDROID_HOME", "")) / "platform-tools" / "adb.exe",
        Path("C:/Users/zengjiale/AppData/Local/Android/Sdk/platform-tools/adb.exe"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return "adb"


ADB = find_adb()


def adb(device, *args, check=False, capture=True):
    cmd = [ADB]
    if device:
        cmd += ["-s", device]
    cmd += [str(a) for a in args]
    r = subprocess.run(cmd, capture_output=capture, text=True, errors="replace")
    if check and r.returncode != 0:
        raise RuntimeError("adb 失败: %s\n%s" % (" ".join(cmd), (r.stderr or "")[:800]))
    return r


def pick_device(prefer_real=True):
    r = adb(None, "devices")
    lines = [l.strip() for l in r.stdout.splitlines()[1:] if l.strip()]
    devs = [l.split("\t")[0] for l in lines if "\tdevice" in l]
    if prefer_real:
        real = [d for d in devs if not d.startswith("emulator-")]
        if real:
            return real[0]
    return devs[0] if devs else None


def pct(values, q):
    v = sorted(x for x in values if isinstance(x, (int, float)) and not isinstance(x, bool))
    if not v:
        return None
    if len(v) == 1:
        return v[0]
    k = (len(v) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return v[lo]
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def mean(values):
    v = [x for x in values if isinstance(x, (int, float)) and not isinstance(x, bool)]
    return sum(v) / len(v) if v else None


def r2(v, nd=2):
    return None if v is None else round(float(v), nd)


def slope(xs, ys):
    """最小二乘斜率；样本不足返回 None。"""
    pts = [(x, y) for x, y in zip(xs, ys) if isinstance(y, (int, float))]
    if len(pts) < 4:
        return None
    n = len(pts)
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    den = sum((p[0] - mx) ** 2 for p in pts)
    if den == 0:
        return None
    return sum((p[0] - mx) * (p[1] - my) for p in pts) / den


def load_session(path):
    p = Path(path)
    rows, errors = [], []
    for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception as e:
            errors.append("第 %d 行不是合法 JSON: %s" % (i, e))
    meta = next((r for r in rows if r.get("type") == "meta"), {}) or {}
    samples = sorted([r for r in rows if r.get("type") == "sample"], key=lambda r: r.get("t", 0))
    frames = sorted([r for r in rows if r.get("type") == "frame"], key=lambda r: r.get("t", 0))
    events = sorted([r for r in rows if r.get("type") == "event"], key=lambda r: r.get("t", 0))
    summary = next((r for r in rows if r.get("type") == "summary"), {}) or {}
    return {
        "path": str(p), "rows": rows, "meta": meta, "samples": samples,
        "frames": frames, "events": events, "summary": summary, "errors": errors,
    }


def validate(s):
    issues = list(s["errors"])
    if not s["meta"]:
        issues.append("缺少 meta 首行")
    if not s["samples"]:
        issues.append("没有任何 sample 行")
    last = -1
    for r in s["rows"]:
        t = r.get("t")
        if not isinstance(t, int):
            issues.append("行缺少整数 t: %s" % str(r)[:80])
            continue
        if t < last:
            issues.append("时间戳非单调: %d < %d" % (t, last))
        last = max(last, t)
        if r.get("v") != 1:
            issues.append("schema 版本不是 1")
    for r in s["samples"]:
        for k in NUMERIC_KEYS:
            v = r.get(k)
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                issues.append("sample seq=%s 的 %s 为 NaN/Inf" % (r.get("seq"), k))
    return issues


# ------------------------------------------------------------------ 诊断引擎

def values(samples, key):
    return [r.get(key) for r in samples if isinstance(r.get(key), (int, float))
            and not isinstance(r.get(key), bool)]


def windows_where(samples, key, pred):
    """返回满足条件的连续区间（索引）。"""
    runs, cur = [], None
    for i, r in enumerate(samples):
        v = r.get(key)
        ok = isinstance(v, (int, float)) and not isinstance(v, bool) and pred(v)
        if ok and cur is None:
            cur = [i, i]
        elif ok:
            cur[1] = i
        elif cur is not None:
            runs.append(tuple(cur))
            cur = None
    if cur is not None:
        runs.append(tuple(cur))
    return runs


def typical_interval_s(samples):
    gaps = [(samples[i + 1]["t"] - samples[i]["t"]) / 1000.0 for i in range(len(samples) - 1)]
    gaps = [g for g in gaps if g > 0]
    return pct(gaps, 0.5) or 1.0


def mk_issue(id_, title, sev, samples, idx, rule, evidence, metrics,
             correlated, hypothesis, actions):
    a, b = idx
    t0 = samples[a]["t"]
    t1 = samples[b]["t"]
    # 单点窗口按采样间隔计，避免显示「持续 0.0s」
    window_s = (t1 - t0) / 1000.0
    if window_s <= 0:
        window_s = typical_interval_s(samples)
    return {
        "id": id_, "title": title, "severity": sev,
        "t0": t0, "t1": t1, "i0": a, "i1": b,
        "window_s": r2(window_s, 1),
        "rule": rule, "evidence": evidence, "metrics": metrics,
        "correlated": correlated, "hypothesis": hypothesis, "actions": actions,
        "score_cost": SEV_WEIGHT[sev],
    }


def analyze(s, baseline=None, rules=None, source_label=None):
    R = dict(RULES)
    if rules:
        R.update(rules)
    samples, frames, events, meta = s["samples"], s["frames"], s["events"], s["meta"]
    if not samples:
        raise RuntimeError("会话中没有 sample，无法诊断")
    t_start = samples[0]["t"]
    xs = [(r["t"] - t_start) / 1000.0 for r in samples]
    declared_hz = float(meta.get("refresh_hz") or 60.0)
    # 设备声明刷新率 ≠ 实际渲染节奏（ColorOS 常把 120Hz 屏按 60fps 出帧）。
    # 帧预算必须以实测帧间隔为准，否则所有窗口都会被误判为「超预算」。
    observed_ms = pct(values(samples, "frame_ms"), 0.5)
    measured_hz = (1000.0 / observed_ms) if observed_ms and observed_ms > 0 else declared_hz
    hz = max(24.0, min(240.0, min(declared_hz, round(measured_hz))))
    budget = 1000.0 / hz
    # 低帧阈值按 60fps 基准归一，避免高刷设备上把正常的 60fps 误判成低帧
    fps_floor = min(60.0, hz) * R["fps_ratio"]
    duration = (samples[-1]["t"] - t_start) / 1000.0

    fps_v = values(samples, "fps")
    cpu_v = values(samples, "cpu_app_pct")
    pss_v = values(samples, "pss_kb")
    p95_v = values(samples, "frame_p95_ms")
    rx_v = values(samples, "net_rx_bps")
    iow_v = values(samples, "io_write_bps")
    busy_v = values(samples, "main_thread_busy_ms")
    jank_total = sum(int(r.get("jank") or 0) for r in samples)
    big_total = sum(int(r.get("big_jank") or 0) for r in samples)
    frozen_total = sum(int(r.get("frozen") or 0) for r in samples)
    net_req = sum(int(r.get("net_req") or 0) for r in samples)
    net_err = sum(int(r.get("net_err") or 0) for r in samples)
    anr_total = sum(int(r.get("anr_risk") or 0) for r in samples)

    exact = bool(frames)
    dt_all = [f.get("dt_ms") for f in frames if isinstance(f.get("dt_ms"), (int, float))]
    if exact and dt_all:
        frame_p95 = pct(dt_all, 0.95)
        frame_p99 = pct(dt_all, 0.99)
        slow = sorted(dt_all, reverse=True)
        slow_n = max(1, int(math.ceil(len(slow) * 0.01)))
        slow5_n = max(1, int(math.ceil(len(slow) * 0.05)))
        low1 = 1000.0 / (sum(slow[:slow_n]) / slow_n)
        low5 = 1000.0 / (sum(slow[:slow5_n]) / slow5_n)
        precision = "逐帧精确"
        avg_frame_ms = mean(dt_all)
    else:
        frame_p95 = mean(p95_v)          # 窗口级 P95 的均值，明确标注为估算
        frame_p99 = None
        low1 = None                     # 未开启逐帧明细就不编造 1% Low
        low5 = 1000.0 / frame_p95 if frame_p95 else None
        precision = "窗口聚合（估算）"
        avg_frame_ms = mean(values(samples, "frame_ms"))

    kpi = {
        "duration_s": r2(duration, 1),
        "samples": len(samples),
        "frames_logged": len(frames),
        "precision": precision,
        "avg_fps": r2(mean(fps_v)),
        "min_fps": r2(min(fps_v)) if fps_v else None,
        "low1_fps": r2(low1),
        "low5_fps": r2(low5),
        "frame_ms": r2(avg_frame_ms),
        "frame_p95_ms": r2(frame_p95),
        "frame_p99_ms": r2(frame_p99),
        "frame_budget_ms": r2(budget),
        "refresh_declared": r2(declared_hz, 1),
        "refresh_effective": r2(hz, 1),
        "jank": jank_total, "big_jank": big_total, "frozen": frozen_total,
        "jank_per_min": r2(jank_total / max(duration / 60.0, 1 / 60.0)),
        "cpu_avg": r2(mean(cpu_v)), "cpu_p95": r2(pct(cpu_v, 0.95)), "cpu_max": r2(max(cpu_v)) if cpu_v else None,
        "pss_avg": r2(mean(pss_v)), "pss_min": r2(min(pss_v)) if pss_v else None,
        "pss_max": r2(max(pss_v)) if pss_v else None,
        "pss_start": r2(pss_v[0]) if pss_v else None, "pss_end": r2(pss_v[-1]) if pss_v else None,
        "pss_growth_kb": r2(pss_v[-1] - min(pss_v)) if pss_v else None,
        "net_tx_total_kb": r2(sum((r.get("net_tx_bps") or 0) for r in samples) * 1.0 / 1024, 1),
        "net_rx_total_kb": r2(sum((r.get("net_rx_bps") or 0) for r in samples) * 1.0 / 1024, 1),
        "net_rx_peak_bps": r2(max(rx_v)) if rx_v else None,
        "net_req": net_req, "net_err": net_err,
        "io_write_peak_bps": r2(max(iow_v)) if iow_v else None,
        "battery_pct": r2((values(samples, "battery_pct") or [None])[-1], 1),
        "temp_c": r2((values(samples, "temp_c") or [None])[-1], 1),
        "thermal_state": (samples[-1].get("thermal_state") or "unknown"),
        "main_thread_max_ms": r2(max(busy_v)) if busy_v else None,
        "anr_risk": anr_total,
        "events": len(events),
        "crashes": sum(1 for e in events if e.get("kind") == "crash"),
        "http_events": sum(1 for e in events if e.get("kind") == "http"),
        "scenes": len(set(str(r.get("scene")) for r in samples)),
    }

    issues = []

    def worst_run(runs, key, reverse=True):
        if not runs:
            return None
        return sorted(runs, key=lambda ab: sum((samples[i].get(key) or 0) for i in range(ab[0], ab[1] + 1)),
                      reverse=reverse)[0]

    # 1. 低帧
    runs = windows_where(samples, "fps", lambda v: v < fps_floor)
    if runs:
        a, b = worst_run(runs, "fps", reverse=False)
        seg = [samples[i].get("fps") for i in range(a, b + 1)]
        cold = any(e.get("kind") == "lifecycle" and "cold_start" in str(e.get("label") or "")
                   for e in events)
        startup = a <= 2 and cold   # 冷启动首帧抖动单独归类，避免误判为稳态性能问题
        issues.append(mk_issue(
            "low_fps" if not startup else "startup_low_fps",
            "启动阶段掉帧" if startup else "帧率低于阈值",
            "warn" if startup else ("critical" if min(seg) < fps_floor * 0.7 else "warn"),
            samples, (a, b), "fps < %.1f（%.0fHz × %.2f）" % (fps_floor, min(60.0, hz), R["fps_ratio"]),
            "窗口最低 %.2f FPS，平均 %.2f FPS，持续 %.1fs（%d 个采样窗口）" % (
                min(seg), mean(seg),
                max((samples[b]["t"] - samples[a]["t"]) / 1000.0, typical_interval_s(samples)),
                b - a + 1),
            {"最低FPS": r2(min(seg)), "窗口均值FPS": r2(mean(seg)), "帧预算ms": r2(budget)},
            ["frame_p95_ms", "cpu_app_pct", "main_thread_busy_ms"],
            ("冷启动初始化（类加载、布局膨胀、首屏数据加载）造成的首窗口抖动；"
             "已与稳态掉帧区分，建议单独看 startup_ms" if startup else
             "主线程长任务 / 过度绘制 / GC 停顿 / GPU 受限，或场景本身负载过高"),
            (["查看 cold_start 事件的 startup_ms 指标", "把首屏非必要初始化延后或异步化",
              "对比稳态窗口 FPS，确认是否只影响启动阶段"] if startup else
             ["点击「定位」查看该时间窗的多指标联动曲线", "检查该窗口的 main_thread_busy_ms 与 GC 增量",
              "在代码中用 Systrace/Profiler 抓取该时段主线程堆栈", "若 CPU 同时飙高，优先排查计算密集逻辑"])))
    # 2. 长帧
    runs = windows_where(samples, "frame_p95_ms", lambda v: v > budget * R["frame_p95_ratio"])
    if runs:
        a, b = worst_run(runs, "frame_p95_ms")
        seg = [samples[i].get("frame_p95_ms") for i in range(a, b + 1)]
        issues.append(mk_issue(
            "long_frame", "窗口 P95 帧耗时超预算", "warn",
            samples, (a, b), "frame_p95_ms > %.1fms（帧预算 %.1fms × %.1f）" % (budget * R["frame_p95_ratio"], budget, R["frame_p95_ratio"]),
            "峰值 %.2fms，均值 %.2fms" % (max(seg), mean(seg)),
            {"P95峰值ms": r2(max(seg)), "帧预算ms": r2(budget)},
            ["fps", "cpu_app_pct", "jank"], "偶发长帧，常见为布局测量/图片解码/同步 IO",
            ["查看事件检索中该窗口的 http / log 事件", "开启逐帧明细（START --ez frames true）精确复盘长帧"]))
    # 3. 卡顿聚集
    per_min = kpi["jank_per_min"] or 0
    if per_min > R["jank_per_min"]:
        runs = windows_where(samples, "jank", lambda v: v > 0)
        a, b = runs[0] if runs else (0, 0)
        issues.append(mk_issue(
            "jank_burst", "卡顿密度超阈值", "warn", samples, (a, b),
            "Jank/分钟 > %.1f" % R["jank_per_min"],
            "共 %d 次 Jank（BigJank %d / 冻帧 %d），折算 %.1f 次/分钟" % (jank_total, big_total, frozen_total, per_min),
            {"Jank": jank_total, "BigJank": big_total, "Frozen": frozen_total, "次/分钟": per_min},
            ["fps", "frame_p95_ms", "main_thread_busy_ms", "gc_count"],
            "连续掉帧多为主线程阻塞或频繁 GC",
            ["对照 main_thread_busy_ms 与 gc_count 曲线", "用场景打点定位具体业务阶段"]))
    # 4. CPU
    if (mean(cpu_v) or 0) > R["cpu_mean_max"] or (pct(cpu_v, 0.95) or 0) > R["cpu_p95_max"]:
        runs = windows_where(samples, "cpu_app_pct", lambda v: v > R["cpu_p95_max"])
        a, b = runs[0] if runs else (0, len(samples) - 1)
        seg = [samples[i].get("cpu_app_pct") or 0 for i in range(a, b + 1)]
        issues.append(mk_issue(
            "cpu_hot", "被测进程 CPU 占用过高", "warn", samples, (a, b),
            "cpu_app_pct 均值>%.0f%% 或 P95>%.0f%%" % (R["cpu_mean_max"], R["cpu_p95_max"]),
            "均值 %.2f%%，P95 %.2f%%，峰值 %.2f%%" % (mean(cpu_v) or 0, pct(cpu_v, 0.95) or 0, max(seg)),
            {"均值": r2(mean(cpu_v)), "P95": r2(pct(cpu_v, 0.95)), "峰值": r2(max(seg))},
            ["fps", "pss_kb", "gc_count", "threads"],
            "计算密集循环 / 死循环 / 频繁对象分配引发 GC / 线程过多",
            ["检查 threads 与 gc_count 是否同步上升", "用 CPU Profiler 抓取该窗口热点方法", "对照场景打点确认是否为预期负载"]))
    # 5. 内存持续增长 / 尖峰
    sl = slope(xs, [r.get("pss_kb") for r in samples])
    growth = (pss_v[-1] - min(pss_v)) if pss_v else 0
    span = (max(pss_v) - min(pss_v)) if pss_v else 0
    steps = [pss_v[i + 1] - pss_v[i] for i in range(len(pss_v) - 1)]
    max_step = max(steps) if steps else 0
    step_like = span > 0 and max_step > span * 0.5   # 一次性大对象分配（阶跃），不是持续泄漏
    release_events = [e for e in events if "mem_release" in str(e.get("label") or "")]
    dropped = bool(pss_v) and span > 0 and (max(pss_v) - pss_v[-1]) > span * 0.15
    # 只有「持续增长 + 未见回落 + 无显式释放打点 + 非单次阶跃」才判泄漏
    leak = (sl is not None and sl > R["pss_slope_kb_per_s"]
            and growth > R["pss_growth_kb"] / 2 and not release_events
            and not dropped and not step_like)
    if leak:
        issues.append(mk_issue(
            "mem_leak", "内存持续增长（疑似泄漏）", "critical" if sl > R["pss_slope_kb_per_s"] * 2 else "warn",
            samples, (0, len(samples) - 1),
            "PSS 线性回归斜率 > %.0f KB/s 且未回落、无释放事件" % R["pss_slope_kb_per_s"],
            "PSS %.1f → %.1f MB，斜率 %.1f KB/s，峰值 %.1f MB" % (
                pss_v[0] / 1024, pss_v[-1] / 1024, sl, max(pss_v) / 1024),
            {"起始MB": r2(pss_v[0] / 1024), "结束MB": r2(pss_v[-1] / 1024),
             "斜率KB/s": r2(sl), "峰值MB": r2(max(pss_v) / 1024)},
            ["heap_kb", "native_kb", "gc_count", "fds"],
            "静态集合/缓存未释放、Bitmap 未回收、监听器未注销、或 native 内存泄漏",
            ["对比 heap_kb 与 native_kb 判断是 Java 层还是 native 层",
             "在场景结束后观察 PSS 是否回落；不回落优先查长生命周期引用",
             "用 Android Studio Memory Profiler / Xcode Memory Graph 抓取该时段堆转储"]))
    elif growth > R["pss_growth_kb"]:
        i = max(range(len(samples)), key=lambda j: samples[j].get("pss_kb") or 0)
        issues.append(mk_issue(
            "mem_spike", "内存出现大幅尖峰", "warn", samples, (i, i),
            "PSS 峰值 - 基线 > %.0f KB" % R["pss_growth_kb"],
            "基线 %.1f MB → 峰值 %.1f MB%s" % (
                min(pss_v) / 1024, max(pss_v) / 1024,
                ("；检测到显式释放打点/末尾已回落" if (release_events or dropped) else "")
                + ("；单次跃升 %.1f MB，属阶跃分配而非持续泄漏" % (max_step / 1024) if step_like else "")),
            {"基线MB": r2(min(pss_v) / 1024), "峰值MB": r2(max(pss_v) / 1024),
             "单次跃升MB": r2(max_step / 1024, 1), "释放打点": len(release_events), "末尾回落": dropped},
            ["heap_kb", "native_kb", "gc_count"],
            "一次性大对象分配（图片/大数组/解码缓冲）或在循环中反复分配",
            ["检查该窗口的 GC 次数与 heap_kb", "确认是否有大图加载或缓存预热"]))
    # 6. 网络 / IO 突发
    if (pct(rx_v, 0.95) or 0) > R["net_rx_p95_bps"]:
        i = max(range(len(samples)), key=lambda j: samples[j].get("net_rx_bps") or 0)
        issues.append(mk_issue(
            "net_burst", "下行流量突发", "info", samples, (i, i),
            "net_rx_bps P95 > %.0f B/s" % R["net_rx_p95_bps"],
            "峰值 %.1f KB/s，累计下行 %.1f KB，HTTP 事件 %d 条" % (
                (max(rx_v) / 1024), kpi["net_rx_total_kb"], kpi["http_events"]),
            {"峰值KB/s": r2(max(rx_v) / 1024), "累计KB": kpi["net_rx_total_kb"]},
            ["net_req", "net_err", "cpu_app_pct", "pss_kb"],
            "批量资源下载 / 未做分页或缓存 / 图片未压缩",
            ["在事件检索中过滤 http 查看请求序列", "确认是否可分页、压缩或缓存"]))
    if (pct(iow_v, 0.95) or 0) > R["io_write_p95_bps"]:
        i = max(range(len(samples)), key=lambda j: samples[j].get("io_write_bps") or 0)
        issues.append(mk_issue(
            "io_burst", "磁盘写入突发", "warn", samples, (i, i),
            "io_write_bps P95 > %.0f B/s" % R["io_write_p95_bps"],
            "峰值 %.1f KB/s（/proc/self/io write_bytes 差分）" % (max(iow_v) / 1024),
            {"峰值KB/s": r2(max(iow_v) / 1024)},
            ["main_thread_busy_ms", "fps", "cpu_app_pct"],
            "主线程同步写文件 / 日志洪泛 / 数据库批量事务",
            ["对照主线程心跳延迟与 FPS 曲线判断是否在关键路径", "把写盘移出主线程或批量合并"]))
    # 7. 主线程阻塞 / ANR / 崩溃 / HTTP 错误 / 热状态 / 耗电
    runs = windows_where(samples, "main_thread_busy_ms", lambda v: v > R["main_thread_ms"])
    if runs:
        a, b = max(runs, key=lambda ab: max(samples[i].get("main_thread_busy_ms") or 0 for i in range(ab[0], ab[1] + 1)))
        peak = max(samples[i].get("main_thread_busy_ms") or 0 for i in range(a, b + 1))
        issues.append(mk_issue(
            "main_thread_block", "主线程心跳延迟（疑似卡顿源）", "warn", samples, (a, b),
            "main_thread_busy_ms > %.0fms" % R["main_thread_ms"],
            "峰值延迟 %.0fms（watchdog 心跳 500ms 投递）" % peak,
            {"峰值ms": r2(peak)}, ["fps", "frame_p95_ms", "jank", "io_write_bps"],
            "主线程同步 IO / 锁竞争 / 复杂布局或measure / 大对象序列化",
            ["对照 FPS 与 Jank 曲线确认影响范围", "抓取主线程堆栈定位阻塞点"]))
    anr_events = [e for e in events if e.get("kind") == "anr"]
    if anr_total > R["anr_max"] or anr_events:
        a = min(range(len(samples)), key=lambda i: abs(samples[i]["t"] - (anr_events[0]["t"] if anr_events else samples[0]["t"])))
        stack = anr_events[0].get("stack") if anr_events else None
        issues.append(mk_issue(
            "anr_risk", "疑似 ANR（主线程 >2s 未响应心跳）", "critical", samples, (a, a),
            "anr_risk=1 或 event(kind=anr)",
            "疑似 ANR 次数 %d；注意：这是 NovaPerf watcher 判定，不等于系统 ANR 弹窗" % max(anr_total, len(anr_events)),
            {"次数": max(anr_total, len(anr_events)), "主线程堆栈": "已在事件检索中" if stack else "未捕获"},
            ["main_thread_busy_ms", "fps"], "主线程被同步调用长时间占住",
            ["打开事件检索查看附带的主线程堆栈", "对照系统 logcat 的 ANR trace 复核"]))
    crashes = [e for e in events if e.get("kind") == "crash"]
    if len(crashes) > R["crash_max"]:
        a = min(range(len(samples)), key=lambda i: abs(samples[i]["t"] - crashes[0]["t"]))
        issues.append(mk_issue(
            "crash", "会话中发生崩溃", "critical", samples, (a, a),
            "event(kind=crash) 数量 > %d" % R["crash_max"],
            "崩溃 %d 次，堆栈已随事件落盘" % len(crashes),
            {"次数": len(crashes)}, ["page", "scene"],
            "未捕获异常 / native signal",
            ["在事件检索中查看 crash 事件的完整堆栈", "对照 page / scene 定位崩溃页面"]))
    http_err_events = [e for e in events if e.get("kind") == "http" and e.get("level") == "error"]
    if net_err > R["http_err_max"] or http_err_events:
        a, b = (0, len(samples) - 1)
        issues.append(mk_issue(
            "http_error", "存在网络请求失败", "warn", samples, (a, b),
            "net_err > %d 或 event(kind=http, level=error)" % R["http_err_max"],
            "失败计数 %d，错误事件 %d 条" % (net_err, len(http_err_events)),
            {"net_err": net_err, "错误事件": len(http_err_events)},
            ["net_rx_bps", "net_req"], "服务端错误 / DNS / TLS / 超时",
            ["在事件检索中过滤 level=error 查看具体 URL 与耗时"]))
    bad_thermal = [i for i, r in enumerate(samples) if r.get("thermal_state") in ("serious", "critical")]
    if bad_thermal:
        issues.append(mk_issue(
            "thermal", "设备进入严重热状态", "warn", samples, (bad_thermal[0], bad_thermal[-1]),
            "thermal_state ∈ {serious, critical}",
            "严重热状态持续 %d 个采样窗口，电池温度 %.1f°C" % (
                len(bad_thermal), kpi["temp_c"] or 0),
            {"窗口数": len(bad_thermal), "温度°C": kpi["temp_c"]},
            ["fps", "cpu_app_pct"], "持续高负载导致降频，帧率可能随温度下降",
            ["对照 FPS 曲线检查是否出现随时间恶化的降帧"]))
    batt = values(samples, "battery_pct")
    if batt and (batt[0] - batt[-1]) >= R["battery_drop_pct"]:
        issues.append(mk_issue(
            "battery_drain", "会话内电量下降明显", "info", samples, (0, len(samples) - 1),
            "电量下降 ≥ %.1f%%" % R["battery_drop_pct"],
            "%.1f%% → %.1f%%（%.1fs）" % (batt[0], batt[-1], duration),
            {"起始": batt[0], "结束": batt[-1]}, ["cpu_app_pct", "net_rx_bps"],
            "持续 CPU / 网络 / 唤醒负载", ["对照 CPU 与网络曲线定位耗电来源"]))

    order = {"critical": 0, "warn": 1, "info": 2}
    issues.sort(key=lambda x: (order[x["severity"]], -x["score_cost"], x["t0"]))
    score = max(0, 100 - sum(i["score_cost"] for i in issues))

    # 指标覆盖率（覆盖面全 + 明确「不可用」）
    coverage = []
    for k in NUMERIC_KEYS:
        v = values(samples, k)
        unit = next((d[1] for d in METRIC_DEFS if d[0] == k or k in d[0].split(" / ")), "")
        coverage.append({"key": k, "unit": unit, "count": len(v),
                         "ratio": r2(len(v) / max(1, len(samples)), 3),
                         "status": "可用" if len(v) == len(samples) else ("部分可用" if v else "不可用")})

    # 场景维度
    scenes = {}
    for r in samples:
        sc = str(r.get("scene") or "default")
        scenes.setdefault(sc, []).append(r)
    scene_rows = []
    for name, rs in scenes.items():
        scene_rows.append({
            "name": name, "samples": len(rs),
            "duration_s": r2((rs[-1]["t"] - rs[0]["t"]) / 1000.0 + 1, 1),
            "fps": r2(mean(values(rs, "fps"))), "cpu": r2(mean(values(rs, "cpu_app_pct"))),
            "pss": r2(mean(values(rs, "pss_kb"))),
            "jank": sum(int(x.get("jank") or 0) for x in rs),
            "t0": rs[0]["t"], "t1": rs[-1]["t"],
        })
    scene_rows.sort(key=lambda x: x["t0"])

    # 图表序列
    series = {}
    for k in ("fps", "frame_p95_ms", "cpu_app_pct", "pss_kb", "net_tx_bps",
              "net_rx_bps", "io_write_bps", "main_thread_busy_ms", "jank", "battery_pct"):
        series[k] = [[r2((r["t"] - t_start) / 1000.0, 2), r2(r.get(k), 2)]
                     for r in samples]

    gate = {
        "score_min": R["score_min"], "score": score,
        "critical": sum(1 for i in issues if i["severity"] == "critical"),
        "warn": sum(1 for i in issues if i["severity"] == "warn"),
        "max_critical": R["max_critical"], "max_warn": R["max_warn"],
    }
    gate["passed"] = (score >= R["score_min"] and gate["critical"] <= R["max_critical"]
                      and gate["warn"] <= R["max_warn"])
    gate["reasons"] = []
    if score < R["score_min"]:
        gate["reasons"].append("健康分 %d < %d" % (score, R["score_min"]))
    if gate["critical"] > R["max_critical"]:
        gate["reasons"].append("严重问题 %d > %d" % (gate["critical"], R["max_critical"]))
    if gate["warn"] > R["max_warn"]:
        gate["reasons"].append("警告 %d > %d" % (gate["warn"], R["max_warn"]))

    baseline_kpi = None
    if baseline:
        baseline_kpi = analyze(baseline, None, rules)["kpi"]

    raw = Path(s["path"]).read_bytes()
    return {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "source": {"file": Path(s["path"]).name, "label": source_label or Path(s["path"]).name,
                   "sha256": hashlib.sha256(raw).hexdigest()[:16], "lines": len(s["rows"])},
        "meta": meta, "kpi": kpi, "score": score, "issues": issues,
        "coverage": coverage, "scenes": scene_rows, "series": series,
        "events": events, "samples": samples, "frames": frames,
        "rules": R, "metric_defs": [list(x) for x in METRIC_DEFS],
        "baseline": baseline_kpi, "gate": gate, "validate": validate(s),
        "t_start": t_start, "fps_floor": r2(fps_floor),
    }


def render(data, out_path):
    tpl = TEMPLATE.read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"),
                         default=str, allow_nan=False)
    # 把所有 < 转成 unicode 转义，避免数据中含 </script> 时提前闭合脚本标签
    payload = payload.replace("<", "\\u003c")
    html = tpl.replace("__NOVAPERF_DATA__", payload)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(html, encoding="utf-8")
    return Path(out_path)


# ------------------------------------------------------------------ 设备侧操作

def status_remote(device, pkg):
    p = "/sdcard/Android/data/%s/files/novaperf/status.json" % pkg
    r = adb(device, "shell", "cat", p)
    try:
        return json.loads(r.stdout.strip())
    except Exception:
        return {}


def broadcast(device, component, action, *extras):
    return adb(device, "shell", "am", "broadcast", "-n", component,
               "-a", action, *[str(x) for x in extras], capture=True)


def pull_latest(device, pkg, dest):
    st = status_remote(device, pkg)
    remote = st.get("session_path")
    if not remote:
        raise RuntimeError("设备侧 status.json 没有 session_path，先运行 collect/START")
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    r = adb(device, "pull", remote, str(Path(dest)))
    if r.returncode != 0:
        raise RuntimeError("pull 失败: " + (r.stderr or r.stdout)[:400])
    return Path(dest), remote


# ------------------------------------------------------------------ 命令

def cmd_doctor(a):
    out("NovaPerf doctor — 环境自检")
    out("  Python       : %s" % sys.version.split()[0])
    out("  adb          : %s" % ADB)
    r = adb(None, "devices")
    devices = [l.split("\t")[0] for l in r.stdout.splitlines()[1:] if "\tdevice" in l]
    out("  设备         : %s" % (", ".join(devices) or "（无）"))
    for label, f in [("报告模板", TEMPLATE), ("SDK AAR", DIST / "NovaPerf-SDK.aar"),
                     ("Demo APK", DIST / "NovaPerf-Demo.apk")]:
        out("  %-10s: %s" % (label, "OK" if f.exists() else "缺失（%s）" % f))
    out("  规则阈值     : score_min=%s cpu_p95_max=%s jank_per_min=%s" %
        (RULES["score_min"], RULES["cpu_p95_max"], RULES["jank_per_min"]))
    return 0 if devices and TEMPLATE.exists() else 1


def cmd_validate(a):
    s = load_session(a.file)
    errs = validate(s)
    out("文件 %s | %d 行 | meta=%s sample=%d frame=%d event=%d summary=%s" % (
        a.file, len(s["rows"]), "有" if s["meta"] else "无",
        len(s["samples"]), len(s["frames"]), len(s["events"]), "有" if s["summary"] else "无"))
    if errs:
        for e in errs[:30]:
            out("  ✗ " + e)
        return 1
    out("  ✓ 数据契约校验通过（版本/时间戳单调/无 NaN/无空行）")
    return 0


def cmd_collect(a):
    device = a.device or pick_device()
    if not device:
        out("✗ 没有可用设备")
        return 1
    pkg = a.pkg
    np = "%s/com.novaperf.sdk.NovaControlReceiver" % pkg
    demo = "%s/com.novaperf.demo.DemoControlReceiver" % pkg
    out("设备 %s | 被测包 %s | 时长 %ss | 逐帧 %s" % (device, pkg, a.duration, a.frames))
    adb(device, "shell", "am", "force-stop", pkg)
    adb(device, "shell", "am", "start", "-n", "%s/%s" % (pkg, a.activity))
    time.sleep(a.launch_wait)
    broadcast(device, np, "com.novaperf.START",
              "--ez", "force", "true",
              "--el", "duration_ms", str(int(a.duration * 1000)),
              "--el", "interval_ms", str(int(a.interval)),
              "--ez", "frames", "true" if a.frames else "false",
              "--es", "scene", a.scene)
    t0 = time.time()
    if a.scenario != "none":
        steps = [
            (0.5, "com.novaperf.FLAG", ["--es", "label", "cli_begin"], np),
            (1.0, "com.novaperf.demo.CPU", ["--ei", "seconds", str(a.cpu_seconds)], demo),
            (float(a.cpu_seconds) + 1.5, "com.novaperf.demo.MEM", ["--ei", "mb", str(a.mem_mb)], demo),
            (float(a.cpu_seconds) + 3.5, "com.novaperf.demo.NET", ["--ei", "count", str(a.net_count)], demo),
            (float(a.cpu_seconds) + 6.5, "com.novaperf.demo.JANK", ["--ei", "ms", str(a.jank_ms)], demo),
            (float(a.cpu_seconds) + 8.0, "com.novaperf.demo.SCENE", ["--es", "scene", "battle"], demo),
            (float(a.cpu_seconds) + 10.0, "com.novaperf.demo.FREE", [], demo),
            (float(a.cpu_seconds) + 12.0, "com.novaperf.FLAG", ["--es", "label", "cli_end"], np),
        ]
        for at, action, extras, comp in steps:
            wait = at - (time.time() - t0)
            if wait > 0:
                time.sleep(wait)
            if action.startswith("com.novaperf.demo") and pkg != "com.novaperf.demo":
                continue
            broadcast(device, comp, action, *extras)
            out("  +%.1fs %s %s" % (at, action, " ".join(extras)))
    remain = a.duration - (time.time() - t0)
    if remain > 0:
        time.sleep(remain)
    broadcast(device, np, "com.novaperf.STOP")
    time.sleep(0.8)
    dest = a.out or str(DIST / ("session_%s.jsonl" % datetime.now().strftime("%Y%m%d_%H%M%S")))
    local, remote = pull_latest(device, pkg, dest)
    out("已拉取 %s -> %s (%d bytes)" % (remote, local, local.stat().st_size))
    s = load_session(local)
    errs = validate(s)
    out("数据校验: %s | sample=%d event=%d frame=%d" %
        ("通过" if not errs else "；".join(errs[:3]), len(s["samples"]), len(s["events"]), len(s["frames"])))
    if a.report:
        data = analyze(s)
        rp = a.report_out or str(DIST / "NovaPerf-Report.html")
        render(data, rp)
        out("诊断报告: %s | 健康分 %d | 问题 %d 项" % (rp, data["score"], len(data["issues"])))
    return 0


def cmd_pull(a):
    device = a.device or pick_device()
    local, remote = pull_latest(device, a.pkg, a.out)
    out("已拉取 %s -> %s" % (remote, local))
    return 0


def cmd_report(a):
    s = load_session(a.file)
    rules = json.loads(Path(a.rules).read_text(encoding="utf-8")) if a.rules else None
    baseline = load_session(a.baseline) if a.baseline else None
    data = analyze(s, baseline, rules, a.title)
    outp = a.out or str(DIST / "NovaPerf-Report.html")
    render(data, outp)
    out("报告 %s" % outp)
    out("  健康分 %d | 问题 %d（critical %d / warn %d / info %d）" % (
        data["score"], len(data["issues"]),
        sum(1 for i in data["issues"] if i["severity"] == "critical"),
        sum(1 for i in data["issues"] if i["severity"] == "warn"),
        sum(1 for i in data["issues"] if i["severity"] == "info")))
    out("  AvgFPS %s | 1%%Low %s | P95帧 %sms | CPU %s%% | PSS %sKB | Jank %s" % (
        data["kpi"]["avg_fps"], data["kpi"]["low1_fps"], data["kpi"]["frame_p95_ms"],
        data["kpi"]["cpu_avg"], data["kpi"]["pss_avg"], data["kpi"]["jank"]))
    for i in data["issues"][:8]:
        out("  [%s] %s — %s" % (i["severity"], i["title"], i["evidence"]))
    return 0


def cmd_gate(a):
    s = load_session(a.file)
    rules = json.loads(Path(a.rules).read_text(encoding="utf-8")) if a.rules else None
    d = analyze(s, None, rules)
    g = d["gate"]
    out("门禁 %s | 健康分 %d（≥%d）| critical %d（≤%d）| warn %d（≤%d）" % (
        "PASS" if g["passed"] else "FAIL", g["score"], g["score_min"],
        g["critical"], g["max_critical"], g["warn"], g["max_warn"]))
    for r in g["reasons"]:
        out("  ✗ " + r)
    for i in d["issues"]:
        out("  [%s] %s @%.1fs: %s" % (i["severity"], i["title"],
                                     (i["t0"] - d["t_start"]) / 1000.0, i["rule"]))
    return 0 if g["passed"] else 1


def cmd_diff(a):
    A = analyze(load_session(a.baseline))
    B = analyze(load_session(a.current))
    keys = ["avg_fps", "low1_fps", "frame_p95_ms", "cpu_avg", "cpu_p95",
            "pss_avg", "pss_max", "jank", "jank_per_min", "net_rx_peak_bps",
            "io_write_peak_bps", "main_thread_max_ms", "duration_s"]
    out("%-24s %14s %14s %14s" % ("指标", "基线", "当前", "变化"))
    for k in keys:
        x, y = A["kpi"].get(k), B["kpi"].get(k)
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            d = y - x
            ratio = (d / x * 100) if x else None
            out("%-24s %14s %14s %14s" % (k, x, y, "%+.2f (%+.1f%%)" % (d, ratio) if ratio is not None else "%+.2f" % d))
        else:
            out("%-24s %14s %14s %14s" % (k, x, y, "-"))
    out("健康分 %d -> %d (%+d)" % (A["score"], B["score"], B["score"] - A["score"]))
    if a.out:
        data = B
        data["baseline"] = A["kpi"]
        render(data, a.out)
        out("对比报告: %s" % a.out)
    return 0


def cmd_summary(a):
    d = analyze(load_session(a.file))
    print(json.dumps({"kpi": d["kpi"], "score": d["score"],
                      "issues": [{k: i[k] for k in ("id", "title", "severity", "evidence", "rule")}
                                 for i in d["issues"]], "gate": d["gate"]},
                     ensure_ascii=False, indent=2))
    return 0


def main():
    ap = argparse.ArgumentParser(prog="novaperf", description="NovaPerf 跨平台性能诊断 CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("doctor", help="环境自检")
    p.set_defaults(fn=cmd_doctor)

    p = sub.add_parser("validate", help="校验 JSONL 数据契约")
    p.add_argument("file")
    p.set_defaults(fn=cmd_validate)

    p = sub.add_parser("collect", help="真机一键采集（启动→负载→停止→拉取→报告）")
    p.add_argument("--device", default=None)
    p.add_argument("--pkg", default="com.novaperf.demo")
    p.add_argument("--activity", default="com.novaperf.demo.MainActivity")
    p.add_argument("--duration", type=float, default=25)
    p.add_argument("--interval", type=int, default=1000)
    p.add_argument("--frames", action="store_true", help="开启逐帧明细（可算精确 1%% Low）")
    p.add_argument("--scene", default="cli")
    p.add_argument("--scenario", choices=["full", "none"], default="full")
    p.add_argument("--cpu-seconds", type=int, default=6)
    p.add_argument("--mem-mb", type=int, default=60)
    p.add_argument("--net-count", type=int, default=20)
    p.add_argument("--jank-ms", type=int, default=350)
    p.add_argument("--launch-wait", type=float, default=1.5)
    p.add_argument("--out", default=None, help="会话 JSONL 本地路径")
    p.add_argument("--report", action="store_true", default=True)
    p.add_argument("--no-report", dest="report", action="store_false")
    p.add_argument("--report-out", default=None)
    p.set_defaults(fn=cmd_collect)

    p = sub.add_parser("pull", help="拉取设备最新会话")
    p.add_argument("--device", default=None)
    p.add_argument("--pkg", default="com.novaperf.demo")
    p.add_argument("--out", default=str(DIST / "session_latest.jsonl"))
    p.set_defaults(fn=cmd_pull)

    p = sub.add_parser("report", help="生成单文件离线诊断报告")
    p.add_argument("file")
    p.add_argument("-o", "--out", default=None)
    p.add_argument("--baseline", default=None)
    p.add_argument("--rules", default=None, help="覆盖阈值的 JSON 文件")
    p.add_argument("--title", default=None)
    p.set_defaults(fn=cmd_report)

    p = sub.add_parser("gate", help="CI 门禁（失败返回 1）")
    p.add_argument("file")
    p.add_argument("--rules", default=None)
    p.set_defaults(fn=cmd_gate)

    p = sub.add_parser("diff", help="与基线对比")
    p.add_argument("baseline")
    p.add_argument("current")
    p.add_argument("--out", default=None)
    p.set_defaults(fn=cmd_diff)

    p = sub.add_parser("summary", help="输出诊断 JSON（供流水线消费）")
    p.add_argument("file")
    p.set_defaults(fn=cmd_summary)

    a = ap.parse_args()
    try:
        return a.fn(a)
    except Exception as e:
        out("✗ %s" % e)
        if os.environ.get("NOVAPERF_DEBUG"):
            raise
        return 2


if __name__ == "__main__":
    sys.exit(main())
