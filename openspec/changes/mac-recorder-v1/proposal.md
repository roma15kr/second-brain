# Proposal: mac-recorder-v1 — Mac app for dictation anywhere and call/meeting recording

Branch: `change/mac-recorder-v1`, created from `main` (uses the device API, recordings and meeting
audio built in `web-os-v1`). Replaces the planned `voice-apps-v1` for now: **Mac only** (owner
decision 2026-10-20: "Start with mac, skip phone"; the iPhone app is out of scope).

## Why

**Problem (in the owner's words):** "I only need an app for my Mac with both dictation and
call/meeting recording. Also import voice memos / call recordings. With hotkeys for both
operations. It's OK if you transcribe meetings after the calls. I have 3–5 calls of 60–90 minutes
per day, so I need a cost-effective solution."

Today calls in desktop apps (Zoom, Telegram, Meet in a browser, phone calls via the Mac) leave no
trace in the second brain, and dictation works only inside the web OS while it is open.

**Evidence:**
- Owner requests 2026-10-18 and 2026-10-20 (quoted above); roadmap "Next": macOS meeting
  assistant / recorder apps — `docs/product/roadmap.md`.
- ADR 0010 (+ 12-month audio amendment) and ADR 0014: system audio of desktop apps and
  system-wide dictation are impossible from the web (`docs/research/web-os-pwa-voice.md`).
- The server side is ready and waiting: device pairing, `/api/devices/recordings`, resumable audio
  upload, matching to calendar events, meeting processing (summary, decisions, loops, task drafts).
- Volume: 3–5 calls × 60–90 min/day ≈ 100–150 h of audio a month. Cloud transcription of both
  tracks would cost ≈ $60–90/month (OpenAI price list in the research note) — above the whole
  $30 monthly AI budget.

**Success metric:** for 4 consecutive weeks, **≥ 90% of the owner's calendar meetings with other
attendees have a transcript attached** (recorded on the Mac) and the monthly transcription cost
stays **≤ $5**. Measured on the Status page: meetings with/without a recording per week, and
transcription spend per month.

## What Changes

- **Mac menu-bar app** (Apple Silicon, for the owner only; built and installed with one command,
  no App Store):
  - **Record a call or meeting** with a global hotkey or the menu: the owner's microphone and the
    computer's audio (any app: Zoom, Telegram, Meet in a browser, FaceTime) as two separate
    tracks ("me" / "others"); a visible recording indicator and timer; stop with the same hotkey.
  - **Dictate anywhere** with a second global hotkey (hold to talk, or press to start/stop): the
    text is typed into the app in front (mail, Telegram, ClickUp, notes), as said or cleaned up;
    a third choice structures it (summary, points, actions) via the server.
  - **Import** voice memos and call recordings: drag files onto the app or choose "Import…"; an
    optional watched folder (e.g. Voice Memos) imports new recordings automatically.
- **Transcription on the Mac, after the call** (no per-minute cost): each track is transcribed
  locally (uk/ru/en, mixed), lines from both tracks are merged by time with "me" / "others" labels;
  silence is skipped. Optional per recording: **cloud transcription with speaker separation** for
  meetings with several other people (cost shown before choosing).
- **Delivery to the second brain**: transcript, timing and both audio tracks are uploaded through
  the existing device API (resumable, survives sleep and network loss); the server attaches them
  to the calendar event or saves an unscheduled call, and processes them as today.
- **Server additions** (small): the device API gains dictation text forms (clean / structured)
  for device tokens, and an optional server-side transcription of uploaded tracks (cloud
  fallback); Status shows recording coverage of meetings and transcription spend.
- **Decision changes (owner confirmation needed):** new dependency **WhisperKit** (open source,
  MIT; on-device Whisper for Apple Silicon) in the Mac app; ADR 0014 amended (Mac first, iPhone
  later; on-device transcription by default).

## Capabilities

### New Capabilities
- `mac-recorder`: the Mac app — recording calls and meetings with two tracks, dictation into any
  app, importing recordings, local transcription, reliable delivery to the second brain, hotkeys,
  permissions and privacy behaviour.
- `device-api`: what the server offers paired devices beyond uploads — dictation text forms and
  optional cloud transcription of uploaded tracks — and the coverage/cost figures on Status.

### Modified Capabilities
None in `openspec/specs/`. The device upload contract, recordings and meeting audio live in the
unarchived `web-os-v1` change (`calendar-meetings`) and are used unchanged.

## Impact

- **New code:** `mac/` — Swift package for the menu-bar app (SwiftUI + AppKit), audio capture
  (Core Audio process tap for system audio, AVAudioEngine for the microphone), WhisperKit, upload
  queue, hotkeys; `mac/install.sh` builds, signs and installs the app on the owner's Mac.
- **Server:** `src/kb/api/routes_devices.py` (dictation forms and transcription endpoints for
  device tokens), `src/kb/recordings.py` (server-side transcription of tracks), Status figures.
- **CI:** a GitHub Actions macOS job builds and tests `mac/` when it changes (this workspace
  cannot run Xcode).
- **Dependencies:** WhisperKit (Swift package) — needs owner approval; Whisper model files are
  downloaded once on the Mac (~0.6–1.6 GB).
- **Docs:** ADR 0014 amendment, architecture, external (Mac permissions), STATUS.
