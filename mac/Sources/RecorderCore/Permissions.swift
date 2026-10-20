import Foundation

/// The macOS permissions the recorder needs, what each is for, and where to grant it.
public enum Permission: String, CaseIterable, Sendable {
    case microphone
    case systemAudio
    case accessibility

    public var title: String {
        switch self {
        case .microphone: return "Microphone"
        case .systemAudio: return "System audio recording"
        case .accessibility: return "Accessibility"
        }
    }

    /// Why the app asks, in the owner's terms.
    public var purpose: String {
        switch self {
        case .microphone: return "Your side of calls and your dictation."
        case .systemAudio: return "The other participants of calls (Zoom, Telegram, Meet, any app)."
        case .accessibility: return "Typing dictated text into the app in front."
        }
    }

    /// What stops working without it.
    public var neededFor: String {
        switch self {
        case .microphone: return "recording and dictation"
        case .systemAudio: return "the \"others\" track of calls"
        case .accessibility: return "typing dictation (the text is copied to the clipboard instead)"
        }
    }

    /// The System Settings pane for this permission.
    public var settingsURL: URL {
        let pane: String
        switch self {
        case .microphone: pane = "Privacy_Microphone"
        case .systemAudio: pane = "Privacy_ScreenCapture"  // "Screen & System Audio Recording"
        case .accessibility: pane = "Privacy_Accessibility"
        }
        return URL(string: "x-apple.systempreferences:com.apple.preference.security?\(pane)")!
    }
}

public enum PermissionState: Equatable, Sendable {
    case granted
    case denied
    case notAsked  // macOS will ask on first use
}

/// Permission states as the app last saw them; the menu and the permissions screen read this.
public struct PermissionsModel: Equatable, Sendable {
    public var states: [Permission: PermissionState]

    public init(_ states: [Permission: PermissionState] = [:]) { self.states = states }

    public func state(_ p: Permission) -> PermissionState { states[p] ?? .notAsked }

    /// Permissions that are not granted, in a stable order.
    public var missing: [Permission] { Permission.allCases.filter { state($0) != .granted } }

    public var canRecordCalls: Bool { state(.microphone) == .granted && state(.systemAudio) != .denied }
    public var canDictate: Bool { state(.microphone) == .granted }
    public var canType: Bool { state(.accessibility) == .granted }

    /// A one-line warning for the menu, or nil when everything needed is granted.
    public var menuWarning: String? {
        let denied = missing.filter { state($0) == .denied }
        guard !denied.isEmpty else { return nil }
        return "Missing: " + denied.map(\.title).joined(separator: ", ")
    }
}
