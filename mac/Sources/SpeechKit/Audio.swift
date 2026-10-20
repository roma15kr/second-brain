import AVFoundation
import Foundation
import RecorderCore

public struct CaptureError: LocalizedError {
    public let message: String
    public init(message: String) { self.message = message }
    public var errorDescription: String? { message }
}

/// Converts any PCM buffer to 16 kHz mono Float32 (what the segment files and models use).
public final class Resampler {
    public init() {}
    public static let target = AVAudioFormat(
        commonFormat: .pcmFormatFloat32, sampleRate: RecorderCore.sampleRate, channels: 1, interleaved: false)!
    private var converter: AVAudioConverter?
    private var from: AVAudioFormat?

    public func convert(_ buffer: AVAudioPCMBuffer) -> [Float] {
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

public enum AudioFiles {
    /// Joins segment files into one m4a without re-encoding; returns its duration in seconds.
    public static func join(_ segments: [URL], to out: URL) async throws -> TimeInterval {
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

    public static func duration(_ url: URL) async throws -> TimeInterval {
        try await AVURLAsset(url: url).load(.duration).seconds
    }

    /// Decodes any audio file AVFoundation reads to 16 kHz mono samples (for transcription).
    public static func samples(_ url: URL) throws -> [Float] {
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

    /// Reads a file as 16 kHz mono in pieces of about `seconds` (long calls never sit in memory whole).
    public static func read(_ url: URL, seconds: Double = 10, _ body: ([Float]) throws -> Void) throws {
        let file = try AVAudioFile(forReading: url)
        let resampler = Resampler()
        let frames = AVAudioFrameCount(seconds * file.processingFormat.sampleRate)
        while file.framePosition < file.length {
            guard let buffer = AVAudioPCMBuffer(pcmFormat: file.processingFormat, frameCapacity: frames) else { break }
            try file.read(into: buffer)
            if buffer.frameLength == 0 { break }
            try body(resampler.convert(buffer))
        }
    }
}
