import Foundation
#if os(iOS)
import UIKit
#endif

/// 帧采集。iOS 用 CADisplayLink；macOS（CI 单元测试）用空实现，保证 swift test 可跑。
public final class FrameMonitor: NSObject {

    public struct Stats {
        public var fps: Double?
        public var frameMs: Double?
        public var p95Ms: Double?
        public var jank: Int = 0
        public var bigJank: Int = 0
        public var frozen: Int = 0
        public var frames: Int = 0
    }

    /// 可选逐帧明细；dt 单位 ms。
    public var onFrame: ((Double, Bool, Bool) -> Void)?
    public var onFirstFrame: (() -> Void)?

    private let lock = NSLock()
    private var window: [Double] = []
    private var last3: [Double] = []
    private var jank = 0, bigJank = 0, frozen = 0
    private var firstReported = false

    #if os(iOS)
    private var link: CADisplayLink?
    private var lastTimestamp: CFTimeInterval = 0
    #endif

    public func start() {
        #if os(iOS)
        lock.lock()
        window.removeAll(); last3.removeAll(); jank = 0; bigJank = 0; frozen = 0
        firstReported = false
        lock.unlock()
        lastTimestamp = 0
        let displayLink = CADisplayLink(target: self, selector: #selector(step(_:)))
        displayLink.add(to: .main, forMode: .common)
        link = displayLink
        #endif
    }

    public func stop() {
        #if os(iOS)
        link?.invalidate()
        link = nil
        #endif
    }

    #if os(iOS)
    @objc private func step(_ link: CADisplayLink) {
        let ts = link.timestamp
        if lastTimestamp > 0 {
            let dt = (ts - lastTimestamp) * 1000.0
            if dt > 0 && dt < 1000 {
                var isJank = false, isBig = false
                lock.lock()
                let prev3 = last3.isEmpty ? 0 : last3.reduce(0, +) / Double(last3.count)
                isJank = prev3 > 0 && dt > 2 * prev3 && dt > 84
                isBig = isJank && dt > 125
                if isJank { jank += 1 }
                if isBig { bigJank += 1 }
                if dt > 700 { frozen += 1 }
                window.append(dt)
                last3.append(dt)
                if last3.count > 3 { last3.removeFirst() }
                lock.unlock()
                onFrame?(dt, isJank, isBig)
            } else if dt >= 1000 {
                lock.lock(); last3.removeAll(); lock.unlock()
            }
        }
        lastTimestamp = ts
        if !firstReported {
            firstReported = true
            onFirstFrame?()
        }
    }
    #endif

    /// 取走本窗口统计并重置。
    public func drain(windowMs: Double) -> Stats {
        var s = Stats()
        lock.lock()
        defer { lock.unlock() }
        s.frames = window.count
        if !window.isEmpty {
            s.frameMs = window.reduce(0, +) / Double(window.count)
            s.p95Ms = Schema.percentile(window, 0.95)
            s.fps = windowMs > 0 ? Double(window.count) * 1000.0 / windowMs : nil
        }
        s.jank = jank; s.bigJank = bigJank; s.frozen = frozen
        window.removeAll(); jank = 0; bigJank = 0; frozen = 0
        return s
    }
}
