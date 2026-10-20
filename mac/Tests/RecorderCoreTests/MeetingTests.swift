import XCTest

@testable import RecorderCore

final class MeetingPickerTests: XCTestCase {
    let now = Date(timeIntervalSince1970: 1_800_000_000)

    func m(_ id: Int, _ startMin: Double, _ endMin: Double) -> MeetingSummary {
        let s = now.addingTimeInterval(startMin * 60)
        let e = now.addingTimeInterval(endMin * 60)
        return MeetingSummary(id: id, title: "m\(id)", start: s, end: e, inProgress: s <= now && now <= e)
    }

    func testInProgressFirstThenByTime() {
        let list = [m(1, -300, -240), m(2, 60, 90), m(3, -2, 58), m(4, -90, -30), m(5, 600, 660), m(6, 30, 45), m(7, 900, 960), m(8, -700, -650)]
        let options = MeetingPicker.options(list, now: now)
        XCTAssertEqual(options.first?.id, 3)
        XCTAssertEqual(options.count, 6)
        XCTAssertFalse(options.contains { $0.id == 8 })  // the farthest are left out
        XCTAssertEqual(options.dropFirst().map(\.start), options.dropFirst().map(\.start).sorted())
    }

    func testOfflineUsesCachedList() async {
        let store = MemoryStore()
        let picker = MeetingPicker(store: store)
        let fresh = await picker.load(now: now) { [self] in [m(1, 0, 60)] }
        XCTAssertEqual(fresh.map(\.id), [1])
        let later = now.addingTimeInterval(3 * 3600)
        let offline = await picker.load(now: later) { throw APIError.offline }
        XCTAssertEqual(offline.map(\.id), [1])
        XCTAssertFalse(offline[0].inProgress)  // ended by then
        let tooOld = await picker.load(now: now.addingTimeInterval(13 * 3600)) { throw APIError.offline }
        XCTAssertTrue(tooOld.isEmpty)
    }
}

final class NewMeetingFormTests: XCTestCase {
    func testTitleRequired() {
        XCTAssertNil(NewMeetingForm(title: "  ").meeting)
    }

    func testParticipantsByNameOrEmail() {
        let form = NewMeetingForm(title: " Dealer — October prices ", scope: "quokka", participants: "Oleh, anna@example.com;\n oleh ,")
        XCTAssertEqual(form.meeting, NewMeeting(title: "Dealer — October prices", scope: "quokka", participants: ["Oleh", "anna@example.com"]))
        XCTAssertNil(NewMeetingForm(title: "x", scope: "").meeting?.scope)
    }
}

final class RelinkTests: XCTestCase {
    func testBeforeDeliveryTheChoiceTravelsWithTheRegistration() {
        var item = Item(kind: .call, startedAt: Date(), source: "")
        Relink.apply(&item, meeting: .event(id: 9, title: "Quokka sync"))
        XCTAssertEqual(item.meeting, .event(id: 9, title: "Quokka sync"))
        XCTAssertNil(item.pendingLink)
    }

    func testAfterDeliveryALinkIsQueued() {
        var item = Item(kind: .call, startedAt: Date(), source: "", status: .delivered)
        item.recordingId = 42
        Relink.apply(&item, meeting: nil, scope: "rdim")
        Relink.apply(&item, meeting: .none)
        XCTAssertEqual(item.pendingLink, LinkRequest(meeting: MeetingChoice.none, scope: "rdim"))
        XCTAssertEqual(Delivery.next(item, paired: true), .link)
    }

    func testMeetingChosenWhileRecording() throws {
        let store = ItemStore(root: temporaryDirectory())
        let rec = Recorder(store: store, factory: FakeSegmentFactory(), sources: { (FakeSource(), FakeSource()) })
        let item = try rec.start(meeting: .automatic, source: "", cloud: false, now: Date())
        try rec.setMeeting(.new(NewMeeting(title: "Call with Oleh")))
        XCTAssertEqual(store.load(item.id)?.meeting.label, "Call with Oleh")
    }
}
