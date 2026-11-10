# 示例会话（真机原始数据）

两份文件均由 OnePlus PJT110 / Android 16 / 免 ROOT 真机上的 NovaPerf Demo 采集，**未做任何手工修改**，可直接用于复现报告、门禁和基线对比。

| 文件 | 行数 | 内容 |
|---|---|---|
| `session_realdevice.jsonl` | 87 | 47 sample / 38 event / 1 meta / 1 summary / 0 frame（窗口聚合模式） |
| `session_frames.jsonl` | 1535+ | 24 sample / 36 event / 1474 frame（逐帧精确模式，含 1% Low） |

复现：

```bash
python cli/novaperf.py validate examples/session_frames.jsonl
python cli/novaperf.py report examples/session_frames.jsonl \
  --baseline examples/session_realdevice.jsonl \
  --title "NovaPerf 端到端真机验证（逐帧精确）" -o dist/NovaPerf-Report.html
python cli/novaperf.py gate examples/session_frames.jsonl       # 预期 PASS
python cli/novaperf.py diff examples/session_realdevice.jsonl examples/session_frames.jsonl
```

会话中制造的可对照负载：CPU 忙循环 6s、分配 60MB、20 个 HTTPS 请求、主线程 350ms 阻塞、场景切换与释放内存。报告中应能看到 CPU / PSS / NET / IO / 主线程延迟随负载变化，以及「启动阶段掉帧」这一条 warn。

`dist/report_preview.png` 是最终报告的无头浏览器渲染截图。
