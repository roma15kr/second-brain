import Foundation

/// Errors from the owner's server, in words the menu can show.
public enum APIError: Error, Equatable, LocalizedError {
    case unauthorized  // the device was revoked or never paired
    case server(status: Int, detail: String)
    case offline
    case invalidResponse

    public var errorDescription: String? {
        switch self {
        case .unauthorized: return "Not paired with the second brain"
        case let .server(status, detail): return "Server error \(status): \(detail)"
        case .offline: return "No connection to the second brain"
        case .invalidResponse: return "Unexpected answer from the second brain"
        }
    }
}

/// A small JSON client for the device API (`/api/devices/*`), authenticated with the device
/// token as a bearer token. The URLSession is injectable so tests can answer requests.
public struct APIClient: Sendable {
    public let baseURL: URL
    public let token: String?
    let session: URLSession

    public init(baseURL: URL, token: String?, session: URLSession = .shared) {
        self.baseURL = baseURL
        self.token = token
        self.session = session
    }

    public func request(
        _ method: String, _ path: String, query: [URLQueryItem] = [], body: Data? = nil,
        contentType: String? = "application/json", headers: [String: String] = [:]
    ) -> URLRequest {
        var components = URLComponents(
            url: baseURL.appendingPathComponent(path), resolvingAgainstBaseURL: false)!
        if !query.isEmpty { components.queryItems = query }
        var req = URLRequest(url: components.url!)
        req.httpMethod = method
        req.httpBody = body
        if let contentType, body != nil { req.setValue(contentType, forHTTPHeaderField: "Content-Type") }
        if let token { req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        for (k, v) in headers { req.setValue(v, forHTTPHeaderField: k) }
        return req
    }

    /// Sends a request and returns the raw body and status; maps transport failures to `.offline`
    /// and 401 to `.unauthorized`.
    public func send(_ req: URLRequest) async throws -> (Data, HTTPURLResponse) {
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: req)
        } catch let error as URLError {
            _ = error
            throw APIError.offline
        }
        guard let http = response as? HTTPURLResponse else { throw APIError.invalidResponse }
        if http.statusCode == 401 { throw APIError.unauthorized }
        return (data, http)
    }

    /// JSON in, JSON out; non-2xx answers become `.server` with the API's `detail`.
    public func json<T: Decodable>(
        _ method: String, _ path: String, body: (any Encodable)? = nil,
        query: [URLQueryItem] = [], as type: T.Type = T.self
    ) async throws -> T {
        let encoded = try body.map { try JSONEncoder.api.encode(AnyEncodable($0)) }
        let (data, http) = try await send(request(method, path, query: query, body: encoded))
        guard (200..<300).contains(http.statusCode) else {
            throw APIError.server(status: http.statusCode, detail: Self.detail(data))
        }
        return try JSONDecoder.api.decode(T.self, from: data)
    }

    static func detail(_ data: Data) -> String {
        struct Detail: Decodable { let detail: String? }
        return (try? JSONDecoder().decode(Detail.self, from: data))?.detail
            ?? String(data: data, encoding: .utf8) ?? ""
    }
}

struct AnyEncodable: Encodable {
    let value: any Encodable
    init(_ value: any Encodable) { self.value = value }
    func encode(to encoder: Encoder) throws { try value.encode(to: encoder) }
}

extension JSONEncoder {
    /// snake_case keys and ISO dates, like the Python API.
    public static var api: JSONEncoder {
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        e.dateEncodingStrategy = .iso8601
        return e
    }
}

extension JSONDecoder {
    public static var api: JSONDecoder {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        d.dateDecodingStrategy = .custom { decoder in
            let s = try decoder.singleValueContainer().decode(String.self)
            if let date = ISO8601DateFormatter.withFractions.date(from: s)
                ?? ISO8601DateFormatter().date(from: s)
            {
                return date
            }
            throw DecodingError.dataCorrupted(
                .init(codingPath: decoder.codingPath, debugDescription: "bad date \(s)"))
        }
        return d
    }
}

extension ISO8601DateFormatter {
    static var withFractions: ISO8601DateFormatter {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }
}
