import XCTest
import Foundation
@testable import NovaPerf

final class NovaPerfTests: XCTestCase {

    func testPercentileMatchesCLIEngine() {
        XCTAssertEqual(Schema.percentile([10, 20, 30, 40], 0.5) ?? -1, 25, accuracy: 0.0001)
        XCTAssertEqual(Schema.percentile([16.6], 0.95) ?? -1, 16.6, accuracy: 0.0001)
        XCTAssertNil(Schema.percentile([], 0.95))
    }

    func testJSONLineWritesNullForNonFiniteAndNonNumeric() throws {
        let text = Schema.line([
            "v": 1, "type": "sample",
            "gpu_pct": Schema.null(),
            "cpu_app_pct": Double.nan,
            "fps": 59.6
        ])
        let data = try XCTUnwrap(text.data(using: .utf8))
        let obj = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertTrue(obj["gpu_pct"] is NSNull)
        XCTAssertTrue(obj["cpu_app_pct"] is NSNull, "NaN 必须降级为 null")
        XCTAssertEqual(obj["v"] as? Int, 1)
    }

    func testSessionWritesMetaSamplesAndSummary() throws {
        let dir = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("novaperf-test-" + UUID().uuidString, isDirectory: true)
        NovaPerf.shared.start(intervalMs: 200, directory: dir)
        XCTAssertTrue(NovaPerf.shared.running)
        Thread.sleep(forTimeInterval: 0.9)
        NovaPerf.shared.stop()
        XCTAssertFalse(NovaPerf.shared.running)

        let files = NovaPerf.shared.sessionFiles()
        XCTAssertEqual(files.count, 1)
        let content = try String(contentsOf: files[0], encoding: .utf8)
        let lines = content.split(separator: "\n").map(String.init).filter { !$0.isEmpty }
        XCTAssertGreaterThanOrEqual(lines.count, 3)

        let objects = try lines.map { line -> [String: Any] in
            let data = try XCTUnwrap(line.data(using: .utf8))
            return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        }
        XCTAssertEqual(objects.first?["type"] as? String, "meta")
        XCTAssertEqual(objects.first?["platform"] as? String, "ios")
        XCTAssertEqual(objects.first?["root_required"] as? Bool, false)
        XCTAssertEqual(objects.last?["type"] as? String, "summary")

        let samples = objects.filter { $0["type"] as? String == "sample" }
        XCTAssertGreaterThanOrEqual(samples.count, 1)
        for s in samples {
            XCTAssertTrue(s["gpu_pct"] is NSNull, "免越狱设备 GPU 占用不可得，必须写 null")
            XCTAssertTrue(s["cpu_sys_pct"] is NSNull)
            XCTAssertTrue(s["net_rx_bps"] is NSNull, "iOS 无系统级按 App 流量统计")
            XCTAssertNotNil(s["seq"])
            XCTAssertNotNil(s["scene"])
        }
        try? FileManager.default.removeItem(at: dir)
    }

    func testStatusReportsRunningState() {
        let status = NovaPerf.shared.status()
        XCTAssertTrue(status.contains("\"running\""))
        XCTAssertTrue(status.contains("novaperf/1.0.0"))
    }
}
