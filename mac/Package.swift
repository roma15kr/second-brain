// swift-tools-version:5.10
// The owner's Mac recorder (mac-recorder-v1): a menu-bar app for dictation and call recording.
// RecorderCore holds the logic that CI can test without audio devices; the app target holds the
// macOS glue (menu bar, audio capture, hotkeys, speech runtime).
import PackageDescription

let package = Package(
    name: "SecondBrainRecorder",
    platforms: [.macOS(.v15)],
    products: [
        .executable(name: "SecondBrainRecorder", targets: ["SecondBrainRecorder"]),
        .library(name: "RecorderCore", targets: ["RecorderCore"]),
    ],
    targets: [
        .target(name: "RecorderCore"),
        .executableTarget(name: "SecondBrainRecorder", dependencies: ["RecorderCore"]),
        .testTarget(name: "RecorderCoreTests", dependencies: ["RecorderCore"]),
    ]
)
