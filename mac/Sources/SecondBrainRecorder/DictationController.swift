import AVFoundation
import AppKit
import ApplicationServices
import RecorderCore
import SpeechKit

/// Types text into the focused app: pasteboard + ⌘V, previous clipboard restored after 1 s.
final class PasteboardPaster: Paster {
    func insert(_ text: String) -> InsertResult {
        let board = NSPasteboard.general
        let saved = board.pasteboardItems?.map { item -> NSPasteboardItem in
            let copy = NSPasteboardItem()
            for type in item.types { if let data = item.data(forType: type) { copy.setData(data, forType: type) } }
            return copy
        } ?? []
        board.clearContents()
        board.setString(text, forType: .string)
        guard AXIsProcessTrusted(), Self.hasFocusedElement() else { return .copied }
        let source = CGEventSource(stateID: .combinedSessionState)
        let down = CGEvent(keyboardEventSource: source, virtualKey: 9, keyDown: true)  // V
        let up = CGEvent(keyboardEventSource: source, virtualKey: 9, keyDown: false)
        down?.flags = .maskCommand
        up?.flags = .maskCommand
        down?.post(tap: .cghidEventTap)
        up?.post(tap: .cghidEventTap)
        DispatchQueue.main.asyncAfter(deadline: .now() + 1) {
            guard board.string(forType: .string) == text else { return }  // the owner copied something since
            board.clearContents()
            if !saved.isEmpty { board.writeObjects(saved) }
        }
        return .typed
    }

    static func hasFocusedElement() -> Bool {
        var focused: CFTypeRef?
        let system = AXUIElementCreateSystemWide()
        return AXUIElementCopyAttributeValue(system, kAXFocusedUIElementAttribute as CFString, &focused) == .success
            && focused != nil
    }
}

/// Records the microphone for one dictation into memory (16 kHz mono).
final class DictationRecorder {
    private let mic = MicrophoneSource()
    private let lock = NSLock()
    private var samples: [Float] = []

    func start() throws {
        samples = []
        mic.onSamples = { [weak self] s, _ in
            guard let self else { return }
            self.lock.withLock { self.samples += s }
        }
        try mic.start()
    }

    /// Stops and returns the samples and the AAC file for the server.
    func stop() -> (samples: [Float], audio: Data) {
        mic.stop()
        let s = lock.withLock { samples }
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("dictation-\(UUID().uuidString).m4a")
        defer { try? FileManager.default.removeItem(at: url) }
        do {
            let file = try AACSegmentFile(url: url)
            try file.write(s)
            file.close()
            return (s, try Data(contentsOf: url))
        } catch {
            return (s, Data())
        }
    }
}

extension AppState {
    var dictationForm: DictationForm {
        DictationForm(rawValue: UserDefaults.standard.string(forKey: "dictation.form") ?? "clean") ?? .clean
    }

    func startDictation(structured: Bool) {
        do {
            try dictation.start()
            dictating = true
            pipeline.flags.dictating = true
            status = structured ? "Dictating (structured)… release or press again to stop" : "Dictating… release or press again to stop"
        } catch {
            gesture.reset()
            notify("Dictation could not start: \(error.localizedDescription)")
        }
    }

    func stopDictation() {
        guard dictating else { return }
        let (samples, audio) = dictation.stop()
        dictating = false
        status = "Transcribing the dictation…"
        let form: DictationForm = dictationStructured ? .structured : dictationForm
        let api = isPaired ? pairing.map { DeviceAPI(client: $0.client) } : nil
        let offline = offlineRecognizer
        Task {
            let outcome = await DictationFlow(api: api, paster: PasteboardPaster(), offline: offline)
                .finish(audio: audio, samples: samples, form: form)
            status = nil
            pipeline.flags.dictating = false
            if let notice = outcome.notice { notify(notice) }
        }
    }

    /// Parakeet for offline dictation (loaded on first use; its own instance so it never waits
    /// for call transcription).
    var offlineRecognizer: SpeechRecognizer? {
        if let r = dictationRecognizer { return r }
        guard pipeline.transcriber.available else { return nil }
        dictationRecognizer = try? ParakeetRecognizer(provider: "cpu", threads: 2)
        return dictationRecognizer
    }
}
