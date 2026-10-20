import Foundation
import XCTest

@testable import RecorderCore

final class PairingTests: XCTestCase {
    override func setUp() { MockURLProtocol.reset() }

    func testPairStoresTokenAndSendsCode() async throws {
        MockURLProtocol.handler = { req in
            XCTAssertEqual(req.url?.path, "/api/devices/pair")
            XCTAssertNil(req.value(forHTTPHeaderField: "Authorization"))
            let body = try JSONSerialization.jsonObject(with: req.httpBody!) as! [String: String]
            XCTAssertEqual(body["code"], "ABCD2345")
            XCTAssertEqual(body["platform"], "macos")
            return (200, #"{"device_id": 7, "token": "tok_secret"}"#.data(using: .utf8)!)
        }
        let store = InMemoryTokenStore()
        let pairing = Pairing(
            serverURL: URL(string: "https://os.example")!, store: store,
            session: MockURLProtocol.session())
        let id = try await pairing.pair(code: "  ABCD2345\n", deviceName: "Roman's MacBook Pro")
        XCTAssertEqual(id, 7)
        XCTAssertEqual(store.load(), "tok_secret")
        XCTAssertTrue(pairing.isPaired)
        XCTAssertEqual(pairing.client.token, "tok_secret")
    }

    func testWrongCodeShowsServerMessage() async {
        MockURLProtocol.handler = { _ in
            (400, #"{"detail": "the pairing code is wrong, used or expired"}"#.data(using: .utf8)!)
        }
        let pairing = Pairing(
            serverURL: URL(string: "https://os.example")!, store: InMemoryTokenStore(),
            session: MockURLProtocol.session())
        do {
            try await pairing.pair(code: "XXXX", deviceName: "Mac")
            XCTFail("expected an error")
        } catch let APIError.server(status, detail) {
            XCTAssertEqual(status, 400)
            XCTAssertEqual(detail, "the pairing code is wrong, used or expired")
        } catch {
            XCTFail("unexpected \(error)")
        }
        XCTAssertFalse(pairing.isPaired)
    }

    func testRevokedDeviceIsUnauthorizedAndForgotten() async {
        MockURLProtocol.handler = { _ in (401, Data()) }
        let store = InMemoryTokenStore("old_token")
        let pairing = Pairing(
            serverURL: URL(string: "https://os.example")!, store: store,
            session: MockURLProtocol.session())
        do {
            let _: [String: String] = try await pairing.client.json("GET", "api/devices/meetings")
            XCTFail("expected unauthorized")
        } catch {
            XCTAssertEqual(error as? APIError, .unauthorized)
        }
        pairing.forget()
        XCTAssertFalse(pairing.isPaired)
    }

    func testOfflineIsReportedAsOffline() async {
        MockURLProtocol.handler = nil  // the mock fails with "not connected"
        let client = APIClient(
            baseURL: URL(string: "https://os.example")!, token: "t", session: MockURLProtocol.session())
        do {
            let _: [String: String] = try await client.json("GET", "api/devices/meetings")
            XCTFail("expected offline")
        } catch {
            XCTAssertEqual(error as? APIError, .offline)
        }
    }
}
