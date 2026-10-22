import RecorderCore
import SpeechKit
import SwiftUI

struct CallSettingsView: View {
    @EnvironmentObject var state: AppState
    @AppStorage("calls.engine") private var engine = "mac"
    @AppStorage("calls.allowBattery") private var allowBattery = false
    @AppStorage("calls.provider") private var provider = "auto"
    @AppStorage("calls.live") private var live = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Call transcription").font(.headline)
            Picker("Transcribe calls", selection: $engine) {
                Text("On this Mac (Parakeet, free)").tag("mac")
                Text("Cloud (the server's provider)").tag("cloud")
            }
            if engine == "mac" {
                if !state.models.installed {
                    Text("The speech model (0.5 GB) is not downloaded yet. Recorded calls wait for it and are transcribed here once it is in place.")
                        .font(.caption).foregroundStyle(.orange)
                    if let p = state.models.progress {
                        ProgressView(value: p) { Text("Downloading the speech model…") }
                    } else {
                        Button("Download the speech model") {
                            Task {
                                await state.models.install()
                                state.processQueue()
                            }
                        }
                    }
                    if let e = state.models.error { Text(e).font(.caption).foregroundStyle(.red) }
                }
                Picker("Processor", selection: $provider) {
                    Text("Automatic (the faster one)").tag("auto")
                    Text("CPU").tag("cpu")
                    Text("GPU (Core ML)").tag("coreml")
                }
                LabeledContent("Measured speed", value: state.speedLabel ?? "measured with the first recording")
                Button("Measure again") {
                    CallSettings.benchmark = []
                    state.speedLabel = nil
                }
                Toggle("Transcribe on battery (otherwise waits for power)", isOn: $allowBattery)
                Toggle("Live captions during calls", isOn: $live)
            }
        }
    }
}
