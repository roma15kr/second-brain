import Foundation

/// Live mode (design D3): each track is transcribed phrase by phrase while the call runs; at the
/// end the transcript is complete without an after-call pass.
public final class LiveAssembler {
    let makeTranscriber: (Track) throws -> StreamingTranscriber
    private var transcribers: [String: StreamingTranscriber] = [:]
    private var order: [String] = []
    private var lines: [String: [TranscriptSegment]] = [:]
    /// Each finished phrase, as soon as it is recognized (caption window).
    public var onPhrase: ((TranscriptSegment) -> Void)?

    public init(makeTranscriber: @escaping (Track) throws -> StreamingTranscriber) {
        self.makeTranscriber = makeTranscriber
    }

    public func feed(track name: String, samples: [Float], offset: TimeInterval) throws {
        if transcribers[name] == nil {
            var track = Track(name: name, file: "\(name).m4a")
            track.offset = offset
            transcribers[name] = try makeTranscriber(track)
            order.append(name)
        }
        for phrase in try transcribers[name]!.feed(samples) {
            lines[name, default: []].append(phrase)
            onPhrase?(phrase)
        }
    }

    /// Ends all tracks; returns the merged transcript.
    public func finish() throws -> [TranscriptSegment] {
        for name in order {
            for phrase in try transcribers[name]!.finish() {
                lines[name, default: []].append(phrase)
                onPhrase?(phrase)
            }
        }
        return TranscriptMerge.merge(order.map { lines[$0] ?? [] })
    }
}
