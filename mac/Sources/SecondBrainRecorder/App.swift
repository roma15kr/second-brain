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
            if state.isRecording {
                Image(systemName: "record.circle.fill")
                Text(Self.clock(state.elapsed))
            } else {
                Image(systemName: state.isPaired ? "waveform.circle" : "waveform.circle.fill")
            }
        }
        Settings {
            SettingsView().environmentObject(state)
        }
    }

    static func clock(_ t: TimeInterval) -> String {
        let s = Int(t)
        return s >= 3600
            ? String(format: "%d:%02d:%02d", s / 3600, s / 60 % 60, s % 60)
            : String(format: "%d:%02d", s / 60, s % 60)
    }
}

struct MenuContent: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        if state.isRecording {
            Button("Stop recording (\(state.hotkeys.record.description))") { state.toggleRecording() }
        } else {
            Button("Record a call (\(state.hotkeys.record.description))") { state.toggleRecording() }
        }
        if !state.isPaired { Text("Not paired — open Settings to pair") }
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
        .frame(width: 480)
    }
}
