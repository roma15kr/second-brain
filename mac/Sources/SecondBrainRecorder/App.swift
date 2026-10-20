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
            if state.dictating {
                Image(systemName: "mic.fill")
            } else if state.isRecording {
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
        Group {
            if state.isRecording {
                Button("Stop recording (\(state.hotkeys.record.description))") { state.toggleRecording() }
                Menu("Meeting: \(state.currentMeeting)") {
                    MeetingChoices(includeAutomatic: true, pick: { state.chooseMeeting($0) }, newMeeting: { state.newMeeting(for: nil) })
                }
            } else {
                Button("Record a call (\(state.hotkeys.record.description))") { state.toggleRecording() }
                Menu("Record for a meeting") {
                    MeetingChoices(includeAutomatic: false, pick: { state.startRecording(meeting: $0) }, newMeeting: { state.newMeeting(for: nil) })
                }
            }
        }
        .onAppear { state.refreshMeetings() }
        if !state.isPaired { Text("Not paired — open Settings to pair") }
        if let error = state.lastError { Text(error) }
        if let warning = state.permissions.menuWarning { Text(warning) }
        if let status = state.status { Text(status) }
        RecentItems()
        Divider()
        Button("Import recordings…") { ImportPanel.show(state) }
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
            CallSettingsView()
            Divider()
            DictationSettings()
            Divider()
            HotkeySettings()
            Divider()
            PermissionsView()
        }
        .padding()
        .frame(width: 480)
    }
}

/// The last recordings with their delivery state, and what can be done with them.
struct RecentItems: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        let recent = Array(state.items.suffix(8).reversed())
        if !recent.isEmpty {
            Divider()
            Text("Recent")
            ForEach(recent) { item in
                Menu(Self.title(item)) {
                    if let reason = item.reason { Text(reason) }
                    if let note = item.note { Text(note) }
                    if item.status != .recording && item.status != .failed {
                        Menu("Change meeting") {
                            MeetingChoices(includeAutomatic: false, pick: { state.relink(item.id, meeting: $0) },
                                           newMeeting: { state.newMeeting(for: item.id) })
                        }
                        Menu("Set project") { ProjectChoices { state.relink(item.id, meeting: nil, scope: $0) } }
                    }
                    if let s = item.transcribeSeconds { Text("Transcribed on this Mac in \(SecondBrainRecorderApp.clock(s))") }
                    if item.recordingId != nil && item.tracks.allSatisfy(\.uploaded) && item.speakers != true {
                        Button("Separate speakers…") { Task { await state.pipeline.separateSpeakers(item) } }
                    }
                    if item.status == .failed || item.status == .waiting {
                        Button("Try again") {
                            _ = try? state.itemStore.update(item.id) {
                                if $0.status == .failed { $0.status = $0.segments == nil && !$0.cloud ? .recorded : .transcribed }
                            }
                            state.processQueue()
                        }
                    }
                    Button("Show in Finder") { NSWorkspace.shared.activateFileViewerSelecting([state.itemStore.folder(item.id)]) }
                }
            }
        }
    }

    static func title(_ item: Item) -> String {
        let f = DateFormatter()
        f.dateFormat = Calendar.current.isDateInToday(item.startedAt) ? "HH:mm" : "d MMM HH:mm"
        let what = item.title ?? (item.meeting == .automatic ? (item.source.isEmpty ? "Call" : item.source) : item.meeting.label)
        return "\(f.string(from: item.startedAt)) \(what) · \(SecondBrainRecorderApp.clock(item.duration)) — \(status(item))"
    }

    static func status(_ item: Item) -> String {
        switch item.status {
        case .recording: return "recording"
        case .recorded: return "waiting to transcribe"
        case .transcribing: return item.reason ?? "transcribing"
        case .transcribed: return "ready to send"
        case .registering, .uploading: return "sending"
        case .cloudTranscribing: return "transcribing on the server"
        case .delivered: return item.pendingLink == nil ? "delivered" : "updating the meeting"
        case .waiting: return item.reason ?? "waiting"
        case .failed: return "failed"
        }
    }
}

struct DictationSettings: View {
    @AppStorage("dictation.form") private var form = "clean"

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Dictation").font(.headline)
            Picker("Default text", selection: $form) {
                Text(DictationForm.verbatim.label).tag("verbatim")
                Text(DictationForm.clean.label).tag("clean")
            }
            Text("With the structured modifier the text becomes a summary with points and actions. Dictation uses OpenAI through your server; offline the Mac types it as said.")
                .font(.caption).foregroundStyle(.secondary)
        }
    }
}
