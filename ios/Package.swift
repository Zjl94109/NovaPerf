// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "NovaPerf",
    platforms: [
        .iOS(.v14),
        .macOS(.v12)
    ],
    products: [
        .library(name: "NovaPerf", targets: ["NovaPerf"])
    ],
    targets: [
        .target(name: "NovaPerf", path: "Sources/NovaPerf"),
        .testTarget(name: "NovaPerfTests", dependencies: ["NovaPerf"], path: "Tests/NovaPerfTests")
    ]
)
