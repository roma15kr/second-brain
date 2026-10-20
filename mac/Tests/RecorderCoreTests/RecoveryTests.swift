import XCTest

@testable import RecorderCore

final class RecoveryTests: XCTestCase {
    func testInterruptedRecordingIsFinished() throws {
        let store = ItemStore(root: temporaryDirectory())
        let t0 = Date(timeIntervalSince1970: 1_800_000_000)
        let rec = Recorder(store: store, factory: FakeSegmentFactory(), sources: { (FakeSource(), FakeSource()) })
        let item = try rec.start(meeting: .automatic, source: "Telegram", cloud: false, now: t0)
        // the app quits here: segment files exist, the state says "recording"
        let seg = store.url(item, "owner").appendingPathComponent(SegmentedTrackWriter.segmentName(1))
        try FileManager.default.createDirectory(at: seg.deletingLastPathComponent(), withIntermediateDirectories: true)
        FileManager.default.createFile(atPath: seg.path, contents: Data([1]))
        let lastWrite = t0.addingTimeInterval(1200)
        try FileManager.default.setAttributes([.modificationDate: lastWrite], ofItemAtPath: seg.path)

        let found = Recovery.unfinished(store)
        XCTAssertEqual(found.map(\.id), [item.id])
        let done = try XCTUnwrap(try Recovery.finish(store, found[0]))
        XCTAssertEqual(done.status, .recorded)
        XCTAssertEqual(done.endedAt, lastWrite)
        XCTAssertEqual(done.tracks.map(\.name), ["owner"])  // "others" had no segments
        XCTAssertEqual(done.reason, "Recovered after the app quit")
        XCTAssertTrue(Recovery.unfinished(store).isEmpty)
    }

    func testNothingWrittenIsFailed() throws {
        let store = ItemStore(root: temporaryDirectory())
        var item = Item(kind: .call, startedAt: Date(), source: "")
        item.tracks = [Track(name: "owner", file: "owner.m4a")]
        try store.save(item)
        let done = try XCTUnwrap(try Recovery.finish(store, item))
        XCTAssertEqual(done.status, .failed)
    }
}
