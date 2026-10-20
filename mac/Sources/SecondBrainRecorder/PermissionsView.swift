import AVFoundation
import AppKit
import ApplicationServices
import RecorderCore
import SwiftUI

/// Reads the current permission states from macOS.
enum PermissionProbe {
    static func current(systemAudioWorked: Bool?) -> PermissionsModel {
        var states: [Permission: PermissionState] = [:]
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized: states[.microphone] = .granted
        case .denied, .restricted: states[.microphone] = .denied
        default: states[.microphone] = .notAsked
        }
        // macOS has no query for the system-audio permission: the recorder reports whether the
        // last process tap delivered audio.
        switch systemAudioWorked {
        case .some(true): states[.systemAudio] = .granted
        case .some(false): states[.systemAudio] = .denied
        case .none: states[.systemAudio] = .notAsked
        }
        states[.accessibility] = AXIsProcessTrusted() ? .granted : .denied
        return PermissionsModel(states)
    }

    static func request(_ p: Permission) {
        switch p {
        case .microphone:
            AVCaptureDevice.requestAccess(for: .audio) { _ in }
        case .accessibility:
            let key = kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String
            _ = AXIsProcessTrustedWithOptions([key: true] as CFDictionary)
        case .systemAudio:
            NSWorkspace.shared.open(p.settingsURL)
        }
    }
}

struct PermissionsView: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Permissions").font(.headline)
            ForEach(Permission.allCases, id: \.self) { p in
                HStack(alignment: .top) {
                    Image(systemName: icon(state.permissions.state(p)))
                        .foregroundStyle(state.permissions.state(p) == .granted ? .green : .orange)
                    VStack(alignment: .leading) {
                        Text(p.title).bold()
                        Text(p.purpose).font(.caption)
                        if state.permissions.state(p) != .granted {
                            Text("Without it: \(p.neededFor)").font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    Spacer()
                    if state.permissions.state(p) != .granted {
                        Button("Allow…") { PermissionProbe.request(p) }
                        Button("Open Settings") { NSWorkspace.shared.open(p.settingsURL) }
                    }
                }
            }
            Button("Check again") { state.refreshPermissions() }
        }
    }

    private func icon(_ s: PermissionState) -> String {
        switch s {
        case .granted: return "checkmark.circle.fill"
        case .denied: return "exclamationmark.triangle.fill"
        case .notAsked: return "questionmark.circle"
        }
    }
}
