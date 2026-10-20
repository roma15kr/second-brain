import XCTest

@testable import RecorderCore

final class PermissionsModelTests: XCTestCase {
    func testNothingGrantedListsAllInOrder() {
        let m = PermissionsModel()
        XCTAssertEqual(m.missing, [.microphone, .systemAudio, .accessibility])
        XCTAssertFalse(m.canDictate)
        XCTAssertNil(m.menuWarning)  // not asked yet: macOS asks on first use
    }

    func testDeniedSystemAudioBlocksCallsButNotDictation() {
        let m = PermissionsModel([.microphone: .granted, .systemAudio: .denied, .accessibility: .granted])
        XCTAssertFalse(m.canRecordCalls)
        XCTAssertTrue(m.canDictate)
        XCTAssertTrue(m.canType)
        XCTAssertEqual(m.missing, [.systemAudio])
        XCTAssertEqual(m.menuWarning, "Missing: System audio recording")
    }

    func testWithoutAccessibilityDictationGoesToClipboard() {
        let m = PermissionsModel([.microphone: .granted, .systemAudio: .granted, .accessibility: .denied])
        XCTAssertTrue(m.canDictate)
        XCTAssertFalse(m.canType)
        XCTAssertTrue(Permission.accessibility.neededFor.contains("clipboard"))
    }

    func testSettingsLinksOpenThePrivacyPanes() {
        XCTAssertEqual(
            Permission.microphone.settingsURL.absoluteString,
            "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone")
        for p in Permission.allCases {
            XCTAssertEqual(p.settingsURL.scheme, "x-apple.systempreferences")
            XCTAssertFalse(p.purpose.isEmpty)
        }
    }
}
