import Foundation

public struct Modifiers: OptionSet, Codable, Hashable, Sendable {
    public let rawValue: Int
    public init(rawValue: Int) { self.rawValue = rawValue }
    public static let control = Modifiers(rawValue: 1)
    public static let option = Modifiers(rawValue: 2)
    public static let shift = Modifiers(rawValue: 4)
    public static let command = Modifiers(rawValue: 8)

    /// In the order macOS menus show them: ⌃⌥⇧⌘.
    public var symbols: String {
        (contains(.control) ? "⌃" : "") + (contains(.option) ? "⌥" : "")
            + (contains(.shift) ? "⇧" : "") + (contains(.command) ? "⌘" : "")
    }
}

/// A key (macOS virtual key code) with modifiers.
public struct KeyCombo: Codable, Hashable, Sendable, CustomStringConvertible {
    public let keyCode: UInt32
    public let modifiers: Modifiers

    public init(keyCode: UInt32, modifiers: Modifiers) {
        self.keyCode = keyCode
        self.modifiers = modifiers
    }

    public static let keyR: UInt32 = 15
    public static let keyD: UInt32 = 2
    public static let space: UInt32 = 49
    public static let tab: UInt32 = 48
    public static let escape: UInt32 = 53

    public var description: String { modifiers.symbols + KeyCombo.keyName(keyCode) }

    public var isFunctionKey: Bool { KeyCombo.functionKeys[keyCode] != nil }

    static let functionKeys: [UInt32: String] = [
        122: "F1", 120: "F2", 99: "F3", 118: "F4", 96: "F5", 97: "F6", 98: "F7", 100: "F8",
        101: "F9", 109: "F10", 103: "F11", 111: "F12",
    ]
    static let names: [UInt32: String] = [
        0: "A", 1: "S", 2: "D", 3: "F", 4: "H", 5: "G", 6: "Z", 7: "X", 8: "C", 9: "V", 11: "B",
        12: "Q", 13: "W", 14: "E", 15: "R", 16: "Y", 17: "T", 18: "1", 19: "2", 20: "3", 21: "4",
        22: "6", 23: "5", 24: "=", 25: "9", 26: "7", 27: "-", 28: "8", 29: "0", 30: "]", 31: "O",
        32: "U", 33: "[", 34: "I", 35: "P", 36: "Return", 37: "L", 38: "J", 39: "'", 40: "K",
        41: ";", 42: "\\", 43: ",", 44: "/", 45: "N", 46: "M", 47: ".", 48: "Tab", 49: "Space",
        50: "`", 51: "Delete", 53: "Esc",
    ]

    public static func keyName(_ code: UInt32) -> String {
        functionKeys[code] ?? names[code] ?? "Key \(code)"
    }
}

public enum HotkeyAction: String, Codable, CaseIterable, Sendable {
    case record
    case dictate
    case dictateStructured  // the dictation hotkey plus the structured modifier
}

public enum HotkeyError: Error, Equatable, LocalizedError {
    case needsModifier
    case reservedBySystem(String)
    case usedByOtherAction(HotkeyAction)
    case taken  // the system or another app refused the registration
    case modifierInDictationHotkey

    public var errorDescription: String? {
        switch self {
        case .needsModifier: return "Use at least one of ⌃ ⌥ ⌘ (or a function key)."
        case let .reservedBySystem(what): return "This combination is used by macOS (\(what))."
        case let .usedByOtherAction(a): return "This combination is already the \(a.label) hotkey."
        case .taken: return "This combination is taken by another app."
        case .modifierInDictationHotkey:
            return "The structured modifier must not already be part of the dictation hotkey."
        }
    }
}

extension HotkeyAction {
    public var label: String {
        switch self {
        case .record: return "recording"
        case .dictate: return "dictation"
        case .dictateStructured: return "structured dictation"
        }
    }
}

/// Registers global hotkeys with macOS (Carbon in the app, a fake in tests).
public protocol HotkeyRegistrar: AnyObject {
    /// Throws `HotkeyError.taken` when the combination cannot be registered.
    func register(_ combo: KeyCombo, for action: HotkeyAction) throws
    func unregister(_ action: HotkeyAction)
}

/// The hotkeys, persisted in settings; changes are validated, applied at once, and the previous
/// hotkey is kept when the new one is refused.
public final class HotkeyConfig {
    public static let defaultRecord = KeyCombo(keyCode: KeyCombo.keyR, modifiers: [.control, .option])
    public static let defaultDictate = KeyCombo(keyCode: KeyCombo.keyD, modifiers: [.control, .option])
    public static let defaultStructured: Modifiers = .shift

    static let reserved: [KeyCombo: String] = [
        KeyCombo(keyCode: KeyCombo.space, modifiers: .command): "Spotlight",
        KeyCombo(keyCode: KeyCombo.space, modifiers: [.command, .option]): "Finder search",
        KeyCombo(keyCode: KeyCombo.space, modifiers: .control): "input source",
        KeyCombo(keyCode: KeyCombo.space, modifiers: [.control, .command]): "emoji",
        KeyCombo(keyCode: KeyCombo.tab, modifiers: .command): "app switcher",
        KeyCombo(keyCode: 12, modifiers: .command): "Quit",
        KeyCombo(keyCode: 13, modifiers: .command): "Close window",
        KeyCombo(keyCode: 8, modifiers: .command): "Copy",
        KeyCombo(keyCode: 9, modifiers: .command): "Paste",
        KeyCombo(keyCode: 7, modifiers: .command): "Cut",
        KeyCombo(keyCode: 6, modifiers: .command): "Undo",
        KeyCombo(keyCode: 0, modifiers: .command): "Select all",
        KeyCombo(keyCode: 12, modifiers: [.control, .command]): "Lock screen",
        KeyCombo(keyCode: KeyCombo.escape, modifiers: [.option, .command]): "Force quit",
        KeyCombo(keyCode: 20, modifiers: [.shift, .command]): "screenshot",
        KeyCombo(keyCode: 21, modifiers: [.shift, .command]): "screenshot",
        KeyCombo(keyCode: 23, modifiers: [.shift, .command]): "screenshot",
    ]

    let store: KeyValueStore
    let registrar: HotkeyRegistrar
    public private(set) var record: KeyCombo
    public private(set) var dictate: KeyCombo
    public private(set) var structured: Modifiers

    public init(store: KeyValueStore, registrar: HotkeyRegistrar) {
        self.store = store
        self.registrar = registrar
        record = store.decoded(KeyCombo.self, forKey: "hotkey.record") ?? Self.defaultRecord
        dictate = store.decoded(KeyCombo.self, forKey: "hotkey.dictate") ?? Self.defaultDictate
        structured = store.decoded(Modifiers.self, forKey: "hotkey.structured") ?? Self.defaultStructured
    }

    public var structuredCombo: KeyCombo {
        KeyCombo(keyCode: dictate.keyCode, modifiers: dictate.modifiers.union(structured))
    }

    public func combo(_ action: HotkeyAction) -> KeyCombo {
        switch action {
        case .record: return record
        case .dictate: return dictate
        case .dictateStructured: return structuredCombo
        }
    }

    /// Registers all hotkeys (at launch); returns the actions that could not be registered.
    @discardableResult
    public func registerAll() -> [HotkeyAction] {
        HotkeyAction.allCases.filter { action in
            (try? registrar.register(combo(action), for: action)) == nil
        }
    }

    static func validate(_ combo: KeyCombo) throws {
        if let what = reserved[combo] { throw HotkeyError.reservedBySystem(what) }
        if combo.modifiers.isDisjoint(with: [.control, .option, .command]) && !combo.isFunctionKey {
            throw HotkeyError.needsModifier
        }
    }

    /// Changes the recording or dictation hotkey. On any refusal the previous one stays active.
    public func change(_ action: HotkeyAction, to combo: KeyCombo) throws {
        precondition(action != .dictateStructured, "change the structured modifier instead")
        try Self.validate(combo)
        let other: HotkeyAction = action == .record ? .dictate : .record
        let newStructured = KeyCombo(keyCode: combo.keyCode, modifiers: combo.modifiers.union(structured))
        if combo == self.combo(other) || (action == .record && combo == structuredCombo) {
            throw HotkeyError.usedByOtherAction(combo == self.combo(other) ? other : .dictateStructured)
        }
        if action == .dictate {
            if !combo.modifiers.isDisjoint(with: structured) { throw HotkeyError.modifierInDictationHotkey }
            if newStructured == record { throw HotkeyError.usedByOtherAction(.record) }
            try Self.validate(newStructured)
        }
        let previous = self.combo(action)
        let previousStructured = structuredCombo
        registrar.unregister(action)
        if action == .dictate { registrar.unregister(.dictateStructured) }
        do {
            try registrar.register(combo, for: action)
            if action == .dictate {
                do {
                    try registrar.register(newStructured, for: .dictateStructured)
                } catch {
                    registrar.unregister(.dictate)
                    throw error
                }
            }
        } catch {
            try? registrar.register(previous, for: action)
            if action == .dictate { try? registrar.register(previousStructured, for: .dictateStructured) }
            throw error
        }
        if action == .record {
            record = combo
            store.encode(combo, forKey: "hotkey.record")
        } else {
            dictate = combo
            store.encode(combo, forKey: "hotkey.dictate")
        }
    }

    /// Changes the modifier that turns dictation into a structured note (default ⇧).
    public func changeStructured(to modifier: Modifiers) throws {
        guard !modifier.isEmpty, dictate.modifiers.isDisjoint(with: modifier) else {
            throw HotkeyError.modifierInDictationHotkey
        }
        let combo = KeyCombo(keyCode: dictate.keyCode, modifiers: dictate.modifiers.union(modifier))
        if combo == record { throw HotkeyError.usedByOtherAction(.record) }
        try Self.validate(combo)
        let previous = structuredCombo
        registrar.unregister(.dictateStructured)
        do {
            try registrar.register(combo, for: .dictateStructured)
        } catch {
            try? registrar.register(previous, for: .dictateStructured)
            throw error
        }
        structured = modifier
        store.encode(modifier, forKey: "hotkey.structured")
    }
}

/// Dictation hotkey gesture: held longer than 0.4 s = hold to talk (release stops); a short press
/// starts, and the next press stops.
public struct DictationGesture: Sendable {
    public enum Output: Equatable, Sendable { case start, stop }

    public static let holdThreshold: TimeInterval = 0.4

    enum Phase { case idle, pressed(at: TimeInterval), toggled, stopping }
    var phase: Phase = .idle

    public init() {}

    public var isActive: Bool {
        if case .idle = phase { return false }
        return true
    }

    public mutating func press(at t: TimeInterval) -> Output? {
        switch phase {
        case .idle:
            phase = .pressed(at: t)
            return .start
        case .toggled:
            phase = .stopping  // the release of this press is ignored
            return .stop
        case .pressed, .stopping:
            return nil  // key repeat
        }
    }

    public mutating func release(at t: TimeInterval) -> Output? {
        switch phase {
        case let .pressed(start):
            if t - start >= Self.holdThreshold {
                phase = .idle
                return .stop
            }
            phase = .toggled
            return nil
        case .stopping:
            phase = .idle
            return nil
        case .idle, .toggled:
            return nil
        }
    }

    /// The recording ended for another reason (error, limit).
    public mutating func reset() { phase = .idle }
}
