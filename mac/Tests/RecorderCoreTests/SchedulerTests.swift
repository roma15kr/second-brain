import XCTest

@testable import RecorderCore

final class SchedulerTests: XCTestCase {
    func testPolicy() {
        XCTAssertEqual(TranscriptionPolicy.gate(MachineState()), .run)
        XCTAssertEqual(TranscriptionPolicy.gate(MachineState(isRecording: true)), .wait("Waiting for the call to end"))
        XCTAssertEqual(TranscriptionPolicy.gate(MachineState(isDictating: true)), .wait("Dictation first"))
        XCTAssertEqual(TranscriptionPolicy.gate(MachineState(onBattery: true)), .wait("Waiting for power"))
        XCTAssertEqual(TranscriptionPolicy.gate(MachineState(onBattery: true, allowBattery: true)), .run)
    }

    func testBackToBackCallPausesAndResumes() throws {
        // a second call is running for three polls, then ends
        var polls = 0
        var reasons: [String?] = []
        let checkpoint = PausableCheckpoint(
            state: { MachineState(isRecording: polls < 3) }, sleep: { _ in polls += 1 })
        checkpoint.onWait = { reasons.append($0) }
        try checkpoint.wait()
        XCTAssertEqual(polls, 3)
        XCTAssertEqual(reasons, ["Waiting for the call to end", nil])
    }

    func testOnBatteryWaitsForPower() throws {
        var plugged = false
        var sleeps = 0
        let checkpoint = PausableCheckpoint(
            state: { MachineState(onBattery: !plugged) },
            sleep: { _ in
                sleeps += 1
                if sleeps == 5 { plugged = true }
            })
        try checkpoint.wait()
        XCTAssertEqual(sleeps, 5)
    }

    func testRunsImmediatelyWhenFree() throws {
        var sleeps = 0
        let checkpoint = PausableCheckpoint(state: { MachineState() }, sleep: { _ in sleeps += 1 })
        try checkpoint.wait()
        XCTAssertEqual(sleeps, 0)
    }

    func testCancelWhileWaiting() {
        var sleeps = 0
        let checkpoint = PausableCheckpoint(
            state: { MachineState(isRecording: true) }, isCancelled: { sleeps >= 2 }, sleep: { _ in sleeps += 1 })
        XCTAssertThrowsError(try checkpoint.wait()) { XCTAssertTrue($0 is CancellationError) }
    }
}
