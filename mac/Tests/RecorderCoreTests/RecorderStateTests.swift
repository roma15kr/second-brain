import XCTest

@testable import RecorderCore

final class RecorderStateTests: XCTestCase {
    var store: ItemStore!
    var mic: FakeSource!
    var tap: FakeSource!

    override func setUp() {
        store = ItemStore(root: temporaryDirectory())
        mic = FakeSource()
        tap = FakeSource()
    }

    func recorder() -> Recorder {
        Recorder(store: store, factory: FakeSegmentFactory(), sources: { [mic, tap] in (mic!, tap!) })
    }

    func testTwoTrackRecording() throws {
        let rec = recorder()
        let t0 = Date(timeIntervalSince1970: 1_800_000_000)
        let started = try rec.start(meeting: .event(id: 5, title: "Quokka sync"), source: "zoom.us", cloud: false, now: t0)
        XCTAssertEqual(store.load(started.id)?.status, .recording)
        XCTAssertThrowsError(try rec.start(meeting: .automatic, source: "", cloud: false, now: t0))
        mic.feed(seconds: 60, from: t0)
        tap.feed(seconds: 58, from: t0.addingTimeInterval(2))
        XCTAssertTrue(rec.othersHeardSound)
        let item = try XCTUnwrap(try rec.stop(now: t0.addingTimeInterval(60)))
        XCTAssertFalse(mic.running || tap.running)
        XCTAssertEqual(item.status, .recorded)
        XCTAssertEqual(item.duration, 60)
        XCTAssertEqual(item.tracks.map(\.name), ["owner", "others"])
        XCTAssertEqual(item.track("others")?.offset, 2)
        XCTAssertEqual(item.track("owner")?.duration, 60)
        XCTAssertEqual(item.meeting, .event(id: 5, title: "Quokka sync"))
        XCTAssertEqual(store.load(item.id), item)
        XCTAssertFalse(rec.isRecording)
    }

    func testStopsAtFourHours() throws {
        let rec = recorder()
        let t0 = Date()
        try rec.start(meeting: .automatic, source: "", cloud: false, now: t0)
        mic.feed(seconds: 1, from: t0)
        XCTAssertNil(try rec.tick(now: t0.addingTimeInterval(3 * 3600)))
        let item = try XCTUnwrap(try rec.tick(now: t0.addingTimeInterval(4 * 3600)))
        XCTAssertEqual(item.reason, "Stopped after 4 hours")
        XCTAssertFalse(rec.isRecording)
    }

    func testMicrophoneFailureStopsTheStart() {
        mic.failStart = TestError(message: "no input device")
        let rec = recorder()
        XCTAssertThrowsError(try rec.start(meeting: .automatic, source: "", cloud: false, now: Date())) {
            XCTAssertEqual($0 as? RecorderError, .microphone("no input device"))
        }
        XCTAssertFalse(rec.isRecording)
        XCTAssertFalse(tap.running)
    }

    func testComputerAudioFailureRecordsMicrophoneOnly() throws {
        tap.failStart = TestError(message: "tap refused")
        let rec = recorder()
        let t0 = Date()
        try rec.start(meeting: .automatic, source: "", cloud: false, now: t0)
        mic.feed(seconds: 5, from: t0)
        let item = try XCTUnwrap(try rec.stop(now: t0.addingTimeInterval(5)))
        XCTAssertEqual(item.tracks.map(\.name), ["owner"])
        XCTAssertEqual(item.note, "Computer audio was not available: tap refused")
    }
}
