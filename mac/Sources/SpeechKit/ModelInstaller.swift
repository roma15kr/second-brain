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
                let present = file.archive
                    ? FileManager.default.fileExists(atPath: Models.parakeetDir.appendingPathComponent("encoder.int8.onnx").path)
                    : FileManager.default.fileExists(atPath: Models.vad.path)
                if present {
                    done += Double(file.bytes)
                    continue
                }
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
                    try? FileManager.default.removeItem(at: local)  // unpacked: the archive is not needed
                } else {
                    try? FileManager.default.removeItem(at: Models.vad)
                    try FileManager.default.copyItem(at: local, to: Models.vad)
                }
            }
        } catch {
            self.error = "Speech model download failed: \(error.localizedDescription)"
        }
    }

    /// Downloads with a download task: resumes after a dropped connection (up to 5 attempts),
    /// waits for the network, keeps a verified file in the cache so it is fetched only once.
    private func download(_ file: SpeechDownloads.File, progress: @escaping @MainActor (Int64) -> Void) async throws -> URL {
        let cache = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("SecondBrainRecorder/downloads")
        try FileManager.default.createDirectory(at: cache, withIntermediateDirectories: true)
        let out = cache.appendingPathComponent(file.url.lastPathComponent)
        if FileManager.default.fileExists(atPath: out.path), (try? DeviceAPI.sha256(of: out)) == file.sha256 {
            return out
        }
        let fetched = try await Downloader.fetch(file.url) { got in Task { @MainActor in progress(got) } }
        try? FileManager.default.removeItem(at: out)
        try FileManager.default.moveItem(at: fetched, to: out)
        guard try DeviceAPI.sha256(of: out) == file.sha256 else {
            try? FileManager.default.removeItem(at: out)
            throw CaptureError(message: "checksum mismatch for \(file.url.lastPathComponent)")
        }
        return out
    }
}

/// One large file over URLSession download tasks with resume data between attempts.
final class Downloader: NSObject, URLSessionDownloadDelegate, @unchecked Sendable {
    static let attempts = 5

    private let onProgress: (Int64) -> Void
    private var continuation: CheckedContinuation<URL, Error>?
    private var resumeOffset: Int64 = 0

    private init(onProgress: @escaping (Int64) -> Void) { self.onProgress = onProgress }

    static func fetch(_ url: URL, onProgress: @escaping (Int64) -> Void) async throws -> URL {
        let d = Downloader(onProgress: onProgress)
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 120  // no data for 2 min → the attempt fails and resumes
        config.timeoutIntervalForResource = 6 * 3600
        config.waitsForConnectivity = true
        let session = URLSession(configuration: config, delegate: d, delegateQueue: nil)
        defer { session.finishTasksAndInvalidate() }
        var resumeData: Data?
        var lastError: Error = CaptureError(message: "the download did not start")
        for attempt in 1...attempts {
            do {
                return try await withCheckedThrowingContinuation { c in
                    d.continuation = c
                    let task = resumeData.map { session.downloadTask(withResumeData: $0) } ?? session.downloadTask(with: url)
                    task.resume()
                }
            } catch {
                lastError = error
                resumeData = (error as NSError).userInfo[NSURLSessionDownloadTaskResumeData] as? Data
                if attempt < attempts { try await Task.sleep(nanoseconds: UInt64(attempt) * 3_000_000_000) }
            }
        }
        throw lastError
    }

    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didWriteData bytesWritten: Int64,
                    totalBytesWritten: Int64, totalBytesExpectedToWrite: Int64) {
        onProgress(totalBytesWritten)
    }

    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didResumeAtOffset fileOffset: Int64,
                    expectedTotalBytes: Int64) {
        onProgress(fileOffset)
    }

    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didFinishDownloadingTo location: URL) {
        // the temporary file disappears when this returns: move it first
        let keep = FileManager.default.temporaryDirectory.appendingPathComponent("sbr-\(UUID().uuidString)")
        let status = (downloadTask.response as? HTTPURLResponse)?.statusCode ?? 0
        do {
            guard status == 200 else { throw CaptureError(message: "the download server answered \(status)") }
            try FileManager.default.moveItem(at: location, to: keep)
            continuation?.resume(returning: keep)
        } catch {
            continuation?.resume(throwing: error)
        }
        continuation = nil
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        guard let error, let c = continuation else { return }
        continuation = nil
        c.resume(throwing: error)
    }
}
