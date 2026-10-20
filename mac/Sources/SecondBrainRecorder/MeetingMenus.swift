import AppKit
import RecorderCore
import SwiftUI

extension AppState {
    func refreshMeetings() {
        guard let pairing, isPaired else { return }
        let api = DeviceAPI(client: pairing.client)
        Task {
            meetings = await meetingPicker.load(now: Date()) { try await api.meetings() }
        }
    }

    /// While recording: link the call to another meeting.
    func chooseMeeting(_ choice: MeetingChoice) {
        do {
            try recorder.setMeeting(choice)
            currentMeeting = choice.label
        } catch {
            lastError = error.localizedDescription
        }
    }

    /// After recording: change the meeting or project of a recent recording.
    func relink(_ id: UUID, meeting: MeetingChoice?, scope: String? = nil) {
        _ = try? itemStore.update(id) { Relink.apply(&$0, meeting: meeting, scope: scope) }
        reloadItems()
        processQueue()
    }

    func newMeeting(for target: UUID?) {
        NewMeetingPanel.show { [weak self] meeting in
            guard let self else { return }
            if let target { relink(target, meeting: .new(meeting)) } else if isRecording { chooseMeeting(.new(meeting)) } else {
                startRecording(meeting: .new(meeting))
            }
        }
    }
}

/// Meetings around now, "No meeting" and "New meeting…" as menu items.
struct MeetingChoices: View {
    @EnvironmentObject var state: AppState
    let includeAutomatic: Bool
    let pick: (MeetingChoice) -> Void
    let newMeeting: () -> Void

    var body: some View {
        if includeAutomatic { Button("Automatic (matched by time)") { pick(.automatic) } }
        ForEach(state.meetings) { m in
            Button(Self.label(m)) { pick(.event(id: m.id, title: m.title)) }
        }
        if state.meetings.isEmpty { Text(state.isPaired ? "No meetings around now" : "Pair to see meetings") }
        Button("No meeting") { pick(.none) }
        Button("New meeting…", action: newMeeting)
    }

    static func label(_ m: MeetingSummary) -> String {
        let f = DateFormatter()
        f.dateFormat = "HH:mm"
        return "\(f.string(from: m.start)) \(m.title)\(m.inProgress ? " (now)" : "")"
    }
}

struct ProjectChoices: View {
    let pick: (String) -> Void

    var body: some View {
        ForEach(Projects.all, id: \.self) { p in Button(p) { pick(p) } }
    }
}

/// The small form for a meeting that is not in the calendar.
enum NewMeetingPanel {
    @MainActor private static var panel: NSPanel?

    @MainActor static func show(onCreate: @escaping (NewMeeting) -> Void) {
        panel?.close()
        let p = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: 420, height: 230), styleMask: [.titled, .closable],
            backing: .buffered, defer: false)
        p.title = "New meeting"
        p.level = .floating
        p.contentView = NSHostingView(rootView: NewMeetingView(
            onCreate: { meeting in
                onCreate(meeting)
                p.close()
            }, onCancel: { p.close() }))
        p.center()
        NSApp.activate(ignoringOtherApps: true)
        p.makeKeyAndOrderFront(nil)
        panel = p
    }
}

struct NewMeetingView: View {
    @State private var form = NewMeetingForm()
    let onCreate: (NewMeeting) -> Void
    let onCancel: () -> Void

    var body: some View {
        Form {
            TextField("Title", text: $form.title, prompt: Text("Dealer — October prices"))
            Picker("Project", selection: Binding(get: { form.scope ?? "" }, set: { form.scope = $0.isEmpty ? nil : $0 })) {
                Text("None").tag("")
                ForEach(Projects.all, id: \.self) { Text($0).tag($0) }
            }
            TextField("Participants", text: $form.participants, prompt: Text("Names or emails, separated by commas"))
            HStack {
                Spacer()
                Button("Cancel", action: onCancel).keyboardShortcut(.cancelAction)
                Button("Create") { if let m = form.meeting { onCreate(m) } }
                    .keyboardShortcut(.defaultAction)
                    .disabled(form.meeting == nil)
            }
        }
        .padding()
    }
}
