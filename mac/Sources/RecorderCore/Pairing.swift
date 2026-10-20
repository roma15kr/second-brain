import Foundation

/// Pairing with the second brain: a one-time code from Settings → Recorder apps is exchanged for
/// a device token (upload-only on the server), which is kept in the token store.
public struct Pairing: Sendable {
    public let serverURL: URL
    let store: TokenStore
    let session: URLSession

    public init(serverURL: URL, store: TokenStore, session: URLSession = .shared) {
        self.serverURL = serverURL
        self.store = store
        self.session = session
    }

    public var isPaired: Bool { store.load() != nil }

    public var client: APIClient { APIClient(baseURL: serverURL, token: store.load(), session: session) }

    struct PairRequest: Encodable { let code: String; let name: String; let platform: String }
    struct PairResponse: Decodable { let deviceId: Int; let token: String }

    /// Exchanges the code; returns the device id. The code is case-insensitive on the server.
    @discardableResult
    public func pair(code: String, deviceName: String) async throws -> Int {
        let anonymous = APIClient(baseURL: serverURL, token: nil, session: session)
        let trimmed = code.trimmingCharacters(in: .whitespacesAndNewlines)
        let res: PairResponse = try await anonymous.json(
            "POST", "api/devices/pair",
            body: PairRequest(code: trimmed, name: deviceName, platform: "macos"))
        try store.save(res.token)
        return res.deviceId
    }

    /// Called when the server answers 401: the device was revoked; recordings stay local.
    public func forget() { store.delete() }
}
