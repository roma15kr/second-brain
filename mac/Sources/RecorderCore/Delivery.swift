import Foundation

/// The next thing to do for an item (design D7 state machine).
public enum DeliveryStep: Equatable, Sendable {
    case transcribeOnMac
    case register
    case link
    case sendSegments
    case upload(String)
    case requestCloud
    case done
    case wait(String)
}

public enum Delivery {
    public static let keepAudio: TimeInterval = 7 * 24 * 3600
    /// The note on calls that went to the server only because the speech model was missing.
    public static let modelMissingNote = "Transcribed on the server (the Mac's speech model is not installed)"
    public static let waitingForModel = "Waiting for the speech model (Settings → Download the speech model)"

    /// Sends an already delivered recording back through transcription on this Mac; its transcript
    /// then replaces the server's. nil when the local audio is gone or it was never registered.
    public static func retranscribeLocally(_ item: Item) -> Item? {
        guard item.recordingId != nil, item.audioRemoved != true, !item.tracks.isEmpty,
              item.status == .delivered || item.status == .failed || item.status == .waiting
        else { return nil }
        var i = item
        i.cloud = false
        i.cloudRequested = nil
        i.segments = nil
        i.segmentsSent = false
        i.status = .recorded
        i.reason = nil
        i.note = "Transcribing on this Mac"
        return i
    }

    /// nil when there is nothing to do (still recording, failed, or finished).
    public static func next(_ item: Item, paired: Bool) -> DeliveryStep? {
        switch item.status {
        case .recording, .failed: return nil
        case .delivered: return item.pendingLink != nil && paired ? .link : nil
        default: break
        }
        if !item.cloud && item.segments == nil { return .transcribeOnMac }
        if !paired { return .wait("Not paired — open Settings") }
        if item.recordingId == nil { return .register }
        if item.pendingLink != nil { return .link }
        if !item.cloud && item.segments != nil && item.segmentsSent == false { return .sendSegments }
        if let t = item.tracks.first(where: { !$0.uploaded }) { return .upload(t.name) }
        if item.cloud && item.cloudRequested != true { return .requestCloud }
        return .done
    }

    /// The link to send right after registering: "no meeting" and a project are not part of the
    /// registration body.
    public static func initialLink(_ item: Item) -> LinkRequest? {
        if item.meeting == .noMeeting || item.scope != nil {
            return LinkRequest(meeting: item.meeting == .noMeeting ? MeetingChoice.noMeeting : nil, scope: item.scope)
        }
        return nil
    }

    /// Delivered items whose local audio can go (7 days after the server confirmed it).
    public static func expiredAudio(_ items: [Item], now: Date) -> [Item] {
        items.filter {
            $0.status == .delivered && $0.audioRemoved != true
                && ($0.deliveredAt.map { now.timeIntervalSince($0) >= keepAudio } ?? false)
        }
    }

    /// The reason shown in the menu for an error.
    public static func describe(_ error: Error) -> (Item.Status, String) {
        switch error as? APIError {
        case .offline?: return (.waiting, "Offline — will send when connected")
        case .unauthorized?: return (.waiting, "Not paired — open Settings")
        case let .server(status, detail)? where status >= 500: return (.waiting, "Server error \(status): \(detail)")
        case let .server(_, detail)?: return (.failed, detail)
        case .invalidResponse?: return (.waiting, "Unexpected answer from the server")
        case nil: return (.failed, error.localizedDescription)
        }
    }
}

/// Sends items to the second brain step by step, saving after each step so a restart resumes.
public final class DeliveryRunner: @unchecked Sendable {
    let store: ItemStore
    let api: DeviceAPI
    let now: () -> Date

    public init(store: ItemStore, api: DeviceAPI, now: @escaping () -> Date = Date.init) {
        self.store = store
        self.api = api
        self.now = now
    }

    /// Runs the network steps of one item until it is delivered, waiting or failed.
    @discardableResult
    public func deliver(_ id: UUID) async -> Item? {
        while var item = store.load(id), let step = Delivery.next(item, paired: true) {
            do {
                switch step {
                case .transcribeOnMac, .wait:
                    return item
                case .register:
                    item.status = .registering
                    try store.save(item)
                    item.recordingId = try await api.register(item)
                    if item.segments != nil { item.segmentsSent = true }
                    item.pendingLink = item.pendingLink ?? Delivery.initialLink(item)
                    item.status = .uploading
                case .link:
                    try await api.link(item.recordingId!, item.pendingLink!)
                    if let m = item.pendingLink?.meeting { item.meeting = m }
                    if let s = item.pendingLink?.scope { item.scope = s }
                    item.pendingLink = nil
                case .sendSegments:
                    try await api.replaceSegments(item.recordingId!, item.segments ?? [])
                    item.segmentsSent = true
                    item.note = nil
                case let .upload(name):
                    item.status = .uploading
                    try store.save(item)
                    let i = item.tracks.firstIndex { $0.name == name }!
                    try await api.upload(
                        item.recordingId!, track: name, file: store.url(item, item.tracks[i].file),
                        duration: item.tracks[i].duration > 0 ? item.tracks[i].duration : nil)
                    item.tracks[i].uploaded = true
                case .requestCloud:
                    _ = try await api.transcribe(item.recordingId!, speakers: item.speakers ?? false, dryRun: false)
                    item.cloudRequested = true
                    item.note = "Transcribing on the server"
                case .done:
                    item.status = .delivered
                    item.reason = nil
                    item.deliveredAt = now()
                }
                item.reason = step == .done ? nil : item.reason
                try store.save(item)
            } catch {
                let (status, reason) = Delivery.describe(error)
                item.status = status
                item.reason = reason
                try? store.save(item)
                return item
            }
        }
        return store.load(id)
    }

    /// Removes local audio of items delivered more than 7 days ago (the state stays for the list).
    public func cleanup() {
        for item in Delivery.expiredAudio(store.all(), now: now()) {
            for t in item.tracks { try? FileManager.default.removeItem(at: store.url(item, t.file)) }
            _ = try? store.update(item.id) { $0.audioRemoved = true }
        }
    }
}
