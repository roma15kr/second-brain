import Foundation

/// One recording or import on its way to the second brain (design D7): a folder
/// `items/<uuid>/` with the audio tracks and `state.json`.
public struct Item: Codable, Equatable, Sendable, Identifiable {
    public enum Kind: String, Codable, Sendable { case call, meeting, voiceNote = "voice_note" }

    public enum Status: String, Codable, Sendable {
        case recording  // audio is being written
        case recorded  // stopped; tracks joined
        case transcribing  // on this Mac
        case transcribed
        case registering
        case uploading
        case cloudTranscribing  // uploaded; the server transcribes ("Cloud" mode)
        case delivered
        case waiting  // e.g. offline, not paired, waiting for power (see `reason`)
        case failed
    }

    public let id: UUID
    public var kind: Kind
    public var startedAt: Date
    public var endedAt: Date?
    public var source: String  // front app when recording started, or "import"
    public var title: String?  // imports: the file name
    public var meeting: MeetingChoice
    public var scope: String?  // project for a call without a meeting
    public var tracks: [Track]
    public var segments: [TranscriptSegment]?
    public var status: Status
    public var reason: String?
    public var recordingId: Int?  // on the server, once registered
    public var deliveredAt: Date?
    public var transcribeSeconds: Double?  // how long the Mac took
    public var cloud: Bool  // transcribed by the server's provider instead of the Mac
    public var pendingLink: LinkRequest?  // a meeting/project change not yet sent
    public var importedFrom: String?
    public var note: String?
    public var cloudRequested: Bool?  // the server was asked to transcribe (Cloud mode / speakers)
    public var speakers: Bool?  // "Separate speakers" requested for this recording
    public var audioRemoved: Bool?  // local audio deleted 7 days after delivery

    public init(
        id: UUID = UUID(), kind: Kind, startedAt: Date, source: String, meeting: MeetingChoice = .automatic,
        tracks: [Track] = [], status: Status = .recording, cloud: Bool = false
    ) {
        self.id = id
        self.kind = kind
        self.startedAt = startedAt
        self.source = source
        self.meeting = meeting
        self.tracks = tracks
        self.status = status
        self.cloud = cloud
    }

    public var duration: TimeInterval { (endedAt ?? startedAt).timeIntervalSince(startedAt) }

    public func track(_ name: String) -> Track? { tracks.first { $0.name == name } }
}

/// An audio track: "owner" (microphone), "others" (computer audio) or "mixed" (imports).
public struct Track: Codable, Equatable, Sendable {
    public var name: String
    public var file: String  // joined file, relative to the item folder
    public var offset: TimeInterval  // when the first sample arrived, after the item's start
    public var duration: TimeInterval
    public var bytes: Int?
    public var sha256: String?
    public var uploaded: Bool

    public init(name: String, file: String, offset: TimeInterval = 0, duration: TimeInterval = 0) {
        self.name = name
        self.file = file
        self.offset = offset
        self.duration = duration
        self.uploaded = false
    }

    /// The label the transcript uses for this track.
    public var speaker: String { name == "owner" ? "me" : name == "others" ? "others" : "" }
}

public struct TranscriptSegment: Codable, Equatable, Sendable {
    public var speaker: String
    public var isOwner: Bool
    public var start: Double
    public var end: Double
    public var text: String

    public init(speaker: String, isOwner: Bool, start: Double, end: Double, text: String) {
        self.speaker = speaker
        self.isOwner = isOwner
        self.start = start
        self.end = end
        self.text = text
    }
}

public struct NewMeeting: Codable, Equatable, Sendable {
    public var title: String
    public var scope: String?
    public var participants: [String]

    public init(title: String, scope: String? = nil, participants: [String] = []) {
        self.title = title
        self.scope = scope
        self.participants = participants
    }
}

/// The meeting a recording belongs to, chosen at the start or later.
public enum MeetingChoice: Codable, Equatable, Sendable {
    case automatic  // matched by time on the server
    case event(id: Int, title: String)
    case new(NewMeeting)
    case noMeeting  // explicitly not a meeting (unscheduled call)

    public var label: String {
        switch self {
        case .automatic: return "Automatic"
        case let .event(_, title): return title
        case let .new(m): return m.title
        case .noMeeting: return "No meeting"
        }
    }
}

/// A change of meeting or project to send to `/api/devices/recordings/{id}/link`.
public struct LinkRequest: Codable, Equatable, Sendable {
    public var meeting: MeetingChoice?  // nil = keep the meeting
    public var scope: String?

    public init(meeting: MeetingChoice?, scope: String? = nil) {
        self.meeting = meeting
        self.scope = scope
    }
}

/// Items on disk under `root/items/<uuid>/state.json`.
public final class ItemStore: @unchecked Sendable {
    public let root: URL
    private let lock = NSLock()

    public init(root: URL) {
        self.root = root
        try? FileManager.default.createDirectory(at: itemsDir, withIntermediateDirectories: true)
    }

    public static var standard: ItemStore {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return ItemStore(root: base.appendingPathComponent("SecondBrainRecorder"))
    }

    public var itemsDir: URL { root.appendingPathComponent("items") }

    public func folder(_ id: UUID) -> URL { itemsDir.appendingPathComponent(id.uuidString) }

    public func url(_ item: Item, _ relative: String) -> URL { folder(item.id).appendingPathComponent(relative) }

    static var encoder: JSONEncoder {
        let e = JSONEncoder()
        e.dateEncodingStrategy = .iso8601
        e.outputFormatting = [.prettyPrinted, .sortedKeys]
        return e
    }

    static var decoder: JSONDecoder {
        let d = JSONDecoder()
        d.dateDecodingStrategy = .iso8601
        return d
    }

    public func save(_ item: Item) throws {
        try lock.withLock {
            let dir = folder(item.id)
            try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            try Self.encoder.encode(item).write(to: dir.appendingPathComponent("state.json"), options: .atomic)
        }
    }

    public func load(_ id: UUID) -> Item? {
        lock.withLock {
            (try? Data(contentsOf: folder(id).appendingPathComponent("state.json")))
                .flatMap { try? Self.decoder.decode(Item.self, from: $0) }
        }
    }

    /// All items, oldest first.
    public func all() -> [Item] {
        let dirs = (try? FileManager.default.contentsOfDirectory(at: itemsDir, includingPropertiesForKeys: nil)) ?? []
        return dirs.compactMap { UUID(uuidString: $0.lastPathComponent).flatMap(load) }
            .sorted { $0.startedAt < $1.startedAt }
    }

    /// Updates an item in place (read, change, write) and returns the new version.
    @discardableResult
    public func update(_ id: UUID, _ change: (inout Item) -> Void) throws -> Item? {
        guard var item = load(id) else { return nil }
        change(&item)
        try save(item)
        return item
    }

    public func delete(_ id: UUID) {
        lock.withLock { _ = try? FileManager.default.removeItem(at: folder(id)) }
    }
}
