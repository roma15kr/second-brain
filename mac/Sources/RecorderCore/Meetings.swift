import Foundation

/// The meetings offered when a recording starts (design D7a): the one in progress first, then the
/// nearest; the last list is kept so the choice also works offline.
public final class MeetingPicker {
    public static let maxOptions = 6
    public static let cacheFor: TimeInterval = 12 * 3600

    let store: KeyValueStore
    struct Cache: Codable { let fetchedAt: Date; let meetings: [MeetingSummary] }

    public init(store: KeyValueStore) { self.store = store }

    public static func options(_ meetings: [MeetingSummary], now: Date) -> [MeetingSummary] {
        func distance(_ m: MeetingSummary) -> TimeInterval {
            if m.start <= now && now <= m.end { return 0 }
            return min(abs(m.start.timeIntervalSince(now)), abs(m.end.timeIntervalSince(now)))
        }
        let sorted = meetings.sorted {
            let a = $0.inProgress || distance($0) == 0
            let b = $1.inProgress || distance($1) == 0
            return a != b ? a : distance($0) < distance($1)
        }
        return Array(sorted.prefix(maxOptions)).sorted {
            $0.inProgress != $1.inProgress ? $0.inProgress : $0.start < $1.start
        }
    }

    /// Fresh list from the server, or the cached one (≤ 12 h old) when offline.
    public func load(now: Date, fetch: () async throws -> [MeetingSummary]) async -> [MeetingSummary] {
        do {
            let fresh = try await fetch()
            store.encode(Cache(fetchedAt: now, meetings: fresh), forKey: "meetings.cache")
            return Self.options(fresh, now: now)
        } catch {
            guard let cache = store.decoded(Cache.self, forKey: "meetings.cache"),
                  now.timeIntervalSince(cache.fetchedAt) < Self.cacheFor
            else { return [] }
            // "in progress" from the cache is recomputed for now
            let recomputed = cache.meetings.map {
                MeetingSummary(id: $0.id, title: $0.title, start: $0.start, end: $0.end,
                               inProgress: $0.start <= now && now <= $0.end)
            }
            return Self.options(recomputed, now: now)
        }
    }
}

/// "New meeting…" for a spontaneous call: title required, project optional, participants by name
/// or email separated by commas, semicolons or new lines.
public struct NewMeetingForm: Equatable, Sendable {
    public var title = ""
    public var scope: String?
    public var participants = ""

    public init(title: String = "", scope: String? = nil, participants: String = "") {
        self.title = title
        self.scope = scope
        self.participants = participants
    }

    public var participantList: [String] {
        var seen = Set<String>()
        return participants.split(whereSeparator: { ",;\n".contains($0) })
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty && seen.insert($0.lowercased()).inserted }
    }

    /// nil while the title is empty.
    public var meeting: NewMeeting? {
        let t = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty else { return nil }
        return NewMeeting(title: t, scope: scope?.isEmpty == true ? nil : scope, participants: participantList)
    }
}

public enum Relink {
    /// Changes the meeting and/or project of an item: before registration the choice simply goes
    /// with the registration; afterwards it is queued as a link request.
    public static func apply(_ item: inout Item, meeting: MeetingChoice?, scope: String? = nil) {
        if item.recordingId == nil {
            if let meeting { item.meeting = meeting }
            if let scope { item.scope = scope }
            return
        }
        var request = item.pendingLink ?? LinkRequest(meeting: nil)
        if let meeting { request.meeting = meeting }
        if let scope { request.scope = scope }
        item.pendingLink = request
    }
}

/// Projects a call can be marked with (the second brain's scopes).
public enum Projects {
    public static let all = ["personal", "digisoft", "quokka", "rdim"]
}
