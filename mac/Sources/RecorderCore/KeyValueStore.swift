import Foundation

/// Settings storage: UserDefaults in the app, a dictionary in tests.
public protocol KeyValueStore: AnyObject {
    func data(forKey key: String) -> Data?
    func set(_ value: Any?, forKey key: String)
}

extension UserDefaults: KeyValueStore {}

public final class MemoryStore: KeyValueStore {
    public var values: [String: Any] = [:]
    public init() {}
    public func data(forKey key: String) -> Data? { values[key] as? Data }
    public func set(_ value: Any?, forKey key: String) { values[key] = value }
}

extension KeyValueStore {
    public func decoded<T: Decodable>(_ type: T.Type, forKey key: String) -> T? {
        data(forKey: key).flatMap { try? JSONDecoder().decode(T.self, from: $0) }
    }

    public func encode<T: Encodable>(_ value: T, forKey key: String) {
        set(try? JSONEncoder().encode(value), forKey: key)
    }
}
