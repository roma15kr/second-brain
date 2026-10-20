import Foundation

/// A stretch of speech found by the voice detector.
public struct SpeechChunk: Equatable, Sendable {
    public var start: Double  // seconds since the first sample fed to the detector
    public var samples: [Float]

    public init(start: Double, samples: [Float]) {
        self.start = start
        self.samples = samples
    }

    public var duration: Double { Double(samples.count) / sampleRate }
}

/// Streaming voice activity detection (Silero VAD in sherpa-onnx; fakes in tests).
public protocol VoiceDetector: AnyObject {
    func accept(_ samples: [Float])
    /// Ends the stream: the speech still open becomes a chunk.
    func flush()
    /// Finished chunks since the last call.
    func pop() -> [SpeechChunk]
    func reset()
}

/// Speech to text for one chunk (Parakeet in sherpa-onnx; fakes in tests).
public protocol SpeechRecognizer: AnyObject {
    func recognize(_ samples: [Float]) throws -> String
}

public enum Segmentation {
    public static let maxSeconds: Double = 30
    static let frame = Int(sampleRate / 10)  // 100 ms

    /// Splits chunks longer than `max` seconds at the quietest 100 ms between half and all of
    /// `max`, so no recognition call gets more than the model handles well.
    public static func split(_ chunk: SpeechChunk, max: Double = maxSeconds) -> [SpeechChunk] {
        var out: [SpeechChunk] = []
        var rest = chunk
        let limit = Int(max * sampleRate)
        while rest.samples.count > limit {
            let cut = quietest(rest.samples, from: limit / 2, to: limit)
            out.append(SpeechChunk(start: rest.start, samples: Array(rest.samples[..<cut])))
            rest = SpeechChunk(start: rest.start + Double(cut) / sampleRate, samples: Array(rest.samples[cut...]))
        }
        out.append(rest)
        return out
    }

    /// The start of the quietest frame in [from, to), as a sample index (the frame's middle).
    static func quietest(_ samples: [Float], from: Int, to: Int) -> Int {
        var best = to
        var bestEnergy = Float.greatestFiniteMagnitude
        var i = from
        while i + frame <= to {
            var energy: Float = 0
            for j in i..<(i + frame) { energy += samples[j] * samples[j] }
            if energy < bestEnergy {
                bestEnergy = energy
                best = i + frame / 2
            }
            i += frame
        }
        return best
    }
}

/// Transcribes one track as its audio arrives (after the call: read from the file; Live mode:
/// from the recorder), phrase by phrase: VAD → split long chunks → recognize → timed segments.
public final class StreamingTranscriber {
    let vad: VoiceDetector
    let recognizer: SpeechRecognizer
    let speaker: String
    let isOwner: Bool
    let offset: Double  // the track's start after the recording's start
    /// Called between phrases; throws to cancel, may block to pause (design D3 scheduling).
    public var checkpoint: () throws -> Void = {}
    public private(set) var speechSeconds: Double = 0

    public init(vad: VoiceDetector, recognizer: SpeechRecognizer, track: Track) {
        self.vad = vad
        self.recognizer = recognizer
        self.speaker = track.speaker
        self.isOwner = track.name == "owner"
        self.offset = track.offset
        vad.reset()
    }

    /// Feeds samples; returns the phrases finished so far.
    public func feed(_ samples: [Float]) throws -> [TranscriptSegment] {
        vad.accept(samples)
        return try drain()
    }

    /// Ends the track; returns the last phrases.
    public func finish() throws -> [TranscriptSegment] {
        vad.flush()
        return try drain()
    }

    private func drain() throws -> [TranscriptSegment] {
        var out: [TranscriptSegment] = []
        for chunk in vad.pop() {
            for part in Segmentation.split(chunk) {
                try checkpoint()
                speechSeconds += part.duration
                let text = try recognizer.recognize(part.samples).trimmingCharacters(in: .whitespacesAndNewlines)
                guard !text.isEmpty else { continue }
                out.append(TranscriptSegment(
                    speaker: speaker, isOwner: isOwner, start: round2(offset + part.start),
                    end: round2(offset + part.start + part.duration), text: text))
            }
        }
        return out
    }
}

func round2(_ x: Double) -> Double { (x * 100).rounded() / 100 }

public enum TranscriptMerge {
    /// Both tracks' segments in time order ("me" first on equal starts); consecutive lines of the
    /// same speaker less than `joinGap` seconds apart are joined while the line stays under a minute.
    public static func merge(_ tracks: [[TranscriptSegment]], joinGap: Double = 1.0) -> [TranscriptSegment] {
        let all = tracks.flatMap { $0 }.sorted {
            $0.start != $1.start ? $0.start < $1.start : ($0.isOwner && !$1.isOwner)
        }
        var out: [TranscriptSegment] = []
        for s in all {
            if var last = out.last, last.speaker == s.speaker, s.start - last.end < joinGap, s.end - last.start < 60 {
                last.end = max(last.end, s.end)
                last.text += " " + s.text
                out[out.count - 1] = last
            } else {
                out.append(s)
            }
        }
        return out
    }
}

/// Result of transcribing the benchmark sample with one sherpa-onnx provider.
public struct Benchmark: Codable, Equatable, Sendable {
    public var provider: String  // "cpu" or "coreml"
    public var audioSeconds: Double
    public var elapsedSeconds: Double

    public init(provider: String, audioSeconds: Double, elapsedSeconds: Double) {
        self.provider = provider
        self.audioSeconds = audioSeconds
        self.elapsedSeconds = elapsedSeconds
    }

    public var speed: Double { elapsedSeconds > 0 ? audioSeconds / elapsedSeconds : 0 }

    /// "7× real time on GPU"
    public var label: String {
        let x = speed >= 10 ? String(Int(speed.rounded())) : String(format: "%.1f", speed)
        return "\(x)× real time on \(provider == "coreml" ? "GPU" : "CPU")"
    }
}

public enum ProviderChoice {
    /// The faster provider, unless the owner chose one in Settings ("cpu" / "coreml").
    public static func choose(_ results: [Benchmark], override: String? = nil) -> String {
        if let override, override == "cpu" || override == "coreml" { return override }
        return results.filter { $0.speed > 0 }.max { $0.speed < $1.speed }?.provider ?? "cpu"
    }

    /// Threads for transcription: half the cores, at most 3 (design D3).
    public static func threads(cores: Int = ProcessInfo.processInfo.activeProcessorCount) -> Int {
        max(1, min(3, cores / 2))
    }
}
