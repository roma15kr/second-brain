import XCTest

@testable import RecorderCore

/// A small in-memory device API: registrations, links, track uploads and cloud requests.
final class FakeServer {
    var registered: [[String: Any]] = []
    var links: [[String: Any]] = []
    var transcribeRequests: [[String: Any]] = []
    var tracks: [String: Data] = [:]  // "<rid>/<track>" → bytes received
    var totals: [String: Int] = [:]
    var failNextPutWith409 = false
    var offline = false
    var revoked = false

    func json(_ obj: Any) -> Data { try! JSONSerialization.data(withJSONObject: obj) }

    func state(_ key: String) -> [String: Any] {
        let got = tracks[key]?.count ?? 0
        return ["track": key, "received_bytes": got, "total_bytes": totals[key] ?? 0, "complete": got == totals[key]]
    }

    func handle(_ req: URLRequest) throws -> (Int, Data) {
        if offline { throw URLError(.notConnectedToInternet) }
        if revoked { return (401, json(["detail": "unknown or revoked device"])) }
        XCTAssertEqual(req.value(forHTTPHeaderField: "Authorization"), "Bearer tok")
        let path = req.url!.path
        let body = req.httpBody ?? Data()
        switch (req.httpMethod!, path) {
        case ("POST", "/api/devices/recordings"):
            let obj = try JSONSerialization.jsonObject(with: body) as! [String: Any]
            registered.append(obj)
            return (200, json(["recording_id": 42]))
        case ("POST", "/api/devices/recordings/42/link"):
            links.append(try JSONSerialization.jsonObject(with: body) as! [String: Any])
            return (200, json(["ok": true]))
        case ("POST", "/api/devices/recordings/42/transcribe"):
            transcribeRequests.append(try JSONSerialization.jsonObject(with: body) as! [String: Any])
            return (200, json(["provider": "openai-diarize", "estimated_usd": 0.36, "job_id": 1]))
        case let ("POST", p) where p.contains("/audio/"):
            let obj = try JSONSerialization.jsonObject(with: body) as! [String: Any]
            let key = "42/" + p.split(separator: "/").last!
            XCTAssertEqual(obj["mime"] as? String, "audio/mp4")
            XCTAssertEqual((obj["sha256"] as? String)?.count, 64)
            totals[key] = obj["total_bytes"] as? Int
            return (200, json(state(key)))
        case let ("PUT", p) where p.contains("/audio/"):
            let key = "42/" + p.split(separator: "/").last!
            let range = req.value(forHTTPHeaderField: "Content-Range")!
            let start = Int(range.dropFirst(6).split(separator: "-")[0])!
            let have = tracks[key]?.count ?? 0
            if failNextPutWith409 || start != have {
                failNextPutWith409 = false
                return (409, json(["detail": "expected the chunk at \(have)", "received_bytes": have]))
            }
            tracks[key, default: Data()].append(body)
            return (200, json(state(key)))
        default:
            return (404, json(["detail": "no route \(path)"]))
        }
    }
}

final class DeliveryTests: XCTestCase {
    var server: FakeServer!
    var store: ItemStore!
    var runner: DeliveryRunner!
    let t0 = Date(timeIntervalSince1970: 1_800_000_000)

    override func setUp() {
        MockURLProtocol.reset()
        server = FakeServer()
        MockURLProtocol.handler = { [unowned self] in try self.server.handle($0) }
        MockURLProtocol.headers = { [unowned self] req in
            // the real server sends Upload-Offset with a 409
            req.httpMethod == "PUT" ? ["Upload-Offset": "\(self.server.tracks.values.first?.count ?? 0)"] : [:]
        }
        store = ItemStore(root: temporaryDirectory())
        let client = APIClient(baseURL: URL(string: "https://os.example")!, token: "tok", session: MockURLProtocol.session())
        runner = DeliveryRunner(store: store, api: DeviceAPI(client: client, chunkSize: 10), now: { [t0] in t0 })
    }

    func makeItem(cloud: Bool = false, meeting: MeetingChoice = .automatic) throws -> Item {
        var item = Item(kind: .call, startedAt: t0, source: "zoom.us", meeting: meeting, status: .recorded, cloud: cloud)
        item.endedAt = t0.addingTimeInterval(3600)
        item.tracks = [Track(name: "owner", file: "owner.m4a"), Track(name: "others", file: "others.m4a")]
        if !cloud {
            item.segments = [TranscriptSegment(speaker: "me", isOwner: true, start: 1, end: 2, text: "Привіт")]
            item.status = .transcribed
        }
        try store.save(item)
        try Data("owner audio bytes here, 35 bytes!!".utf8).write(to: store.url(item, "owner.m4a"))
        try Data("others".utf8).write(to: store.url(item, "others.m4a"))
        return item
    }

    func testDeliversTranscriptAndBothTracks() async throws {
        let item = try makeItem(meeting: .event(id: 7, title: "Quokka sync"))
        let done = await runner.deliver(item.id)
        XCTAssertEqual(done?.status, .delivered)
        XCTAssertEqual(done?.recordingId, 42)
        XCTAssertEqual(done?.deliveredAt, t0)
        let reg = try XCTUnwrap(server.registered.first)
        XCTAssertEqual(reg["idempotency_key"] as? String, item.id.uuidString)
        XCTAssertEqual(reg["event_id"] as? Int, 7)
        XCTAssertEqual(reg["kind"] as? String, "call")
        XCTAssertEqual((reg["segments"] as? [[String: Any]])?.first?["is_owner"] as? Bool, true)
        XCTAssertEqual(server.tracks["42/owner"], Data("owner audio bytes here, 35 bytes!!".utf8))  // 4 chunks of 10
        XCTAssertEqual(server.tracks["42/others"], Data("others".utf8))
        XCTAssertTrue(server.links.isEmpty)
        XCTAssertTrue(server.transcribeRequests.isEmpty)
    }

    func testResumesAfter409AndAfterGoingOffline() async throws {
        let item = try makeItem()
        server.failNextPutWith409 = true
        server.offline = true
        let waiting = await runner.deliver(item.id)
        XCTAssertEqual(waiting?.status, .waiting)
        XCTAssertEqual(waiting?.reason, "Offline — will send when connected")
        server.offline = false
        let done = await runner.deliver(item.id)
        XCTAssertEqual(done?.status, .delivered)
        XCTAssertEqual(server.registered.count, 1)
        XCTAssertEqual(server.tracks["42/owner"]?.count, 34)
    }

    func testRevokedDeviceKeepsTheRecording() async throws {
        let item = try makeItem()
        server.revoked = true
        let waiting = await runner.deliver(item.id)
        XCTAssertEqual(waiting?.status, .waiting)
        XCTAssertEqual(waiting?.reason, "Not paired — open Settings")
        XCTAssertTrue(FileManager.default.fileExists(atPath: store.url(item, "owner.m4a").path))
    }

    func testUnscheduledCallWithProjectSendsExplicitNullMeeting() async throws {
        var item = try makeItem(meeting: .noMeeting)
        item.scope = "rdim"
        try store.save(item)
        _ = await runner.deliver(item.id)
        let link = try XCTUnwrap(server.links.first)
        XCTAssertTrue(link.keys.contains("event_id"))
        XCTAssertTrue(link["event_id"] is NSNull)
        XCTAssertEqual(link["scope"] as? String, "rdim")
    }

    // CloudModeTests: the server's provider transcribes instead of the Mac
    func testCloudRegistersWithoutSegmentsThenRequestsTranscription() async throws {
        let item = try makeItem(cloud: true)
        XCTAssertEqual(Delivery.next(item, paired: true), .register)  // no Mac transcription
        let done = await runner.deliver(item.id)
        XCTAssertEqual(done?.status, .delivered)
        XCTAssertEqual((server.registered.first?["segments"] as? [Any])?.count, 0)
        XCTAssertEqual(server.transcribeRequests.first?["speakers"] as? Bool, false)
        XCTAssertEqual(server.tracks.count, 2)  // tracks uploaded before the request
        XCTAssertEqual(done?.cloudRequested, true)
    }

    func testRelinkAfterDelivery() async throws {
        let item = try makeItem()
        _ = await runner.deliver(item.id)
        try store.update(item.id) { $0.pendingLink = LinkRequest(meeting: .new(NewMeeting(title: "Dealer — October prices", scope: "quokka", participants: ["Oleh"]))) }
        let done = await runner.deliver(item.id)
        XCTAssertEqual(done?.status, .delivered)
        XCTAssertNil(done?.pendingLink)
        let link = try XCTUnwrap(server.links.first)
        let meeting = try XCTUnwrap(link["new_meeting"] as? [String: Any])
        XCTAssertEqual(meeting["title"] as? String, "Dealer — October prices")
        XCTAssertEqual(meeting["participants"] as? [String], ["Oleh"])
        XCTAssertEqual(done?.meeting.label, "Dealer — October prices")
    }
}

final class StateMachineTests: XCTestCase {
    func item(_ status: Item.Status, cloud: Bool = false, segments: Bool = false) -> Item {
        var i = Item(kind: .call, startedAt: Date(), source: "", status: status, cloud: cloud)
        i.tracks = [Track(name: "owner", file: "owner.m4a")]
        if segments { i.segments = [] }
        return i
    }

    func testSteps() {
        XCTAssertNil(Delivery.next(item(.recording), paired: true))
        XCTAssertNil(Delivery.next(item(.failed), paired: true))
        XCTAssertEqual(Delivery.next(item(.recorded), paired: false), .transcribeOnMac)  // offline-capable
        XCTAssertEqual(Delivery.next(item(.transcribed, segments: true), paired: false), .wait("Not paired — open Settings"))
        var i = item(.transcribed, segments: true)
        XCTAssertEqual(Delivery.next(i, paired: true), .register)
        i.recordingId = 1
        XCTAssertEqual(Delivery.next(i, paired: true), .upload("owner"))
        i.tracks[0].uploaded = true
        XCTAssertEqual(Delivery.next(i, paired: true), .done)
        i.status = .delivered
        XCTAssertNil(Delivery.next(i, paired: true))
        i.pendingLink = LinkRequest(meeting: .event(id: 3, title: "x"))
        XCTAssertEqual(Delivery.next(i, paired: true), .link)
    }

    func testInitialLink() {
        var i = item(.recorded)
        XCTAssertNil(Delivery.initialLink(i))
        i.scope = "rdim"
        XCTAssertEqual(Delivery.initialLink(i), LinkRequest(meeting: nil, scope: "rdim"))
        i.meeting = .noMeeting
        XCTAssertEqual(Delivery.initialLink(i), LinkRequest(meeting: MeetingChoice.noMeeting, scope: "rdim"))
    }

    func testErrors() {
        XCTAssertEqual(Delivery.describe(APIError.server(status: 400, detail: "bad")).0, .failed)
        XCTAssertEqual(Delivery.describe(APIError.server(status: 502, detail: "gateway")).0, .waiting)
    }
}

final class CleanupTests: XCTestCase {
    func testAudioRemovedSevenDaysAfterDelivery() throws {
        let store = ItemStore(root: temporaryDirectory())
        let now = Date(timeIntervalSince1970: 1_800_000_000)
        var old = Item(kind: .call, startedAt: now.addingTimeInterval(-9 * 86400), source: "", status: .delivered)
        old.tracks = [Track(name: "owner", file: "owner.m4a")]
        old.deliveredAt = now.addingTimeInterval(-8 * 86400)
        var recent = old
        recent = Item(kind: .call, startedAt: now.addingTimeInterval(-2 * 86400), source: "", status: .delivered)
        recent.tracks = old.tracks
        recent.deliveredAt = now.addingTimeInterval(-86400)
        var pending = Item(kind: .call, startedAt: now.addingTimeInterval(-30 * 86400), source: "", status: .waiting)
        pending.tracks = old.tracks
        for i in [old, recent, pending] {
            try store.save(i)
            try Data([1]).write(to: store.url(i, "owner.m4a"))
        }
        let client = APIClient(baseURL: URL(string: "https://os.example")!, token: nil)
        DeliveryRunner(store: store, api: DeviceAPI(client: client), now: { now }).cleanup()
        XCTAssertFalse(FileManager.default.fileExists(atPath: store.url(old, "owner.m4a").path))
        XCTAssertEqual(store.load(old.id)?.audioRemoved, true)
        XCTAssertTrue(FileManager.default.fileExists(atPath: store.url(recent, "owner.m4a").path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: store.url(pending, "owner.m4a").path))  // never before delivery
    }
}
