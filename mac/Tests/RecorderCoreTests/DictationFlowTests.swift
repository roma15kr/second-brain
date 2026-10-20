import XCTest

@testable import RecorderCore

final class FakePaster: Paster {
    var focused = true
    var inserted: [String] = []
    func insert(_ text: String) -> InsertResult {
        inserted.append(text)
        return focused ? .typed : .copied
    }
}

final class DictationFlowTests: XCTestCase {
    let samples = [Float](repeating: 0.2, count: 32_000)  // 2 s
    let audio = Data("m4a bytes".utf8)

    override func setUp() { MockURLProtocol.reset() }

    func api() -> DeviceAPI {
        DeviceAPI(client: APIClient(baseURL: URL(string: "https://os.example")!, token: "tok", session: MockURLProtocol.session()))
    }

    func testServerTextTypedWithChosenForm() async throws {
        MockURLProtocol.handler = { req in
            XCTAssertEqual(req.url?.path, "/api/devices/dictations")
            let q = URLComponents(url: req.url!, resolvingAgainstBaseURL: false)!.queryItems!
            XCTAssertEqual(q.first { $0.name == "form" }?.value, "clean")
            XCTAssertEqual(q.first { $0.name == "seconds" }?.value, "2.0")
            XCTAssertEqual(req.value(forHTTPHeaderField: "Content-Type"), "audio/mp4")
            XCTAssertEqual(req.httpBody, Data("m4a bytes".utf8))
            return (200, #"{"id": 5, "text": "Давай зустрінемось завтра."}"#.data(using: .utf8)!)
        }
        let paster = FakePaster()
        let out = await DictationFlow(api: api(), paster: paster, offline: FakeRecognizer()).finish(audio: audio, samples: samples, form: .clean)
        XCTAssertEqual(paster.inserted, ["Давай зустрінемось завтра."])
        XCTAssertEqual(out.inserted, .typed)
        XCTAssertFalse(out.offline)
        XCTAssertNil(out.notice)
    }

    func testOfflineUsesTheMacModelAsSaid() async {
        MockURLProtocol.handler = nil  // no connection
        let paster = FakePaster()
        let out = await DictationFlow(api: api(), paster: paster, offline: FakeRecognizer()).finish(audio: audio, samples: samples, form: .clean)
        XCTAssertTrue(out.offline)
        XCTAssertEqual(paster.inserted, ["2s"])
        XCTAssertEqual(out.notice, "Transcribed on this Mac as said: cleaning was not available offline")
    }

    func testNowhereToTypeCopiesToClipboard() async {
        MockURLProtocol.handler = { _ in (200, #"{"text": "Hello", "note": "over budget: as said"}"#.data(using: .utf8)!) }
        let paster = FakePaster()
        paster.focused = false
        let out = await DictationFlow(api: api(), paster: paster, offline: nil).finish(audio: audio, samples: samples, form: .structured)
        XCTAssertEqual(out.inserted, .copied)
        XCTAssertEqual(out.notice, "over budget: as said. No text field had focus: the text is on the clipboard")
    }

    func testTooShortIsIgnored() async {
        let paster = FakePaster()
        let out = await DictationFlow(api: api(), paster: paster, offline: nil).finish(audio: audio, samples: [Float](repeating: 0, count: 1_000), form: .verbatim)
        XCTAssertNil(out.inserted)
        XCTAssertTrue(paster.inserted.isEmpty)
        XCTAssertTrue(MockURLProtocol.requests.isEmpty)
    }

    func testServerErrorIsReportedNotTyped() async {
        MockURLProtocol.handler = { _ in (422, #"{"detail": "the recording is empty"}"#.data(using: .utf8)!) }
        let paster = FakePaster()
        let out = await DictationFlow(api: api(), paster: paster, offline: FakeRecognizer()).finish(audio: audio, samples: samples, form: .verbatim)
        XCTAssertEqual(out.notice, "Dictation failed: Server error 422: the recording is empty")
        XCTAssertTrue(paster.inserted.isEmpty)
    }
}
