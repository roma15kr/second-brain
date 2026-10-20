import AVFoundation
import CoreAudio
import Foundation
import RecorderCore
import ScreenCaptureKit

struct CaptureError: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

/// Converts any PCM buffer to 16 kHz mono Float32 (what the segment files and models use).
final class Resampler {
    static let target = AVAudioFormat(
        commonFormat: .pcmFormatFloat32, sampleRate: RecorderCore.sampleRate, channels: 1, interleaved: false)!
    private var converter: AVAudioConverter?
    private var from: AVAudioFormat?

    func convert(_ buffer: AVAudioPCMBuffer) -> [Float] {
        if from != buffer.format {
            from = buffer.format
            converter = AVAudioConverter(from: buffer.format, to: Self.target)
            converter?.downmix = true
        }
        guard let converter, buffer.frameLength > 0 else { return [] }
        let ratio = Self.target.sampleRate / buffer.format.sampleRate
        let capacity = AVAudioFrameCount(Double(buffer.frameLength) * ratio) + 64
        guard let out = AVAudioPCMBuffer(pcmFormat: Self.target, frameCapacity: capacity) else { return [] }
        var fed = false
        var error: NSError?
        converter.convert(to: out, error: &error) { _, status in
            if fed {
                status.pointee = .noDataNow
                return nil
            }
            fed = true
            status.pointee = .haveData
            return buffer
        }
        guard error == nil, let data = out.floatChannelData else { return [] }
        return Array(UnsafeBufferPointer(start: data[0], count: Int(out.frameLength)))
    }
}

/// The owner's microphone (AVAudioEngine); restarts on a device or route change (AirPods).
final class MicrophoneSource: AudioSource {
    var onSamples: (([Float], Date) -> Void)?
    private var engine = AVAudioEngine()
    private let resampler = Resampler()
    private var observer: NSObjectProtocol?
    private var running = false

    func start() throws {
        running = true
        try startEngine()
    }

    private func startEngine() throws {
        engine = AVAudioEngine()
        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0 else {
            throw CaptureError(message: "no microphone is available")
        }
        input.installTap(onBus: 0, bufferSize: 4096, format: format) { [weak self] buffer, _ in
            guard let self else { return }
            let samples = self.resampler.convert(buffer)
            let at = Date().addingTimeInterval(-Double(buffer.frameLength) / format.sampleRate)
            self.onSamples?(samples, at)
        }
        engine.prepare()
        try engine.start()
        observer = NotificationCenter.default.addObserver(
            forName: .AVAudioEngineConfigurationChange, object: engine, queue: .main
        ) { [weak self] _ in self?.restart(attempt: 1) }
    }

    /// The input device changed: start again with the new one (the track writer pads the gap).
    private func restart(attempt: Int) {
        guard running else { return }
        teardown()
        do {
            try startEngine()
        } catch where attempt < 5 {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { [weak self] in self?.restart(attempt: attempt + 1) }
        } catch {}
    }

    private func teardown() {
        if let observer { NotificationCenter.default.removeObserver(observer) }
        observer = nil
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
    }

    func stop() {
        running = false
        teardown()
    }
}

/// The computer's audio output from every app through a Core Audio process tap (macOS 14.2+):
/// only the "System Audio Recording" permission, no screen-recording indicator (design D2).
final class ProcessTapSource: AudioSource {
    var onSamples: (([Float], Date) -> Void)?
    private var tapID = AudioObjectID(kAudioObjectUnknown)
    private var aggregateID = AudioObjectID(kAudioObjectUnknown)
    private var procID: AudioDeviceIOProcID?
    private let resampler = Resampler()
    private let queue = DispatchQueue(label: "recorder.process-tap", qos: .userInitiated)

    private func check(_ status: OSStatus, _ what: String) throws {
        guard status == noErr else { throw CaptureError(message: "could not \(what) (error \(status))") }
    }

    func start() throws {
        let description = CATapDescription(monoGlobalTapButExcludeProcesses: [])
        description.uuid = UUID()
        description.isPrivate = true
        description.muteBehavior = .unmuted
        do {
            try check(AudioHardwareCreateProcessTap(description, &tapID), "create the audio tap")
            var asbd = AudioStreamBasicDescription()
            var size = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
            var address = AudioObjectPropertyAddress(
                mSelector: kAudioTapPropertyFormat, mScope: kAudioObjectPropertyScopeGlobal,
                mElement: kAudioObjectPropertyElementMain)
            try check(AudioObjectGetPropertyData(tapID, &address, 0, nil, &size, &asbd), "read the tap format")
            guard let format = AVAudioFormat(streamDescription: &asbd) else {
                throw CaptureError(message: "unsupported tap format")
            }
            let outputUID = try Self.defaultOutputUID()
            let aggregate: [String: Any] = [
                kAudioAggregateDeviceNameKey: "Second Brain Recorder tap",
                kAudioAggregateDeviceUIDKey: UUID().uuidString,
                kAudioAggregateDeviceMainSubDeviceKey: outputUID,
                kAudioAggregateDeviceIsPrivateKey: true,
                kAudioAggregateDeviceIsStackedKey: false,
                kAudioAggregateDeviceTapAutoStartKey: true,
                kAudioAggregateDeviceSubDeviceListKey: [[kAudioSubDeviceUIDKey: outputUID]],
                kAudioAggregateDeviceTapListKey: [
                    [kAudioSubTapDriftCompensationKey: true, kAudioSubTapUIDKey: description.uuid.uuidString]
                ],
            ]
            try check(AudioHardwareCreateAggregateDevice(aggregate as CFDictionary, &aggregateID), "create the tap device")
            try check(
                AudioDeviceCreateIOProcIDWithBlock(&procID, aggregateID, queue) { [weak self] _, input, _, _, _ in
                    guard let self,
                          let buffer = AVAudioPCMBuffer(pcmFormat: format, bufferListNoCopy: input, deallocator: nil)
                    else { return }
                    let samples = self.resampler.convert(buffer)
                    self.onSamples?(samples, Date().addingTimeInterval(-Double(buffer.frameLength) / format.sampleRate))
                }, "attach to the tap device")
            try check(AudioDeviceStart(aggregateID, procID), "start the tap device")
        } catch {
            stop()
            throw error
        }
    }

    func stop() {
        if aggregateID != kAudioObjectUnknown {
            if let procID {
                AudioDeviceStop(aggregateID, procID)
                AudioDeviceDestroyIOProcID(aggregateID, procID)
            }
            AudioHardwareDestroyAggregateDevice(aggregateID)
        }
        if tapID != kAudioObjectUnknown { AudioHardwareDestroyProcessTap(tapID) }
        procID = nil
        aggregateID = AudioObjectID(kAudioObjectUnknown)
        tapID = AudioObjectID(kAudioObjectUnknown)
    }

    static func defaultOutputUID() throws -> String {
        var device = AudioDeviceID(kAudioObjectUnknown)
        var size = UInt32(MemoryLayout<AudioDeviceID>.size)
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioHardwarePropertyDefaultSystemOutputDevice, mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain)
        var status = AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &size, &device)
        guard status == noErr else { throw CaptureError(message: "no audio output device (error \(status))") }
        var uid: Unmanaged<CFString>?
        size = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
        address.mSelector = kAudioDevicePropertyDeviceUID
        status = AudioObjectGetPropertyData(device, &address, 0, nil, &size, &uid)
        guard status == noErr, let uid else { throw CaptureError(message: "could not read the output device") }
        return uid.takeRetainedValue() as String
    }
}

/// Fallback for computer audio: ScreenCaptureKit audio capture (needs Screen Recording).
final class ScreenCaptureAudioSource: NSObject, AudioSource, SCStreamOutput {
    var onSamples: (([Float], Date) -> Void)?
    var onError: ((String) -> Void)?
    private var stream: SCStream?
    private let resampler = Resampler()
    private let queue = DispatchQueue(label: "recorder.screencapture-audio", qos: .userInitiated)

    func start() throws {
        SCShareableContent.getExcludingDesktopWindows(false, onScreenWindowsOnly: true) { [weak self] content, error in
            guard let self else { return }
            guard let display = content?.displays.first else {
                self.onError?(error?.localizedDescription ?? "no display to capture audio from")
                return
            }
            let config = SCStreamConfiguration()
            config.capturesAudio = true
            config.excludesCurrentProcessAudio = true
            config.sampleRate = Int(RecorderCore.sampleRate)
            config.channelCount = 1
            config.width = 2
            config.height = 2
            config.minimumFrameInterval = CMTime(value: 1, timescale: 1)
            let stream = SCStream(filter: SCContentFilter(display: display, excludingWindows: []), configuration: config, delegate: nil)
            do {
                try stream.addStreamOutput(self, type: .audio, sampleHandlerQueue: self.queue)
                self.stream = stream
                stream.startCapture { error in
                    if let error { self.onError?(error.localizedDescription) }
                }
            } catch {
                self.onError?(error.localizedDescription)
            }
        }
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .audio, var asbd = sampleBuffer.formatDescription?.audioStreamBasicDescription,
              let format = AVAudioFormat(streamDescription: &asbd)
        else { return }
        try? sampleBuffer.withAudioBufferList { list, _ in
            guard let buffer = AVAudioPCMBuffer(pcmFormat: format, bufferListNoCopy: list.unsafePointer, deallocator: nil)
            else { return }
            let samples = resampler.convert(buffer)
            onSamples?(samples, Date().addingTimeInterval(-Double(buffer.frameLength) / format.sampleRate))
        }
    }

    func stop() {
        stream?.stopCapture { _ in }
        stream = nil
    }
}

/// Computer audio: the process tap, or ScreenCaptureKit when the tap cannot start.
final class SystemAudioSource: AudioSource {
    var onSamples: (([Float], Date) -> Void)? {
        didSet {
            tap.onSamples = onSamples
            fallback.onSamples = onSamples
        }
    }
    private let tap = ProcessTapSource()
    private let fallback = ScreenCaptureAudioSource()
    private var usingFallback = false
    private(set) var usedFallback = false

    func start() throws {
        do {
            try tap.start()
        } catch {
            usingFallback = true
            usedFallback = true
            try fallback.start()
        }
    }

    func stop() {
        if usingFallback { fallback.stop() } else { tap.stop() }
        usingFallback = false
    }
}
