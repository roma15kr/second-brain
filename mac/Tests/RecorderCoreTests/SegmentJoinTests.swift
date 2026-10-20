import XCTest

@testable import RecorderCore

final class SegmentJoinTests: XCTestCase {
    func testRotatesEveryFiveMinutes() {
        let factory = FakeSegmentFactory()
        let writer = SegmentedTrackWriter(dir: temporaryDirectory(), factory: factory)
        let t0 = Date()
        for i in 0..<301 {
            writer.append([Float](repeating: 0, count: 16_000), at: t0.addingTimeInterval(Double(i)))
        }
        writer.close()
        XCTAssertEqual(factory.files.map(\.samples), [300 * 16_000, 16_000])
        XCTAssertEqual(factory.files.map(\.url.lastPathComponent), ["seg-0001.m4a", "seg-0002.m4a"])
        XCTAssertTrue(factory.files.allSatisfy(\.closed))
        XCTAssertEqual(writer.seconds, 301)
    }

    func testSegmentsAreJoinedInRecordingOrder() {
        let dir = temporaryDirectory()
        for i in [10, 2, 1, 9, 11] {
            FileManager.default.createFile(
                atPath: dir.appendingPathComponent(SegmentedTrackWriter.segmentName(i)).path, contents: Data())
        }
        FileManager.default.createFile(atPath: dir.appendingPathComponent("notes.txt").path, contents: Data())
        XCTAssertEqual(
            SegmentedTrackWriter.segments(in: dir).map(\.lastPathComponent),
            ["seg-0001.m4a", "seg-0002.m4a", "seg-0009.m4a", "seg-0010.m4a", "seg-0011.m4a"])
    }

    func testGapIsFilledWithSilenceToStayAligned() {
        let factory = FakeSegmentFactory()
        let writer = SegmentedTrackWriter(dir: temporaryDirectory(), factory: factory)
        let t0 = Date()
        writer.append([Float](repeating: 0.2, count: 16_000), at: t0)
        // the microphone switched to AirPods: the next buffer arrives 1.8 s later
        writer.append([Float](repeating: 0.2, count: 16_000), at: t0.addingTimeInterval(2.8))
        XCTAssertEqual(writer.seconds, 3.8, accuracy: 0.001)
        XCTAssertTrue(writer.heardSound)
    }

    func testSmallJitterIsNotPadded() {
        XCTAssertEqual(SegmentedTrackWriter.zerosNeeded(elapsed: 1.3, written: 16_000), 0)
        XCTAssertEqual(SegmentedTrackWriter.zerosNeeded(elapsed: 2.0, written: 16_000), 16_000)
    }
}
