import XCTest

@testable import RecorderCore

final class ImportDedupTests: XCTestCase {
    func testImportedOnceAcrossRestarts() throws {
        let dir = temporaryDirectory()
        let url = dir.appendingPathComponent("imported.json")
        let modified = Date(timeIntervalSince1970: 1_800_000_000)
        let ledger = ImportLedger(url: url)
        XCTAssertFalse(ledger.contains(path: "/a/call.m4a", size: 100, modified: modified))
        try ledger.add(path: "/a/call.m4a", size: 100, modified: modified)
        let reloaded = ImportLedger(url: url)
        XCTAssertTrue(reloaded.contains(path: "/a/call.m4a", size: 999, modified: Date()))
        // the same recording dropped again from another folder
        XCTAssertTrue(reloaded.contains(path: "/Downloads/call copy.m4a", size: 100, modified: modified))
        XCTAssertFalse(reloaded.contains(path: "/b/other.m4a", size: 100, modified: modified.addingTimeInterval(60)))
    }

    func testImportedItem() {
        let created = Date(timeIntervalSince1970: 1_800_000_000)
        let f = WatchedFolder.Found(url: URL(fileURLWithPath: "/x/Oleh call.m4a"), size: 10, modified: created, created: created)
        let item = Item.imported(f, kind: .call, duration: 754, cloud: false)
        XCTAssertEqual(item.startedAt, created)
        XCTAssertEqual(item.duration, 754)
        XCTAssertEqual(item.title, "Oleh call")
        XCTAssertEqual(item.tracks.map(\.name), ["mixed"])
        XCTAssertEqual(item.status, .recorded)
        XCTAssertEqual(Delivery.next(item, paired: true), .transcribeOnMac)
    }
}

final class WatchedFolderTests: XCTestCase {
    func touch(_ url: URL, modified: Date) throws {
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data([1, 2, 3]).write(to: url)
        try FileManager.default.setAttributes([.modificationDate: modified], ofItemAtPath: url.path)
    }

    func testNewSettledAudioFilesOnce() throws {
        let dir = temporaryDirectory()
        let ledger = ImportLedger(url: temporaryDirectory().appendingPathComponent("imported.json"))
        let now = Date()
        try touch(dir.appendingPathComponent("20261020 101500.m4a"), modified: now.addingTimeInterval(-600))
        try touch(dir.appendingPathComponent("sub/memo.m4a"), modified: now.addingTimeInterval(-300))
        try touch(dir.appendingPathComponent("syncing.m4a"), modified: now.addingTimeInterval(-5))
        try touch(dir.appendingPathComponent("notes.txt"), modified: now.addingTimeInterval(-600))
        let first = try WatchedFolder.newFiles(in: dir, ledger: ledger, now: now)
        XCTAssertEqual(Set(first.map(\.url.lastPathComponent)), ["20261020 101500.m4a", "memo.m4a"])
        for f in first { try ledger.add(path: f.url.path, size: f.size, modified: f.modified) }
        XCTAssertTrue(try WatchedFolder.newFiles(in: dir, ledger: ledger, now: now).isEmpty)
        // the syncing memo is picked up once it has settled
        let later = try WatchedFolder.newFiles(in: dir, ledger: ledger, now: now.addingTimeInterval(60))
        XCTAssertEqual(later.map(\.url.lastPathComponent), ["syncing.m4a"])
    }

    func testUnreadableFolderThrows() {
        XCTAssertThrowsError(try WatchedFolder.newFiles(
            in: URL(fileURLWithPath: "/nonexistent-\(UUID())"), ledger: ImportLedger(url: temporaryDirectory().appendingPathComponent("l.json")), now: Date()))
    }
}
