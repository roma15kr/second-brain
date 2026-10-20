import CryptoKit
import Foundation

/// A calendar meeting offered when a recording starts (`GET /api/devices/meetings`).
public struct MeetingSummary: Codable, Equatable, Sendable, Identifiable {
    public var id: Int
    public var title: String
    public var start: Date
    public var end: Date
    public var inProgress: Bool

    public init(id: Int, title: String, start: Date, end: Date, inProgress: Bool) {
        self.id = id
        self.title = title
        self.start = start
        self.end = end
        self.inProgress = inProgress
    }
}

public struct TranscribeAnswer: Decodable, Equatable, Sendable {
    public var provider: String
    public var estimatedUsd: Double
    public var jobId: Int?
}

public struct DictationAnswer: Decodable, Equatable, Sendable {
    public var id: Int?
    public var text: String
    public var note: String?
}

struct UploadState: Decodable { let receivedBytes: Int; let totalBytes: Int; let complete: Bool }

/// The device side of the second brain's API (`/api/devices/*`, design D7).
public struct DeviceAPI: Sendable {
    public let client: APIClient
    public var chunkSize: Int

    public init(client: APIClient, chunkSize: Int = 8 * 1024 * 1024) {
        self.client = client
        self.chunkSize = chunkSize
    }

    struct Segment: Encodable { let speaker: String; let isOwner: Bool; let start: Double; let end: Double; let text: String }

    struct Registration: Encodable {
        let kind: String
        let startedAt: Date
        let endedAt: Date
        let source: String
        let segments: [Segment]
        let notes: String
        let idempotencyKey: String
        let eventId: Int?
        let newMeeting: NewMeeting?
    }

    struct Created: Decodable { let recordingId: Int }

    /// Registers the recording once (idempotent by the item id); returns the server's id.
    public func register(_ item: Item) async throws -> Int {
        var eventId: Int?
        var newMeeting: NewMeeting?
        switch item.meeting {
        case let .event(id, _): eventId = id
        case let .new(m): newMeeting = m
        case .automatic, .none: break
        }
        let body = Registration(
            kind: item.kind.rawValue, startedAt: item.startedAt, endedAt: item.endedAt ?? item.startedAt,
            source: item.source,
            segments: (item.segments ?? []).map {
                Segment(speaker: $0.speaker, isOwner: $0.isOwner, start: $0.start, end: $0.end, text: $0.text)
            },
            notes: item.note ?? "", idempotencyKey: item.id.uuidString, eventId: eventId, newMeeting: newMeeting)
        let created: Created = try await client.json("POST", "api/devices/recordings", body: body)
        return created.recordingId
    }

    /// `event_id: null` must be sent explicitly to detach a recording from its meeting.
    struct LinkBody: Encodable {
        let meeting: MeetingChoice?
        let scope: String?
        enum Keys: String, CodingKey { case eventId, newMeeting, scope }

        func encode(to encoder: Encoder) throws {
            var c = encoder.container(keyedBy: Keys.self)
            switch meeting {
            case let .event(id, _): try c.encode(id, forKey: .eventId)
            case let .new(m): try c.encode(m, forKey: .newMeeting)
            case .none?: try c.encodeNil(forKey: .eventId)
            case .automatic?, nil: break
            }
            try c.encodeIfPresent(scope, forKey: .scope)
        }
    }

    public func link(_ recordingId: Int, _ request: LinkRequest) async throws {
        struct Answer: Decodable {}
        let _: Answer = try await client.json(
            "POST", "api/devices/recordings/\(recordingId)/link",
            body: LinkBody(meeting: request.meeting, scope: request.scope))
    }

    public func meetings() async throws -> [MeetingSummary] {
        struct List: Decodable { let meetings: [MeetingSummary] }
        let list: List = try await client.json("GET", "api/devices/meetings")
        return list.meetings
    }

    public func transcribe(_ recordingId: Int, speakers: Bool, dryRun: Bool) async throws -> TranscribeAnswer {
        struct Body: Encodable { let speakers: Bool; let dryRun: Bool }
        return try await client.json(
            "POST", "api/devices/recordings/\(recordingId)/transcribe", body: Body(speakers: speakers, dryRun: dryRun))
    }

    public func dictate(_ audio: Data, mime: String, form: String, seconds: Double) async throws -> DictationAnswer {
        let req = client.request(
            "POST", "api/devices/dictations",
            query: [URLQueryItem(name: "form", value: form), URLQueryItem(name: "seconds", value: String(format: "%.1f", seconds))],
            body: audio, contentType: mime)
        let (data, http) = try await client.send(req)
        guard (200..<300).contains(http.statusCode) else {
            throw APIError.server(status: http.statusCode, detail: APIClient.detail(data))
        }
        return try JSONDecoder.api.decode(DictationAnswer.self, from: data)
    }

    public static func sha256(of url: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var hasher = SHA256()
        while let data = try handle.read(upToCount: 1 << 20), !data.isEmpty { hasher.update(data: data) }
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }

    /// Uploads a track resumably: announce (returns what already arrived), then PUT chunks with
    /// `Content-Range`; a 409 continues from the server's offset, a checksum failure starts over once.
    public func upload(_ recordingId: Int, track: String, file: URL, duration: Double?) async throws {
        let total = (try FileManager.default.attributesOfItem(atPath: file.path)[.size] as? NSNumber)?.intValue ?? 0
        let sha = try Self.sha256(of: file)
        struct Announce: Encodable { let mime: String; let totalBytes: Int; let sha256: String; let durationSeconds: Double? }
        let path = "api/devices/recordings/\(recordingId)/audio/\(track)"
        let body = try JSONEncoder.api.encode(Announce(mime: "audio/mp4", totalBytes: total, sha256: sha, durationSeconds: duration))
        let (data, http) = try await client.send(client.request("POST", path, body: body))
        if http.statusCode == 409 { return }  // a complete track is already stored for this recording
        guard (200..<300).contains(http.statusCode) else {
            throw APIError.server(status: http.statusCode, detail: APIClient.detail(data))
        }
        var state = try JSONDecoder.api.decode(UploadState.self, from: data)
        var restarts = 0
        let handle = try FileHandle(forReadingFrom: file)
        defer { try? handle.close() }
        var offset = state.receivedBytes
        while !state.complete && offset < total {
            try handle.seek(toOffset: UInt64(offset))
            let chunk = try handle.read(upToCount: chunkSize) ?? Data()
            let end = offset + chunk.count - 1
            let req = client.request(
                "PUT", path, body: chunk, contentType: "application/octet-stream",
                headers: ["Content-Range": "bytes \(offset)-\(end)/\(total)"])
            let (data, http) = try await client.send(req)
            switch http.statusCode {
            case 200..<300:
                state = try JSONDecoder.api.decode(UploadState.self, from: data)
                offset = state.receivedBytes
            case 409:  // the server has a different amount: continue from there
                let header = http.value(forHTTPHeaderField: "Upload-Offset").flatMap(Int.init)
                let body = try? JSONDecoder.api.decode(UploadState.self, from: data)
                guard let next = header ?? body?.receivedBytes else {
                    throw APIError.server(status: 409, detail: APIClient.detail(data))
                }
                offset = next
            case 422 where restarts == 0:  // checksum mismatch: the server starts over
                restarts += 1
                offset = 0
            default:
                throw APIError.server(status: http.statusCode, detail: APIClient.detail(data))
            }
        }
    }
}
