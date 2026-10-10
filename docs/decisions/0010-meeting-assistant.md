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
