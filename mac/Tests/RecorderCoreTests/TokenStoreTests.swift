import XCTest

@testable import RecorderCore

final class TokenStoreTests: XCTestCase {
    func testInMemoryStoreRoundTrip() throws {
        let store = InMemoryTokenStore()
        XCTAssertNil(store.load())
        try store.save("a")
        try store.save("b")
        XCTAssertEqual(store.load(), "b")
        store.delete()
        XCTAssertNil(store.load())
    }

    func testKeychainStoreRoundTrip() throws {
        // a separate service name so the test never touches the app's real item
        let store = KeychainTokenStore(service: "biz.zhukovsky.second-brain.recorder.tests")
        store.delete()
        do {
            try store.save("tok")
        } catch KeychainError.status(let status) {
            throw XCTSkip("no usable keychain on this machine (status \(status))")
        }
        XCTAssertEqual(store.load(), "tok")
        store.delete()
        XCTAssertNil(store.load())
    }
}
