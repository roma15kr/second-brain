import Foundation

@testable import RecorderCore

/// Segment files that record sample counts (and touch a real file so folder scans see them).
final class FakeSegmentFactory: SegmentFileFactory {
    final class File: SegmentFile {
        let url: URL
        var samples = 0
        var closed = false
        init(url: URL) { self.url = url }
        func write(_ s: [Float]) throws { samples += s.count }
        func close() { closed = true }
    }

    var files: [File] = []

    func create(at url: URL) throws -> SegmentFile {
        FileManager.default.createFile(atPath: url.path, contents: Data([0]))
        let f = File(url: url)
        files.append(f)
        return f
    }
}

final class FakeSource: AudioSource {
    var onSamples: (([Float], Date) -> Void)?
    var failStart: Error?
    var running = false

    func start() throws {
        if let failStart { throw failStart }
        running = true
    }

    func stop() { running = false }

    /// Feeds `seconds` of a quiet tone in one-second buffers starting at `from`.
    func feed(seconds: Int, from: Date, level: Float = 0.1) {
        for i in 0..<seconds {
            onSamples?([Float](repeating: level, count: Int(sampleRate)), from.addingTimeInterval(Double(i)))
        }
    }
}

struct TestError: Error, LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

func temporaryDirectory() -> URL {
    let url = FileManager.default.temporaryDirectory.appendingPathComponent("sbr-tests-\(UUID().uuidString)")
    try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
    return url
}
