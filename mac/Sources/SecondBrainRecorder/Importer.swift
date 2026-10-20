import AppKit
import RecorderCore
import SpeechKit
import SwiftUI
import UniformTypeIdentifiers

extension AppState {
    var watchedFolder: URL? {
        UserDefaults.standard.string(forKey: "imports.folder").map { URL(fileURLWithPath: $0) }
    }

    /// Imports files (dropped, chosen, or found in the watched folder) as one-track recordings.
    func importFiles(_ files: [WatchedFolder.Found], kind: Item.Kind, quiet: Bool = false) async {
        let store = itemStore
        let ledger = importLedger
        let cloud = CallSettings.engine == "cloud"
        for f in files {
            if ledger.contains(path: f.url.path, size: f.size, modified: f.modified) {
                if !quiet { notify("\(f.url.lastPathComponent) was imported before") }
                continue
            }
            let result: Result<Item, Error> = await Task.detached(priority: .utility) {
                Result {
                    var item = Item.imported(f, kind: kind, duration: 0, cloud: cloud)
                    try FileManager.default.createDirectory(at: store.folder(item.id), withIntermediateDirectories: true)
                    let out = AACSegmentFile.self
                    let file = try out.init(url: store.url(item, "mixed.m4a"))
                    var samples = 0
                    try AudioFiles.read(f.url) { chunk in
                        samples += chunk.count
                        try file.write(chunk)
                    }
                    file.close()
                    guard samples > 0 else { throw CaptureError(message: "no audio in the file") }
                    let seconds = Double(samples) / RecorderCore.sampleRate
                    item.tracks[0].duration = seconds
                    item.endedAt = item.startedAt.addingTimeInterval(seconds)
                    try store.save(item)
                    return item
                }
            }.value
            switch result {
            case .success:
                try? ledger.add(path: f.url.path, size: f.size, modified: f.modified)
            case let .failure(error):
                notify("Could not import \(f.url.lastPathComponent): \(error.localizedDescription)")
            }
        }
        reloadItems()
        processQueue()
    }

    func importURLs(_ urls: [URL], kind: Item.Kind) {
        let found = urls.filter(ImportLedger.isAudio).compactMap(WatchedFolder.attributes)
        if found.count < urls.count { notify("Only audio files can be imported (m4a, mp3, wav, caf, ogg)") }
        Task { await importFiles(found, kind: kind) }
    }

    /// New settled voice memos in the watched folder become voice notes (design D8).
    func scanWatchedFolder() {
        guard let dir = watchedFolder else { return }
        do {
            let found = try WatchedFolder.newFiles(in: dir, ledger: importLedger, now: Date())
            importHint = nil
            if !found.isEmpty { Task { await importFiles(found, kind: .voiceNote, quiet: true) } }
        } catch {
            importHint = "macOS does not let the app read this folder. For Voice Memos, add Second Brain Recorder in System Settings → Privacy & Security → Full Disk Access."
        }
    }

    func watch(_ dir: URL?) {
        UserDefaults.standard.set(dir?.path, forKey: "imports.folder")
        folderWatcher?.cancel()
        folderWatcher = nil
        guard let dir else { importHint = nil; return }
        let fd = open(dir.path, O_EVTONLY)
        if fd >= 0 {
            let source = DispatchSource.makeFileSystemObjectSource(fileDescriptor: fd, eventMask: [.write, .extend, .rename], queue: .main)
            source.setEventHandler { [weak self] in
                // settle time: look again once the new file has stopped changing
                DispatchQueue.main.asyncAfter(deadline: .now() + WatchedFolder.settle + 2) { self?.scanWatchedFolder() }
            }
            source.setCancelHandler { close(fd) }
            source.resume()
            folderWatcher = source
        }
        scanWatchedFolder()
    }
}

enum ImportPanel {
    @MainActor private static var panel: NSPanel?

    @MainActor static func show(_ state: AppState) {
        panel?.close()
        let p = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: 460, height: 330), styleMask: [.titled, .closable],
            backing: .buffered, defer: false)
        p.title = "Import recordings"
        p.contentView = NSHostingView(rootView: ImportView().environmentObject(state))
        p.center()
        NSApp.activate(ignoringOtherApps: true)
        p.makeKeyAndOrderFront(nil)
        panel = p
    }
}

struct ImportView: View {
    @EnvironmentObject var state: AppState
    @State private var kind = Item.Kind.call
    @State private var targeted = false
    @State private var folder = UserDefaults.standard.string(forKey: "imports.folder")

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Picker("Import as", selection: $kind) {
                Text("Call").tag(Item.Kind.call)
                Text("Voice note").tag(Item.Kind.voiceNote)
            }
            .pickerStyle(.segmented)
            RoundedRectangle(cornerRadius: 8)
                .strokeBorder(style: StrokeStyle(lineWidth: 2, dash: [6]))
                .foregroundStyle(targeted ? Color.accentColor : .secondary)
                .overlay(Text("Drop m4a, mp3, wav, caf or ogg files here"))
                .frame(height: 100)
                .dropDestination(for: URL.self) { urls, _ in
                    state.importURLs(urls, kind: kind)
                    return true
                } isTargeted: { targeted = $0 }
            Button("Choose files…") {
                let open = NSOpenPanel()
                open.allowsMultipleSelection = true
                open.allowedContentTypes = [.audio]
                if open.runModal() == .OK { state.importURLs(open.urls, kind: kind) }
            }
            Divider()
            Text("Watched folder (new recordings become voice notes automatically)").bold()
            Text(folder ?? "None").font(.caption).foregroundStyle(.secondary)
            HStack {
                Button("Choose folder…") {
                    let open = NSOpenPanel()
                    open.canChooseDirectories = true
                    open.canChooseFiles = false
                    open.message = "Voice Memos: ~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings"
                    if open.runModal() == .OK, let url = open.url {
                        state.watch(url)
                        folder = url.path
                    }
                }
                if folder != nil {
                    Button("Stop watching") {
                        state.watch(nil)
                        folder = nil
                    }
                }
            }
            if let hint = state.importHint {
                Text(hint).font(.caption).foregroundStyle(.orange)
                Button("Open Full Disk Access settings") {
                    NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles")!)
                }
            }
        }
        .padding()
    }
}
