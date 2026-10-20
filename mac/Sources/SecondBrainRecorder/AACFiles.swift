import AVFoundation
import Foundation
import RecorderCore
import SpeechKit

/// AAC 16 kHz mono segment files (~14 MB/h; design D2).
final class AACSegmentFactory: SegmentFileFactory {
    func create(at url: URL) throws -> SegmentFile { try AACSegmentFile(url: url) }
}

final class AACSegmentFile: SegmentFile {
    private var file: AVAudioFile?

    init(url: URL) throws {
        var settings: [String: Any] = [
            AVFormatIDKey: kAudioFormatMPEG4AAC, AVSampleRateKey: RecorderCore.sampleRate, AVNumberOfChannelsKey: 1,
            AVEncoderBitRateKey: 32_000,
        ]
        do {
            file = try AVAudioFile(forWriting: url, settings: settings, commonFormat: .pcmFormatFloat32, interleaved: false)
        } catch {
            settings[AVEncoderBitRateKey] = nil  // let the encoder pick a rate it supports
            file = try AVAudioFile(forWriting: url, settings: settings, commonFormat: .pcmFormatFloat32, interleaved: false)
        }
    }

    func write(_ samples: [Float]) throws {
        guard let file, !samples.isEmpty,
              let buffer = AVAudioPCMBuffer(pcmFormat: file.processingFormat, frameCapacity: AVAudioFrameCount(samples.count))
        else { return }
        buffer.frameLength = AVAudioFrameCount(samples.count)
        samples.withUnsafeBufferPointer { src in
            buffer.floatChannelData![0].update(from: src.baseAddress!, count: samples.count)
        }
        try file.write(from: buffer)
    }

    func close() { file = nil }  // the file is finalised when released
}
