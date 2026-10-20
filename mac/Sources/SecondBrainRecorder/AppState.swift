import AppKit
import Combine
import RecorderCore
import SpeechKit
import SwiftUI

@MainActor
final class AppState: ObservableObject {
    @AppStorage("serverURL") var serverURL = "https://os.zhukovsky.biz"
    @Published var isPaired = false
    @Published var lastError: String?
    @Published var status: String?
    @Published var permissions = PermissionsModel()
    @Published var isRecording = false
    @Published var elapsed: TimeInterval = 0
    @Published var items: [Item] = []
    var systemAudioWorked: Bool?

    let store: TokenStore = KeychainTokenStore()
    let registrar = CarbonRegistrar()
    lazy var hotkeys = HotkeyConfig(store: UserDefaults.standard, registrar: registrar)
    var gesture = DictationGesture()
    var dictationStructured = false

    let itemStore = ItemStore.standard
    lazy var recorder = Recorder(
        store: itemStore, factory: AACSegmentFactory(),
        sources: { (MicrophoneSource(), SystemAudioSource()) })
    private var timer: AnyCancellable?

    init() {
        isPaired = store.load() != nil
        refreshPermissions()
        registrar.onEvent = { [weak self] action, pressed in
            Task { @MainActor in self?.hotkey(action, pressed: pressed) }
        }
        let failed = hotkeys.registerAll()
        if !failed.isEmpty {
            lastError = "Hotkeys taken by another app: " + failed.map { hotkeys.combo($0).description }
                .joined(separator: ", ") + ". Change them in Settings."
        }
        timer = Timer.publish(every: 1, on: .main, in: .common).autoconnect().sink { [weak self] now in
            self?.tick(now)
        }
        Task { await recoverInterrupted() }
    }

    // MARK: pairing and permissions

    var pairing: Pairing? {
        guard let url = URL(string: serverURL) else { return nil }
        return Pairing(serverURL: url, store: store)
    }

    func pair(code: String) async {
        guard let pairing else { lastError = "The server address is not valid"; return }
        do {
            try await pairing.pair(code: code, deviceName: Host.current().localizedName ?? "Mac")
            isPaired = true
            lastError = nil
        } catch {
            lastError = error.localizedDescription
        }
    }

    func unpaired() {
        pairing?.forget()
        isPaired = false
    }

    func refreshPermissions() {
        permissions = PermissionProbe.current(systemAudioWorked: systemAudioWorked)
    }

    // MARK: hotkeys

    func hotkey(_ action: HotkeyAction, pressed: Bool) {
        let now = ProcessInfo.processInfo.systemUptime
        switch action {
        case .record:
            if pressed { toggleRecording() }
        case .dictate, .dictateStructured:
            let output = pressed ? gesture.press(at: now) : gesture.release(at: now)
            if output == .start { dictationStructured = action == .dictateStructured }
            switch output {
            case .start: startDictation(structured: dictationStructured)
            case .stop: stopDictation()
            case nil: break
            }
        }
    }

    // MARK: recording

    func toggleRecording(meeting: MeetingChoice = .automatic) {
        if isRecording {
            stopRecording(reason: nil)
        } else {
            startRecording(meeting: meeting)
        }
    }

    func startRecording(meeting: MeetingChoice) {
        do {
            let front = NSWorkspace.shared.frontmostApplication?.localizedName ?? ""
            try recorder.start(meeting: meeting, source: front, cloud: false, now: Date())
            isRecording = true
            elapsed = 0
            lastError = nil
        } catch {
            lastError = error.localizedDescription
        }
    }

    func stopRecording(reason: String?) {
        do {
            if recorder.othersHeardSound { systemAudioWorked = true }
            guard let item = try recorder.stop(now: Date(), reason: reason) else { return }
            isRecording = false
            refreshPermissions()
            Task { await finish(item) }
        } catch {
            lastError = error.localizedDescription
        }
    }

    private func tick(_ now: Date) {
        guard isRecording else { return }
        elapsed = recorder.elapsed(now: now)
        if (try? recorder.tick(now: now)) ?? nil != nil {
            stopRecording(reason: "Stopped after 4 hours")
            notify("Recording stopped after 4 hours")
        }
    }

    /// Joins each track's segment files into `<track>.m4a` and hands the item on.
    func finish(_ item: Item) async {
        var item = item
        for i in item.tracks.indices {
            let name = item.tracks[i].name
            let dir = itemStore.url(item, name)
            let segments = SegmentedTrackWriter.segments(in: dir)
            guard !segments.isEmpty else { continue }
            do {
                item.tracks[i].duration = try await AudioFiles.join(segments, to: itemStore.url(item, item.tracks[i].file))
                try? FileManager.default.removeItem(at: dir)
            } catch {
                item.status = .failed
                item.reason = "Could not join the \(name) track: \(error.localizedDescription)"
            }
        }
        try? itemStore.save(item)
        reloadItems()
        processQueue()
    }

    private func recoverInterrupted() async {
        for item in Recovery.unfinished(itemStore) {
            if let done = try? Recovery.finish(itemStore, item), done.status == .recorded {
                await finish(done)
            }
        }
        reloadItems()
        processQueue()
    }

    func reloadItems() { items = itemStore.all() }

    /// Transcription and delivery of waiting items (added with the pipeline).
    func processQueue() {}

    // MARK: dictation

    func startDictation(structured: Bool) { status = structured ? "Dictating (structured)…" : "Dictating…" }
    func stopDictation() { status = nil }

    func notify(_ text: String) { Notifier.show(text) }
}
