import Foundation
import RecorderCore

/// Downloads the speech model inside the app (the .dmg install has no script to do it).
/// The pins are the same as in install.sh; CI checks that they match.
public enum SpeechDownloads {
    public struct File: Sendable {
        public let url: URL
        public let sha256: String
        public let archive: Bool  // .tar.bz2 to unpack into the models folder
        public let bytes: Int64
    }

    public static let model = File(
        url: URL(string: "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2")!,
        sha256: "5793d0fd397c5778d2cf2126994d58e9d56b1be7c04d13c7a15bb1b4eafb16bf", archive: true, bytes: 487_170_055)
    public static let vad = File(
        url: URL(string: "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx")!,
        sha256: "9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6", archive: false, bytes: 643_854)
}

@MainActor
public final class ModelInstaller: ObservableObject {
    @Published public private(set) var progress: Double?  // 0…1 while downloading
    @Published public private(set) var error: String?
    @Published public private(set) var installed = Models.installed

    public init() {}

    public func install() async {
        guard progress == nil, !Models.installed else { return }
        error = nil
        progress = 0
        defer { progress = nil; installed = Models.installed }
        do {
            try FileManager.default.createDirectory(at: Models.dir, withIntermediateDirectories: true)
            let total = Double(SpeechDownloads.model.bytes + SpeechDownloads.vad.bytes)
            var done: Double = 0
            for file in [SpeechDownloads.vad, SpeechDownloads.model] {
                let local = try await download(file) { [weak self] got in
                    self?.progress = (done + Double(got)) / total
                }
                done += Double(file.bytes)
                if file.archive {
                    let tar = Process()
                    tar.executableURL = URL(fileURLWithPath: "/usr/bin/tar")
                    tar.arguments = ["xjf", local.path, "-C", Models.dir.path]
                    try tar.run()
                    await withCheckedContinuation { c in DispatchQueue.global().async { tar.waitUntilExit(); c.resume() } }
                    guard tar.terminationStatus == 0 else { throw CaptureError(message: "could not unpack the model") }
                    try? FileManager.default.removeItem(at: local)
                } else {
                    try? FileManager.default.removeItem(at: Models.vad)
                    try FileManager.default.moveItem(at: local, to: Models.vad)
                }
            }
        } catch {
            self.error = "Speech model download failed: \(error.localizedDescription)"
        }
    }

    private func download(_ file: SpeechDownloads.File, progress: @escaping @MainActor (Int64) -> Void) async throws -> URL {
        let (bytes, response) = try await URLSession.shared.bytes(from: file.url)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else {
            throw CaptureError(message: "the download server answered \((response as? HTTPURLResponse)?.statusCode ?? 0)")
        }
        let out = FileManager.default.temporaryDirectory.appendingPathComponent(file.url.lastPathComponent)
        FileManager.default.createFile(atPath: out.path, contents: nil)
        let handle = try FileHandle(forWritingTo: out)
        var buffer = Data()
        var got: Int64 = 0
        for try await byte in bytes {
            buffer.append(byte)
            if buffer.count >= 1 << 20 {
                try handle.write(contentsOf: buffer)
                got += Int64(buffer.count)
                buffer.removeAll(keepingCapacity: true)
                await progress(got)
            }
        }
        try handle.write(contentsOf: buffer)
        try handle.close()
        guard try DeviceAPI.sha256(of: out) == file.sha256 else {
            try? FileManager.default.removeItem(at: out)
            throw CaptureError(message: "checksum mismatch for \(file.url.lastPathComponent)")
        }
        return out
    }
}
