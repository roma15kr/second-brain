# Research: second brain as a web OS (PWA) + dictation + call/meeting transcription

Date: 2026-10-18. Question from the owner: can the second brain become a web app ("web OS",
installable PWA) that also does dictation and call/meeting transcription with OpenAI's speech
models, plus the rest of the planned functionality?

**Short answer: yes for almost everything, with two hard platform limits that need small native
helpers:** (1) recording *desktop app* calls (Zoom/Telegram/Teams desktop) on macOS, and
(2) long recordings on iPhone in the background. Everything else — search, people, inbox,
summaries, chat with the knowledge base, dictation inside the app, uploading recordings, recording
browser meetings (Google Meet in Chrome), transcripts with speakers — fits a PWA served by the
existing server.

## 1. Speech-to-text options (OpenAI, official pricing page, 2026-10-18)

| Use | Model | Price | Notes |
|---|---|---|---|
| Recorded audio (default) | `gpt-transcribe` | $0.0045/min | Recommended by OpenAI; supports `prompt`, `keywords`, `languages`; streaming of file results |
| Meetings with speaker labels | `gpt-4o-transcribe-diarize` | ≈ $0.006/min | Only diarization model; returns `speaker`, `start`, `end`; not available in realtime |
| Live (while speaking) | `gpt-live-transcribe` (or `gpt-realtime-whisper`) | $0.017/min | Realtime path (WebSocket/WebRTC) for live captions and dictation |
| Word timestamps | `whisper-1` | $0.006/min | Only model with `timestamp_granularities` |
| Cheapest | `gpt-4o-mini-transcribe` | ≈ $0.003/min | Lower quality fallback |

Limits: 25 MB per upload (long recordings must be chunked, e.g. 10-minute Opus/webm pieces);
formats mp3, mp4, m4a, wav, webm. Ukrainian/Russian are not listed explicitly on the guide page
(Whisper's language list includes both); quality must be checked on our own recordings.

Cost example: 20 h of meetings/month with diarization ≈ $7; 5 h of live dictation ≈ $5;
recorded dictation instead of live ≈ $1.35. Well inside the $100/month budget.
Local alternative (no API cost, private): faster-whisper on the server CPU, ~1–3 h of compute per
hour of audio — fine for overnight re-transcription, not for live use.

## 2. What a browser/PWA can capture (MDN browser-compat-data, 2026-10-18)

| Capability | Chrome/Edge desktop | Safari macOS | iOS (Safari/PWA) | Android Chrome |
|---|---|---|---|---|
| Microphone (`getUserMedia`) + `MediaRecorder` | yes | yes (14.1+) | yes (14+) | yes |
| Screen/tab capture (`getDisplayMedia`) | yes | yes (no audio) | 27+ (no audio) | no |
| **Tab audio** (e.g. Google Meet in a tab) | **yes** | no | no | no |
| **System audio** (any desktop app) | **Windows/ChromeOS only; macOS & Linux: tab audio only** | no | no | no |
| Web Share Target (receive files from share sheet) | yes (89+) | no | **no** | yes (76+) |

Consequences:
- **Browser meetings** (Meet/Zoom-web/Teams-web in a Chrome tab): the PWA can record tab audio +
  microphone as two tracks (you vs. others) and transcribe them. ✔
- **Desktop app calls on the Mac** (Zoom app, Telegram desktop, phone calls via Mac): a web app
  cannot capture them → needs the small native macOS recorder from ADR 0010 (ScreenCaptureKit),
  which uploads to the same server API.
- **iPhone**: a PWA can record dictation and short in-person notes while open, but iOS suspends web
  apps on screen lock/app switch (known platform behaviour; verify on device), and PWAs cannot be
  share targets. For long recordings and calls use the built-in apps (Voice Memos; iOS call
  recording in the Phone app) and send the file with an **iOS Shortcut** ("Share → upload to second
  brain" — a Shortcut can POST a file to our HTTPS endpoint with the token). ✔ workaround
- **Android**: PWA can be a share target, so "Share → Second brain" works natively.
- **System-wide dictation** (typing into other apps): not possible from a web app. Options: macOS
  menu-bar helper with a hotkey (same native app as the recorder), or keep OS dictation.

## 3. "Web OS" shape

A PWA served by the existing `kb` service (same server, same auth), desktop-like on a large
screen (launcher, windows/panes) and a tab bar on mobile. Apps inside:

| App | Backed by | Status |
|---|---|---|
| Search (words + meaning, uk/ru/en) | existing search API | built (MCP) — needs HTTP API + UI |
| Inbox / recent activity, conversation viewer | `recent_activity`, `get_item` | built — UI only |
| People | `person`, merge/split | built — UI only |
| Status / health | `status` | built — UI only |
| Chat with the knowledge base | LLM with tools over the same API | new: OpenAI (`gpt-6.1-sol` class) with tool calls; ≈ $0.01–0.05 per question. Claude Desktop/Code via MCP stays free under the Pro plan. |
| Dictation → notes | record → `gpt-transcribe` → note item (new source "notes") | new |
| Recorder / meetings | upload or Chrome tab capture → diarized transcript → summary | new (+ macOS helper for desktop calls) |
| Unsorted review, scopes | `kb unsorted` / scope rules | built — UI only |
| Later: ClickUp, Karakeep, Calendar, metrics, CMO standups, vault pointers | roadmap | planned |

Off-the-shelf "web OS" shells exist (e.g. open-source browser desktops such as Puter or daedalOS);
they add a large dependency and their own auth/storage model. Recommendation: build our own light
PWA shell with an OS-like launcher on top of our API — the "OS" is the layout, not a platform.

## 4. Security implications (public HTTPS, ADR 0009 amendment)
A web UI reachable on the internet needs real login, not a static bearer token in the browser:
passkeys (WebAuthn) for the single owner, short-lived session cookies, CSRF protection; the MCP
token stays for Claude clients. Audio and transcripts are as sensitive as mail: same redaction of
hard secrets before LLM use; raw audio kept 30 days (ADR 0010).

## 5. Recommended plan
1. **web-app-v1 (PWA shell)**: passkey login; HTTP API over existing search/people/status/
   recent/get_item; launcher + Search, Inbox, People, Status apps; installable on Mac/iPhone/Android.
2. **voice-v1**: dictation (record → `gpt-transcribe` → notes source), recording upload API +
   iOS Shortcut + Android share target, diarized meeting transcripts (`gpt-4o-transcribe-diarize`),
   Chrome tab-audio meeting recorder, transcripts summarized and indexed like conversations.
3. **chat-v1**: chat with the knowledge base inside the PWA (OpenAI with tool calls, cost cap).
4. **mac-helper**: native menu-bar recorder for desktop calls (+ optional global dictation hotkey).
5. Live captions / live KB assistant during calls (`gpt-live-transcribe`), as in ADR 0010.

## Sources
- OpenAI API pricing: https://developers.openai.com/api/docs/pricing
- OpenAI speech-to-text guide: https://developers.openai.com/api/docs/guides/speech-to-text
- MDN getDisplayMedia: https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getDisplayMedia
- MDN browser-compat-data (getDisplayMedia audio notes, MediaRecorder, share_target):
  https://github.com/mdn/browser-compat-data (api/MediaDevices.json, api/MediaRecorder.json,
  manifests/webapp/share_target.json)
- Chrome screen-sharing controls (systemAudio): https://developer.chrome.com/docs/web-platform/screen-sharing-controls
