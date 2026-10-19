# 0014. Dictation and call/meeting transcription are native macOS and iOS apps
Date: 2026-10-18
Status: accepted

## Context
Research (docs/research/web-os-pwa-voice.md) showed what a web app cannot do: on macOS, Chrome
captures only tab audio (no system audio from Zoom/Telegram desktop apps), Safari captures none;
iOS suspends web apps on screen lock and web apps cannot be share targets; system-wide dictation
(typing into other apps) is impossible from the web.

## Decision
- Voice capture is native: a **macOS app** (menu bar: call/meeting recorder via ScreenCaptureKit
  + microphone as separate tracks, global dictation hotkey) and an **iOS app** (dictation, in-person
  recordings with background audio, import from Voice Memos / call recordings via the share sheet).
- Both upload to the server API; transcription uses OpenAI (`gpt-transcribe` for recordings,
  `gpt-4o-transcribe-diarize` for meetings, `gpt-live-transcribe` for live captions/dictation).
- The web OS does **not** implement recording or dictation; it shows notes, transcripts and their
  summaries like any other source.
- Supersedes the macOS-only scope of ADR 0010 (its transcript/retention rules still apply).

## Consequences
Two native codebases (Swift/SwiftUI, shared package), App Store / TestFlight distribution,
Apple developer account. Planned as its own OpenSpec change after the web OS.

## Amendment (2026-10-19, change `assistant-command-v1`)
The web OS now records **dictation inside the app while it is open** (MediaRecorder; webm/opus, or
mp4 on iPhone), uploads it, transcribes it with `gpt-transcribe` and deletes the audio once the
transcript is stored (failed ones after 7 days). It offers Verbatim, Clean, Structured and "as a
request". Still native-only: system-wide dictation (typing into other apps), background recording,
and call/meeting recording (`voice-apps-v1`). Reason: the owner asked to dictate requests and notes
in the web OS; research showed in-app foreground recording works in the installed PWA on iPhone,
macOS Safari and Chrome (docs/research/web-os-pwa-voice.md).
