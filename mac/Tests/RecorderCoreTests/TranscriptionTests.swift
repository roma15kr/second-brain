import XCTest

@testable import RecorderCore

/// Speech = samples above 0.05; chunks end after 0.5 s of quiet.
final class FakeVAD: VoiceDetector {
    var fed = 0
    var open: (start: Int, samples: [Float])?
    var quiet = 0
    var done: [SpeechChunk] = []

    func accept(_ samples: [Float]) {
        for s in samples {
            if abs(s) > 0.05 {
                if open == nil { open = (fed, []) }
                open!.samples.append(s)
                quiet = 0
            } else if open != nil {
                quiet += 1
                if quiet >= 8000 { close() } else { open!.samples.append(s) }
            }
            fed += 1
        }
    }

    func close() {
        if let o = open { done.append(SpeechChunk(start: Double(o.start) / sampleRate, samples: o.samples)) }
        open = nil
        quiet = 0
    }

    func flush() { close() }
    func pop() -> [SpeechChunk] { defer { done = [] }; return done }
    func reset() { fed = 0; open = nil; done = [] }
}

/// "Recognizes" a chunk as its length in whole seconds.
final class FakeRecognizer: SpeechRecognizer {
    var calls: [Int] = []
    func recognize(_ samples: [Float]) throws -> String {
        calls.append(samples.count)
        return "\(Int((Double(samples.count) / sampleRate).rounded()))s"
    }
}

func speech(_ seconds: Double) -> [Float] { [Float](repeating: 0.3, count: Int(seconds * sampleRate)) }
func silence(_ seconds: Double) -> [Float] { [Float](repeating: 0, count: Int(seconds * sampleRate)) }

final class SegmentationTests: XCTestCase {
    func testShortChunkUnchanged() {
        let c = SpeechChunk(start: 3, samples: speech(12))
        XCTAssertEqual(Segmentation.split(c), [c])
    }

    func testLongChunkSplitAtQuietestPoint() {
        // 20 s speech, 0.3 s near-silence, 25 s speech
        let samples = speech(20) + [Float](repeating: 0.001, count: 4800) + speech(25)
        let parts = Segmentation.split(SpeechChunk(start: 100, samples: samples))
        XCTAssertEqual(parts.count, 2)
        XCTAssertEqual(parts[0].start, 100)
        XCTAssertEqual(parts[0].duration, 20.05, accuracy: 0.01)  // cut inside the quiet stretch
        XCTAssertEqual(parts[1].start, 100 + parts[0].duration, accuracy: 0.0001)
        XCTAssertEqual(parts.map(\.samples.count).reduce(0, +), samples.count)
        XCTAssertTrue(parts.allSatisfy { $0.duration <= Segmentation.maxSeconds })
    }

    func testVeryLongMonotoneChunkStillSplits() {
        let parts = Segmentation.split(SpeechChunk(start: 0, samples: speech(95)))
        XCTAssertTrue(parts.allSatisfy { $0.duration <= 30 })
        XCTAssertEqual(parts.map(\.duration).reduce(0, +), 95, accuracy: 0.001)
    }

    func testStreamingTranscriberSkipsSilenceAndKeepsTimes() throws {
        var track = Track(name: "others", file: "others.m4a")
        track.offset = 2
        let rec = FakeRecognizer()
        let t = StreamingTranscriber(vad: FakeVAD(), recognizer: rec, track: track)
        var out: [TranscriptSegment] = []
        // fed in 1-second buffers like the file reader does
        let audio = silence(5) + speech(4) + silence(10) + speech(3)
        for i in stride(from: 0, to: audio.count, by: 16_000) {
            out += try t.feed(Array(audio[i..<min(i + 16_000, audio.count)]))
        }
        out += try t.finish()
        XCTAssertEqual(out.map(\.text), ["4s", "3s"])  // silence never reached the recognizer
        XCTAssertEqual(out[0].start, 7)  // 2 s offset + 5 s silence
        XCTAssertEqual(out[0].speaker, "others")
        XCTAssertFalse(out[0].isOwner)
        XCTAssertEqual(out[1].start, 21)
        XCTAssertEqual(t.speechSeconds, 7.5, accuracy: 0.6)
    }

    func testCheckpointCancels() {
        let t = StreamingTranscriber(vad: FakeVAD(), recognizer: FakeRecognizer(), track: Track(name: "owner", file: ""))
        t.checkpoint = { throw CancellationError() }
        XCTAssertThrowsError(try t.feed(speech(2) + silence(1)))
    }
}

final class MergeTests: XCTestCase {
    func seg(_ who: String, _ start: Double, _ end: Double, _ text: String) -> TranscriptSegment {
        TranscriptSegment(speaker: who, isOwner: who == "me", start: start, end: end, text: text)
    }

    func testInterleavesByTime() {
        let me = [seg("me", 0, 3, "Привіт"), seg("me", 10, 12, "Так, згоден.")]
        let others = [seg("others", 4, 9, "Добрий день, почнемо?"), seg("others", 12.5, 15, "Отже")]
        XCTAssertEqual(
            TranscriptMerge.merge([me, others]).map(\.text),
            ["Привіт", "Добрий день, почнемо?", "Так, згоден.", "Отже"])
    }

    func testJoinsCloseLinesOfOneSpeaker() {
        let me = [seg("me", 0, 3, "one"), seg("me", 3.4, 5, "two"), seg("me", 8, 9, "three")]
        let merged = TranscriptMerge.merge([me])
        XCTAssertEqual(merged.map(\.text), ["one two", "three"])
        XCTAssertEqual(merged[0].end, 5)
    }

    func testMeFirstOnEqualStart() {
        let merged = TranscriptMerge.merge([[seg("others", 1, 2, "b")], [seg("me", 1, 2, "a")]])
        XCTAssertEqual(merged.map(\.speaker), ["me", "others"])
    }
}

final class ProviderChoiceTests: XCTestCase {
    func testFasterProviderWins() {
        let cpu = Benchmark(provider: "cpu", audioSeconds: 30, elapsedSeconds: 6)
        let gpu = Benchmark(provider: "coreml", audioSeconds: 30, elapsedSeconds: 4.2)
        XCTAssertEqual(ProviderChoice.choose([cpu, gpu]), "coreml")
        XCTAssertEqual(gpu.label, "7.1× real time on GPU")
        XCTAssertEqual(cpu.label, "5.0× real time on CPU")
    }

    func testFailedProviderAndOverride() {
        let cpu = Benchmark(provider: "cpu", audioSeconds: 30, elapsedSeconds: 2.5)
        let broken = Benchmark(provider: "coreml", audioSeconds: 30, elapsedSeconds: 0)
        XCTAssertEqual(ProviderChoice.choose([cpu, broken]), "cpu")
        XCTAssertEqual(cpu.label, "12× real time on CPU")
        XCTAssertEqual(ProviderChoice.choose([cpu], override: "coreml"), "coreml")
        XCTAssertEqual(ProviderChoice.choose([]), "cpu")
    }

    func testThreads() {
        XCTAssertEqual(ProviderChoice.threads(cores: 12), 3)
        XCTAssertEqual(ProviderChoice.threads(cores: 4), 2)
        XCTAssertEqual(ProviderChoice.threads(cores: 1), 1)
    }
}
