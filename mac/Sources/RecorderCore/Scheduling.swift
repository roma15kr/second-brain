import Foundation

/// What the Mac is doing, as far as call transcription cares (design D3 "Never in the way").
public struct MachineState: Equatable, Sendable {
    public var isRecording: Bool
    public var isDictating: Bool
    public var onBattery: Bool
    public var allowBattery: Bool

    public init(isRecording: Bool = false, isDictating: Bool = false, onBattery: Bool = false, allowBattery: Bool = false) {
        self.isRecording = isRecording
        self.isDictating = isDictating
        self.onBattery = onBattery
        self.allowBattery = allowBattery
    }
}

public enum Gate: Equatable, Sendable {
    case run
    case wait(String)
}

public enum TranscriptionPolicy {
    public static func gate(_ s: MachineState) -> Gate {
        if s.isRecording { return .wait("Waiting for the call to end") }
        if s.isDictating { return .wait("Dictation first") }
        if s.onBattery && !s.allowBattery { return .wait("Waiting for power") }
        return .run
    }
}

/// Blocks a transcription between phrases while the policy says wait; throws when cancelled.
/// Runs on the transcription queue, never on the main thread.
public final class PausableCheckpoint: @unchecked Sendable {
    let state: () -> MachineState
    let sleep: (TimeInterval) -> Void
    let isCancelled: () -> Bool
    /// The reason while waiting, nil when running again.
    public var onWait: ((String?) -> Void)?
    public static let poll: TimeInterval = 2

    public init(
        state: @escaping () -> MachineState, isCancelled: @escaping () -> Bool = { false },
        sleep: @escaping (TimeInterval) -> Void = { Thread.sleep(forTimeInterval: $0) }
    ) {
        self.state = state
        self.isCancelled = isCancelled
        self.sleep = sleep
    }

    public func wait() throws {
        var waited = false
        while true {
            if isCancelled() { throw CancellationError() }
            guard case let .wait(reason) = TranscriptionPolicy.gate(state()) else { break }
            if !waited { onWait?(reason) }
            waited = true
            sleep(Self.poll)
        }
        if waited { onWait?(nil) }
    }
}
