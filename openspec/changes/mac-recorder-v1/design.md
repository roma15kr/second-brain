# Design: mac-recorder-v1

## Context

See proposal.md (Why). The server already has what a recorder needs (web-os-v1 13.3/13.4):
pairing codes → device tokens (hashed, upload-only, revocable), `POST /api/devices/recordings`
(idempotent by key; segments `{speaker, is_owner, start, end, text}`; matching to calendar events),
resumable per-track audio (`POST …/audio/{track}` announce, `HEAD` offset, `PUT` with
`Content-Range`, sha256 check, 12-month retention), meeting processing (summary, decisions, loops,
task drafts), and dictation in the web OS (`kb.dictation`: OpenAI `gpt-transcribe`, clean and
structured forms).

Constraints: one Mac — MacBook Pro 15" 2018, 6-core Intel i7-8750H, 16 GB, Radeon Pro 555X,
macOS 15.8; the app is only for the owner (no App Store); this workspace is Linux and cannot run
Xcode, so Swift is built and tested on a GitHub Actions macOS runner and installed with a script;
the monthly AI budget is $30 for everything while calls are 100–150 h/month.

## Goals / Non-Goals

**Goals:** a reliable two-track recorder for any call app; dictation into any app with OpenAI
quality; free call transcription on the Mac with a switch to cloud if quality disappoints;
changeable hotkeys; delivery that never loses a recording; small server changes.

Audio: both tracks of every recording and import are always uploaded to the server's `kb-audio`
store (12 months, backups, playback) regardless of the transcription engine; dictation audio is
not stored (text only).

**Non-Goals:**
- iPhone app (owner: "skip phone"); phone recordings arrive by import on the Mac.
- A live assistant during calls (ADR 0010 direction; later change). Live *captions* are optional.
- Automatic recording when a call starts (manual hotkey in v1).
- Whisper re-transcription on the Mac (too slow on this CPU; can be added later).
- Video; screen capture; App Store / TestFlight distribution.

## Decisions

### D1. Packaging: Swift package + install script, signed for the owner's Mac
`mac/` is a Swift package (Swift 6, macOS 15, universal x86_64 + arm64) with an executable target
`SecondBrainRecorder` (SwiftUI + AppKit menu-bar app, `LSUIElement`) and a library target with the
testable logic. `mac/install.sh` (needs the Xcode command line tools) builds release, downloads the
pinned sherpa-onnx macOS build and the Parakeet model on first install (checksums verified),
assembles `Second Brain Recorder.app` (Info.plist with `NSMicrophoneUsageDescription`,
`NSAudioCaptureUsageDescription`), signs it, copies it to `/Applications` and adds a Login Item.
Signing uses the owner's free "Apple Development" certificate (Xcode → Settings → Accounts, any
Apple ID) so macOS keeps granted permissions across updates; without it the script ad-hoc signs and
warns that permissions will be asked again after each update.
*Alternatives:* an Xcode project (needs Xcode UI for every change); App Store / TestFlight (needs
the paid program; one user).

### D2. Audio capture: two tracks, written continuously
- **Microphone:** `AVAudioEngine` input, mono; on a route/configuration change (AirPods) the engine
  restarts within ~1 s into the same track.
- **Computer audio:** a Core Audio **process tap** (macOS 14.2+ `CATapDescription` over all processes
  except the app) on a private aggregate device — any app's output, only the "System Audio
  Recording" permission, no screen-recording indicator. Fallback: ScreenCaptureKit audio.
- Both tracks → AAC mono 16 kHz ~32 kbps (~14 MB/h) in **5-minute segment files**; joined per track
  on stop or on the next start after a crash (`AVMutableComposition`, no re-encode). 4-hour limit.
  16 kHz mono is what the speech models expect, so no resampling is needed for transcription.

### D3. Call transcription: NVIDIA Parakeet v3 via sherpa-onnx on the Mac
- **sherpa-onnx** (Apache-2.0; C API with Swift bindings; prebuilt macOS x86_64/arm64) runs
  **Parakeet TDT 0.6B v3** (int8 ONNX, ~0.6 GB, CC-BY-4.0). Language detection is automatic; output
  has punctuation and capitalisation.
- **Segmentation:** sherpa-onnx's Silero VAD splits each track into speech segments (silence
  skipped); each segment is transcribed; segments carry track label ("me" / "others") and times;
  both tracks are merged by start time. Segments longer than 30 s are split at the quietest point.
- **CPU or GPU:** sherpa-onnx can run on the CPU or through Core ML (which may use the Radeon on
  this Mac). On first use the app transcribes a bundled 30-second sample with each provider and
  keeps the faster; the result ("7× real time on GPU") is shown in Settings and can be overridden.
- **Never in the way:** jobs run on a utility-QoS queue with ≤ 3 threads (half the cores); a full
  transcription does not run while a recording is active (the job pauses at a segment boundary and
  resumes); on battery, call jobs wait for power unless "Use battery" is on (IOKit power source
  notifications). Dictation fallback (offline) has its own queue and always goes first.
- **Live mode** (setting, off by default): during recording the same VAD + model run on each
  track's audio as it arrives; finished phrases appear in a floating caption window ~1–2 s after
  the phrase ends; the transcript is complete when the call ends (no after-call pass).
- Expected speed on this CPU: roughly 4–8× real time (90-min call ≈ 12–25 min); measured, not
  assumed — the acceptance checklist records the real number.

### D4. Call engine switch and cloud fallback
Settings → "Call transcription": **On this Mac** (default) or **Cloud**. In Cloud mode the app
skips local transcription and, after both tracks are uploaded, calls
`POST /api/devices/recordings/{id}/transcribe {speakers: false}`. The server's provider is a
setting (`calls_provider`: `openai-diarize` | `openai-whisper` | `groq`; default `openai-diarize`),
so switching between OpenAI and Groq needs no app change. Only providers that return timed
segments can interleave the two tracks: OpenAI's `gpt-4o-mini-transcribe` and `gpt-transcribe`
return text without timestamps, so they are used for dictation only (found while building 1.2). Per recording, "Separate speakers"
(`{speakers: true}`) uses OpenAI `gpt-4o-transcribe-diarize` for the "others" track, with the
estimated cost (speech minutes × price) shown before confirming.
Server: `kb.transcription` with providers behind one function
`transcribe(path, provider, speakers) -> segments, seconds, usd`; OpenAI via the existing SDK; Groq
via its OpenAI-compatible endpoint (`base_url` + `GROQ_API_KEY`; enabled only when the key is set;
no new library). Files over 25 MB are split by time (ffmpeg is not needed: the AAC segments from
D2 are uploaded alongside the joined track when a track exceeds 25 MB). Jobs run in the routines
service (`transcription_jobs`), replace the recording's segments for the transcribed tracks, record
the cost and re-process the recording.

### D5. Dictation with OpenAI through the server
- Hotkeys (D6). Audio is recorded to memory (AAC 16 kHz mono) and sent as the raw body to
  `POST /api/devices/dictations?form=verbatim|clean|structured&seconds=…` (device token). The
  server reuses `kb.dictation`: `gpt-transcribe` (keeps the language mix), then the requested form
  (clean: cheap model with the wording check; structured: briefs model), stores the dictation
  without audio, returns `{text}`. Typical latency 2–4 s for a short phrase.
- Over budget: verbatim with a note. **Offline:** the app transcribes locally with Parakeet,
  types it as said and notifies; the dictation is not sent later (text only stays on the Mac).
- Insertion: text on the pasteboard, ⌘V sent to the focused app (CGEvent; Accessibility
  permission), previous pasteboard content restored after 1 s; if the focused element is not
  editable (AX role check) the text stays on the clipboard with a notification.

### D6. Hotkeys, changeable
Carbon `RegisterEventHotKey` (press and release events; no Accessibility needed). Defaults: record
⌃⌥R, dictate ⌃⌥D, structured modifier ⇧. Settings has a recorder field per hotkey ("press the new
combination"); registration failure (already taken by the system or another app) is reported and
the previous hotkey kept; changes apply immediately and persist in user defaults. Dictation: held
longer than 0.4 s = hold-to-talk, otherwise toggle.

### D7. Delivery queue
Each recording/import is a folder `~/Library/Application Support/SecondBrainRecorder/items/<uuid>/`
with audio, transcript and `state.json` (recorded → transcribing → transcribed → registering →
uploading → delivered | waiting(reason) | failed(reason)). Uploader: register with
`idempotency_key = <uuid>` (kind, started/ended, source = front app at start, segments), then per
track announce (size, sha256, `audio/mp4`, duration) → `HEAD` offset → `PUT` 8 MB chunks; 409 →
continue from the server's offset. Cloud mode registers without segments first, uploads, then
requests transcription. Retries with backoff; `NWPathMonitor` resumes on network; 401 → "not
paired", delivery paused. Local audio deleted 7 days after delivery. The menu lists pending,
waiting (e.g. "waiting for power"), failed with reasons.

### D7a. Linking to meetings and projects
- `GET /api/devices/meetings?around=now` (device token): events of marked calendars within ±12 h,
  fields id, title, start, end, `in_progress` only. This is the one read a device token gets
  (design D22 of web-os-v1 anticipated a narrow device read); everything else stays upload-only.
- At recording start the menu shows those meetings (in progress first) with "Automatic" selected;
  the choice is stored in the item and sent as `event_id` when registering. `store()` already
  accepts an explicit `event_id` (used by notes import).
- Changing later: `POST /api/devices/recordings/{id}/link {event_id | null, scope}` for the
  device's own recordings, and the same as an owner route `POST /api/recordings/{id}/link` with a
  meeting picker and project select on the recording page in the web OS. Re-linking updates
  `recordings.event_id`, title and scopes, re-indexes the `meeting` item (new locator, scopes),
  and re-runs processing (summary, loops, task drafts for the new meeting; earlier task drafts
  from this recording that are still pending are discarded with reason "re-linked").

### D7b. Meetings that are not in a calendar
- A built-in calendar "Second brain": a `connector_accounts` row (kind `calendar`,
  `settings.type = 'local'`, no secret) with one `calendars` row (sync on, mark per meeting),
  created by migration; `calendar.sync_due` skips type `local` (nothing to fetch). Events in it are
  ordinary `events` rows (uid `local-<uuid>`), so Meetings, prep, reminders (if in the future),
  matching and processing work unchanged. Their project is stored per event (`events.scopes`
  override, falling back to the calendar's) because one local calendar holds several projects.
- Device: registering a recording may carry `new_meeting {title, scope, participants[]}`
  instead of `event_id`; the server creates the event for the recording's time and links it.
  `POST /api/devices/recordings/{id}/link` accepts the same `new_meeting` for "New meeting…" after
  the call. Participants are names or emails; the server matches emails to identities and names to
  people (unambiguous display name), stores them as attendees `{email?, name, person_id?}`.
- Web OS: Meetings page "New meeting" (title, project, start/end, participants with People
  autocomplete — the owner's session can read People), "Make a meeting" on an unscheduled call
  (re-link to a new local event), and edit title/project/participants of local events only.
  Connected Google/iCloud events stay read-only.

### D8. Imports
Drag & drop on the menu-bar icon or window, "Import…" (`NSOpenPanel`), and an optional watched
folder (security-scoped bookmark + FSEvents; for Voice Memos the owner selects
`~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings`, which may need Full Disk
Access — detected and explained). Imported once (path + size + mtime in `imported.json`). Imports
are one-track recordings (kind `voice_note` or `call`, chosen on drop; watched folder →
`voice_note`), started at the file's creation time; formats m4a, mp3, wav, caf, ogg (decoded with
AVFoundation; ogg via sherpa-onnx's decoder).

### D9. Server additions (summary)
- `dictations.device_id`; `POST /api/devices/dictations` (D5).
- `transcription_jobs`, `transcription_costs (day, kind dictation|call, provider, model, seconds,
  usd)`; `distill.month_spend_usd` includes them; `POST /api/devices/recordings/{id}/transcribe`
  (D4); `kb.transcription` providers; `app_settings` key for the call provider (Settings page).
- Status: meetings with attendees vs meetings with a recording per week; transcription spend by
  kind this month.
- Meetings for devices and re-linking (D7a).

### D10. CI and tests
- `.github/workflows/mac.yml` (the repository is public, so macOS runner minutes are free): on
  `mac/**` changes, a `macos-15` runner runs `swift build` and
  `swift test` for the logic (segment merge, state machine, uploader against a URLProtocol mock of
  the device API, import de-duplication, hotkey hold/toggle and conflict handling, scheduling rules
  for battery/recording, provider benchmark choice with fake timings). Real audio capture, Parakeet
  inference speed and quality are checked on the owner's Mac in acceptance (runners have no audio
  devices; the model is too large for every run). The sherpa-onnx build is cached in CI.
- Server parts are tested in `make check`.

## Risks / Trade-offs

- [Parakeet quality on the owner's calls (mixing uk/ru within a sentence, noise)] → acceptance
  compares 2–3 real calls with OpenAI gpt-transcribe; one switch moves calls to OpenAI or Groq.
- [Speed/heat on a 2018 Intel MacBook] → measured CPU vs GPU, ≤ 3 threads, utility QoS, pause
  during calls, wait for power on battery; Live mode off by default.
- [Process-tap API is new and sparsely documented] → ScreenCaptureKit fallback; manual test
  matrix: Zoom, Telegram, Meet in Chrome/Safari, FaceTime.
- [Code cannot be compiled in this workspace] → macOS CI on every change; small slices; owner
  acceptance checklist at the end.
- [Permissions reset after updates with ad-hoc signing] → free Apple Development certificate (D1);
  the app shows missing permissions with buttons to System Settings.
- [Dictation depends on the network and OpenAI] → offline local fallback (as said).
- [Recording consent] → the owner's responsibility (ADR 0010); the app never records on its own.
- [Cloud costs if the fallback is used] → Status shows transcription spend by kind; provider
  default is the cheapest OpenAI model; Groq ≈ $0.04/h if configured.

## Migration Plan

Server: additive migrations, deployed as usual. Mac: `mac/install.sh` on the owner's Mac; updates
= pull + rerun; uninstall = delete the app (local data in Application Support). The device can be
revoked in the web OS.

## Open Questions

- Whether Core ML on the Radeon Pro 555X is faster than the CPU for Parakeet — decided at runtime
  by the built-in measurement; no plan change either way.
