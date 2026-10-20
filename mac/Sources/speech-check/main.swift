// Runs the Mac's call transcription (Silero VAD + Parakeet through sherpa-onnx) on audio files
// and prints the timed lines and the CPU/GPU benchmark. Used by CI's speech job and for
// checking quality on the owner's Mac:
//   SBR_SHERPA_LIB=…/libsherpa-onnx-c-api.dylib SBR_MODELS_DIR=…/models speech-check a.wav b.m4a
import Foundation
import RecorderCore
import SpeechKit

let files = CommandLine.arguments.dropFirst()
guard !files.isEmpty else {
    print("usage: speech-check <audio file>…")
    exit(2)
}
do {
    let recognizer = try ParakeetRecognizer(provider: "cpu", threads: ProviderChoice.threads())
    let vad = try SileroVAD()
    var empty = 0
    for path in files {
        let url = URL(fileURLWithPath: path)
        let t = StreamingTranscriber(vad: vad, recognizer: recognizer, track: Track(name: "others", file: path))
        let t0 = Date()
        var lines: [TranscriptSegment] = []
        var seconds = 0.0
        try AudioFiles.read(url) { samples in
            seconds += Double(samples.count) / RecorderCore.sampleRate
            lines += try t.feed(samples)
        }
        lines += try t.finish()
        let took = Date().timeIntervalSince(t0)
        print("== \(url.lastPathComponent): \(String(format: "%.1f", seconds)) s audio in \(String(format: "%.1f", took)) s")
        for l in lines { print(String(format: "[%6.2f–%6.2f] ", l.start, l.end) + l.text) }
        if lines.isEmpty { empty += 1 }
    }
    for b in SpeechBenchmark.run() {
        print("benchmark \(b.provider): " + (b.elapsedSeconds > 0 ? b.label : "not available"))
    }
    if empty > 0 {
        print("error: \(empty) file(s) produced no text")
        exit(1)
    }
} catch {
    print("error: \(error.localizedDescription)")
    exit(1)
}
