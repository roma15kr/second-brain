import AppKit
import RecorderCore
import ServiceManagement
import SwiftUI

/// Menu-bar app (no Dock icon: LSUIElement in Info.plist, set by install.sh).
@main
struct SecondBrainRecorderApp: App {
    @StateObject private var state = AppState()

    var body: some Scene {
        MenuBarExtra {
            MenuContent().environmentObject(state)
        } label: {
            Image(systemName: state.isPaired ? "waveform.circle" : "waveform.circle.fill")
        }
        Settings {
            SettingsView().environmentObject(state)
        }
    }
}

@MainActor
final class AppState: ObservableObject {
    @AppStorage("serverURL") var serverURL = "https://os.zhukovsky.biz"
    @Published var isPaired = false
    @Published var lastError: String?
    @Published var permissions = PermissionsModel()
    var systemAudioWorked: Bool?

    @Published var status: String?

    let store: TokenStore = KeychainTokenStore()
    let registrar = CarbonRegistrar()
    lazy var hotkeys = HotkeyConfig(store: UserDefaults.standard, registrar: registrar)
    var gesture = DictationGesture()
    var dictationStructured = false

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
    }

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

    func toggleRecording() { status = "Recording is not available yet" }
    func startDictation(structured: Bool) { status = structured ? "Dictating (structured)…" : "Dictating…" }
    func stopDictation() { status = nil }

    func refreshPermissions() {
        permissions = PermissionProbe.current(systemAudioWorked: systemAudioWorked)
    }

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
}

struct MenuContent: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        if state.isPaired {
            Text("Paired with the second brain")
        } else {
            Text("Not paired — open Settings to pair")
        }
        if let error = state.lastError { Text(error) }
        if let warning = state.permissions.menuWarning { Text(warning) }
        if let status = state.status { Text(status) }
        Divider()
        SettingsLink { Text("Settings…") }
        Button("Quit") { NSApplication.shared.terminate(nil) }.keyboardShortcut("q")
    }
}

struct SettingsView: View {
    @EnvironmentObject var state: AppState
    @State private var code = ""
    @State private var openAtLogin = SMAppService.mainApp.status == .enabled

    var body: some View {
        Form {
            TextField("Server", text: $state.serverURL)
            Toggle("Open at login", isOn: $openAtLogin)
                .onChange(of: openAtLogin) { _, on in
                    do {
                        if on { try SMAppService.mainApp.register() } else { try SMAppService.mainApp.unregister() }
                    } catch {
                        state.lastError = "Open at login: \(error.localizedDescription)"
                    }
                }
            if state.isPaired {
                LabeledContent("Status", value: "Paired")
                Button("Unpair this Mac") { state.unpaired() }
            } else {
                Text("Second brain → Settings → Recorder apps → Pair a device, then enter the code.")
                    .font(.caption)
                TextField("Pairing code", text: $code)
                Button("Pair") { Task { await state.pair(code: code) } }
                    .disabled(code.trimmingCharacters(in: .whitespaces).isEmpty)
            }
            if let error = state.lastError { Text(error).foregroundStyle(.red) }
            Divider()
            HotkeySettings()
            Divider()
            PermissionsView()
        }
        .padding()
        .frame(width: 420)
    }
}
