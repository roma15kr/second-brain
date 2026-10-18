# 0010. macOS meeting assistant with live transcript and live KB lookups
Date: 2026-10-10
Status: accepted

## Context
Meetings happen on many platforms (Meet, Zoom, Teams, Telegram); some clients forbid bots.
Live transcription quality is lower than batch, especially with uk/ru/en code-switching.

## Decision
- Native macOS app: ScreenCaptureKit system audio + microphone as separate tracks (you vs others).
- Streaming cloud STT for a live transcript, rolling notes, live KB assistant (context from
  previous meetings, ClickUp tasks, metrics) and action items before the call ends.
- After the call, batch re-transcription with diarization becomes the canonical transcript stored
  in the KB; audio is kept 30 days, then deleted. Video is not stored.
- Consent to record is the owner's responsibility; no in-app feature.

## Consequences
A separate product (Swift) built after the core KB exists, since the live assistant queries it.
Streaming STT cost scales with call hours; budget target <= $100/month total for cloud AI.

## Amendment 2026-10-18 — audio kept 12 months in the knowledge base
Owner decision: meeting and call audio is saved to the knowledge base and kept **12 months**
(was 30 days), then deleted automatically; transcripts, summaries and decisions are kept forever.
Audio (separate tracks: owner / others) is uploaded by the recorder apps, played back on the
meeting page in sync with the transcript, can be deleted earlier per recording or per scope, and is
included in backups. Storage estimate: Opus 15–30 MB per hour, ≈ 8–15 GB per year at ~10 h/week.
Implemented in `web-os-v1` (storage, upload, playback, retention); recording itself in `voice-apps-v1`.

