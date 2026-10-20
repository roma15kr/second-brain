import Foundation

public enum InsertResult: Equatable, Sendable {
    case typed  // pasted into the focused app
    case copied  // no text field had focus (or no Accessibility): left on the clipboard
}

/// Puts text where the owner is typing (pasteboard + ⌘V in the app).
public protocol Paster: AnyObject {
    func insert(_ text: String) -> InsertResult
}

/// Dictation form chosen in Settings; the structured modifier overrides it.
public enum DictationForm: String, CaseIterable, Sendable {
    case verbatim, clean, structured

    public var label: String {
        switch self {
        case .verbatim: return "As said"
        case .clean: return "Cleaned (fillers removed, wording kept)"
        case .structured: return "Structured (summary, points, actions)"
        }
    }
}

public struct DictationOutcome: Equatable, Sendable {
    public var text: String
    public var inserted: InsertResult?
    public var offline: Bool
    public var notice: String?
}

/// One dictation after the hotkey is released (design D5): the server's OpenAI transcription in
/// the chosen form, or the Mac's own model as said when there is no connection.
public final class DictationFlow {
    let api: DeviceAPI?
    let paster: Paster
    let offline: SpeechRecognizer?
    public static let minimumSeconds = 0.3

    public init(api: DeviceAPI?, paster: Paster, offline: SpeechRecognizer?) {
        self.api = api
        self.paster = paster
        self.offline = offline
    }

    /// `audio` is the AAC recording for the server, `samples` the same audio for the local model.
    public func finish(audio: Data, samples: [Float], form: DictationForm) async -> DictationOutcome {
        let seconds = Double(samples.count) / sampleRate
        guard seconds >= Self.minimumSeconds else {
            return DictationOutcome(text: "", inserted: nil, offline: false, notice: nil)
        }
        var text = ""
        var notice: String?
        var wasOffline = false
        do {
            guard let api else { throw APIError.offline }
            let answer = try await api.dictate(audio, mime: "audio/mp4", form: form.rawValue, seconds: seconds)
            text = answer.text
            notice = answer.note
        } catch let error as APIError where error == .offline || error == .unauthorized {
            wasOffline = true
            guard let offline else {
                return DictationOutcome(
                    text: "", inserted: nil, offline: true,
                    notice: "No connection and the speech model is not installed: nothing was transcribed")
            }
            do {
                text = try offline.recognize(samples)
                notice = form == .verbatim ? "Transcribed on this Mac (offline)" :
                    "Transcribed on this Mac as said: cleaning was not available offline"
            } catch {
                return DictationOutcome(text: "", inserted: nil, offline: true, notice: "Dictation failed: \(error.localizedDescription)")
            }
        } catch {
            return DictationOutcome(text: "", inserted: nil, offline: false, notice: "Dictation failed: \(error.localizedDescription)")
        }
        text = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else {
            return DictationOutcome(text: "", inserted: nil, offline: wasOffline, notice: notice ?? "Nothing was heard")
        }
        let inserted = paster.insert(text)
        if inserted == .copied {
            notice = [notice, "No text field had focus: the text is on the clipboard"].compactMap { $0 }.joined(separator: ". ")
        }
        return DictationOutcome(text: text, inserted: inserted, offline: wasOffline, notice: notice)
    }
}
