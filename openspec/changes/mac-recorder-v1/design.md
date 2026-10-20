# Design: mac-recorder-v1

## Context

See proposal.md (Why). The server already has everything a recorder needs (web-os-v1 13.3/13.4):
pairing codes → device tokens (hashed, upload-only, revocable), `POST /api/devices/recordings`
(idempotent by key; segments `{speaker, is_owner, start, end, text}`; matching to calendar events),
resumable per-track audio (`POST …/audio/{track}` announce, `HEAD` offset, `PUT` with
`Content-Range`, sha256 check, 12-month retention), and processing into summary / decisions /
loops / task drafts. Dictation forms (clean, structured) exist for the web OS (`kb.dictation`).

Constraints: the owner uses one Mac, wants the app only for themself (no App Store); this
workspace is Linux and cannot run Xcode, so the Swift code is built and tested on a GitHub Actions
macOS runner and installed on the owner's Mac with a script; monthly AI budget is $30 for
everything, while the call volume is 100–150 h/month.

## Goals / Non-Goals

**Goals:** a reliable two-track recorder for any call app, dictation into any app, local
transcription by default, delivery that never loses a recording, minimal server changes.

**Non-Goals:**
- iPhone app (owner: "skip phone"); recordings from the phone arrive by import on the Mac.
- Live captions or a live assistant during calls (ADR 0010 stays the direction; later change).
- Automatic recording when a call starts (manual hotkey in v1; a prompt can come later).
- Video; screen capture; Intel Macs (WhisperKit needs Apple Silicon for usable speed).
- App Store / TestFlight distribution.

## Decisions

### D1. Packaging: a Swift package + install script, signed for the owner's Mac
`mac/` is a Swift package (Swift 6, macOS 14.4+) with an executable target `SecondBrainRecorder`
(SwiftUI + AppKit menu-bar app, `LSUIElement`) and a library target with the testable logic.
`mac/install.sh` (run on the owner's Mac; needs the Xcode command line tools) builds release,
assembles `Second Brain Recorder.app` (Info.plist with `NSMicrophoneUsageDescription`,
`NSAudioCaptureUsageDescription`), signs it and copies it to `/Applications`, then adds it to Login
Items. Signing uses the owner's free "Apple Development" certificate (Xcode → Settings → Accounts,
any Apple ID) so macOS keeps the granted permissions across updates; without it the script
ad-hoc signs and macOS asks for permissions again after each update.
*Alternatives:* an Xcode project (needs Xcode UI for every change; a package builds headless in
CI); App Store / TestFlight (needs the paid program; the owner needs the app only for themself).

### D2. Audio capture: two tracks, written continuously
- **Microphone:** `AVAudioEngine` input node, mono; a route/configuration change (AirPods on/off)
  restarts the engine within ~1 s and recording continues in the same track.
- **Computer audio:** a Core Audio **process tap** (macOS 14.2+ `CATapDescription` over all
  processes except the app itself) attached to a private aggregate device; this captures any app's
  output without screen recording and needs only the "System Audio Recording" permission.
  *Alternative:* ScreenCaptureKit audio (needs Screen Recording permission and shows the screen
  capture indicator) — kept as a fallback if the tap API fails on the owner's macOS.
- Both tracks are encoded to AAC (mono, 24 kHz, ~32 kbps ≈ 14 MB/h) in **5-minute segment files**;
  stop, quit or a crash loses at most the open segment's last second. On stop (or on the next
  start after a crash) segments are joined per track (`AVMutableComposition` export, no re-encode).
  4-hour hard limit with a notification.

### D3. Transcription: WhisperKit on the Mac, per track, merged by time
- **WhisperKit** (MIT, Swift package; Core ML Whisper on Apple Silicon) with the large-v3 turbo
  model (compressed ~0.6 GB variant, downloaded once to Application Support on first use).
  Language detected per 30 s window, so uk/ru/en and mixed speech work without settings.
- **Voice activity detection** (WhisperKit's energy VAD) skips silence — the owner's track is
  silent most of a call, so each track costs only its own speech time.
- Each track is transcribed separately; segments are labelled "me" (microphone) or "others"
  (computer audio) and merged by start time; overlapping speech stays as two lines. This gives a
  reliable me/others split without diarization.
- One worker actor with a priority queue: dictation first, then recordings and imports; the model
  stays loaded while there is work and is unloaded after 10 min idle (memory).
- Expected speed on M-series: large-v3 turbo runs many times faster than real time, so a 90-minute
  call with ~60 min of speech per track finishes in minutes (acceptance check: ≤ 15 min).
*Alternatives:* cloud only (≈ $60–90/month at this volume); server CPU (faster-whisper, 1–3 h of
compute per hour of audio — cannot keep up with 5 calls a day); Apple's on-device speech
framework (Ukrainian support not guaranteed).

### D4. Cloud transcription with speakers (optional, per recording)
For meetings with several other people the owner can pick "Transcribe in the cloud with speakers"
(menu on a pending or delivered recording). The app shows the estimate (others-track speech
minutes × the price per minute from the server's settings) and, after confirmation, asks the
server: `POST /api/devices/recordings/{id}/transcribe {speakers: true}`. The server (routines
service) sends the uploaded "others" track to `gpt-4o-transcribe-diarize` (the "me" track keeps the
local transcript), replaces the segments, records the cost in `transcription_costs`, and
re-processes the recording. Tracks are ≤ 25 MB at 32 kbps up to ~2 h; longer tracks are refused
with a clear message in v1.

### D5. Dictation into any app
- Hotkeys via Carbon `RegisterEventHotKey` (press and release events, no Accessibility needed):
  hold-to-talk when held longer than 0.4 s, otherwise toggle; ⇧ adds the structured form.
- Short clips are transcribed locally (model kept warm while the hotkey was used in the last
  10 min). "As said" is fully local; "cleaned" and "structured" call
  `POST /api/devices/dictations {text, form}` (server: `kb.dictation` forms; cleaned uses the
  cheap model, structured the briefs model).
- Insertion: the text is put on the pasteboard and ⌘V is sent to the focused app (CGEvent; needs
  the Accessibility permission); the previous pasteboard content is restored after 1 s. If the
  focused element is not editable (AX role check), the text stays on the clipboard with a
  notification.

### D6. Delivery queue
Each recording/import/dictation-free item is a folder in
`~/Library/Application Support/SecondBrainRecorder/items/<uuid>/` with the audio, the transcript
and a `state.json` (recorded → transcribing → transcribed → registering → uploading → delivered |
failed(reason)). The uploader:
1. `POST /api/devices/recordings` with `idempotency_key = <uuid>`, kind, started/ended, source
   (front app at start, e.g. "zoom.us"), language, segments → recording id;
2. for each track: announce (size, sha256, `audio/mp4`, duration), `HEAD` for the offset, `PUT`
   8 MB chunks; 409 → continue from the server's offset;
3. marks delivered; local audio deleted 7 days later.
Retries with backoff; `NWPathMonitor` resumes on network return; the menu shows counts and the
last error. A revoked token (401) pauses delivery and shows "not paired".

### D7. Imports
Drag & drop on the menu-bar icon or the app window, and "Import…" (`NSOpenPanel`). A watched
folder is chosen once with `NSOpenPanel` (security-scoped bookmark; for Voice Memos the owner
selects `~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings`, which may also
need Full Disk Access — the app detects and explains). New files are noticed with FSEvents and
imported once (key: path + size + modification time, kept in `imported.json`). Imports are
one-track recordings (kind `voice_note` or `call`, owner chooses on drop; watched folder
defaults to `voice_note`), started at the file's creation time.

### D8. Server additions
- `dictations.device_id` (nullable) + `POST /api/devices/dictations {text, form}` → stores a done
  dictation with the given (redacted) transcript and returns the requested form via
  `dictation.render`; verbatim returns the text. Over budget → verbatim with a note.
- `POST /api/devices/recordings/{id}/transcribe` (device token, own recordings) → queues a
  `transcription_jobs` row; the routines service runs it (OpenAI transcription, chunk ≤ 25 MB),
  stores segments via `recordings` (replacing the others-track lines), processes the recording.
- `transcription_costs (day, source, model, seconds, usd)`; month spend includes it (budget).
- Status: meetings with attendees vs meetings with a recording per week; transcription spend.

### D9. CI and tests
- `.github/workflows/mac.yml`: on changes under `mac/**`, a `macos-15` runner runs `swift build`
  and `swift test` (logic tests: segment merge, state machine, uploader against a URLProtocol mock
  speaking the real device API shapes, import de-duplication, hotkey hold/toggle timing). Audio
  capture and WhisperKit inference are covered by a manual acceptance checklist on the owner's
  Mac (CI runners have no audio devices; model downloads are too large for every run).
- Server parts are tested in the existing `make check`.

## Risks / Trade-offs

- [Whisper quality on uk/ru mixed speech or noisy calls] → large-v3 turbo is the strongest local
  option; cloud with speakers stays one click away; the owner checks quality in acceptance.
- [Whisper hallucinations on silence/music] → VAD skips silence; segments with very low average
  log-probability are dropped.
- [Process-tap API is new and sparsely documented] → ScreenCaptureKit fallback (D2); manual test
  matrix: Zoom, Telegram, Meet in Chrome/Safari, FaceTime.
- [Code cannot be compiled in this workspace] → macOS CI on every change; owner runs the
  acceptance checklist; small slices delivered one at a time.
- [macOS permissions reset after updates with ad-hoc signing] → free Apple Development
  certificate (D1); the app shows missing permissions with a button to open System Settings.
- [Recording consent] → the owner's responsibility (ADR 0010); the app never records on its own.
- [Disk use] → ~14 MB/h per track; local audio removed 7 days after delivery.

## Migration Plan

Server: additive migrations (`dictations.device_id`, `transcription_jobs`, `transcription_costs`),
deployed as usual. Mac: `mac/install.sh` on the owner's Mac; updates = pull + rerun; uninstall =
delete the app (local data in Application Support). The device can be revoked in the web OS.

## Open Questions

- The owner's Mac model and macOS version (Apple Silicon and macOS 14.4+ assumed); checked in the
  first task before audio work starts.
