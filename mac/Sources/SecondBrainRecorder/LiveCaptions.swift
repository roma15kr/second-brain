import AppKit
import RecorderCore
import SpeechKit
import SwiftUI

/// Live mode: transcribes both tracks during the call on a background queue and shows each
/// finished phrase in a small floating window (design D3).
final class LiveSession: @unchecked Sendable {
    private let queue = DispatchQueue(label: "recorder.live", qos: .userInitiated)
    private let assembler: LiveAssembler
    private var failed: Error?
    let captions = Captions()

    init(recognizer: ParakeetRecognizer) {
        assembler = LiveAssembler { track in
            StreamingTranscriber(vad: try SileroVAD(), recognizer: recognizer, track: track)
        }
        assembler.onPhrase = { [captions] phrase in
            DispatchQueue.main.async { captions.add(phrase) }
        }
    }

    /// Called from the recorder's audio threads; the work happens on the live queue.
    func feed(_ track: String, _ samples: [Float], _ offset: TimeInterval) {
        queue.async {
            guard self.failed == nil else { return }
            do { try self.assembler.feed(track: track, samples: samples, offset: offset) } catch { self.failed = error }
        }
    }

    /// The complete transcript, or nil when live transcription failed (the after-call path runs).
    func finish() async -> [TranscriptSegment]? {
        await withCheckedContinuation { continuation in
            queue.async {
                guard self.failed == nil, let t = try? self.assembler.finish() else {
                    continuation.resume(returning: nil)
                    return
                }
                continuation.resume(returning: t)
            }
        }
    }
}

@MainActor
final class Captions: ObservableObject {
    @Published var lines: [TranscriptSegment] = []
    private var panel: NSPanel?

    nonisolated init() {}

    func add(_ line: TranscriptSegment) {
        lines.append(line)
        if lines.count > 6 { lines.removeFirst(lines.count - 6) }
    }

    func show() {
        let panel = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: 520, height: 180),
            styleMask: [.titled, .closable, .resizable, .utilityWindow, .nonactivatingPanel],
            backing: .buffered, defer: false)
        panel.title = "Live captions"
        panel.level = .floating
        panel.isFloatingPanel = true
        panel.hidesOnDeactivate = false
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.contentView = NSHostingView(rootView: CaptionsView(captions: self))
        if let screen = NSScreen.main?.visibleFrame {
            panel.setFrameOrigin(NSPoint(x: screen.maxX - 540, y: screen.minY + 20))
        }
        panel.orderFrontRegardless()
        self.panel = panel
    }

    func close() {
        panel?.close()
        panel = nil
    }
}

struct CaptionsView: View {
    @ObservedObject var captions: Captions

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 6) {
                    if captions.lines.isEmpty { Text("Listening…").foregroundStyle(.secondary) }
                    ForEach(Array(captions.lines.enumerated()), id: \.offset) { i, line in
                        (Text(line.speaker + ": ").bold().foregroundColor(line.isOwner ? .blue : .orange) + Text(line.text))
                            .id(i)
                    }
                }
                .padding(10)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .onChange(of: captions.lines.count) { _, n in proxy.scrollTo(n - 1) }
        }
    }
}
