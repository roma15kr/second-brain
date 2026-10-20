import Foundation

public let sampleRate: Double = 16_000  // what the speech models expect (design D2)

/// One audio segment file being written (AAC in the app, memory in tests).
public protocol SegmentFile: AnyObject {
    func write(_ samples: [Float]) throws
    func close()
}

public protocol SegmentFileFactory: AnyObject {
    func create(at url: URL) throws -> SegmentFile
}

/// Writes one track as numbered 5-minute segment files (`seg-0001.m4a`, …) and keeps the track in
/// step with the wall clock: when samples stop arriving (e.g. the microphone changes), the gap is
/// filled with silence so both tracks stay aligned.
public final class SegmentedTrackWriter: @unchecked Sendable {
    public static let segmentSeconds: Double = 300
    public static let gapTolerance: Double = 0.5

    public let dir: URL
    let factory: SegmentFileFactory
    let segmentSamples: Int
    private let lock = NSLock()
    private var current: SegmentFile?
    private var inSegment = 0
    public private(set) var segmentCount = 0
    public private(set) var samplesWritten = 0
    public private(set) var firstSampleAt: Date?
    public private(set) var heardSound = false
    public private(set) var lastError: Error?
    /// Everything written, silence padding included (Live mode transcribes exactly the file's audio).
    public var onWrite: (([Float]) -> Void)?

    public init(dir: URL, factory: SegmentFileFactory, segmentSeconds: Double = SegmentedTrackWriter.segmentSeconds) {
        self.dir = dir
        self.factory = factory
        self.segmentSamples = Int(segmentSeconds * sampleRate)
    }

    public static func segmentName(_ index: Int) -> String { String(format: "seg-%04d.m4a", index) }

    /// Silence needed before samples arriving at `elapsed` seconds after the first sample.
    public static func zerosNeeded(elapsed: TimeInterval, written: Int) -> Int {
        let expected = Int(elapsed * sampleRate)
        return expected - written > Int(gapTolerance * sampleRate) ? expected - written : 0
    }

    public var seconds: Double { Double(samplesWritten) / sampleRate }

    /// Appends 16 kHz mono samples that arrived at `at` (the time of the buffer's first sample).
    public func append(_ samples: [Float], at: Date) {
        lock.withLock {
            if firstSampleAt == nil { firstSampleAt = at }
            let pad = Self.zerosNeeded(elapsed: at.timeIntervalSince(firstSampleAt!), written: samplesWritten)
            if pad > 0 {
                let zeros = [Float](repeating: 0, count: pad)
                write(zeros)
                onWrite?(zeros)
            }
            if !heardSound, samples.contains(where: { abs($0) > 1e-4 }) { heardSound = true }
            write(samples)
            onWrite?(samples)
        }
    }

    private func write(_ samples: [Float]) {
        var rest = samples[...]
        while !rest.isEmpty {
            do {
                if current == nil || inSegment >= segmentSamples {
                    current?.close()
                    segmentCount += 1
                    try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
                    current = try factory.create(at: dir.appendingPathComponent(Self.segmentName(segmentCount)))
                    inSegment = 0
                }
                let n = min(rest.count, segmentSamples - inSegment)
                try current!.write(Array(rest.prefix(n)))
                inSegment += n
                samplesWritten += n
                rest = rest.dropFirst(n)
            } catch {
                lastError = error
                return
            }
        }
    }

    public func close() {
        lock.withLock {
            current?.close()
            current = nil
        }
    }

    /// The segment files of a track folder in recording order.
    public static func segments(in dir: URL) -> [URL] {
        let files = (try? FileManager.default.contentsOfDirectory(at: dir, includingPropertiesForKeys: nil)) ?? []
        return files.filter { $0.lastPathComponent.hasPrefix("seg-") && $0.pathExtension == "m4a" }
            .sorted { index($0) < index($1) }
    }

    static func index(_ url: URL) -> Int {
        Int(url.deletingPathExtension().lastPathComponent.dropFirst(4)) ?? Int.max
    }
}

/// An audio input delivering 16 kHz mono samples (microphone, computer audio; fakes in tests).
public protocol AudioSource: AnyObject {
    /// Called on an audio thread with samples and the time of the first one.
    var onSamples: (([Float], Date) -> Void)? { get set }
    func start() throws
    func stop()
}

public enum RecorderError: Error, Equatable, LocalizedError {
    case alreadyRecording
    case microphone(String)

    public var errorDescription: String? {
        switch self {
        case .alreadyRecording: return "Already recording"
        case let .microphone(why): return "The microphone could not start: \(why)"
        }
    }
}

/// Starts and stops two-track recordings into items (design D2). Joining the segment files is
/// done by the caller on stop (AVFoundation in the app).
public final class Recorder: @unchecked Sendable {
    public static let limit: TimeInterval = 4 * 3600

    let store: ItemStore
    let factory: SegmentFileFactory
    let makeSources: () -> (owner: AudioSource, others: AudioSource)
    public private(set) var current: Item?
    private var writers: [String: SegmentedTrackWriter] = [:]
    private var sources: [AudioSource] = []
    /// Extra consumer (Live mode): track name, samples as written, the track's offset.
    public var onSamples: ((String, [Float], TimeInterval) -> Void)?

    public init(store: ItemStore, factory: SegmentFileFactory, sources: @escaping () -> (owner: AudioSource, others: AudioSource)) {
        self.store = store
        self.factory = factory
        self.makeSources = sources
    }

    public var isRecording: Bool { current != nil }

    public func elapsed(now: Date) -> TimeInterval { current.map { now.timeIntervalSince($0.startedAt) } ?? 0 }

    /// Whether the computer-audio track has delivered anything but silence (permission check).
    public var othersHeardSound: Bool { writers["others"]?.heardSound ?? false }

    @discardableResult
    public func start(kind: Item.Kind = .call, meeting: MeetingChoice, source: String, cloud: Bool, now: Date) throws -> Item {
        guard current == nil else { throw RecorderError.alreadyRecording }
        var item = Item(kind: kind, startedAt: now, source: source, meeting: meeting, cloud: cloud)
        let (owner, others) = makeSources()
        var started: [AudioSource] = []
        for (name, src) in [("owner", owner), ("others", others)] {
            let writer = SegmentedTrackWriter(dir: store.url(item, name), factory: factory)
            let startedAt = item.startedAt
            writer.onWrite = { [weak self, weak writer] samples in
                let offset = max(0, (writer?.firstSampleAt ?? startedAt).timeIntervalSince(startedAt))
                self?.onSamples?(name, samples, offset)
            }
            src.onSamples = { samples, at in writer.append(samples, at: at) }
            do {
                try src.start()
                writers[name] = writer
                started.append(src)
                item.tracks.append(Track(name: name, file: "\(name).m4a"))
            } catch {
                if name == "owner" {
                    started.forEach { $0.stop() }
                    writers = [:]
                    throw RecorderError.microphone(error.localizedDescription)
                }
                item.note = "Computer audio was not available: \(error.localizedDescription)"
            }
        }
        sources = started
        try store.save(item)
        current = item
        return item
    }

    /// Stops the recording; the item is saved as `recorded` with each track's offset and length
    /// (its segment files still to be joined into `<track>.m4a`).
    @discardableResult
    public func stop(now: Date, reason: String? = nil) throws -> Item? {
        guard var item = current else { return nil }
        sources.forEach { $0.stop() }
        sources = []
        item.endedAt = now
        item.status = .recorded
        if let reason { item.reason = reason }
        for i in item.tracks.indices {
            guard let w = writers[item.tracks[i].name] else { continue }
            w.close()
            item.tracks[i].duration = w.seconds
            item.tracks[i].offset = max(0, (w.firstSampleAt ?? now).timeIntervalSince(item.startedAt))
        }
        item.tracks.removeAll { writers[$0.name]?.samplesWritten ?? 0 == 0 }
        writers = [:]
        current = nil
        try store.save(item)
        return item
    }

    /// Called every second while recording; stops at the 4-hour limit.
    public func tick(now: Date) throws -> Item? {
        guard elapsed(now: now) >= Self.limit else { return nil }
        return try stop(now: now, reason: "Stopped after 4 hours")
    }
}

/// Recordings left `recording` because the app quit or crashed (design D2: finished on the next
/// start like a normal recording).
public enum Recovery {
    public static func unfinished(_ store: ItemStore) -> [Item] {
        store.all().filter { $0.status == .recording }
    }

    /// Marks an interrupted item as recorded, ending at its last written segment.
    public static func finish(_ store: ItemStore, _ item: Item) throws -> Item? {
        try store.update(item.id) { item in
            var last = item.startedAt
            var kept: [Track] = []
            for var track in item.tracks {
                let segs = SegmentedTrackWriter.segments(in: store.url(item, track.name))
                guard !segs.isEmpty else { continue }
                for s in segs {
                    let modified = (try? s.resourceValues(forKeys: [.contentModificationDateKey]))?.contentModificationDate
                    if let modified, modified > last { last = modified }
                }
                track.duration = 0  // measured when the segments are joined
                kept.append(track)
            }
            item.tracks = kept
            item.endedAt = last
            item.status = kept.isEmpty ? .failed : .recorded
            item.reason = kept.isEmpty ? "Nothing was recorded before the app quit" : "Recovered after the app quit"
        }
    }
}
