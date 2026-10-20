import CSherpaOnnx
import Darwin
import Foundation
import RecorderCore

/// sherpa-onnx loaded from the app bundle (Contents/Frameworks) with dlopen (design D3).
final class SherpaRuntime: @unchecked Sendable {
    typealias CreateRecognizer = @convention(c) (UnsafePointer<SherpaOnnxOfflineRecognizerConfig>?) -> OpaquePointer?
    typealias Destroy = @convention(c) (OpaquePointer?) -> Void
    typealias CreateStream = @convention(c) (OpaquePointer?) -> OpaquePointer?
    typealias AcceptWaveform = @convention(c) (OpaquePointer?, Int32, UnsafePointer<Float>?, Int32) -> Void
    typealias Decode = @convention(c) (OpaquePointer?, OpaquePointer?) -> Void
    typealias GetResult = @convention(c) (OpaquePointer?) -> UnsafePointer<SherpaOnnxOfflineRecognizerResult>?
    typealias DestroyResult = @convention(c) (UnsafePointer<SherpaOnnxOfflineRecognizerResult>?) -> Void
    typealias CreateVad = @convention(c) (UnsafePointer<SherpaOnnxVadModelConfig>?, Float) -> OpaquePointer?
    typealias VadAccept = @convention(c) (OpaquePointer?, UnsafePointer<Float>?, Int32) -> Void
    typealias VadEmpty = @convention(c) (OpaquePointer?) -> Int32
    typealias VadFront = @convention(c) (OpaquePointer?) -> UnsafePointer<SherpaOnnxSpeechSegment>?
    typealias DestroySegment = @convention(c) (UnsafePointer<SherpaOnnxSpeechSegment>?) -> Void

    let createRecognizer: CreateRecognizer
    let destroyRecognizer: Destroy
    let createStream: CreateStream
    let destroyStream: Destroy
    let acceptWaveform: AcceptWaveform
    let decode: Decode
    let getResult: GetResult
    let destroyResult: DestroyResult
    let createVad: CreateVad
    let destroyVad: Destroy
    let vadAccept: VadAccept
    let vadEmpty: VadEmpty
    let vadFront: VadFront
    let vadPop: Destroy
    let vadFlush: Destroy
    let vadReset: Destroy
    let destroySegment: DestroySegment

    static let shared: Result<SherpaRuntime, Error> = Result { try SherpaRuntime() }

    static var libraryURL: URL? {
        Bundle.main.privateFrameworksURL?.appendingPathComponent("libsherpa-onnx-c-api.dylib")
    }

    private init() throws {
        guard let url = Self.libraryURL, FileManager.default.fileExists(atPath: url.path) else {
            throw CaptureError(message: "the speech runtime is not installed (run install.sh again)")
        }
        guard let handle = dlopen(url.path, RTLD_NOW | RTLD_LOCAL) else {
            throw CaptureError(message: "the speech runtime could not load: \(String(cString: dlerror()))")
        }
        func fn<T>(_ name: String) throws -> T {
            guard let sym = dlsym(handle, name) else {
                throw CaptureError(message: "the speech runtime lacks \(name)")
            }
            return unsafeBitCast(sym, to: T.self)
        }
        createRecognizer = try fn("SherpaOnnxCreateOfflineRecognizer")
        destroyRecognizer = try fn("SherpaOnnxDestroyOfflineRecognizer")
        createStream = try fn("SherpaOnnxCreateOfflineStream")
        destroyStream = try fn("SherpaOnnxDestroyOfflineStream")
        acceptWaveform = try fn("SherpaOnnxAcceptWaveformOffline")
        decode = try fn("SherpaOnnxDecodeOfflineStream")
        getResult = try fn("SherpaOnnxGetOfflineStreamResult")
        destroyResult = try fn("SherpaOnnxDestroyOfflineRecognizerResult")
        createVad = try fn("SherpaOnnxCreateVoiceActivityDetector")
        destroyVad = try fn("SherpaOnnxDestroyVoiceActivityDetector")
        vadAccept = try fn("SherpaOnnxVoiceActivityDetectorAcceptWaveform")
        vadEmpty = try fn("SherpaOnnxVoiceActivityDetectorEmpty")
        vadFront = try fn("SherpaOnnxVoiceActivityDetectorFront")
        vadPop = try fn("SherpaOnnxVoiceActivityDetectorPop")
        vadFlush = try fn("SherpaOnnxVoiceActivityDetectorFlush")
        vadReset = try fn("SherpaOnnxVoiceActivityDetectorReset")
        destroySegment = try fn("SherpaOnnxDestroySpeechSegment")
    }
}

enum Models {
    static let parakeet = "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8"

    static var dir: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("SecondBrainRecorder/models")
    }

    static var parakeetDir: URL { dir.appendingPathComponent(parakeet) }
    static var vad: URL { dir.appendingPathComponent("silero_vad.onnx") }

    static var installed: Bool {
        FileManager.default.fileExists(atPath: parakeetDir.appendingPathComponent("encoder.int8.onnx").path)
            && FileManager.default.fileExists(atPath: vad.path)
    }
}

/// Keeps C strings alive while a config is used.
private final class CStrings {
    private var pointers: [UnsafeMutablePointer<CChar>] = []
    func callAsFunction(_ s: String) -> UnsafePointer<CChar> {
        let p = strdup(s)!
        pointers.append(p)
        return UnsafePointer(p)
    }
    deinit { pointers.forEach { free($0) } }
}

/// Parakeet TDT 0.6B v3 (uk/ru/en and more; punctuation and capitals included).
final class ParakeetRecognizer: SpeechRecognizer {
    private let rt: SherpaRuntime
    private let recognizer: OpaquePointer

    init(provider: String, threads: Int) throws {
        rt = try SherpaRuntime.shared.get()
        let s = CStrings()
        var config = SherpaOnnxOfflineRecognizerConfig()
        config.feat_config.sample_rate = Int32(RecorderCore.sampleRate)
        config.feat_config.feature_dim = 80
        let dir = Models.parakeetDir
        config.model_config.transducer.encoder = s(dir.appendingPathComponent("encoder.int8.onnx").path)
        config.model_config.transducer.decoder = s(dir.appendingPathComponent("decoder.int8.onnx").path)
        config.model_config.transducer.joiner = s(dir.appendingPathComponent("joiner.int8.onnx").path)
        config.model_config.tokens = s(dir.appendingPathComponent("tokens.txt").path)
        config.model_config.num_threads = Int32(threads)
        config.model_config.provider = s(provider)
        config.model_config.model_type = s("nemo_transducer")
        config.decoding_method = s("greedy_search")
        guard let r = withUnsafePointer(to: &config, { rt.createRecognizer($0) }) else {
            throw CaptureError(message: "the speech model could not start with \(provider)")
        }
        recognizer = r
    }

    deinit { rt.destroyRecognizer(recognizer) }

    func recognize(_ samples: [Float]) throws -> String {
        guard !samples.isEmpty, let stream = rt.createStream(recognizer) else { return "" }
        defer { rt.destroyStream(stream) }
        samples.withUnsafeBufferPointer {
            rt.acceptWaveform(stream, Int32(RecorderCore.sampleRate), $0.baseAddress, Int32(samples.count))
        }
        rt.decode(recognizer, stream)
        guard let result = rt.getResult(stream) else { return "" }
        defer { rt.destroyResult(result) }
        return result.pointee.text.map { String(cString: $0) } ?? ""
    }
}

/// Silero VAD: speech chunks with their start, silence skipped.
final class SileroVAD: VoiceDetector {
    private let rt: SherpaRuntime
    private let vad: OpaquePointer
    private var pending: [Float] = []
    static let window = 512

    init() throws {
        rt = try SherpaRuntime.shared.get()
        let s = CStrings()
        var config = SherpaOnnxVadModelConfig()
        config.silero_vad.model = s(Models.vad.path)
        config.silero_vad.threshold = 0.5
        config.silero_vad.min_silence_duration = 0.5
        config.silero_vad.min_speech_duration = 0.25
        config.silero_vad.window_size = Int32(Self.window)
        config.silero_vad.max_speech_duration = 28
        config.sample_rate = Int32(RecorderCore.sampleRate)
        config.num_threads = 1
        config.provider = s("cpu")
        guard let v = withUnsafePointer(to: &config, { rt.createVad($0, 60) }) else {
            throw CaptureError(message: "the voice detector could not start")
        }
        vad = v
    }

    deinit { rt.destroyVad(vad) }

    func accept(_ samples: [Float]) {
        pending += samples
        let whole = pending.count / Self.window * Self.window
        guard whole > 0 else { return }
        pending.withUnsafeBufferPointer { rt.vadAccept(vad, $0.baseAddress, Int32(whole)) }
        pending.removeFirst(whole)
    }

    func flush() {
        if !pending.isEmpty {
            pending.withUnsafeBufferPointer { rt.vadAccept(vad, $0.baseAddress, Int32(pending.count)) }
            pending = []
        }
        rt.vadFlush(vad)
    }

    func pop() -> [SpeechChunk] {
        var out: [SpeechChunk] = []
        while rt.vadEmpty(vad) == 0 {
            if let seg = rt.vadFront(vad) {
                let s = seg.pointee
                out.append(SpeechChunk(
                    start: Double(s.start) / RecorderCore.sampleRate,
                    samples: Array(UnsafeBufferPointer(start: s.samples, count: Int(s.n)))))
                rt.destroySegment(seg)
            }
            rt.vadPop(vad)
        }
        return out
    }

    func reset() {
        pending = []
        rt.vadReset(vad)
    }
}

/// Measures CPU vs Core ML on the model's own sample recordings (design D3).
enum SpeechBenchmark {
    static func run() -> [Benchmark] {
        let wavs = ((try? FileManager.default.contentsOfDirectory(
            at: Models.parakeetDir.appendingPathComponent("test_wavs"), includingPropertiesForKeys: nil)) ?? [])
            .filter { $0.pathExtension == "wav" }
        let samples = wavs.compactMap { try? AudioFiles.samples($0) }
        guard !samples.isEmpty else { return [] }
        let audio = Double(samples.map(\.count).reduce(0, +)) / RecorderCore.sampleRate
        return ["cpu", "coreml"].map { provider in
            guard let r = try? ParakeetRecognizer(provider: provider, threads: ProviderChoice.threads()) else {
                return Benchmark(provider: provider, audioSeconds: audio, elapsedSeconds: 0)
            }
            _ = try? r.recognize(samples[0])  // warm-up (Core ML compiles on first use)
            let t0 = Date()
            for s in samples { _ = try? r.recognize(s) }
            return Benchmark(provider: provider, audioSeconds: audio, elapsedSeconds: Date().timeIntervalSince(t0))
        }
    }
}
