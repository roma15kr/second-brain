import Foundation
import IOKit.ps
import RecorderCore
import SpeechKit

/// Owner settings for call transcription (Settings window).
enum CallSettings {
    static var defaults: UserDefaults { .standard }
    /// "mac" (Parakeet on this Mac, default) or "cloud" (the server's provider).
    static var engine: String { defaults.string(forKey: "calls.engine") ?? "mac" }
    static var allowBattery: Bool { defaults.bool(forKey: "calls.allowBattery") }
    /// "auto", "cpu" or "coreml".
    static var providerOverride: String { defaults.string(forKey: "calls.provider") ?? "auto" }
    static var liveMode: Bool { defaults.bool(forKey: "calls.live") }

    static var benchmark: [Benchmark] {
        get { defaults.data(forKey: "calls.benchmark").flatMap { try? JSONDecoder().decode([Benchmark].self, from: $0) } ?? [] }
        set { defaults.set(try? JSONEncoder().encode(newValue), forKey: "calls.benchmark") }
    }

    static var provider: String {
        ProviderChoice.choose(benchmark, override: providerOverride == "auto" ? nil : providerOverride)
    }

    static var speedLabel: String? {
        benchmark.first { $0.provider == provider && $0.speed > 0 }?.label
    }
}

enum Power {
    static var onBattery: Bool {
        guard let info = IOPSCopyPowerSourcesInfo()?.takeRetainedValue(),
              let type = IOPSGetProvidingPowerSourceType(info)?.takeUnretainedValue() as String?
        else { return false }
        return type == kIOPSBatteryPowerValue
    }
}

/// Transcribes recorded calls on this Mac at low priority, one at a time (design D3).
final class CallTranscriber: @unchecked Sendable {
    private let queue = DispatchQueue(label: "recorder.call-transcription", qos: .utility)
    private var recognizer: (provider: String, value: ParakeetRecognizer)?
    /// Read on the transcription queue; set by the app.
    var machineState: () -> MachineState = { MachineState() }
    var onWait: ((String?) -> Void)?

    var available: Bool { Models.installed && (try? SherpaRuntime.shared.get()) != nil }

    /// Measures CPU vs GPU once (first use); the result shows in Settings.
    private func ensureBenchmark() {
        if CallSettings.benchmark.isEmpty { CallSettings.benchmark = SpeechBenchmark.run() }
    }

    private func recognizerForCurrentProvider() throws -> ParakeetRecognizer {
        ensureBenchmark()
        let provider = CallSettings.provider
        if let r = recognizer, r.provider == provider { return r.value }
        let r: ParakeetRecognizer
        do {
            r = try ParakeetRecognizer(provider: provider, threads: ProviderChoice.threads())
        } catch where provider != "cpu" {
            r = try ParakeetRecognizer(provider: "cpu", threads: ProviderChoice.threads())
        }
        recognizer = (provider, r)
        return r
    }

    /// Returns the merged "me"/"others" transcript and how long it took.
    func transcribe(_ item: Item, store: ItemStore) async throws -> (segments: [TranscriptSegment], seconds: Double) {
        try await withCheckedThrowingContinuation { continuation in
            queue.async {
                do {
                    let t0 = Date()
                    let recognizer = try self.recognizerForCurrentProvider()
                    let checkpoint = PausableCheckpoint(state: self.machineState)
                    checkpoint.onWait = self.onWait
                    var perTrack: [[TranscriptSegment]] = []
                    for track in item.tracks {
                        let t = StreamingTranscriber(vad: try SileroVAD(), recognizer: recognizer, track: track)
                        t.checkpoint = { try checkpoint.wait() }
                        var lines: [TranscriptSegment] = []
                        try checkpoint.wait()
                        try AudioFiles.read(store.url(item, track.file)) { lines += try t.feed($0) }
                        lines += try t.finish()
                        perTrack.append(lines)
                    }
                    continuation.resume(returning: (TranscriptMerge.merge(perTrack), Date().timeIntervalSince(t0)))
                } catch {
                    continuation.resume(throwing: error)
                }
            }
        }
    }
}
