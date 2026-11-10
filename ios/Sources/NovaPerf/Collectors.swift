import Foundation
#if canImport(Darwin)
import Darwin
#endif
#if os(iOS)
import UIKit
#endif

/// 免越狱采集器：只用公开 API 与 Mach task_info；读不到的字段返回 nil（写入 JSON null）。
public enum Collectors {

    /// 进程累计 CPU 时间（秒）= task_basic_info.user_time + system_time。
    /// 与 Android 的 /proc/self/stat jiffies 差分是同一口径：Δcpu_time / Δwall。
    public static func cpuTimeSeconds() -> Double? {
        #if canImport(Darwin)
        var info = task_basic_info()
        var count = mach_msg_type_number_t(MemoryLayout<task_basic_info>.size / MemoryLayout<integer_t>.size)
        let kr = withUnsafeMutablePointer(to: &info) { ptr -> kern_return_t in
            ptr.withMemoryRebound(to: integer_t.self, capacity: Int(count)) { p in
                task_info(mach_task_self_, task_flavor_t(TASK_BASIC_INFO), p, &count)
            }
        }
        guard kr == KERN_SUCCESS else { return nil }
        let user = Double(info.user_time.seconds) + Double(info.user_time.microseconds) / 1_000_000.0
        let sys = Double(info.system_time.seconds) + Double(info.system_time.microseconds) / 1_000_000.0
        return user + sys
        #else
        return nil
        #endif
    }

    /// phys_footprint（KB）—— 与 Xcode Memory Gauge 同源。
    public static func physFootprintKB() -> Double? {
        #if canImport(Darwin)
        var info = task_vm_info()
        var count = mach_msg_type_number_t(MemoryLayout<task_vm_info>.size / MemoryLayout<integer_t>.size)
        let kr = withUnsafeMutablePointer(to: &info) { ptr -> kern_return_t in
            ptr.withMemoryRebound(to: integer_t.self, capacity: Int(count)) { p in
                task_info(mach_task_self_, task_flavor_t(TASK_VM_INFO), p, &count)
            }
        }
        guard kr == KERN_SUCCESS else { return nil }
        return Double(info.phys_footprint) / 1024.0
        #else
        return nil
        #endif
    }

    /// 线程数（task_threads）。
    public static func threadCount() -> Int? {
        #if canImport(Darwin)
        var list: thread_act_array_t?
        var count: mach_msg_type_number_t = 0
        let kr = task_threads(mach_task_self_, &list, &count)
        guard kr == KERN_SUCCESS, let arr = list else { return nil }
        let n = Int(count)
        let address = unsafeBitCast(arr, to: UInt.self)
        vm_deallocate(mach_task_self_, vm_address_t(address),
                      vm_size_t(n * MemoryLayout<thread_act_t>.size))
        return n
        #else
        return nil
        #endif
    }

    /// 电量百分比；模拟器/未开启监控时返回 nil。
    public static func batteryPercent() -> Double? {
        #if os(iOS) && !targetEnvironment(simulator)
        let device = UIDevice.current
        if !device.isBatteryMonitoringEnabled { device.isBatteryMonitoringEnabled = true }
        let level = device.batteryLevel
        return level >= 0 ? Double(level) * 100.0 : nil
        #else
        return nil
        #endif
    }

    /// 热状态：nominal / fair / serious / critical / unknown。
    /// Linux（CI）的 Foundation 无 thermalState，诚实返回 unknown，不编造数值。
    public static func thermalState() -> String {
        #if canImport(Darwin)
        switch ProcessInfo.processInfo.thermalState {
        case .nominal: return "nominal"
        case .fair: return "fair"
        case .serious: return "serious"
        case .critical: return "critical"
        @unknown default: return "unknown"
        }
        #else
        return "unknown"
        #endif
    }

    public static func refreshHz() -> Double {
        #if os(iOS)
        return Double(UIScreen.main.maximumFramesPerSecond)
        #else
        return 60.0
        #endif
    }

    public static func cores() -> Int {
        ProcessInfo.processInfo.activeProcessorCount
    }

    public static func osVersion() -> String {
        #if os(iOS)
        return "iOS " + UIDevice.current.systemVersion
        #elseif os(Linux)
        return "Linux " + ProcessInfo.processInfo.operatingSystemVersionString
        #else
        return "macOS " + ProcessInfo.processInfo.operatingSystemVersionString
        #endif
    }

    public static func modelIdentifier() -> String {
        #if canImport(Darwin)
        var systemInfo = utsname()
        uname(&systemInfo)
        return withUnsafePointer(to: &systemInfo.machine) { ptr in
            ptr.withMemoryRebound(to: CChar.self,
                                  capacity: MemoryLayout.size(ofValue: systemInfo.machine)) {
                String(cString: $0)
            }
        }
        #else
        return "unknown"
        #endif
    }

    public static func appInfo() -> (id: String, name: String, version: String) {
        let bundle = Bundle.main
        let id = bundle.bundleIdentifier ?? "unknown"
        let name = (bundle.object(forInfoDictionaryKey: "CFBundleName") as? String) ?? id
        let version = (bundle.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String) ?? "unknown"
        return (id, name, version)
    }
}
