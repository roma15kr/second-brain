import AppKit
import RecorderCore
import SwiftUI

/// "Press the new combination" fields for the hotkeys (design D6).
struct HotkeySettings: View {
    @EnvironmentObject var state: AppState
    @State private var listening: HotkeyAction?
    @State private var monitor: Any?
    @State private var message: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Hotkeys").font(.headline)
            row("Record a call", .record)
            row("Dictate", .dictate)
            HStack {
                Text("Structured dictation: add")
                Picker("", selection: Binding(
                    get: { state.hotkeys.structured.rawValue },
                    set: { raw in
                        do {
                            try state.hotkeys.changeStructured(to: Modifiers(rawValue: raw))
                            message = nil
                        } catch {
                            message = error.localizedDescription
                        }
                        state.objectWillChange.send()
                    }
                )) {
                    ForEach([Modifiers.shift, .command, .option, .control], id: \.rawValue) { m in
                        Text(m.symbols).tag(m.rawValue)
                    }
                }
                .frame(width: 70)
                Text("→ \(state.hotkeys.structuredCombo.description)").foregroundStyle(.secondary)
            }
            Text("Dictation: hold the keys to talk, or press once to start and again to stop.")
                .font(.caption).foregroundStyle(.secondary)
            if let message { Text(message).foregroundStyle(.red).font(.caption) }
        }
        .onDisappear(perform: stopListening)
    }

    private func row(_ title: String, _ action: HotkeyAction) -> some View {
        HStack {
            Text(title).frame(width: 120, alignment: .leading)
            Button(listening == action ? "Press the new combination…" : state.hotkeys.combo(action).description) {
                listen(for: action)
            }
            .frame(minWidth: 200)
            if listening == action { Button("Cancel", action: stopListening) }
        }
    }

    private func listen(for action: HotkeyAction) {
        stopListening()
        listening = action
        monitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
            if event.keyCode == KeyCombo.escape && event.modifierFlags.intersection(.deviceIndependentFlagsMask).isEmpty {
                stopListening()
                return nil
            }
            let combo = KeyCombo(
                keyCode: UInt32(event.keyCode), modifiers: CarbonRegistrar.modifiers(event.modifierFlags))
            do {
                try state.hotkeys.change(action, to: combo)
                message = nil
            } catch {
                message = "\(combo): \(error.localizedDescription) The previous hotkey is kept."
            }
            state.objectWillChange.send()
            stopListening()
            return nil
        }
    }

    private func stopListening() {
        if let monitor { NSEvent.removeMonitor(monitor) }
        monitor = nil
        listening = nil
    }
}
