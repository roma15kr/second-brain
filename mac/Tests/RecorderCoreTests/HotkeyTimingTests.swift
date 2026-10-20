import XCTest

@testable import RecorderCore

final class HotkeyTimingTests: XCTestCase {
    func testHoldToTalk() {
        var g = DictationGesture()
        XCTAssertEqual(g.press(at: 0), .start)
        XCTAssertNil(g.press(at: 0.2))  // key repeat
        XCTAssertEqual(g.release(at: 2.5), .stop)
        XCTAssertFalse(g.isActive)
    }

    func testShortPressToggles() {
        var g = DictationGesture()
        XCTAssertEqual(g.press(at: 0), .start)
        XCTAssertNil(g.release(at: 0.15))
        XCTAssertTrue(g.isActive)
        XCTAssertEqual(g.press(at: 6), .stop)
        XCTAssertNil(g.release(at: 6.1))
        XCTAssertFalse(g.isActive)
        XCTAssertEqual(g.press(at: 9), .start)  // a new dictation
    }

    func testThresholdIsHold() {
        var g = DictationGesture()
        _ = g.press(at: 1)
        XCTAssertEqual(g.release(at: 1.4), .stop)
    }
}
