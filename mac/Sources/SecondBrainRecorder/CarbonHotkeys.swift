import AppKit
import Carbon.HIToolbox
import RecorderCore

/// Global hotkeys through Carbon's RegisterEventHotKey: press and release events, no
/// Accessibility permission needed (design D6).
final class CarbonRegistrar: HotkeyRegistrar {
    private var refs: [HotkeyAction: EventHotKeyRef] = [:]
    private var handler: EventHandlerRef?
    /// (action, pressed) on the main thread.
    var onEvent: ((HotkeyAction, Bool) -> Void)?

    private static let signature: OSType = 0x5342_5252  // "SBRR"

    init() {
        var types = [
            EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed)),
            EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyReleased)),
        ]
        let callback: EventHandlerUPP = { _, event, userData in
            guard let event, let userData else { return OSStatus(eventNotHandledErr) }
            var id = EventHotKeyID()
            let status = GetEventParameter(
                event, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID), nil,
                MemoryLayout<EventHotKeyID>.size, nil, &id)
            guard status == noErr, id.signature == CarbonRegistrar.signature else {
                return OSStatus(eventNotHandledErr)
            }
            let me = Unmanaged<CarbonRegistrar>.fromOpaque(userData).takeUnretainedValue()
            let pressed = GetEventKind(event) == UInt32(kEventHotKeyPressed)
            let index = Int(id.id) - 1
            if HotkeyAction.allCases.indices.contains(index) {
                me.onEvent?(HotkeyAction.allCases[index], pressed)
            }
            return noErr
        }
        InstallEventHandler(
            GetApplicationEventTarget(), callback, types.count, &types,
            Unmanaged.passUnretained(self).toOpaque(), &handler)
    }

    func register(_ combo: KeyCombo, for action: HotkeyAction) throws {
        unregister(action)
        let index = UInt32(HotkeyAction.allCases.firstIndex(of: action)! + 1)
        var ref: EventHotKeyRef?
        let status = RegisterEventHotKey(
            combo.keyCode, Self.carbonModifiers(combo.modifiers),
            EventHotKeyID(signature: Self.signature, id: index), GetApplicationEventTarget(), 0, &ref)
        guard status == noErr, let ref else { throw HotkeyError.taken }
        refs[action] = ref
    }

    func unregister(_ action: HotkeyAction) {
        if let ref = refs.removeValue(forKey: action) { UnregisterEventHotKey(ref) }
    }

    static func carbonModifiers(_ m: Modifiers) -> UInt32 {
        var out = 0
        if m.contains(.command) { out |= cmdKey }
        if m.contains(.option) { out |= optionKey }
        if m.contains(.control) { out |= controlKey }
        if m.contains(.shift) { out |= shiftKey }
        return UInt32(out)
    }

    static func modifiers(_ flags: NSEvent.ModifierFlags) -> Modifiers {
        var m: Modifiers = []
        if flags.contains(.command) { m.insert(.command) }
        if flags.contains(.option) { m.insert(.option) }
        if flags.contains(.control) { m.insert(.control) }
        if flags.contains(.shift) { m.insert(.shift) }
        return m
    }
}
