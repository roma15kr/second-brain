import XCTest

@testable import RecorderCore

final class LiveAssemblerTests: XCTestCase {
    let me = silence(1) + speech(3) + silence(6) + speech(2) + silence(2)
    let others = silence(4) + speech(5) + silence(5)

    func afterCall() throws -> [TranscriptSegment] {
        var tracks: [[TranscriptSegment]] = []
        for (name, audio, offset) in [("owner", me, 0.0), ("others", others, 0.5)] {
            var track = Track(name: name, file: "")
            track.offset = offset
            let t = StreamingTranscriber(vad: FakeVAD(), recognizer: FakeRecognizer(), track: track)
            var lines: [TranscriptSegment] = []
            for i in stride(from: 0, to: audio.count, by: 160_000) {  // the file reader's 10 s pieces
                lines += try t.feed(Array(audio[i..<min(i + 160_000, audio.count)]))
            }
            lines += try t.finish()
            tracks.append(lines)
        }
        return TranscriptMerge.merge(tracks)
    }

    func testLiveTranscriptEqualsAfterCallTranscript() throws {
        var phrases: [TranscriptSegment] = []
        let live = LiveAssembler { StreamingTranscriber(vad: FakeVAD(), recognizer: FakeRecognizer(), track: $0) }
        live.onPhrase = { phrases.append($0) }
        // audio arrives interleaved in small, uneven buffers like the audio callbacks deliver it
        var i = 0
        var j = 0
        var step = 0
        while i < me.count || j < others.count {
            let a = [1_600, 4_096, 800][step % 3]
            if i < me.count {
                try live.feed(track: "owner", samples: Array(me[i..<min(i + a, me.count)]), offset: 0)
                i += a
            }
            if j < others.count {
                try live.feed(track: "others", samples: Array(others[j..<min(j + 1_024, others.count)]), offset: 0.5)
                j += 1_024
            }
            step += 1
        }
        let firstPhraseCount = phrases.count
        XCTAssertGreaterThanOrEqual(firstPhraseCount, 2)  // captions appeared during the call
        let transcript = try live.finish()
        XCTAssertEqual(transcript, try afterCall())
        XCTAssertEqual(transcript.map(\.speaker), ["me", "others", "me"])
        XCTAssertEqual(transcript[1].start, 4.5)  // the others' offset is kept
    }

    func testRecorderPassesWrittenAudioWithPadding() throws {
        let store = ItemStore(root: temporaryDirectory())
        let mic = FakeSource()
        let rec = Recorder(store: store, factory: FakeSegmentFactory(), sources: { (mic, FakeSource()) })
        var got: [(String, Int, TimeInterval)] = []
        rec.onSamples = { got.append(($0, $1.count, $2)) }
        let t0 = Date()
        try rec.start(meeting: .automatic, source: "", cloud: false, now: t0)
        mic.feed(seconds: 1, from: t0.addingTimeInterval(1))
        mic.onSamples?(speech(1), t0.addingTimeInterval(4))  // after a 2 s gap
        XCTAssertEqual(got.map(\.1).reduce(0, +), 4 * 16_000)  // 1 s + 2 s padding + 1 s
        XCTAssertEqual(got.first?.2, 1)
        XCTAssertTrue(got.allSatisfy { $0.0 == "owner" })
    }
}
