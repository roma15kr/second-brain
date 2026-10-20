import AVFoundation
import Foundation
import RecorderCore

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

enum AudioFiles {
    /// Joins segment files into one m4a without re-encoding; returns its duration in seconds.
    static func join(_ segments: [URL], to out: URL) async throws -> TimeInterval {
        try? FileManager.default.removeItem(at: out)
        if segments.count == 1 {
            try FileManager.default.copyItem(at: segments[0], to: out)
            return try await duration(out)
        }
        let composition = AVMutableComposition()
        guard let track = composition.addMutableTrack(withMediaType: .audio, preferredTrackID: kCMPersistentTrackID_Invalid)
        else { throw CaptureError(message: "could not create the joined track") }
        var cursor = CMTime.zero
        for url in segments {
            let asset = AVURLAsset(url: url)
            guard let source = try await asset.loadTracks(withMediaType: .audio).first else { continue }
            let length = try await asset.load(.duration)
            try track.insertTimeRange(CMTimeRange(start: .zero, duration: length), of: source, at: cursor)
            cursor = cursor + length
        }
        for preset in [AVAssetExportPresetPassthrough, AVAssetExportPresetAppleM4A] {
            guard let export = AVAssetExportSession(asset: composition, presetName: preset) else { continue }
            do {
                try await export.export(to: out, as: .m4a)
                return cursor.seconds
            } catch {
                try? FileManager.default.removeItem(at: out)
                if preset == AVAssetExportPresetAppleM4A { throw error }
            }
        }
        throw CaptureError(message: "could not join the recording")
    }

    static func duration(_ url: URL) async throws -> TimeInterval {
        try await AVURLAsset(url: url).load(.duration).seconds
    }

    /// Decodes any audio file AVFoundation reads to 16 kHz mono samples (for transcription).
    static func samples(_ url: URL) throws -> [Float] {
        let file = try AVAudioFile(forReading: url)
        let resampler = Resampler()
        var out: [Float] = []
        out.reserveCapacity(Int(Double(file.length) * RecorderCore.sampleRate / file.processingFormat.sampleRate))
        while file.framePosition < file.length {
            guard let buffer = AVAudioPCMBuffer(pcmFormat: file.processingFormat, frameCapacity: 65_536) else { break }
            try file.read(into: buffer)
            if buffer.frameLength == 0 { break }
            out += resampler.convert(buffer)
        }
        return out
    }
}
