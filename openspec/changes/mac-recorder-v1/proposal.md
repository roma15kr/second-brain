# Proposal: mac-recorder-v1 — Mac app for dictation anywhere and call/meeting recording

Branch: `change/mac-recorder-v1`, created from `main` (uses the device API, recordings and meeting
audio built in `web-os-v1`). Replaces the planned `voice-apps-v1` for now: **Mac only** (owner
decision 2026-10-20: "Start with mac, skip phone").

## Why

**Problem (in the owner's words):** "I only need an app for my Mac with both dictation and
call/meeting recording. Also import voice memos / call recordings. With hotkeys for both
operations — and I need to be able to change the hotkeys. It's OK if you transcribe meetings after
the calls. I have 3–5 calls of 60–90 minutes per day, so I need a cost-effective solution."

Today calls in desktop apps (Zoom, Telegram, Meet in a browser, phone calls via the Mac) leave no
trace in the second brain, and dictation works only inside the web OS while it is open.

**Evidence:**
- Owner requests 2026-10-18 and 2026-10-20 (quoted above); roadmap "Next": macOS meeting
  assistant / recorder apps — `docs/product/roadmap.md`.
- ADR 0010 (+ 12-month audio amendment) and ADR 0014: system audio of desktop apps and
  system-wide dictation are impossible from the web (`docs/research/web-os-pwa-voice.md`).
- The server side is ready: device pairing, `/api/devices/recordings`, resumable audio upload,
  matching to calendar events, meeting processing (summary, decisions, loops, task drafts).
- Owner's Mac: MacBook Pro 15" 2018, 6-core Intel Core i7-8750H, 16 GB, Radeon Pro 555X 4 GB,
  macOS 15.8 — Intel, so Apple-Silicon-only tools (WhisperKit) are out.
- Volume ≈ 100–150 h of calls a month. Transcription prices (OpenAI price list, 2026-10-20):
  gpt-4o-mini-transcribe $0.003/min, gpt-transcribe $0.0045/min, diarize $0.006/min, live
  $0.017/min → $20–45/month for calls in the cloud (live: $70–340), against a $30 monthly AI
  budget for everything. NVIDIA Parakeet TDT 0.6B v3 runs on a CPU, supports Ukrainian and Russian
  and scores 6.8% WER on Ukrainian FLEURS vs 6.5% for Whisper large-v3 (NVIDIA, arXiv 2509.14128).
- Owner decisions 2026-10-20: dictation keeps OpenAI (transcription + cleaning + structuring);
  calls try NVIDIA Parakeet on the Mac first; if the owner's tests are bad, calls move to OpenAI or
  Groq (Whisper large-v3-turbo, ≈ $0.04/h).

**Success metric:** for 4 consecutive weeks, **≥ 90% of the owner's calendar meetings with other
attendees have a transcript attached** (recorded on the Mac), and transcription costs **≤ $10 a
month** (dictation included). Measured on the Status page: meetings with/without a recording per
week, and transcription spend per month.

## What Changes

- **Mac menu-bar app** (Intel and Apple Silicon, macOS 15; for the owner only; built and installed
  with one command, no App Store):
  - **Record a call or meeting** with a global hotkey or the menu: the owner's microphone and the
    computer's audio (any app: Zoom, Telegram, Meet in a browser, FaceTime) as two separate tracks
    ("me" / "others"); recording indicator and timer; stop with the same hotkey.
  - **Dictate anywhere** with a second global hotkey (hold to talk, or press to start/stop): the
    text is typed into the app in front, as said or cleaned up; with a modifier it is structured
    (summary, points, actions). Dictation uses OpenAI through the server.
  - **Link each recording to a meeting**: at the start the app offers the calendar meetings around
    now (or "Automatic" matching by time), or **"New meeting…" for a spontaneous call** (title,
    project, participants); the meeting or project can be changed later in the app or on the
    recording's page in the web OS, where meetings outside the calendar can also be created.
  - **All hotkeys can be changed** in Settings (recording, dictation, the structured modifier);
    taken combinations are refused with a message.
  - **Import** voice memos and call recordings: drag files onto the app, "Import…", or a watched
    folder (e.g. Voice Memos) that imports new recordings automatically.
- **Call transcription on the Mac with NVIDIA Parakeet v3** (no per-minute cost; uk/ru/en): after
  the call by default, at low priority so calls are never slowed, waiting for power on battery; an
  optional **Live** mode shows captions phrase by phrase during the call. The app measures whether
  the Mac's CPU or GPU is faster and uses that.
- **Cloud fallback for calls, switchable without rebuilding the app:** the server can transcribe
  uploaded tracks with OpenAI (diarize or Whisper — the models that return timestamps, needed to
  interleave "me" and "others") or Groq (Whisper large-v3-turbo); the owner
  chooses the call engine in the app (Mac / cloud) and the cloud provider on the server. Speaker
  separation (OpenAI diarize) can be requested per meeting, with the cost shown first.
- **Audio is stored on the owner's server**: both tracks of every call and import, whatever engine
  transcribes them (12 months, backups, playback beside the transcript); dictation keeps text only.
- **Delivery to the second brain**: transcript, timing and both audio tracks through the existing
  device API (resumable, survives sleep and network loss); attached to the calendar event or saved
  as an unscheduled call; processed as today.
- **Server additions:** device dictation (audio in → OpenAI transcript → as said / cleaned /
  structured text back), cloud transcription of uploaded tracks (OpenAI or Groq), transcription
  costs in the monthly budget, recording coverage and cost on Status.
- **Decision changes (owner confirmation needed):** new dependency **sherpa-onnx** (Apache-2.0,
  speech runtime with macOS builds) and the **Parakeet TDT 0.6B v3** model (CC-BY-4.0, ~0.6 GB,
  downloaded once) in the Mac app; Groq as an optional transcription provider (only if the
  fallback is needed; its API key added then); ADR 0014 amended (Mac first, iPhone later).

## Capabilities

### New Capabilities
- `mac-recorder`: the Mac app — recording calls and meetings with two tracks, dictation into any
  app, changeable hotkeys, importing recordings, local call transcription (after the call or live),
  reliable delivery, permissions and privacy behaviour.
- `device-api`: what the server offers paired devices beyond uploads — meetings around now (the only
  read), linking recordings to meetings or projects, dictation with OpenAI and
  text forms, cloud transcription of uploaded tracks (OpenAI or Groq, optional speaker
  separation) — and the coverage/cost figures on Status.

### Modified Capabilities
None in `openspec/specs/`. The device upload contract, recordings and meeting audio live in the
unarchived `web-os-v1` change (`calendar-meetings`) and are used unchanged.

## Impact

- **New code:** `mac/` — Swift package for the menu-bar app (SwiftUI + AppKit), audio capture
  (Core Audio process tap for system audio, AVAudioEngine for the microphone), sherpa-onnx with
  Parakeet, upload queue, hotkeys; `mac/install.sh` builds, signs and installs the app.
- **Server:** `src/kb/api/routes_devices.py` (device dictation, transcription requests),
  `src/kb/transcription.py` (OpenAI / Groq providers, costs), `src/kb/recordings.py` (replace
  segments from cloud results), Status figures.
- **CI:** a GitHub Actions macOS job builds and tests `mac/` when it changes (this workspace
  cannot run Xcode; the repository is public, so the macOS minutes are free).
- **Dependencies:** sherpa-onnx + Parakeet model (Mac app); Groq only if the fallback is chosen
  (OpenAI-compatible HTTP API, no new library).
- **Docs:** ADR 0014 amendment, architecture, external (Mac permissions, Groq key), STATUS.
