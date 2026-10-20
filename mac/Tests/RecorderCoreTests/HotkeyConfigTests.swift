import XCTest

@testable import RecorderCore

final class FakeRegistrar: HotkeyRegistrar {
    var active: [HotkeyAction: KeyCombo] = [:]
    var takenByOthers: Set<KeyCombo> = []

    func register(_ combo: KeyCombo, for action: HotkeyAction) throws {
        if takenByOthers.contains(combo) || active.values.contains(combo) { throw HotkeyError.taken }
        active[action] = combo
    }

    func unregister(_ action: HotkeyAction) { active[action] = nil }
}

final class HotkeyConfigTests: XCTestCase {
    let optionSpace = KeyCombo(keyCode: KeyCombo.space, modifiers: .option)

    func testDefaults() {
        let reg = FakeRegistrar()
        let config = HotkeyConfig(store: MemoryStore(), registrar: reg)
        XCTAssertEqual(config.registerAll(), [])
        XCTAssertEqual(reg.active[.record]?.description, "⌃⌥R")
        XCTAssertEqual(reg.active[.dictate]?.description, "⌃⌥D")
        XCTAssertEqual(reg.active[.dictateStructured]?.description, "⌃⌥⇧D")
    }

    func testNewDictationHotkeyAppliesAtOnceAndPersists() throws {
        let store = MemoryStore()
        let reg = FakeRegistrar()
        let config = HotkeyConfig(store: store, registrar: reg)
        config.registerAll()
        try config.change(.dictate, to: optionSpace)
        XCTAssertEqual(reg.active[.dictate], optionSpace)
        XCTAssertEqual(reg.active[.dictateStructured]?.description, "⌥⇧Space")
        XCTAssertFalse(reg.active.values.contains(HotkeyConfig.defaultDictate))  // ⌃⌥D no longer works
        let reloaded = HotkeyConfig(store: store, registrar: FakeRegistrar())
        XCTAssertEqual(reloaded.dictate, optionSpace)
    }

    func testSpotlightIsRefusedAndPreviousKept() {
        let reg = FakeRegistrar()
        let config = HotkeyConfig(store: MemoryStore(), registrar: reg)
        config.registerAll()
        let cmdSpace = KeyCombo(keyCode: KeyCombo.space, modifiers: .command)
        XCTAssertThrowsError(try config.change(.dictate, to: cmdSpace)) {
            XCTAssertEqual($0 as? HotkeyError, .reservedBySystem("Spotlight"))
        }
        XCTAssertEqual(config.dictate, HotkeyConfig.defaultDictate)
        XCTAssertEqual(reg.active[.dictate], HotkeyConfig.defaultDictate)
    }

    func testTakenByAnotherAppKeepsPrevious() {
        let reg = FakeRegistrar()
        let config = HotkeyConfig(store: MemoryStore(), registrar: reg)
        config.registerAll()
        let taken = KeyCombo(keyCode: 1, modifiers: [.control, .option])
        reg.takenByOthers = [taken]
        XCTAssertThrowsError(try config.change(.record, to: taken)) {
            XCTAssertEqual($0 as? HotkeyError, .taken)
        }
        XCTAssertEqual(reg.active[.record], HotkeyConfig.defaultRecord)
        XCTAssertEqual(config.record, HotkeyConfig.defaultRecord)
    }

    func testStructuredComboTakenRollsBackDictation() {
        let reg = FakeRegistrar()
        let config = HotkeyConfig(store: MemoryStore(), registrar: reg)
        config.registerAll()
        reg.takenByOthers = [KeyCombo(keyCode: KeyCombo.space, modifiers: [.option, .shift])]
        XCTAssertThrowsError(try config.change(.dictate, to: optionSpace))
        XCTAssertEqual(reg.active[.dictate], HotkeyConfig.defaultDictate)
        XCTAssertEqual(reg.active[.dictateStructured], config.structuredCombo)
    }

    func testConflictsBetweenActionsAndModifierRules() {
        let config = HotkeyConfig(store: MemoryStore(), registrar: FakeRegistrar())
        config.registerAll()
        XCTAssertThrowsError(try config.change(.record, to: HotkeyConfig.defaultDictate)) {
            XCTAssertEqual($0 as? HotkeyError, .usedByOtherAction(.dictate))
        }
        XCTAssertThrowsError(try config.change(.record, to: KeyCombo(keyCode: 1, modifiers: []))) {
            XCTAssertEqual($0 as? HotkeyError, .needsModifier)
        }
        XCTAssertNoThrow(try config.change(.record, to: KeyCombo(keyCode: 109, modifiers: [])))  // F10
        XCTAssertThrowsError(
            try config.change(.dictate, to: KeyCombo(keyCode: KeyCombo.keyD, modifiers: [.control, .shift]))
        ) { XCTAssertEqual($0 as? HotkeyError, .modifierInDictationHotkey) }
        XCTAssertThrowsError(try config.changeStructured(to: .option)) {
            XCTAssertEqual($0 as? HotkeyError, .modifierInDictationHotkey)
        }
        XCTAssertNoThrow(try config.changeStructured(to: .command))
        XCTAssertEqual(config.structuredCombo.description, "⌃⌥⌘D")
    }
}
