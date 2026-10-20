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

## Amendment (2026-10-20, change `mac-recorder-v1`)
- **Mac first, iPhone later** (owner: "Start with mac, skip phone"); phone recordings reach the
  second brain by import on the Mac (drop, "Import…", or a watched Voice Memos folder).
- **Calls are transcribed on the Mac** with NVIDIA Parakeet TDT 0.6B v3 through sherpa-onnx
  (CPU or Core ML, whichever the built-in measurement finds faster), after the call by default,
  optionally live. Reason: 100–150 h of calls a month would cost $20–45 in the cloud against a
  $30 budget for everything; Parakeet matches Whisper large-v3 on Ukrainian (6.8% vs 6.5% WER).
  System audio is captured with a Core Audio process tap (ScreenCaptureKit as fallback).
- **Dictation stays on OpenAI** through the server (`gpt-transcribe`, then as said / cleaned /
  structured); offline the Mac types it as said with Parakeet.
- **Cloud fallback without an app update:** Settings → "Cloud" sends calls to the server's provider
  (OpenAI diarize or Whisper, or Groq Whisper large-v3-turbo when `GROQ_API_KEY` is set).
- **Distribution:** no App Store. `mac/install.sh` (signed with a free Apple Development
  certificate so permissions survive updates) or the universal `.dmg` from the `mac-latest`
  GitHub release (ad-hoc signed: "Open Anyway" once; the app downloads the model itself).
