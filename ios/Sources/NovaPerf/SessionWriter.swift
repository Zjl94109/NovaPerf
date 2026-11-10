import Foundation

/// JSONL 会话写入器：逐行 append + synchronize，进程被杀也不丢已采数据。
/// iOS 落在 Documents/novaperf（配合 UIFileSharingEnabled 可直接从 Finder 导出）。
public final class SessionWriter {
    public let fileURL: URL
    public let sessionId: String
    public let startedAt: Int64
    private let handle: FileHandle
    private let lock = NSLock()
    private var closed = false
    private var sampleCount = 0
    private var frameCount = 0

    public init(directory: URL? = nil) throws {
        let dir = directory ?? SessionWriter.defaultDirectory()
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyyMMdd_HHmmss_SSS"
        formatter.locale = Locale(identifier: "en_US_POSIX")
        let now = Date()
        sessionId = formatter.string(from: now)
        startedAt = Int64(now.timeIntervalSince1970 * 1000.0)
        fileURL = dir.appendingPathComponent("session_\(sessionId).jsonl")
        if !FileManager.default.fileExists(atPath: fileURL.path) {
            FileManager.default.createFile(atPath: fileURL.path, contents: nil)
        }
        handle = try FileHandle(forWritingTo: fileURL)
    }

    public static func defaultDirectory() -> URL {
        #if os(iOS)
        let base = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first!
        #else
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        #endif
        return base.appendingPathComponent("novaperf", isDirectory: true)
    }

    public func write(_ object: [String: Any]) {
        let text = Schema.line(object) + "\n"
        guard let data = text.data(using: .utf8) else { return }
        lock.lock()
        defer { lock.unlock() }
        if closed { return }
        do {
            try handle.seekToEnd()
            try handle.write(contentsOf: data)
            try? handle.synchronize()
        } catch {
            // 写盘失败不打断被测 App
        }
    }

    public func incSample() {
        lock.lock(); sampleCount += 1; lock.unlock()
    }

    public func noteFrames(_ n: Int) {
        lock.lock(); frameCount += n; lock.unlock()
    }

    public func writeMeta(app: String, appName: String, appVersion: String,
                          model: String, os: String, cores: Int, refreshHz: Double) {
        write([
            "v": Schema.version, "t": startedAt, "type": "meta",
            "session_id": sessionId, "platform": "ios",
            "app": app, "app_name": appName, "app_version": appVersion,
            "device": "Apple", "model": model, "os": os,
            "api": Schema.null(), "cores": cores, "refresh_hz": refreshHz,
            "root_required": false, "sdk": Schema.sdkTag, "started_at": startedAt
        ])
    }

    public func writeEvent(kind: String, level: String, label: String,
                           detail: Any?, stack: Any?, durationMs: Any?, page: String?) {
        write([
            "v": Schema.version, "t": Schema.nowMs(), "type": "event",
            "kind": kind, "level": level, "label": label,
            "detail": detail ?? Schema.null(), "stack": stack ?? Schema.null(),
            "page": page ?? Schema.null(), "duration_ms": durationMs ?? Schema.null()
        ])
    }

    public func writeSummary() {
        lock.lock()
        let samples = sampleCount, frames = frameCount
        lock.unlock()
        write([
            "v": Schema.version, "t": Schema.nowMs(), "type": "summary",
            "duration_ms": Schema.nowMs() - startedAt,
            "samples": samples, "frames": frames
        ])
    }

    public func close() {
        lock.lock()
        defer { lock.unlock() }
        if closed { return }
        closed = true
        try? handle.synchronize()
        try? handle.close()
    }
}
