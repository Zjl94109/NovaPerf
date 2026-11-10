import Foundation
import Dispatch
#if os(iOS)
import UIKit
#endif

#if canImport(Darwin)
private var previousNovaPerfExceptionHandler: (@convention(c) (NSException) -> Void)?
#endif

/// NovaPerf iOS SDK：免越狱、无私有 API、无第三方依赖，输出与 Android 完全相同的 JSONL 契约。
///
/// 接入：
///   NovaPerf.shared.start()                       // AppDelegate / SceneDelegate
///   NovaPerf.shared.setScene("battle")
///   NovaPerf.shared.flag("进入战斗")
///   NovaPerf.shared.noteHTTP(url:..., durationMs:..., statusCode:200, error:false)
///   NovaPerf.shared.stop()
public final class NovaPerf {

    public static let shared = NovaPerf()

    private static let processStart = Date()

    private let stateQueue = DispatchQueue(label: "com.novaperf.state", qos: .utility)
    private var writer: SessionWriter?
    private var timer: DispatchSourceTimer?
    private var watchdogTimer: DispatchSourceTimer?
    private let frames = FrameMonitor()

    private var isRunning = false
    private var intervalMs = 1000
    private var frameDetail = false
    private var scene = "default"
    private var page = "unknown"
    private var seq = 0
    private var startDate: Date?
    private var sessionDirectory: URL?

    private var prevCPU: Double?
    private var prevWall: TimeInterval = 0
    private var netReq = 0
    private var netErr = 0
    private var maxDelay: Double = 0
    private var anrRisk = 0
    private var anrFired = false
    private var lastBeat = Date()

    private init() {}

    // ------------------------------------------------------------ 公共 API

    public var running: Bool { stateQueue.sync { isRunning } }

    public var currentSessionPath: String? { stateQueue.sync { writer?.fileURL.path } }

    public func start(durationMs: Int64 = 0, intervalMs: Int = 1000,
                      frameDetail: Bool = false, scene: String = "default",
                      directory: URL? = nil) {
        stateQueue.sync {
            guard !isRunning else { return }
            let w: SessionWriter
            do {
                w = try SessionWriter(directory: directory)
            } catch {
                NSLog("[NovaPerf] cannot open session: \(error)")
                return
            }
            writer = w
            sessionDirectory = (directory ?? SessionWriter.defaultDirectory())
            self.intervalMs = max(200, intervalMs)
            self.frameDetail = frameDetail
            self.scene = scene
            seq = 0
            startDate = Date()
            prevCPU = Collectors.cpuTimeSeconds()
            prevWall = Date().timeIntervalSince1970
            netReq = 0; netErr = 0; maxDelay = 0; anrRisk = 0; anrFired = false

            let app = Collectors.appInfo()
            w.writeMeta(app: app.id, appName: app.name, appVersion: app.version,
                        model: Collectors.modelIdentifier(), os: Collectors.osVersion(),
                        cores: Collectors.cores(), refreshHz: Collectors.refreshHz())

            frames.onFrame = { [weak self] dt, jank, bigJank in
                guard let self = self, self.frameDetail else { return }
                self.writer?.write([
                    "v": Schema.version, "t": Schema.nowMs(), "type": "frame",
                    "dt_ms": dt, "jank": jank, "big_jank": bigJank
                ])
            }
            frames.onFirstFrame = { [weak self] in
                guard let self = self else { return }
                let ms = Date().timeIntervalSince(NovaPerf.processStart) * 1000.0
                self.stateQueue.async {
                    self.eventUnsafe(kind: "lifecycle", level: "info", label: "cold_start",
                                     detail: "Application init -> first frame", stack: nil,
                                     durationMs: ms, page: self.page)
                }
            }
            // CADisplayLink 必须在主线程注册
            DispatchQueue.main.async { self.frames.start() }

            isRunning = true
            installCrashHandlerOnce()
            eventUnsafe(kind: "lifecycle", level: "info", label: "session_start",
                        detail: "SDK 自采集会话开始", stack: nil, durationMs: nil, page: page)
            startTimer()
            startWatchdog()
            writeStatusUnsafe()
            if durationMs > 0 {
                stateQueue.asyncAfter(deadline: .now() + .milliseconds(Int(durationMs))) { [weak self] in
                    self?.stop()
                }
            }
        }
    }

    public func stop() {
        stateQueue.sync {
            guard isRunning else { return }
            isRunning = false
            timer?.cancel(); timer = nil
            watchdogTimer?.cancel(); watchdogTimer = nil
            let f = frames
            DispatchQueue.main.async { f.stop() }
            eventUnsafe(kind: "lifecycle", level: "info", label: "session_stop",
                        detail: nil, stack: nil, durationMs: nil, page: page)
            writer?.writeSummary()
            writer?.close()
            writeStatusUnsafe()
            writer = nil
        }
    }

    public func flag(_ label: String, detail: String? = nil) {
        stateQueue.async {
            self.eventUnsafe(kind: "scene", level: "info", label: label,
                             detail: detail, stack: nil, durationMs: nil, page: self.page)
        }
    }

    public func setScene(_ name: String) {
        guard !name.isEmpty else { return }
        stateQueue.async {
            self.scene = name
            self.eventUnsafe(kind: "scene", level: "info", label: "场景切换:" + name,
                             detail: nil, stack: nil, durationMs: nil, page: self.page)
        }
    }

    public func setPage(_ name: String) {
        stateQueue.async { self.page = name }
    }

    public func lifecycle(_ label: String) {
        stateQueue.async {
            self.eventUnsafe(kind: "lifecycle", level: "info", label: label,
                             detail: nil, stack: nil, durationMs: nil, page: self.page)
        }
    }

    public func log(_ level: String, _ message: String) {
        stateQueue.async {
            self.eventUnsafe(kind: "log", level: level, label: message,
                             detail: nil, stack: nil, durationMs: nil, page: self.page)
        }
    }

    /// 与 URLSessionTaskMetrics 配合使用：net_req / net_err 与 http 事件。
    public func noteHTTP(url: String, durationMs: Double, statusCode: Int, error: Bool) {
        stateQueue.async {
            self.netReq += 1
            if error { self.netErr += 1 }
            let label = (statusCode > 0 ? "\(statusCode) " : "") + String(url.prefix(180))
            self.eventUnsafe(kind: "http", level: error ? "error" : "info", label: label,
                             detail: nil, stack: nil, durationMs: durationMs, page: self.page)
        }
    }

    /// 供 CLI / 应用内 UI 读取的状态（与 Android status.json 同构）。
    public func status() -> String {
        stateQueue.sync {
            Schema.line([
                "running": isRunning,
                "sdk": Schema.sdkTag,
                "session_path": writer?.fileURL.path.map { $0 as Any } ?? Schema.null(),
                "started_at": startDate.map { Int64($0.timeIntervalSince1970 * 1000) as Any } ?? Schema.null(),
                "samples": seq,
                "scene": scene,
                "page": page
            ])
        }
    }

    public func sessionFiles() -> [URL] {
        let dir = sessionDirectory ?? SessionWriter.defaultDirectory()
        let files = (try? FileManager.default.contentsOfDirectory(
            at: dir, includingPropertiesForKeys: nil, options: .skipsHiddenFiles)) ?? []
        return files.filter { $0.pathExtension == "jsonl" }.sorted { $0.lastPathComponent < $1.lastPathComponent }
    }

    // ------------------------------------------------------------ 采样

    private func startTimer() {
        let t = DispatchSource.makeTimerSource(queue: stateQueue)
        t.schedule(deadline: .now() + .milliseconds(intervalMs),
                   repeating: .milliseconds(intervalMs))
        t.setEventHandler { [weak self] in
            guard let self = self, self.isRunning else { return }
            self.sampleOnce()
        }
        t.resume()
        timer = t
    }

    private func sampleOnce() {
        let now = Date()
        let wall = now.timeIntervalSince1970
        let dtMs = max(1.0, (wall - prevWall) * 1000.0)
        let cpu = Collectors.cpuTimeSeconds()
        var cpuPct: Any = Schema.null()
        if let c = cpu, let p = prevCPU, dtMs > 0 {
            let v = 100.0 * (c - p) / (dtMs / 1000.0)
            cpuPct = min(100.0, max(0.0, v))
        }
        prevCPU = cpu
        prevWall = wall

        let fs = frames.drain(windowMs: dtMs)
        writer?.noteFrames(fs.frames)
        let busy = maxDelay; maxDelay = 0
        let risk = anrRisk; anrRisk = 0
        let req = netReq; netReq = 0
        let err = netErr; netErr = 0
        seq += 1

        let mem = Collectors.physFootprintKB()
        let sample: [String: Any] = [
            "v": Schema.version, "t": Schema.nowMs(), "type": "sample", "seq": seq,
            "fps": box(fs.fps), "frame_ms": box(fs.frameMs), "frame_p95_ms": box(fs.p95Ms),
            "jank": fs.jank, "big_jank": fs.bigJank, "frozen": fs.frozen,
            "cpu_app_pct": cpuPct, "cpu_sys_pct": Schema.null(),
            "threads": boxI(Collectors.threadCount()), "fds": Schema.null(),
            "pss_kb": boxI(mem.map { Int($0.rounded()) }),
            "heap_kb": Schema.null(), "native_kb": Schema.null(), "gc_count": Schema.null(),
            "net_tx_bps": Schema.null(), "net_rx_bps": Schema.null(),
            "net_req": req, "net_err": err,
            "io_read_bps": Schema.null(), "io_write_bps": Schema.null(),
            "battery_pct": box(Collectors.batteryPercent()), "temp_c": Schema.null(),
            "thermal_state": Collectors.thermalState(), "gpu_pct": Schema.null(),
            "main_thread_busy_ms": busy, "anr_risk": risk,
            "page": page, "scene": scene
        ]
        writer?.write(sample)
        writer?.incSample()
    }

    // ------------------------------------------------------------ 主线程 watchdog

    private func startWatchdog() {
        lastBeat = Date()
        scheduleHeartbeat()
        let t = DispatchSource.makeTimerSource(queue: stateQueue)
        t.schedule(deadline: .now(), repeating: .milliseconds(250))
        t.setEventHandler { [weak self] in
            guard let self = self, self.isRunning else { return }
            let gap = Date().timeIntervalSince(self.lastBeat)
            if gap > 2.0 {
                if !self.anrFired {
                    self.anrFired = true
                    self.anrRisk = 1
                    self.eventUnsafe(kind: "anr", level: "error", label: "疑似主线程阻塞(>2s)",
                                     detail: "NovaPerf watchdog，非系统 ANR 弹窗",
                                     stack: nil, durationMs: nil, page: self.page)
                }
            } else if gap < 1.0 {
                self.anrFired = false
            }
        }
        t.resume()
        watchdogTimer = t
    }

    private func scheduleHeartbeat() {
        let scheduled = Date()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self] in
            guard let self = self else { return }
            self.stateQueue.async {
                guard self.isRunning else { return }
                let delay = max(0.0, Date().timeIntervalSince(scheduled) - 0.5) * 1000.0
                self.maxDelay = max(self.maxDelay, delay)
                self.lastBeat = Date()
                self.scheduleHeartbeat()
            }
        }
    }

    // ------------------------------------------------------------ 事件 / 崩溃 / 状态

    private func eventUnsafe(kind: String, level: String, label: String,
                             detail: Any?, stack: Any?, durationMs: Any?, page: String?) {
        writer?.writeEvent(kind: kind, level: level, label: label,
                           detail: detail, stack: stack,
                           durationMs: durationMs, page: page)
    }

    private var crashInstalled = false

    private func installCrashHandlerOnce() {
        guard !crashInstalled else { return }
        // NSUncaughtExceptionHandler 是 Darwin/Objective-C 运行时能力；Linux（CI）无此 API。
        #if canImport(Darwin)
        crashInstalled = true
        previousNovaPerfExceptionHandler = NSGetUncaughtExceptionHandler()
        NSSetUncaughtExceptionHandler { exception in
            NovaPerf.shared.recordCrash(reason: exception.reason,
                                        stack: exception.callStackSymbols.joined(separator: "\n"))
            previousNovaPerfExceptionHandler?(exception)
        }
        #endif
    }

    private func recordCrash(reason: String?, stack: String) {
        stateQueue.sync {
            eventUnsafe(kind: "crash", level: "error", label: "未捕获异常",
                        detail: reason, stack: stack, durationMs: nil, page: page)
            writer?.writeSummary()
            writer?.close()
        }
    }

    private func writeStatusUnsafe() {
        let dir = sessionDirectory ?? SessionWriter.defaultDirectory()
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let url = dir.appendingPathComponent("status.json")
        let text = Schema.line([
            "running": isRunning,
            "sdk": Schema.sdkTag,
            "session_path": writer?.fileURL.path.map { $0 as Any } ?? Schema.null(),
            "started_at": startDate.map { Int64($0.timeIntervalSince1970 * 1000) as Any } ?? Schema.null(),
            "samples": seq,
            "scene": scene,
            "page": page
        ])
        try? (text + "\n").write(to: url, atomically: true, encoding: .utf8)
    }

    private func box(_ v: Double?) -> Any { v.map { $0 as Any } ?? Schema.null() }
    private func boxI(_ v: Int?) -> Any { v.map { $0 as Any } ?? Schema.null() }
}
