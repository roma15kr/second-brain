import AppKit
import Foundation
import Network
import RecorderCore
import SpeechKit

/// Flags the transcription queue reads from its own thread.
final class SharedFlags: @unchecked Sendable {
    private let lock = NSLock()
    private var _recording = false
    private var _dictating = false
    var recording: Bool {
        get { lock.withLock { _recording } }
        set { lock.withLock { _recording = newValue } }
    }
    var dictating: Bool {
        get { lock.withLock { _dictating } }
        set { lock.withLock { _dictating = newValue } }
    }
}

/// Transcription on the Mac and delivery to the second brain for every waiting item (design D7).
@MainActor
final class Pipeline {
    unowned let state: AppState
    let transcriber = CallTranscriber()
    let flags = SharedFlags()
    private var running = false
    private var again = false
    private let monitor = NWPathMonitor()

    init(state: AppState) {
        self.state = state
        transcriber.machineState = { [flags] in
            MachineState(
                isRecording: flags.recording, isDictating: flags.dictating, onBattery: Power.onBattery,
                allowBattery: CallSettings.allowBattery)
        }
        monitor.pathUpdateHandler = { [weak self] path in
            guard path.status == .satisfied else { return }
            Task { @MainActor in self?.run() }  // the network is back
        }
        monitor.start(queue: DispatchQueue(label: "recorder.network"))
    }

    var api: DeviceAPI? { state.pairing.map { DeviceAPI(client: $0.client) } }

    /// Starts a pass over the queue (or schedules another one if a pass is running).
    func run() {
        if running {
            again = true
            return
        }
        running = true
        Task {
            repeat {
                again = false
                await pass()
            } while again
            running = false
        }
    }

    private func pass() async {
        let store = state.itemStore
        if transcriber.available {
            // calls sent to the cloud only because the model was missing: transcribe them here now
            for item in store.all() where item.cloud && item.note == Delivery.modelMissingNote {
                if let again = Delivery.retranscribeLocally(item) { try? store.save(again) }
            }
        }
        for item in store.all() {
            guard let step = Delivery.next(item, paired: state.isPaired) else { continue }
            switch step {
            case .wait:
                continue
            case .transcribeOnMac:
                await transcribe(item)
                if let updated = store.load(item.id), updated.segments != nil || updated.cloud,
                   state.isPaired, let api {
                    await deliver(updated.id, api)
                }
            default:
                if let api { await deliver(item.id, api) }
            }
            state.reloadItems()
        }
        if let api { DeliveryRunner(store: store, api: api).cleanup() }
        state.reloadItems()
    }

    private func transcribe(_ item: Item) async {
        let store = state.itemStore
        guard transcriber.available else {
            // the owner chose "On this Mac": wait for the model (downloaded at launch or from
            // Settings) instead of the cloud, which cannot take long calls in one piece
            _ = try? store.update(item.id) { $0.reason = Delivery.waitingForModel }
            return
        }
        _ = try? store.update(item.id) {
            $0.status = .transcribing
            $0.reason = nil
        }
        state.reloadItems()
        transcriber.onWait = { [weak self] reason in
            Task { @MainActor in
                _ = try? store.update(item.id) { $0.reason = reason }
                self?.state.reloadItems()
            }
        }
        do {
            let (segments, seconds) = try await transcriber.transcribe(item, store: store)
            _ = try? store.update(item.id) {
                $0.segments = segments
                $0.transcribeSeconds = seconds
                $0.status = .transcribed
                $0.reason = nil
            }
            state.speedLabel = CallSettings.speedLabel
        } catch {
            _ = try? store.update(item.id) {
                $0.status = .failed
                $0.reason = "Transcription failed: \(error.localizedDescription)"
            }
        }
    }

    private func deliver(_ id: UUID, _ api: DeviceAPI) async {
        let result = await DeliveryRunner(store: state.itemStore, api: api).deliver(id)
        if result?.status == .waiting, result?.reason == Delivery.describe(APIError.unauthorized).1 {
            state.unpaired()  // revoked in the web OS: keep recordings, show "not paired"
        }
    }

    /// "Transcribe on this Mac": the Mac's transcript replaces the server's.
    func transcribeHere(_ item: Item) {
        guard let again = Delivery.retranscribeLocally(item) else { return }
        try? state.itemStore.save(again)
        state.reloadItems()
        run()
    }

    /// "Separate speakers…": shows the estimate, then asks the server (OpenAI diarize).
    func separateSpeakers(_ item: Item) async {
        guard let api, let rid = item.recordingId else { return }
        do {
            let estimate = try await api.transcribe(rid, speakers: true, dryRun: true)
            let alert = NSAlert()
            alert.messageText = "Separate the speakers of “\(item.meeting.label)”?"
            alert.informativeText = String(
                format: "The server transcribes the others' track again with speaker separation (%@). Estimated cost: $%.2f.",
                estimate.provider, estimate.estimatedUsd)
            alert.addButton(withTitle: "Separate speakers")
            alert.addButton(withTitle: "Cancel")
            NSApp.activate(ignoringOtherApps: true)
            guard alert.runModal() == .alertFirstButtonReturn else { return }
            _ = try await api.transcribe(rid, speakers: true, dryRun: false)
            _ = try? state.itemStore.update(item.id) {
                $0.speakers = true
                $0.note = "Speakers are being separated on the server"
            }
            state.reloadItems()
        } catch {
            state.lastError = error.localizedDescription
        }
    }
}
