import Foundation

/// Files already imported (`imported.json`), so each recording is imported once (design D8).
public final class ImportLedger: @unchecked Sendable {
    public struct Entry: Codable, Equatable, Sendable {
        public let path: String
        public let size: Int
        public let modified: Date
    }

    let url: URL
    private let lock = NSLock()
    private var entries: [Entry]

    public init(url: URL) {
        self.url = url
        let d = JSONDecoder()
        d.dateDecodingStrategy = .iso8601
        entries = (try? Data(contentsOf: url)).flatMap { try? d.decode([Entry].self, from: $0) } ?? []
    }

    public static let extensions: Set<String> = ["m4a", "mp3", "wav", "caf", "ogg", "aac", "aiff", "qta"]

    public static func isAudio(_ url: URL) -> Bool { extensions.contains(url.pathExtension.lowercased()) }

    /// Imported before: the same file (path) or the same recording elsewhere (size and date).
    public func contains(path: String, size: Int, modified: Date) -> Bool {
        lock.withLock {
            entries.contains {
                $0.path == path || ($0.size == size && abs($0.modified.timeIntervalSince(modified)) < 1)
            }
        }
    }

    public func add(path: String, size: Int, modified: Date) throws {
        try lock.withLock {
            entries.append(Entry(path: path, size: size, modified: modified))
            let e = JSONEncoder()
            e.dateEncodingStrategy = .iso8601
            try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            try e.encode(entries).write(to: url, options: .atomic)
        }
    }
}

public enum WatchedFolder {
    /// A file must be unchanged this long before it is imported (a voice memo still syncing).
    public static let settle: TimeInterval = 30

    public struct Found: Equatable, Sendable {
        public let url: URL
        public let size: Int
        public let modified: Date
        public let created: Date
    }

    public static func attributes(_ url: URL) -> Found? {
        guard let v = try? url.resourceValues(forKeys: [.fileSizeKey, .contentModificationDateKey, .creationDateKey, .isRegularFileKey]),
              v.isRegularFile == true, let size = v.fileSize, let modified = v.contentModificationDate
        else { return nil }
        return Found(url: url, size: size, modified: modified, created: v.creationDate ?? modified)
    }

    /// Audio files in the folder (and its subfolders, as Voice Memos keeps them) that are settled
    /// and not imported yet, oldest first. Throws when the folder cannot be read (permissions).
    public static func newFiles(in dir: URL, ledger: ImportLedger, now: Date) throws -> [Found] {
        _ = try FileManager.default.contentsOfDirectory(atPath: dir.path)  // surfaces "not permitted"
        let walker = FileManager.default.enumerator(
            at: dir, includingPropertiesForKeys: [.fileSizeKey, .contentModificationDateKey, .creationDateKey, .isRegularFileKey],
            options: [.skipsHiddenFiles])
        var out: [Found] = []
        while let url = walker?.nextObject() as? URL {
            guard ImportLedger.isAudio(url), let f = attributes(url), f.size > 0,
                  now.timeIntervalSince(f.modified) >= settle,
                  !ledger.contains(path: url.path, size: f.size, modified: f.modified)
            else { continue }
            out.append(f)
        }
        return out.sorted { $0.created < $1.created }
    }
}

extension Item {
    /// A one-track item for an imported file, dated by the file (design D8).
    public static func imported(_ f: WatchedFolder.Found, kind: Kind, duration: TimeInterval, cloud: Bool) -> Item {
        var item = Item(kind: kind, startedAt: f.created, source: "import", status: .recorded, cloud: cloud)
        item.endedAt = f.created.addingTimeInterval(duration)
        item.title = f.url.deletingPathExtension().lastPathComponent
        item.importedFrom = f.url.path
        var track = Track(name: "mixed", file: "mixed.m4a")
        track.duration = duration
        item.tracks = [track]
        return item
    }
}
