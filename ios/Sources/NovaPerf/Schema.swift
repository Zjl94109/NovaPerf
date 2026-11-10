import Foundation

/// 与 Android 完全一致的 JSONL 数据契约 v1（docs/DATA_SCHEMA.md）。
/// 平台不支持的指标一律写 JSON null，绝不填 0 冒充。
public enum Schema {
    public static let version = 1
    public static let sdkTag = "novaperf/1.0.0"

    public static func nowMs() -> Int64 {
        Int64(Date().timeIntervalSince1970 * 1000.0)
    }

    /// 把字典序列化为单行 JSON；NaN / Infinity 自动降级为 null。
    public static func line(_ object: [String: Any]) -> String {
        var safe: [String: Any] = [:]
        for (key, value) in object {
            if let d = value as? Double, !d.isFinite {
                safe[key] = NSNull()
            } else if let f = value as? Float, !f.isFinite {
                safe[key] = NSNull()
            } else {
                safe[key] = value
            }
        }
        guard JSONSerialization.isValidJSONObject(safe),
              let data = try? JSONSerialization.data(withJSONObject: safe,
                                                    options: [.sortedKeys, .withoutEscapingSlashes]),
              let text = String(data: data, encoding: .utf8) else {
            return "{}"
        }
        return text
    }

    /// 线性插值分位数，与 CLI 诊断引擎口径一致。
    public static func percentile(_ values: [Double], _ q: Double) -> Double? {
        let v = values.filter { $0.isFinite }.sorted()
        guard !v.isEmpty else { return nil }
        if v.count == 1 { return v[0] }
        let k = Double(v.count - 1) * q
        let lo = Int(floor(k)), hi = Int(ceil(k))
        if lo == hi { return v[lo] }
        return v[lo] + (v[hi] - v[lo]) * (k - Double(lo))
    }

    public static func null() -> Any { NSNull() }
}
