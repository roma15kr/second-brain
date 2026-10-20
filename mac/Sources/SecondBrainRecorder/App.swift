import AppKit
import RecorderCore
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

    let store: TokenStore = KeychainTokenStore()

    init() { isPaired = store.load() != nil }

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
        Divider()
        SettingsLink { Text("Settings…") }
        Button("Quit") { NSApplication.shared.terminate(nil) }.keyboardShortcut("q")
    }
}

struct SettingsView: View {
    @EnvironmentObject var state: AppState
    @State private var code = ""

    var body: some View {
        Form {
            TextField("Server", text: $state.serverURL)
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
        }
        .padding()
        .frame(width: 420)
    }
}
